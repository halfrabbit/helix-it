from __future__ import annotations

import re
import shlex
import time
from datetime import datetime
from pathlib import Path

from helix_it import collections, remote
from helix_it.db import Store, utcnow


VAR_RE = re.compile(r"\$\(([A-Za-z]+)\)")


def default_codes(kind: str) -> str:
    if kind == "install":
        return "0,1641,3010"
    if kind == "reboot":
        return "0,1190"
    return "0"


def expand(text: str | None, device) -> str:
    if not text:
        return ""

    mapping = {
        "ComputerName": device["name"] or "",
        "Hostname": device["hostname"] or "",
        "IP": device["ip"] or "",
        "OU": device["ou"] or "",
        "Domain": device["domain"] or "",
        "OS": device["os"] or "",
    }

    def repl(match: re.Match[str]) -> str:
        return str(mapping.get(match.group(1), match.group(0)))

    return VAR_RE.sub(repl, text)


def append_log(existing: str | None, line: str) -> str:
    stamp = datetime.now().strftime("%H:%M:%S")
    text = f"{existing or ''}[{stamp}] {line}\n"
    if len(text) > 100_000:
        text = text[-100_000:]
    return text


def create_deployment(
    store: Store,
    package_id: int,
    device_ids: list[int],
    credential: str | None,
    schedule_id: int | None = None,
) -> int:
    package = store.package(package_id)
    if not package:
        raise RuntimeError("Package is missing.")
    unique = list(dict.fromkeys(device_ids))
    if not unique:
        raise RuntimeError("No computers to deploy to.")
    name = f"{package['name']} · {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    return store.create_deployment(package_id, name, unique, credential, schedule_id)


def run_deployment(store: Store, deployment_id: int, progress=None) -> str:
    deployment = store.deployment(deployment_id)
    if not deployment:
        raise RuntimeError("Deployment is missing.")
    steps = store.package_steps(int(deployment["package_id"]))
    targets = [row for row in store.deployment_targets(deployment_id) if row["status"] != "success"]
    store.execute(
        "UPDATE deployments SET status = 'running', finished_at = NULL WHERE id = ?",
        (deployment_id,),
    )
    for target in targets:
        label = target["device_name"]
        if progress:
            progress(f"Deploying to {label}")
        _run_target(store, deployment, steps, target)
    status = store.rollup_deployment(deployment_id)
    store.log("deploy", f"{deployment['package_name']} → {status}")
    return status


def _note(store: Store, target_id: int, status: str, line: str, exit_code: int | None = None, finished: bool = False) -> None:
    row = store.fetchone("SELECT log, started_at FROM deployment_targets WHERE id = ?", (target_id,))
    fields = {
        "log": append_log(row["log"] if row else "", line),
        "status": status,
    }
    if row and not row["started_at"]:
        fields["started_at"] = utcnow()
    if exit_code is not None:
        fields["exit_code"] = exit_code
    if finished:
        fields["finished_at"] = utcnow()
    store.update_target(target_id, **fields)


def _run_target(store: Store, deployment, steps, target) -> None:
    device = store.device(int(target["device_id"]))
    target_id = int(target["id"])
    if not device:
        _note(store, target_id, "failed", "Computer is gone.", finished=True)
        return
    _note(store, target_id, "running", f"Starting {deployment['package_name']} on {device['name']}")
    try:
        ok, code = _run_steps(
            store,
            device,
            steps,
            target_id,
            int(deployment["id"]),
            deployment["credential"],
            int(deployment["timeout_sec"] or 3600),
            depth=0,
        )
    except Exception as exc:
        _note(store, target_id, "failed", str(exc), finished=True)
        return
    if ok:
        _note(store, target_id, "success", "Finished.", exit_code=code, finished=True)
    else:
        _note(store, target_id, "failed", "One or more steps failed.", exit_code=code, finished=True)


def _run_steps(store, device, steps, target_id, deployment_id, credential, timeout, depth: int) -> tuple[bool, int | None]:
    if depth > 8:
        raise RuntimeError("Nested packages are nested too deeply.")
    fact = store.fact_for(int(device["id"])) or {"text": {}, "lists": {}}
    failed = False
    code: int | None = None
    if not steps:
        _note(store, target_id, "running", "Package has no steps.")
        return True, 0
    for step in steps:
        if step["condition_field"]:
            allowed = collections.matches(
                fact["text"],
                fact["lists"],
                step["condition_field"],
                step["condition_op"] or "contains",
                step["condition_value"] or "",
            )
            if not allowed:
                _note(store, target_id, "running", f"Skipped {step['name']} (condition).")
                continue
        try:
            code = _run_step(store, device, step, target_id, deployment_id, credential, timeout, depth)
        except Exception as exc:
            code = 1
            _note(store, target_id, "running", f"{step['name']} failed: {exc}", exit_code=code)
            if int(step["continue_on_error"] or 0):
                failed = True
                continue
            return False, code
        if step["kind"] == "reboot":
            _note(store, target_id, "running", "Reboot requested. Later steps were not run.")
            return not failed, code
    return not failed, 0 if code is None else code


