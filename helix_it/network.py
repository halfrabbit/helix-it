from __future__ import annotations

import ipaddress
import json
import re
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Interface:
    name: str
    mac: str | None
    addrs: list[str] = field(default_factory=list)
    cidrs: list[str] = field(default_factory=list)
    rx_bytes: int = 0
    tx_bytes: int = 0
    operstate: str = "unknown"


@dataclass
class Neighbor:
    ip: str
    mac: str | None
    iface: str | None
    state: str
    hostname: str | None = None


def _run(args: list[str], timeout: float = 4.0) -> str:
    try:
        result = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def local_hostname() -> str:
    return socket.gethostname()


def os_pretty_name() -> str:
    path = Path("/etc/os-release")
    if not path.exists():
        return "Linux"
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value.strip().strip('"')
    return values.get("PRETTY_NAME", "Linux")


def cpu_model() -> str | None:
    path = Path("/proc/cpuinfo")
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        if line.lower().startswith("model name"):
            return line.split(":", 1)[1].strip()
    return None


def ram_gb() -> float | None:
    path = Path("/proc/meminfo")
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        if line.startswith("MemTotal:"):
            kb = int(line.split()[1])
            return round(kb / 1024 / 1024, 1)
    return None


def default_mac() -> str | None:
    for iface in list_interfaces():
        if iface.name != "lo" and iface.mac:
            return iface.mac
    return None


def default_ip() -> str | None:
    for iface in list_interfaces():
        for addr in iface.addrs:
            ip = ipaddress.ip_address(addr)
            if ip.version == 4 and not ip.is_loopback:
                return addr
    return None


def list_interfaces() -> list[Interface]:
    raw = _run(["ip", "-j", "addr"])
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    interfaces: list[Interface] = []
    for item in payload:
        name = item.get("ifname") or ""
        mac = item.get("address")
        addrs: list[str] = []
        cidrs: list[str] = []
        for info in item.get("addr_info") or []:
            local = info.get("local")
            prefix = info.get("prefixlen")
            if local:
                addrs.append(local)
                if prefix is not None:
                    cidrs.append(f"{local}/{prefix}")
        stats_dir = Path("/sys/class/net") / name / "statistics"
        rx = _read_int(stats_dir / "rx_bytes")
        tx = _read_int(stats_dir / "tx_bytes")
        oper = Path("/sys/class/net") / name / "operstate"
        interfaces.append(
            Interface(
                name=name,
                mac=mac,
                addrs=addrs,
                cidrs=cidrs,
                rx_bytes=rx,
                tx_bytes=tx,
                operstate=oper.read_text().strip() if oper.exists() else item.get("operstate", "unknown"),
            )
        )
    return interfaces


def _read_int(path: Path) -> int:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return 0


def list_neighbors() -> list[Neighbor]:
    raw = _run(["ip", "-j", "neigh"])
    neighbors: list[Neighbor] = []
    if raw:
        try:
            for item in json.loads(raw):
                dst = item.get("dst")
                if not dst:
                    continue
                neighbors.append(
                    Neighbor(
                        ip=dst,
                        mac=item.get("lladdr"),
                        iface=item.get("dev"),
                        state=(item.get("state") or ["UNKNOWN"])[0]
                        if isinstance(item.get("state"), list)
                        else str(item.get("state") or "UNKNOWN"),
                    )
                )
        except json.JSONDecodeError:
            pass
    return neighbors


def reverse_name(ip: str) -> str | None:
    try:
        name, *_ = socket.gethostbyaddr(ip)
        return name.rstrip(".")
    except (socket.herror, socket.gaierror, OSError):
        return None


def ping(ip: str, timeout: float = 1.0) -> bool:
    result = subprocess.run(
        ["ping", "-c", "1", "-W", "1", ip],
        check=False,
        capture_output=True,
        timeout=2.0,
    )
    return result.returncode == 0


def scan_targets() -> list[str]:
    targets: list[str] = []
    seen: set[str] = set()
    for iface in list_interfaces():
        if iface.name == "lo":
            continue
        for cidr in iface.cidrs:
            try:
                net = ipaddress.ip_network(cidr, strict=False)
            except ValueError:
                continue
            if net.version != 4 or not net.is_private:
                continue
            if net.prefixlen < 24:
                net = ipaddress.ip_network(f"{cidr.split('/')[0]}/24", strict=False)
            if net.num_addresses > 256:
                continue
            for host in net.hosts():
                ip = str(host)
                if ip not in seen:
                    seen.add(ip)
                    targets.append(ip)
    return targets


def ping_sweep(ips: list[str], workers: int = 48) -> set[str]:
    alive: set[str] = set()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(ping, ip): ip for ip in ips}
        for future in as_completed(futures):
            ip = futures[future]
            try:
                if future.result():
                    alive.add(ip)
            except Exception:
                continue
    return alive


def guess_type(name: str, ip: str) -> str:
    lowered = name.lower()
    if any(token in lowered for token in ("sw", "switch", "router", "fw", "gateway", "ap-")):
        return "network"
    if any(token in lowered for token in ("prn", "printer", "hp-", "lexmark")):
        return "printer"
    if any(token in lowered for token in ("srv", "server", "nas", "dc-", "fs-")):
        return "server"
    last = ip.rsplit(".", 1)[-1]
    if last in {"1", "254"}:
        return "network"
    return "computer"


def discover_lan(store) -> tuple[int, int]:
    """Ping private subnets on this host and upsert what answers. Returns (alive, targeted)."""
    targets = scan_targets()
    alive = ping_sweep(targets) if targets else set()
    neighbors = {item.ip: item for item in list_neighbors()}
    imported = 0
    ordered = sorted(alive, key=lambda value: tuple(int(part) for part in value.split(".")))
    for ip in ordered:
        neigh = neighbors.get(ip)
        hostname = reverse_name(ip)
        name = hostname.split(".")[0] if hostname else f"host-{ip.replace('.', '-')}"
        store.upsert_discovered(
            name=name,
            ip=ip,
            mac=neigh.mac if neigh else None,
            hostname=hostname,
            status="online",
            device_type=guess_type(name, ip),
        )
        imported += 1
    for ip, neigh in neighbors.items():
        if ip in alive:
            continue
        hostname = reverse_name(ip)
        name = hostname.split(".")[0] if hostname else f"host-{ip.replace('.', '-')}"
        store.upsert_discovered(
            name=name,
            ip=ip,
            mac=neigh.mac,
            hostname=hostname,
            status="unknown",
            device_type=guess_type(name, ip),
        )
        imported += 1
    store.log("scan", f"Scan finished — {len(alive)} answering hosts, {imported} inventory rows updated")
    return len(alive), len(targets)


def format_bytes(value: int) -> str:
    number = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if number < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(number)} {unit}"
            return f"{number:.1f} {unit}"
        number /= 1024
    return f"{value} B"


_MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$", re.I)
