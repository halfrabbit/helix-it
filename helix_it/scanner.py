from __future__ import annotations

import json
import platform
import pwd
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from helix_it import network, remote
from helix_it.db import Store, utcnow


@dataclass
class ScanOutcome:
    device_id: int
    ok: bool
    message: str


def profile_dict(row) -> dict:
    data = dict(row)
    for key in ("software", "hotfixes", "services", "hardware", "users", "shares", "printers", "startup"):
        data[key] = bool(int(data.get(key) if data.get(key) is not None else 1))
    data["custom_script"] = data.get("custom_script") or ""
    return data


def inventory_script(profile: dict) -> str:
    sections = ["$ErrorActionPreference = 'SilentlyContinue'", "$ProgressPreference = 'SilentlyContinue'"]
    sections.append(
        """
$os = Get-CimInstance Win32_OperatingSystem
$cs = Get-CimInstance Win32_ComputerSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$bios = Get-CimInstance Win32_BIOS
$computer = [ordered]@{
  hostname = $(if ($cs.DNSHostName) { $cs.DNSHostName } else { $env:COMPUTERNAME })
  domain = $(if ($cs.PartOfDomain) { $cs.Domain } else { $null })
  manufacturer = [string]$cs.Manufacturer
  model = [string]$cs.Model
  current_user = [string]$cs.UserName
  os = [string]$os.Caption
  os_version = [string]$os.Version
  architecture = [string]$os.OSArchitecture
  ram_gb = [math]::Round(($cs.TotalPhysicalMemory / 1GB), 1)
  cpu = [string]$cpu.Name
  serial = [string]$bios.SerialNumber
  last_boot = $(if ($os.LastBootUpTime) { $os.LastBootUpTime.ToString('o') } else { $null })
}
$hardware = $null
""".strip()
    )
    if profile.get("hardware", True):
        sections.append(
            """
$hardware = [ordered]@{
  memory = @(Get-CimInstance Win32_PhysicalMemory | ForEach-Object {
    [ordered]@{ bank = [string]$_.BankLabel; gb = [math]::Round($_.Capacity / 1GB, 1); speed = $_.Speed; manufacturer = [string]$_.Manufacturer }
  })
  video = @(Get-CimInstance Win32_VideoController | ForEach-Object {
    [ordered]@{ name = [string]$_.Name; driver = [string]$_.DriverVersion }
  })
}
$disks = @(Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | ForEach-Object {
  [ordered]@{
    name = [string]$_.DeviceID
    size_gb = $(if ($_.Size) { [math]::Round($_.Size / 1GB, 1) } else { $null })
    free_gb = $(if ($_.FreeSpace) { [math]::Round($_.FreeSpace / 1GB, 1) } else { $null })
    filesystem = [string]$_.FileSystem
  }
})
$nics = @(Get-CimInstance Win32_NetworkAdapterConfiguration -Filter "IPEnabled=True" | ForEach-Object {
  $ipv4 = $_.IPAddress | Where-Object { $_ -match '^\\d+\\.' } | Select-Object -First 1
  [ordered]@{ name = [string]$_.Description; mac = [string]$_.MACAddress; ip = [string]$ipv4; speed_mbps = $null }
})
""".strip()
        )
    if profile.get("software", True):
        sections.append(
            """
$paths = @(
  'HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*',
  'HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*'
)
$software = @(foreach ($path in $paths) {
  Get-ItemProperty $path -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName } | ForEach-Object {
    [ordered]@{ name = [string]$_.DisplayName; version = [string]$_.DisplayVersion; publisher = [string]$_.Publisher }
  }
})
""".strip()
        )
    if profile.get("hotfixes", True):
        sections.append(
            """
$hotfixes = @(Get-HotFix | ForEach-Object {
  [ordered]@{
    hotfix_id = [string]$_.HotFixID
    description = [string]$_.Description
    installed_on = $(if ($_.InstalledOn) { $_.InstalledOn.ToString('yyyy-MM-dd') } else { $null })
  }
})
""".strip()
        )
    if profile.get("services", True):
        sections.append(
            """
$services = @(Get-CimInstance Win32_Service | ForEach-Object {
  [ordered]@{ name = [string]$_.Name; display_name = [string]$_.DisplayName; status = [string]$_.State; start_mode = [string]$_.StartMode }
})
""".strip()
        )
    if profile.get("users", True):
        sections.append(
            """
$users = @(Get-CimInstance Win32_UserAccount -Filter "LocalAccount=True" | ForEach-Object {
  [ordered]@{ name = [string]$_.Name; disabled = $(if ($_.Disabled) { 1 } else { 0 }); full_name = [string]$_.FullName }
})
""".strip()
        )
    if profile.get("shares", True):
        sections.append(
            """
$shares = @(Get-CimInstance Win32_Share | ForEach-Object {
  [ordered]@{ name = [string]$_.Name; path = [string]$_.Path; description = [string]$_.Description }
})
""".strip()
        )
    if profile.get("printers", True):
        sections.append(
            """
$printers = @(Get-CimInstance Win32_Printer | ForEach-Object {
  [ordered]@{ name = [string]$_.Name; driver = [string]$_.DriverName; port = [string]$_.PortName }
})
""".strip()
        )
    if profile.get("startup", True):
        sections.append(
            """
$startup = @(Get-CimInstance Win32_StartupCommand | ForEach-Object {
  [ordered]@{ name = [string]$_.Name; command = [string]$_.Command; location = [string]$_.Location }
})
""".strip()
        )
    emit = ["$result = [ordered]@{ computer = $computer }"]
    if profile.get("hardware", True):
        emit.append("$result.hardware = $hardware")
        emit.append("$result.disks = @($disks)")
        emit.append("$result.nics = @($nics)")
    if profile.get("software", True):
        emit.append("$result.software = @($software)")
    if profile.get("hotfixes", True):
        emit.append("$result.hotfixes = @($hotfixes)")
    if profile.get("services", True):
        emit.append("$result.services = @($services)")
    if profile.get("users", True):
        emit.append("$result.users = @($users)")
    if profile.get("shares", True):
        emit.append("$result.shares = @($shares)")
    if profile.get("printers", True):
        emit.append("$result.printers = @($printers)")
    if profile.get("startup", True):
        emit.append("$result.startup = @($startup)")
    emit.append("$result | ConvertTo-Json -Depth 6 -Compress")
    sections.append("\n".join(emit))
    return "\n".join(sections)


