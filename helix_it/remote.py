from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from helix_it import network, secrets


@dataclass
class RemoteResult:
    exit_code: int
    stdout: str
    stderr: str

    def succeeded(self, codes: str) -> bool:
        return self.exit_code in parse_codes(codes)


def parse_codes(spec: str | None) -> set[int]:
    found: set[int] = set()
    for part in (spec or "0").split(","):
        part = part.strip()
        if not part:
            continue
        found.add(int(part))
    return found or {0}


def device_host(device) -> str:
    host = str(device["hostname"] or "").strip()
    ip = str(device["ip"] or "").strip()
    if host and "." in host:
        return host
    return ip or host or str(device["name"] or "").strip()


def is_local_device(device) -> bool:
    try:
        if int(device["discovered"] or 0) == 2:
            return True
    except (KeyError, TypeError, ValueError):
        pass
    local_name = network.local_hostname().lower()
    local_ip = network.default_ip()
    name = str(device["hostname"] or device["name"] or "").lower()
    ip = device["ip"]
    short = local_name.split(".")[0]
    same_name = name in {local_name, short} or name.startswith(short + ".")
    return bool(local_ip and ip == local_ip and same_name)


def is_windows_device(device) -> bool:
    if str(device["type"] or "") in {"printer", "network", "other"}:
        return False
    os_name = str(device["os"] or "").lower()
    if any(token in os_name for token in ("linux", "debian", "ubuntu", "fedora", "arch", "cachy", "truenas", "opnsense", "cisco", "unifi", "jetdirect")):
        return False
    if "windows" in os_name:
        return True
    return bool(device["dn"])


def wake_on_lan(mac: str, broadcast: str = "255.255.255.255") -> None:
    cleaned = mac.replace(":", "").replace("-", "").strip()
    if len(cleaned) != 12:
        raise RuntimeError("Wake-on-LAN needs a MAC address.")
    payload = bytes.fromhex("FF" * 6 + cleaned * 16)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(payload, (broadcast, 9))
    finally:
        sock.close()


