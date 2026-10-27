from __future__ import annotations

import ssl
import uuid
from datetime import datetime, timezone
from typing import Any

from helix_it.db import Store, utcnow
from helix_it import secrets


ACCOUNT_DISABLED = 2


def base_dn_from_domain(domain: str) -> str:
    parts = [part.strip() for part in domain.split(".") if part.strip()]
    return ",".join(f"DC={part}" for part in parts)


def split_dn(dn: str) -> list[tuple[str, str]]:
    parts: list[str] = []
    buf: list[str] = []
    escape = False
    for char in dn or "":
        if escape:
            buf.append(char)
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == ",":
            parts.append("".join(buf).strip())
            buf = []
            continue
        buf.append(char)
    if buf:
        parts.append("".join(buf).strip())
    parsed: list[tuple[str, str]] = []
    for part in parts:
        if "=" not in part:
            continue
        attr, value = part.split("=", 1)
        parsed.append((attr.strip(), value.strip()))
    return parsed


def ou_from_dn(dn: str) -> str:
    ous = [value for attr, value in split_dn(dn)[1:] if attr.lower() == "ou"]
    return "/".join(reversed(ous))


def cn_from_dn(dn: str) -> str:
    parts = split_dn(dn)
    return parts[0][1] if parts else dn


def parent_dn(dn: str) -> str | None:
    parts = split_dn(dn)
    if len(parts) < 2:
        return None
    return ",".join(f"{attr}={value}" for attr, value in parts[1:])


def guid_text(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, memoryview):
        value = bytes(value)
    if isinstance(value, bytes) and len(value) == 16:
        return str(uuid.UUID(bytes_le=value))
    text = str(value).strip("{}")
    try:
        return str(uuid.UUID(text))
    except ValueError:
        return text


def is_disabled(value: Any) -> int:
    try:
        return 1 if int(value) & ACCOUNT_DISABLED else 0
    except (TypeError, ValueError):
        return 0


