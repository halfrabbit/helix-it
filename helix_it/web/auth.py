from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path

from helix_it.db import Store, data_dir, utcnow


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return f"pbkdf2_sha256$200000${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt_hex, digest_hex = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        salt = bytes.fromhex(salt_hex)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(rounds))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def session_secret() -> bytes:
    path = data_dir() / "session.key"
    if path.exists():
        return path.read_bytes()
    key = secrets.token_bytes(32)
    path.write_bytes(key)
    os.chmod(path, 0o600)
    return key


def dumps(data: dict, key: bytes) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
    payload = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    sig = hmac.new(key, payload.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def loads(token: str, key: bytes) -> dict | None:
    if "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    expected = hmac.new(key, payload.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    pad = "=" * (-len(payload) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(payload + pad))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    exp = int(data.get("exp") or 0)
    if exp < int(__import__("time").time()):
        return None
    return data


def issue_session(username: str, csrf: str, key: bytes, hours: int = 18) -> str:
    exp = int(__import__("time").time()) + hours * 3600
    return dumps({"user": username, "csrf": csrf, "exp": exp}, key)


def ensure_admin(store: Store) -> Path | None:
    row = store.fetchone("SELECT id FROM agents LIMIT 1")
    if row:
        return None
    username = (os.environ.get("HELIX_ADMIN_USER") or "admin").strip() or "admin"
    password = os.environ.get("HELIX_ADMIN_PASSWORD") or ""
    generated = False
    if not password:
        password = secrets.token_urlsafe(12)
        generated = True
    store.execute(
        "INSERT INTO agents(username, display_name, password_hash, created_at) VALUES (?, ?, ?, ?)",
        (username, username, hash_password(password), utcnow()),
    )
    if not generated:
        print(f"Helix agent created from HELIX_ADMIN_USER ({username}).", flush=True)
        return None
    path = data_dir() / "initial-admin.txt"
    path.write_text(f"username={username}\npassword={password}\n", encoding="utf-8")
    os.chmod(path, 0o600)
    print(f"Helix admin password written to {path}", flush=True)
    return path


def authenticate(store: Store, username: str, password: str):
    row = store.fetchone("SELECT * FROM agents WHERE username = ?", (username.strip(),))
    if not row or not verify_password(password, row["password_hash"]):
        return None
    return row
