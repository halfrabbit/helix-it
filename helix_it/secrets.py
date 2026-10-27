from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from helix_it.db import data_dir


DEFAULT: dict[str, Any] = {
    "directory": {
        "server": "",
        "port": 389,
        "use_ssl": False,
        "dns_domain": "",
        "netbios": "",
        "base_dn": "",
        "username": "",
        "password": "",
    },
    "winrm": {
        "port": 5985,
        "use_ssl": False,
        "transport": "ntlm",
        "credential": "",
    },
    "credentials": [],
}


def secrets_path() -> Path:
    return data_dir() / "secrets.json"


def _secure(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    if path.exists():
        os.chmod(path, 0o600)


def load(path: Path | None = None) -> dict[str, Any]:
    path = path or secrets_path()
    merged = copy.deepcopy(DEFAULT)
    if not path.exists():
        return merged
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return merged
    for key in ("directory", "winrm"):
        if isinstance(data.get(key), dict):
            merged[key].update(data[key])
    if isinstance(data.get("credentials"), list):
        merged["credentials"] = data["credentials"]
    return merged


def save(data: dict[str, Any], path: Path | None = None) -> None:
    path = path or secrets_path()
    _secure(path)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.chmod(path, 0o600)


def directory(path: Path | None = None) -> dict[str, Any]:
    return dict(load(path)["directory"])


def set_directory(updates: dict[str, Any], path: Path | None = None) -> None:
    data = load(path)
    for key, value in updates.items():
        if key == "password" and value == "":
            continue
        data["directory"][key] = value
    save(data, path)


def winrm_config(path: Path | None = None) -> dict[str, Any]:
    return dict(load(path)["winrm"])


def set_winrm(updates: dict[str, Any], path: Path | None = None) -> None:
    data = load(path)
    data["winrm"].update(updates)
    save(data, path)


def credentials(path: Path | None = None) -> list[dict[str, Any]]:
    return list(load(path)["credentials"])


def get_credential(name: str | None, path: Path | None = None) -> dict[str, Any] | None:
    if not name:
        return None
    for cred in credentials(path):
        if cred.get("name") == name:
            return dict(cred)
    return None


def upsert_credential(cred: dict[str, Any], path: Path | None = None, previous: str | None = None) -> None:
    data = load(path)
    name = str(cred.get("name") or "").strip()
    if not name:
        raise ValueError("Credential needs a name")
    current = next((item for item in data["credentials"] if item.get("name") in {name, previous}), None)
    password = cred.get("password") or (current or {}).get("password") or ""
    kept = [item for item in data["credentials"] if item.get("name") not in {name, previous}]
    kept.append(
        {
            "name": name,
            "username": str(cred.get("username") or "").strip(),
            "domain": str(cred.get("domain") or "").strip(),
            "password": password,
        }
    )
    data["credentials"] = sorted(kept, key=lambda item: str(item.get("name") or "").lower())
    save(data, path)


def delete_credential(name: str, path: Path | None = None) -> None:
    data = load(path)
    data["credentials"] = [item for item in data["credentials"] if item.get("name") != name]
    if data["winrm"].get("credential") == name:
        data["winrm"]["credential"] = ""
    save(data, path)


def credential_for_winrm(name: str | None = None, path: Path | None = None) -> dict[str, Any] | None:
    data = load(path)
    chosen = name or data["winrm"].get("credential") or ""
    if chosen:
        found = get_credential(str(chosen), path)
        if found:
            return found
    creds = data["credentials"]
    return dict(creds[0]) if creds else None


def account_name(cred: dict[str, Any], transport: str = "ntlm") -> str:
    user = str(cred.get("username") or "").strip()
    domain = str(cred.get("domain") or "").strip()
    if transport == "kerberos":
        if "@" in user:
            return user
        dns = str(directory().get("dns_domain") or "").strip()
        if dns:
            return f"{user}@{dns.upper()}"
        return user
    if "\\" in user or "@" in user:
        return user
    if domain:
        return f"{domain}\\{user}"
    return user