def extract_json(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Inventory script did not return JSON")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("Inventory JSON was not an object")
    return data


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _clean_rows(rows: list[dict], required: str) -> list[dict]:
    cleaned = []
    for row in rows:
        if not str(row.get(required) or "").strip():
            continue
        cleaned.append(row)
    return cleaned


def save_inventory(store: Store, device_id: int, data: dict) -> None:
    computer = data.get("computer") or {}
    fields: dict = {
        "status": "online",
        "scan_status": "ok",
        "scan_error": None,
        "last_seen": utcnow(),
        "last_scan": utcnow(),
    }
    mapping = {
        "hostname": "hostname",
        "domain": "domain",
        "manufacturer": "manufacturer",
        "model": "model",
        "current_user": "current_user",
        "os": "os",
        "os_version": "os_version",
        "architecture": "architecture",
        "cpu": "cpu",
        "serial": "serial",
        "last_boot": "last_boot",
    }
    for source, dest in mapping.items():
        value = computer.get(source)
        if value not in (None, ""):
            fields[dest] = value
    if computer.get("ram_gb") not in (None, ""):
        fields["ram_gb"] = computer.get("ram_gb")
    if "disks" in data:
        total = 0.0
        saw = False
        for disk in _as_list(data.get("disks")):
            try:
                total += float(disk.get("size_gb") or 0)
                saw = True
            except (TypeError, ValueError):
                continue
        if saw:
            fields["disk_gb"] = round(total, 1)
    nics = _as_list(data.get("nics"))
    for nic in nics:
        ip = nic.get("ip")
        if isinstance(ip, list):
            ip = next((item for item in ip if item), "")
        ip = str(ip or "")
        if ip and ":" not in ip and not ip.startswith("127."):
            fields["ip"] = ip
            break
    if "hardware" in data and data.get("hardware") is not None:
        fields["hardware_json"] = json.dumps(data.get("hardware"))
    if "custom" in data:
        fields["custom_scan"] = data.get("custom") or ""
    current = store.device(device_id)
    if current and current["ip"] and remote.is_local_device(current):
        fields.pop("ip", None)
    with store.transaction():
        store.update_device(device_id, **fields)
        if "software" in data:
            store.replace_device_rows("software", device_id, _clean_rows(_as_list(data["software"]), "name"))
        if "hotfixes" in data:
            store.replace_device_rows("hotfixes", device_id, _clean_rows(_as_list(data["hotfixes"]), "hotfix_id"))
        if "services" in data:
            store.replace_device_rows("services", device_id, _clean_rows(_as_list(data["services"]), "name"))
        if "disks" in data:
            store.replace_device_rows("disks", device_id, _as_list(data["disks"]))
        if "nics" in data:
            store.replace_device_rows("nics", device_id, _as_list(data["nics"]))
        if "users" in data:
            users = []
            for row in _clean_rows(_as_list(data["users"]), "name"):
                users.append({**row, "disabled": 1 if row.get("disabled") else 0})
            store.replace_device_rows("local_users", device_id, users)
        if "shares" in data:
            store.replace_device_rows("shares", device_id, _clean_rows(_as_list(data["shares"]), "name"))
        if "printers" in data:
            store.replace_device_rows("printers", device_id, _clean_rows(_as_list(data["printers"]), "name"))
        if "startup" in data:
            store.replace_device_rows("startup_items", device_id, _clean_rows(_as_list(data["startup"]), "name"))


def _query_lines(args: list[str]) -> list[str]:
    try:
        completed = subprocess.run(args, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []
    return [line for line in completed.stdout.splitlines() if line.strip()]


def _linux_software() -> list[dict]:
    if shutil.which("pacman"):
        rows = []
        for line in _query_lines(["pacman", "-Q"]):
            parts = line.split()
            if len(parts) >= 2:
                rows.append({"name": parts[0], "version": parts[1], "publisher": ""})
        return rows
    if shutil.which("dpkg-query"):
        rows = []
        for line in _query_lines(["dpkg-query", "-W", "-f", "${Package}\\t${Version}\\n"]):
            name, _, version = line.partition("\t")
            if name:
                rows.append({"name": name, "version": version, "publisher": ""})
        return rows
    if shutil.which("rpm"):
        rows = []
        for line in _query_lines(["rpm", "-qa", "--queryformat", "%{NAME}\\t%{VERSION}\\n"]):
            name, _, version = line.partition("\t")
            if name:
                rows.append({"name": name, "version": version, "publisher": ""})
        return rows
    return []


def _linux_services() -> list[dict]:
    try:
        completed = subprocess.run(
            ["systemctl", "list-units", "--type=service", "--all", "--no-pager", "--output=json", "--no-legend"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        data = json.loads(completed.stdout or "[]")
    except (OSError, json.JSONDecodeError, subprocess.TimeoutExpired):
        return []
    rows = []
    for item in data if isinstance(data, list) else []:
        name = item.get("unit") or item.get("id")
        if not name:
            continue
        rows.append(
            {
                "name": name,
                "display_name": item.get("description") or "",
                "status": item.get("sub") or item.get("active") or "",
                "start_mode": item.get("load") or "",
            }
        )
    return rows


def _linux_disks() -> list[dict]:
    rows = []
    for line in _query_lines(["df", "-B1", "-P", "-x", "tmpfs", "-x", "devtmpfs", "-x", "squashfs"]):
        parts = line.split()
        if len(parts) < 6 or not parts[0].startswith("/"):
            continue
        try:
            size = int(parts[1]) / 1024 / 1024 / 1024
            free = int(parts[3]) / 1024 / 1024 / 1024
        except ValueError:
            continue
        rows.append({"name": parts[5], "size_gb": round(size, 1), "free_gb": round(free, 1), "filesystem": parts[0]})
    return rows


def _linux_users() -> list[dict]:
    rows = []
    for entry in pwd.getpwall():
        shell = entry.pw_shell or ""
        if entry.pw_uid != 0 and entry.pw_uid < 1000:
            continue
        if shell.endswith("nologin") or shell.endswith("false"):
            continue
        rows.append({"name": entry.pw_name, "disabled": 0, "full_name": entry.pw_gecos.split(",")[0]})
    return rows


def _linux_startup() -> list[dict]:
    rows = []
    folder = Path("/etc/xdg/autostart")
    if not folder.is_dir():
        return rows
    for item in sorted(folder.glob("*.desktop")):
        rows.append({"name": item.stem, "command": str(item), "location": "xdg autostart"})
    return rows


def scan_local(profile: dict) -> dict:
    os_name = network.os_pretty_name()
    version = ""
    release = Path("/etc/os-release")
    if release.exists():
        for line in release.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("VERSION_ID="):
                version = line.split("=", 1)[1].strip().strip('"')
    data: dict = {
        "computer": {
            "hostname": network.local_hostname(),
            "os": os_name,
            "os_version": version,
            "architecture": platform.machine(),
            "manufacturer": "Local",
            "model": "This Linux workstation",
            "cpu": network.cpu_model(),
            "ram_gb": network.ram_gb(),
            "current_user": __import__("os").environ.get("USER") or "",
        }
    }
    if profile.get("hardware", True):
        data["disks"] = _linux_disks()
        data["nics"] = [
            {"name": iface.name, "mac": iface.mac, "ip": next(iter(iface.addrs), None), "speed_mbps": None}
            for iface in network.list_interfaces()
            if iface.name != "lo"
        ]
        data["hardware"] = {"memory": [], "video": []}
    if profile.get("software", True):
        data["software"] = _linux_software()
    if profile.get("hotfixes", True):
        data["hotfixes"] = []
    if profile.get("services", True):
        data["services"] = _linux_services()
    if profile.get("users", True):
        data["users"] = _linux_users()
    if profile.get("shares", True):
        data["shares"] = []
    if profile.get("printers", True):
        data["printers"] = []
    if profile.get("startup", True):
        data["startup"] = _linux_startup()
    return data


def _reachable(host: str) -> bool:
    if not host:
        return False
    try:
        return network.ping(host)
    except (OSError, subprocess.TimeoutExpired):
        return False


def scan_windows(device, profile: dict, credential: str | None = None) -> dict:
    host = remote.device_host(device)
    if not host:
        raise RuntimeError(f"{device['name']} has no hostname or IP.")
    result = remote.run_powershell(device, inventory_script(profile), credential, timeout=180)
    if result.exit_code not in {0} and "{" not in result.stdout:
        detail = result.stderr or result.stdout or f"exit {result.exit_code}"
        raise RuntimeError(detail[:500])
    try:
        data = extract_json(result.stdout)
    except ValueError as exc:
        detail = result.stderr or result.stdout or str(exc)
        raise RuntimeError(detail[:500]) from exc
    script = (profile.get("custom_script") or "").strip()
    if script:
        custom = remote.run_powershell(device, script, credential, timeout=180)
        data["custom"] = custom.stdout if custom.exit_code == 0 else custom.stderr or custom.stdout
    return data


def scan_one(store: Store, device_id: int, credential: str | None = None) -> ScanOutcome:
    device = store.device(device_id)
    if not device:
        return ScanOutcome(device_id, False, "Computer is gone")
    name = device["name"]
    store.update_device(device_id, scan_status="running", scan_error=None)
    try:
        profile = profile_dict(store.scan_profile())
        if remote.is_local_device(device):
            data = scan_local(profile)
            script = str(profile.get("custom_script") or "").strip()
            if script:
                try:
                    custom = remote.run_powershell(device, script)
                    data["custom"] = custom.stdout if custom.exit_code == 0 else (custom.stderr or custom.stdout)
                except Exception as exc:
                    data["custom"] = str(exc)
        elif remote.is_windows_device(device):
            data = scan_windows(device, profile, credential)
        else:
            host = remote.device_host(device)
            if _reachable(host):
                store.update_device(
                    device_id,
                    status="online",
                    last_seen=utcnow(),
                    last_scan=utcnow(),
                    scan_status="skipped",
                    scan_error="Not a Windows computer and not this console.",
                )
                return ScanOutcome(device_id, False, f"{name} is not a Windows target")
            store.update_device(
                device_id,
                status="offline",
                last_scan=utcnow(),
                scan_status="failed",
                scan_error="Host did not answer ping.",
            )
            return ScanOutcome(device_id, False, f"{name} did not answer")
        save_inventory(store, device_id, data)
        return ScanOutcome(device_id, True, name)
    except Exception as exc:
        message = str(exc)[:500]
        host = remote.device_host(device)
        status = "offline" if host and not _reachable(host) and not remote.is_local_device(device) else "online"
        if remote.is_local_device(device):
            status = "online"
        store.update_device(
            device_id,
            status=status,
            scan_status="failed",
            scan_error=message,
            last_scan=utcnow(),
        )
        return ScanOutcome(device_id, False, f"{name}: {message}")


def scannable_ids(store: Store) -> list[int]:
    ids = []
    for device in store.devices():
        if remote.is_local_device(device) or remote.is_windows_device(device):
            ids.append(int(device["id"]))
    return ids


def scan_many(store: Store, device_ids: list[int], progress=None, on_success=None, credential: str | None = None) -> list[ScanOutcome]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if not device_ids:
        return []
    outcomes: list[ScanOutcome] = []

    def work(device_id: int) -> ScanOutcome:
        device = store.device(device_id)
        label = device["name"] if device else str(device_id)
        if progress:
            progress(f"Scanning {label}")
        return scan_one(store, device_id, credential)

    workers = min(4, len(device_ids))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(work, device_id) for device_id in device_ids]
        for future in as_completed(futures):
            outcome = future.result()
            outcomes.append(outcome)
            if outcome.ok and on_success:
                on_success(outcome.device_id)
            if progress:
                progress(outcome.message if outcome.ok else outcome.message)
    return outcomes