def windows_time(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.year < 1970:
            return None
        stamp = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return stamp.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    try:
        number = int(value)
    except (TypeError, ValueError):
        return str(value)
    if number in {0, 9223372036854775807}:
        return None
    seconds = (number - 116444736000000000) / 10_000_000
    try:
        return datetime.fromtimestamp(seconds, timezone.utc).replace(microsecond=0).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _ldap3():
    try:
        import ldap3
    except ImportError as exc:
        raise RuntimeError(
            "Active Directory needs the ldap3 package. Install it with: pip install ldap3"
        ) from exc
    return ldap3


def _values(entry: dict, name: str) -> list[Any]:
    raw = (entry.get("attributes") or {}).get(name)
    if raw is None or raw == []:
        return []
    if isinstance(raw, list):
        return raw
    return [raw]


def _first(entry: dict, name: str, default: str = "") -> Any:
    values = _values(entry, name)
    if not values or values[0] is None:
        return default
    return values[0]


def simple_username(directory: dict) -> str:
    user = str(directory.get("username") or "").strip()
    if "@" in user or "\\" in user or "=" in user:
        return user
    dns = str(directory.get("dns_domain") or "").strip()
    return f"{user}@{dns}" if dns else user


def resolved_base(directory: dict) -> str:
    base = str(directory.get("base_dn") or "").strip()
    if base:
        return base
    dns = str(directory.get("dns_domain") or "").strip()
    if not dns:
        raise RuntimeError("Enter a DNS domain or a base DN.")
    return base_dn_from_domain(dns)


class ReadOnlyDirectory:
    """LDAP session that can search. Object writes are refused before they are sent."""

    def __init__(self, conn) -> None:
        if not getattr(conn, "read_only", False):
            raise RuntimeError("Active Directory connections must be read-only.")
        self._conn = conn

    def search(self, *args, **kwargs):
        return self._conn.search(*args, **kwargs)

    def unbind(self) -> None:
        self._conn.unbind()

    @property
    def response(self):
        return self._conn.response

    @property
    def result(self):
        return self._conn.result

    def __getattr__(self, name: str):
        raise RuntimeError("Active Directory is read-only. Helix does not change the directory.")


def connect(directory: dict):
    ldap3 = _ldap3()
    server_name = str(directory.get("server") or "").strip()
    user = str(directory.get("username") or "").strip()
    password = str(directory.get("password") or "")
    if not server_name or not user or not password:
        raise RuntimeError("Enter the domain controller, username, and password.")
    use_ssl = bool(directory.get("use_ssl"))
    port = int(directory.get("port") or (636 if use_ssl else 389))
    tls = ldap3.Tls(validate=ssl.CERT_NONE) if use_ssl else None
    server = ldap3.Server(
        server_name,
        port=port,
        use_ssl=use_ssl,
        get_info=ldap3.NONE,
        connect_timeout=8,
        tls=tls,
    )
    attempts: list[tuple[Any, str]] = []
    netbios = str(directory.get("netbios") or "").strip()
    if netbios and "\\" not in user and "@" not in user:
        attempts.append((ldap3.NTLM, f"{netbios}\\{user}"))
    attempts.append((ldap3.SIMPLE, simple_username(directory)))
    last: Exception | None = None
    for auth, bind_user in attempts:
        try:
            conn = ldap3.Connection(
                server,
                user=bind_user,
                password=password,
                authentication=auth,
                auto_bind=False,
                auto_referrals=False,
                read_only=True,
                receive_timeout=30,
                raise_exceptions=True,
            )
            conn.bind()
            return ReadOnlyDirectory(conn), bind_user
        except Exception as exc:
            last = exc
    raise RuntimeError(f"Could not bind to {server_name}: {last}")


def paged_search(conn, base: str, filt: str, attributes: list[str]) -> list[dict]:
    from ldap3 import SUBTREE

    found: list[dict] = []
    cookie = None
    while True:
        conn.search(
            search_base=base,
            search_filter=filt,
            search_scope=SUBTREE,
            attributes=attributes,
            paged_size=500,
            paged_cookie=cookie,
        )
        for item in conn.response or []:
            if item.get("type") == "searchResEntry":
                found.append(item)
        controls = (conn.result or {}).get("controls") or {}
        page = controls.get("1.2.840.113556.1.4.319", {})
        cookie = (page.get("value") or {}).get("cookie")
        if not cookie:
            break
    return found


def test_directory(directory: dict | None = None) -> str:
    directory = directory or secrets.directory()
    base = resolved_base(directory)
    conn, bind_user = connect(directory)
    try:
        from ldap3 import BASE

        conn.search(base, "(objectClass=*)", search_scope=BASE, attributes=["distinguishedName"])
        hit = any(item.get("type") == "searchResEntry" for item in (conn.response or []))
        if not hit:
            raise RuntimeError(f"Base DN not found: {base}")
        return f"Connected read-only to {directory['server']} as {bind_user}. Base {base} is readable."
    finally:
        conn.unbind()


def _computer_record(entry: dict, dns_domain: str) -> dict[str, Any] | None:
    name = str(_first(entry, "cn") or "").strip()
    if not name:
        return None
    os_name = str(_first(entry, "operatingSystem") or "")
    kind = "server" if "server" in os_name.lower() else "computer"
    hostname = str(_first(entry, "dNSHostName") or "") or name
    groups = []
    for dn in _values(entry, "memberOf"):
        text = str(dn)
        groups.append((text, cn_from_dn(text)))
    return {
        "name": name,
        "hostname": hostname,
        "dn": entry.get("dn") or "",
        "ou": ou_from_dn(entry.get("dn") or ""),
        "ad_guid": guid_text(_first(entry, "objectGUID", "")),
        "os": os_name,
        "os_version": str(_first(entry, "operatingSystemVersion") or ""),
        "description": str(_first(entry, "description") or ""),
        "domain": dns_domain,
        "ad_disabled": is_disabled(_first(entry, "userAccountControl", 0)),
        "type": kind,
        "groups": groups,
    }


def _user_record(entry: dict) -> dict[str, Any] | None:
    name = str(_first(entry, "displayName") or _first(entry, "cn") or _first(entry, "sAMAccountName") or "").strip()
    if not name:
        return None
    email = str(_first(entry, "mail") or "") or None
    return {
        "name": name,
        "email": email,
        "department": str(_first(entry, "department") or "") or None,
        "title": str(_first(entry, "title") or "") or None,
        "ad_dn": entry.get("dn") or "",
        "ad_guid": guid_text(_first(entry, "objectGUID", "")),
    }


def sync(store: Store, directory: dict | None = None) -> dict[str, int]:
    directory = directory or secrets.directory()
    base = resolved_base(directory)
    dns = str(directory.get("dns_domain") or "").strip()
    conn, _bind = connect(directory)
    try:
        computers = paged_search(
            conn,
            base,
            "(objectClass=computer)",
            [
                "cn",
                "dNSHostName",
                "operatingSystem",
                "operatingSystemVersion",
                "distinguishedName",
                "objectGUID",
                "description",
                "userAccountControl",
                "memberOf",
            ],
        )
        ous = paged_search(conn, base, "(objectClass=organizationalUnit)", ["ou", "distinguishedName"])
        groups = paged_search(conn, base, "(objectClass=group)", ["cn", "distinguishedName", "description"])
        users = paged_search(
            conn,
            base,
            "(&(objectCategory=person)(objectClass=user)(!(objectClass=computer)))",
            ["displayName", "cn", "mail", "department", "title", "distinguishedName", "objectGUID", "sAMAccountName"],
        )
    finally:
        conn.unbind()

    seen = utcnow()
    computer_rows = []
    for entry in computers:
        rec = _computer_record(entry, dns)
        if rec:
            computer_rows.append(rec)
    ou_rows = []
    for entry in ous:
        dn = entry.get("dn") or ""
        name = str(_first(entry, "ou") or cn_from_dn(dn))
        if dn and name:
            ou_rows.append((dn, name, parent_dn(dn)))
    group_rows = []
    for entry in groups:
        dn = entry.get("dn") or ""
        name = str(_first(entry, "cn") or cn_from_dn(dn))
        if dn and name:
            group_rows.append((dn, name, str(_first(entry, "description") or "") or None))
    user_rows = []
    for entry in users:
        rec = _user_record(entry)
        if rec:
            user_rows.append(rec)

    with store.transaction():
        store.replace_ous(ou_rows)
        store.replace_groups(group_rows)
        store.clear_device_groups()
        for rec in computer_rows:
            groups_for = rec.pop("groups")
            device_id = store.upsert_ad_computer(rec, seen)
            store.replace_device_groups(device_id, groups_for)
        for rec in user_rows:
            store.upsert_directory_user(rec)
        store.set_meta("ad_sync_token", seen)
        store.set_meta("ad_synced_at", seen)
        store.set_meta(
            "ad_status",
            f"{len(computer_rows)} computers, {len(ou_rows)} OUs, {len(group_rows)} groups, {len(user_rows)} users",
        )
    store.log("ad", f"Directory sync: {store.get_meta('ad_status')}")
    return {
        "computers": len(computer_rows),
        "ous": len(ou_rows),
        "groups": len(group_rows),
        "users": len(user_rows),
    }