def _decode(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return bytes(value).decode("utf-8", errors="replace")


def _winrm():
    try:
        import winrm
    except ImportError as exc:
        raise RuntimeError(
            "Windows scan and deploy need pywinrm. Install it with: pip install pywinrm"
        ) from exc
    return winrm


def open_session(host: str, cred: dict, timeout: int):
    winrm = _winrm()
    cfg = secrets.winrm_config()
    use_ssl = bool(cfg.get("use_ssl"))
    port = int(cfg.get("port") or (5986 if use_ssl else 5985))
    scheme = "https" if use_ssl else "http"
    transport = str(cfg.get("transport") or "ntlm")
    endpoint = f"{scheme}://{host}:{port}/wsman"
    user = secrets.account_name(cred, transport)
    try:
        return winrm.Session(
            endpoint,
            auth=(user, cred.get("password") or ""),
            transport=transport,
            server_cert_validation="ignore",
            read_timeout_sec=max(30, timeout + 20),
            operation_timeout_sec=max(20, timeout),
        )
    except Exception as exc:
        raise RuntimeError(f"Could not open WinRM to {host}: {exc}") from exc


def _credential(name: str | None) -> dict:
    cred = secrets.credential_for_winrm(name)
    if not cred or not cred.get("username"):
        raise RuntimeError("No scan account is saved. Add one in Settings before reaching Windows computers.")
    return cred


def _result_from_winrm(result) -> RemoteResult:
    return RemoteResult(int(result.status_code or 0), _decode(result.std_out).strip(), _decode(result.std_err).strip())


def run_command(device, command: str, credential: str | None = None, timeout: int = 300) -> RemoteResult:
    if is_local_device(device):
        return _local_shell(command, timeout)
    host = device_host(device)
    if not host:
        raise RuntimeError(f"{device['name']} has no hostname or IP.")
    session = open_session(host, _credential(credential), timeout)
    try:
        result = session.run_cmd("cmd.exe", ["/c", command])
    except Exception as exc:
        raise RuntimeError(f"WinRM command to {host} failed: {exc}") from exc
    return _result_from_winrm(result)


def run_powershell(device, script: str, credential: str | None = None, timeout: int = 300) -> RemoteResult:
    if is_local_device(device):
        return _local_powershell(script, timeout)
    host = device_host(device)
    if not host:
        raise RuntimeError(f"{device['name']} has no hostname or IP.")
    session = open_session(host, _credential(credential), timeout)
    try:
        result = session.run_ps(script)
    except Exception as exc:
        raise RuntimeError(f"WinRM PowerShell to {host} failed: {exc}") from exc
    return _result_from_winrm(result)


def run_argv(device, argv: list[str], credential: str | None = None, timeout: int = 3600) -> RemoteResult:
    if not argv:
        raise RuntimeError("Nothing to run.")
    if is_local_device(device):
        try:
            completed = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Command timed out after {timeout}s") from exc
        except OSError as exc:
            raise RuntimeError(str(exc)) from exc
        return RemoteResult(int(completed.returncode), (completed.stdout or "").strip(), (completed.stderr or "").strip())
    host = device_host(device)
    session = open_session(host, _credential(credential), timeout)
    try:
        result = session.run_cmd(argv[0], argv[1:])
    except Exception as exc:
        raise RuntimeError(f"WinRM program on {host} failed: {exc}") from exc
    return _result_from_winrm(result)


def reboot(device, credential: str | None = None) -> RemoteResult:
    if is_local_device(device):
        raise RuntimeError("This is the Helix console, so reboot is not sent to it.")
    return run_argv(device, ["shutdown.exe", "/r", "/t", "5", "/f", "/c", "Helix Deploy"], credential, timeout=60)


def _local_shell(command: str, timeout: int) -> RemoteResult:
    try:
        completed = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Command timed out after {timeout}s") from exc
    return RemoteResult(int(completed.returncode), (completed.stdout or "").strip(), (completed.stderr or "").strip())


def _local_powershell(script: str, timeout: int) -> RemoteResult:
    binary = shutil.which("pwsh") or shutil.which("powershell")
    if not binary:
        raise RuntimeError("PowerShell is not installed on this Linux computer. Install pwsh, or target a Windows PC.")
    try:
        completed = subprocess.run(
            [binary, "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"PowerShell timed out after {timeout}s") from exc
    return RemoteResult(int(completed.returncode), (completed.stdout or "").strip(), (completed.stderr or "").strip())


def stage_file(device, local_path: str, remote_dir: str, credential: str | None = None) -> str:
    source = Path(local_path)
    if not source.is_file():
        raise RuntimeError(f"Package file not found: {local_path}")
    if is_local_device(device):
        dest_dir = Path("/tmp/helix-deploy") / remote_dir.replace("\\", "/")
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / source.name
        shutil.copy2(source, dest)
        return str(dest)
    host = device_host(device)
    if not host:
        raise RuntimeError(f"{device['name']} has no hostname or IP.")
    windows_dir = remote_dir.replace("/", "\\").strip("\\")
    remote_windows = f"C:\\{windows_dir}\\{source.name}"
    _upload(host, source, windows_dir, credential)
    return remote_windows


def _upload(host: str, source: Path, windows_dir: str, credential: str | None) -> None:
    cred = _credential(credential)
    user = secrets.account_name(cred, "ntlm")
    password = cred.get("password") or ""
    try:
        import smbclient
    except ImportError:
        smbclient = None
    if smbclient is not None:
        remote = "\\\\" + host + "\\C$\\" + windows_dir.replace("/", "\\") + "\\" + source.name
        try:
            smbclient.register_session(host, username=user, password=password, connection_timeout=20)
            smbclient.makedirs("\\\\" + host + "\\C$\\" + windows_dir.replace("/", "\\"), exist_ok=True)
            with source.open("rb") as src, smbclient.open_file(remote, mode="wb") as dst:
                shutil.copyfileobj(src, dst)
            return
        except Exception as exc:
            smb_error = exc
        finally:
            try:
                smbclient.delete_session(host)
            except Exception:
                pass
        if shutil.which("smbclient") is None:
            raise RuntimeError(f"Could not copy {source.name} to {host}: {smb_error}")
    else:
        smb_error = None
    if shutil.which("smbclient") is None:
        raise RuntimeError(
            "Copying installers needs smbprotocol (pip install smbprotocol) or the smbclient program from Samba."
        )
    _smbclient_put(host, source, windows_dir, cred, smb_error)


def _smbclient_put(host: str, source: Path, windows_dir: str, cred: dict, previous: Exception | None) -> None:
    domain = ""
    username = secrets.account_name(cred, "ntlm")
    if "\\" in username:
        domain, username = username.split("\\", 1)
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
    try:
        handle.write(f"username = {username}\npassword = {cred.get('password') or ''}\n")
        if domain:
            handle.write(f"domain = {domain}\n")
        handle.close()
        os.chmod(handle.name, 0o600)
        built = ""
        for part in windows_dir.split("\\"):
            if not part:
                continue
            built = f"{built}\\{part}" if built else part
            subprocess.run(
                ["smbclient", f"//{host}/C$", "-A", handle.name, "-m", "SMB3", "-c", f"mkdir {built}"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        remote_name = f"{windows_dir}\\{source.name}"
        local_quoted = '"' + str(source).replace('"', "") + '"'
        remote_quoted = '"' + remote_name.replace('"', "") + '"'
        completed = subprocess.run(
            ["smbclient", f"//{host}/C$", "-A", handle.name, "-m", "SMB3", "-c", f"put {local_quoted} {remote_quoted}"],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or str(previous or "")).strip()
        raise RuntimeError(f"Could not copy {source.name} to {host}: {detail}")