def _run_step(store, device, step, target_id, deployment_id, credential, timeout, depth: int) -> int:
    kind = step["kind"]
    name = step["name"] or kind
    payload = expand(step["payload"], device)
    args = expand(step["args"], device)
    codes = step["success_codes"] or default_codes(kind)
    if kind == "sleep":
        seconds = int(float(payload or "1"))
        time.sleep(min(max(seconds, 0), 3600))
        _note(store, target_id, "running", f"{name}: waited {seconds}s")
        return 0
    if kind == "message":
        if remote.is_local_device(device):
            _note(store, target_id, "running", f"Message: {payload}")
            return 0
        result = remote.run_argv(device, ["msg.exe", "*", "/TIME:30", payload or name], credential, timeout=60)
        if result.succeeded(codes):
            _note(store, target_id, "running", f"Message: {payload}")
            return result.exit_code
        detail = result.stderr or result.stdout or "no user is logged on"
        if int(step["continue_on_error"] or 0):
            _note(store, target_id, "running", f"{name}: {detail}")
            return 0
        raise RuntimeError(detail)
    if kind == "command":
        result = remote.run_command(device, payload, credential, timeout)
        return _check(store, target_id, name, result, codes)
    if kind == "powershell":
        result = remote.run_powershell(device, payload, credential, timeout)
        return _check(store, target_id, name, result, codes)
    if kind == "nested":
        nested_id = step["nested_package_id"]
        if not nested_id:
            raise RuntimeError(f"{name} does not point at a package.")
        nested = store.package_steps(int(nested_id))
        ok, code = _run_steps(store, device, nested, target_id, deployment_id, credential, timeout, depth + 1)
        if not ok:
            raise RuntimeError(f"Nested package {name} failed.")
        return int(code or 0)
    if kind in {"copy", "install"}:
        if not payload:
            raise RuntimeError(f"{name} needs a file on this computer.")
        _note(store, target_id, "copying", f"Copying {Path(payload).name}")
        remote_dir = f"Windows\\Temp\\Helix\\{deployment_id}\\{step['id']}"
        remote_path = remote.stage_file(device, payload, remote_dir, credential)
        _note(store, target_id, "running", f"Copied to {remote_path}")
        if kind == "copy":
            return 0
        return _install(store, device, target_id, name, remote_path, args, codes, credential, timeout)
    if kind == "reboot":
        result = remote.reboot(device, credential)
        if result.exit_code not in remote.parse_codes(codes) and result.exit_code not in {0, 1190}:
            raise RuntimeError(result.stderr or result.stdout or f"reboot exit {result.exit_code}")
        _note(store, target_id, "running", "Reboot command sent.")
        return result.exit_code
    raise RuntimeError(f"Unknown step type {kind}")


def _install(store, device, target_id, name, remote_path, args, codes, credential, timeout) -> int:
    suffix = Path(remote_path).suffix.lower()
    if remote.is_local_device(device) and suffix in {".msi", ".msix", ".msixbundle", ".exe"}:
        raise RuntimeError("This is a Windows installer. Deploy it to a Windows computer.")
    if suffix in {".msix", ".msixbundle"}:
        quoted = "'" + remote_path.replace("'", "''") + "'"
        result = remote.run_powershell(device, f"Add-AppxPackage -Path {quoted}", credential, timeout)
        return _check(store, target_id, name, result, codes)
    argv = _install_argv(remote_path, args)
    result = remote.run_argv(device, argv, credential, timeout)
    return _check(store, target_id, name, result, codes)


def _install_argv(remote_path: str, args: str) -> list[str]:
    extra = shlex.split(args) if args.strip() else []
    lower = remote_path.lower()
    if lower.endswith(".msi"):
        return ["msiexec.exe", "/i", remote_path, *(extra or ["/qn", "/norestart"])]
    if lower.endswith(".ps1"):
        return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", remote_path, *extra]
    if lower.endswith(".bat") or lower.endswith(".cmd"):
        return ["cmd.exe", "/c", remote_path, *extra]
    return [remote_path, *extra]


def _check(store, target_id, name, result: remote.RemoteResult, codes: str) -> int:
    detail = (result.stdout or result.stderr or "").strip()
    if len(detail) > 2000:
        detail = detail[:2000]
    if result.succeeded(codes):
        _note(store, target_id, "running", f"{name} exit {result.exit_code}" + (f"\n{detail}" if detail else ""))
        return result.exit_code
    message = detail or f"exit {result.exit_code}"
    raise RuntimeError(message)
