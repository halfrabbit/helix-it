from __future__ import annotations

import os
import sqlite3
import threading
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT,
    department TEXT,
    title TEXT,
    ad_dn TEXT,
    ad_guid TEXT
);

CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    hostname TEXT,
    ip TEXT,
    mac TEXT,
    type TEXT NOT NULL DEFAULT 'computer',
    os TEXT,
    manufacturer TEXT,
    model TEXT,
    serial TEXT,
    status TEXT NOT NULL DEFAULT 'unknown',
    last_seen TEXT,
    notes TEXT,
    cpu TEXT,
    ram_gb REAL,
    disk_gb REAL,
    owner_id INTEGER REFERENCES people(id),
    discovered INTEGER NOT NULL DEFAULT 0,
    dn TEXT,
    ou TEXT,
    ad_guid TEXT,
    os_version TEXT,
    architecture TEXT,
    domain TEXT,
    last_boot TEXT,
    scan_status TEXT,
    scan_error TEXT,
    description TEXT,
    ad_disabled INTEGER NOT NULL DEFAULT 0,
    ad_seen TEXT,
    last_scan TEXT,
    current_user TEXT,
    hardware_json TEXT,
    custom_scan TEXT
);

CREATE TABLE IF NOT EXISTS software (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    version TEXT,
    publisher TEXT
);

CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number INTEGER NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    priority TEXT NOT NULL DEFAULT 'medium',
    requester_id INTEGER REFERENCES people(id),
    assignee TEXT,
    device_id INTEGER REFERENCES devices(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    author TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ad_ous (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dn TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    parent_dn TEXT
);

CREATE TABLE IF NOT EXISTS ad_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dn TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS device_groups (
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    group_dn TEXT NOT NULL,
    group_name TEXT,
    PRIMARY KEY (device_id, group_dn)
);

CREATE TABLE IF NOT EXISTS hotfixes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    hotfix_id TEXT NOT NULL,
    description TEXT,
    installed_on TEXT
);

CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    display_name TEXT,
    status TEXT,
    start_mode TEXT
);

CREATE TABLE IF NOT EXISTS disks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    name TEXT,
    size_gb REAL,
    free_gb REAL,
    filesystem TEXT
);

CREATE TABLE IF NOT EXISTS nics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    name TEXT,
    mac TEXT,
    ip TEXT,
    speed_mbps INTEGER
);

CREATE TABLE IF NOT EXISTS local_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    disabled INTEGER NOT NULL DEFAULT 0,
    full_name TEXT
);

CREATE TABLE IF NOT EXISTS shares (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    path TEXT,
    description TEXT
);

CREATE TABLE IF NOT EXISTS printers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    driver TEXT,
    port TEXT
);

CREATE TABLE IF NOT EXISTS startup_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    command TEXT,
    location TEXT
);

CREATE TABLE IF NOT EXISTS collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL DEFAULT 'dynamic',
    description TEXT,
    match_mode TEXT NOT NULL DEFAULT 'all'
);

CREATE TABLE IF NOT EXISTS collection_filters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    field TEXT NOT NULL,
    op TEXT NOT NULL,
    value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS collection_members (
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    PRIMARY KEY (collection_id, device_id)
);

CREATE TABLE IF NOT EXISTS scan_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    software INTEGER NOT NULL DEFAULT 1,
    hotfixes INTEGER NOT NULL DEFAULT 1,
    services INTEGER NOT NULL DEFAULT 1,
    hardware INTEGER NOT NULL DEFAULT 1,
    users INTEGER NOT NULL DEFAULT 1,
    shares INTEGER NOT NULL DEFAULT 1,
    printers INTEGER NOT NULL DEFAULT 1,
    startup INTEGER NOT NULL DEFAULT 1,
    custom_script TEXT
);

CREATE TABLE IF NOT EXISTS packages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    version TEXT,
    description TEXT,
    timeout_sec INTEGER NOT NULL DEFAULT 3600,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS package_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    package_id INTEGER NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    payload TEXT,
    args TEXT,
    success_codes TEXT NOT NULL DEFAULT '0',
    condition_field TEXT,
    condition_op TEXT,
    condition_value TEXT,
    continue_on_error INTEGER NOT NULL DEFAULT 0,
    nested_package_id INTEGER
);

CREATE TABLE IF NOT EXISTS deployments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    package_id INTEGER NOT NULL REFERENCES packages(id),
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    schedule_id INTEGER,
    credential TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS deployment_targets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deployment_id INTEGER NOT NULL REFERENCES deployments(id) ON DELETE CASCADE,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'queued',
    started_at TEXT,
    finished_at TEXT,
    log TEXT NOT NULL DEFAULT '',
    exit_code INTEGER
);

CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    trigger TEXT NOT NULL,
    package_id INTEGER,
    collection_id INTEGER,
    interval_minutes INTEGER,
    time_of_day TEXT,
    credential TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    next_run TEXT,
    last_run TEXT
);

CREATE TABLE IF NOT EXISTS agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

DEVICE_EXTRA = {
    "dn": "TEXT",
    "ou": "TEXT",
    "ad_guid": "TEXT",
    "os_version": "TEXT",
    "architecture": "TEXT",
    "domain": "TEXT",
    "last_boot": "TEXT",
    "scan_status": "TEXT",
    "scan_error": "TEXT",
    "description": "TEXT",
    "ad_disabled": "INTEGER NOT NULL DEFAULT 0",
    "ad_seen": "TEXT",
    "last_scan": "TEXT",
    "current_user": "TEXT",
    "hardware_json": "TEXT",
    "custom_scan": "TEXT",
}

PEOPLE_EXTRA = {
    "ad_dn": "TEXT",
    "ad_guid": "TEXT",
}

CHILD_COLUMNS = {
    "software": ("name", "version", "publisher"),
    "hotfixes": ("hotfix_id", "description", "installed_on"),
    "services": ("name", "display_name", "status", "start_mode"),
    "disks": ("name", "size_gb", "free_gb", "filesystem"),
    "nics": ("name", "mac", "ip", "speed_mbps"),
    "local_users": ("name", "disabled", "full_name"),
    "shares": ("name", "path", "description"),
    "printers": ("name", "driver", "port"),
    "startup_items": ("name", "command", "location"),
}


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def data_dir() -> Path:
    override = os.environ.get("HELIX_DATA")
    path = Path(override) if override else Path.home() / ".local/share/helix-it"
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


class Store:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or data_dir() / "helix.db"
        self._lock = threading.RLock()
        self._tx = 0
        self.conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 10000")
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self._migrate()
        self.ensure_builtin()

    def close(self) -> None:
        self.conn.close()

    def _columns(self, table: str) -> set[str]:
        return {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}

    def _add_columns(self, table: str, columns: dict[str, str]) -> None:
        have = self._columns(table)
        for name, decl in columns.items():
            if name not in have:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

    def _migrate(self) -> None:
        self._add_columns("devices", DEVICE_EXTRA)
        self._add_columns("people", PEOPLE_EXTRA)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_devices_guid ON devices(ad_guid)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_devices_host ON devices(hostname)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_software_device ON software(device_id)")
        self.conn.commit()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        outer = self._tx == 0
        if outer:
            self._lock.acquire()
        self._tx += 1
        try:
            yield
            if outer:
                self.conn.commit()
        except BaseException:
            if outer:
                self.conn.rollback()
            raise
        finally:
            self._tx = max(0, self._tx - 1)
            if outer:
                self._lock.release()

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.fetchone("SELECT value FROM meta WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        self.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def fetchall(self, sql: str, args: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self.conn.execute(sql, args).fetchall())

    def fetchone(self, sql: str, args: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self.conn.execute(sql, args).fetchone()

    def execute(self, sql: str, args: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.execute(sql, args)
            if self._tx == 0:
                self.conn.commit()
            return cur

    def executemany(self, sql: str, rows: list[tuple[Any, ...]]) -> None:
        with self._lock:
            self.conn.executemany(sql, rows)
            if self._tx == 0:
                self.conn.commit()

    def stats(self) -> dict[str, int]:
        def count(sql: str) -> int:
            return int(self.fetchone(sql)[0])

        return {
            "devices": count("SELECT COUNT(*) FROM devices"),
            "online": count("SELECT COUNT(*) FROM devices WHERE status = 'online'"),
            "offline": count("SELECT COUNT(*) FROM devices WHERE status = 'offline'"),
            "open_tickets": count(
                "SELECT COUNT(*) FROM tickets WHERE status IN ('new', 'open', 'waiting')"
            ),
            "critical": count(
                "SELECT COUNT(*) FROM tickets WHERE status != 'closed' AND priority = 'critical'"
            ),
            "people": count("SELECT COUNT(*) FROM people"),
            "software": count("SELECT COUNT(DISTINCT name) FROM software"),
            "directory": count("SELECT COUNT(*) FROM devices WHERE IFNULL(dn, '') != ''"),
            "windows": count("SELECT COUNT(*) FROM devices WHERE os LIKE '%Windows%'"),
            "scan_failed": count("SELECT COUNT(*) FROM devices WHERE scan_status = 'failed'"),
            "deployments": count("SELECT COUNT(*) FROM deployments"),
            "deploy_failed": count("SELECT COUNT(*) FROM deployment_targets WHERE status = 'failed'"),
        }

    def devices(self, type_filter: str | None = None, search: str = "") -> list[sqlite3.Row]:
        sql = "SELECT d.*, p.name AS owner_name FROM devices d LEFT JOIN people p ON p.id = d.owner_id"
        clauses: list[str] = []
        args: list[Any] = []
        if type_filter and type_filter != "all":
            clauses.append("d.type = ?")
            args.append(type_filter)
        if search:
            clauses.append(
                "(d.name LIKE ? OR IFNULL(d.hostname,'') LIKE ? OR IFNULL(d.ip,'') LIKE ? OR IFNULL(d.os,'') LIKE ? OR IFNULL(d.ou,'') LIKE ? OR IFNULL(d.domain,'') LIKE ?)"
            )
            term = f"%{search}%"
            args.extend([term, term, term, term, term, term])
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY d.name COLLATE NOCASE"
        return self.fetchall(sql, tuple(args))

    def device(self, device_id: int) -> sqlite3.Row | None:
        return self.fetchone(
            "SELECT d.*, p.name AS owner_name FROM devices d LEFT JOIN people p ON p.id = d.owner_id WHERE d.id = ?",
            (device_id,),
        )

    def upsert_discovered(
        self,
        *,
        name: str,
        ip: str | None,
        mac: str | None,
        hostname: str | None,
        status: str,
        device_type: str = "computer",
    ) -> int:
        row = None
        if mac:
            row = self.fetchone("SELECT id FROM devices WHERE mac = ?", (mac.lower(),))
        if row is None and ip:
            row = self.fetchone("SELECT id FROM devices WHERE ip = ?", (ip,))
        now = utcnow()
        if row:
            self.execute(
                """UPDATE devices SET name = COALESCE(NULLIF(?, ''), name), ip = ?, mac = COALESCE(?, mac),
                   hostname = COALESCE(?, hostname), status = ?, last_seen = ?, discovered = 1 WHERE id = ?""",
                (name, ip, mac.lower() if mac else None, hostname, status, now, row["id"]),
            )
            return int(row["id"])
        cur = self.execute(
            """INSERT INTO devices(name, hostname, ip, mac, type, status, last_seen, discovered)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
            (name, hostname, ip, mac.lower() if mac else None, device_type, status, now),
        )
        self.log("scan", f"Discovered {name}" + (f" ({ip})" if ip else ""))
        return int(cur.lastrowid)

    def add_device(self, **fields: Any) -> int:
        cols = ", ".join(fields)
        placeholders = ", ".join("?" for _ in fields)
        cur = self.execute(f"INSERT INTO devices({cols}) VALUES({placeholders})", tuple(fields.values()))
        self.log("inventory", f"Added device {fields.get('name', cur.lastrowid)}")
        return int(cur.lastrowid)

    def update_device(self, device_id: int, **fields: Any) -> None:
        assignments = ", ".join(f"{k} = ?" for k in fields)
        self.execute(f"UPDATE devices SET {assignments} WHERE id = ?", (*fields.values(), device_id))

    def delete_device(self, device_id: int) -> None:
        row = self.device(device_id)
        self.execute("DELETE FROM software WHERE device_id = ?", (device_id,))
        self.execute("UPDATE tickets SET device_id = NULL WHERE device_id = ?", (device_id,))
        self.execute("DELETE FROM devices WHERE id = ?", (device_id,))
        if row:
            self.log("inventory", f"Removed device {row['name']}")

    def device_software(self, device_id: int) -> list[sqlite3.Row]:
        return self.fetchall(
            "SELECT * FROM software WHERE device_id = ? ORDER BY name COLLATE NOCASE",
            (device_id,),
        )

    def software_summary(self, search: str = "") -> list[sqlite3.Row]:
        sql = """SELECT name, MAX(publisher) AS publisher, COUNT(*) AS installs,
                        GROUP_CONCAT(DISTINCT version) AS versions
                 FROM software"""
        args: tuple[Any, ...] = ()
        if search:
            sql += " WHERE name LIKE ? OR IFNULL(publisher,'') LIKE ?"
            term = f"%{search}%"
            args = (term, term)
        sql += " GROUP BY name ORDER BY installs DESC, name COLLATE NOCASE"
        return self.fetchall(sql, args)

    def people(self, search: str = "") -> list[sqlite3.Row]:
        if search:
            term = f"%{search}%"
            return self.fetchall(
                """SELECT p.*, (SELECT COUNT(*) FROM devices d WHERE d.owner_id = p.id) AS devices,
                          (SELECT COUNT(*) FROM tickets t WHERE t.requester_id = p.id AND t.status != 'closed') AS open_tickets
                   FROM people p
                   WHERE p.name LIKE ? OR IFNULL(p.email,'') LIKE ? OR IFNULL(p.department,'') LIKE ?
                   ORDER BY p.name COLLATE NOCASE""",
                (term, term, term),
            )
        return self.fetchall(
            """SELECT p.*, (SELECT COUNT(*) FROM devices d WHERE d.owner_id = p.id) AS devices,
                      (SELECT COUNT(*) FROM tickets t WHERE t.requester_id = p.id AND t.status != 'closed') AS open_tickets
               FROM people p ORDER BY p.name COLLATE NOCASE"""
        )

    def person(self, person_id: int) -> sqlite3.Row | None:
        return self.fetchone("SELECT * FROM people WHERE id = ?", (person_id,))

    def add_person(self, name: str, email: str, department: str, title: str) -> int:
        cur = self.execute(
            "INSERT INTO people(name, email, department, title) VALUES (?, ?, ?, ?)",
            (name, email, department, title),
        )
        return int(cur.lastrowid)

    def next_ticket_number(self) -> int:
        row = self.fetchone("SELECT COALESCE(MAX(number), 1000) FROM tickets")
        return int(row[0]) + 1

    def tickets(self, status: str | None = None, search: str = "") -> list[sqlite3.Row]:
        sql = """SELECT t.*, p.name AS requester, d.name AS device_name
                 FROM tickets t
                 LEFT JOIN people p ON p.id = t.requester_id
                 LEFT JOIN devices d ON d.id = t.device_id"""
        clauses: list[str] = []
        args: list[Any] = []
        if status and status != "all":
            if status == "active":
                clauses.append("t.status IN ('new', 'open', 'waiting')")
            else:
                clauses.append("t.status = ?")
                args.append(status)
        if search:
            clauses.append("(t.title LIKE ? OR CAST(t.number AS TEXT) LIKE ?)")
            term = f"%{search}%"
            args.extend([term, term])
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY CASE t.priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, t.updated_at DESC"
        return self.fetchall(sql, tuple(args))

    def ticket(self, ticket_id: int) -> sqlite3.Row | None:
        return self.fetchone(
            """SELECT t.*, p.name AS requester, d.name AS device_name
               FROM tickets t
               LEFT JOIN people p ON p.id = t.requester_id
               LEFT JOIN devices d ON d.id = t.device_id
               WHERE t.id = ?""",
            (ticket_id,),
        )

    def add_ticket(
        self,
        title: str,
        description: str,
        priority: str,
        requester_id: int | None,
        assignee: str,
        device_id: int | None,
    ) -> int:
        now = utcnow()
        number = self.next_ticket_number()
        cur = self.execute(
            """INSERT INTO tickets(number, title, description, status, priority, requester_id, assignee, device_id, created_at, updated_at)
               VALUES (?, ?, ?, 'open', ?, ?, ?, ?, ?, ?)""",
            (number, title, description, priority, requester_id, assignee or None, device_id, now, now),
        )
        self.log("ticket", f"Opened #{number}: {title}")
        return int(cur.lastrowid)

    def update_ticket(self, ticket_id: int, **fields: Any) -> None:
        fields["updated_at"] = utcnow()
        assignments = ", ".join(f"{k} = ?" for k in fields)
        self.execute(f"UPDATE tickets SET {assignments} WHERE id = ?", (*fields.values(), ticket_id))
        ticket = self.ticket(ticket_id)
        if ticket and "status" in fields:
            self.log("ticket", f"#{ticket['number']} → {fields['status']}")

    def comments(self, ticket_id: int) -> list[sqlite3.Row]:
        return self.fetchall(
            "SELECT * FROM comments WHERE ticket_id = ? ORDER BY created_at",
            (ticket_id,),
        )

    def add_comment(self, ticket_id: int, author: str, body: str) -> None:
        self.execute(
            "INSERT INTO comments(ticket_id, author, body, created_at) VALUES (?, ?, ?, ?)",
            (ticket_id, author, body, utcnow()),
        )
        self.execute("UPDATE tickets SET updated_at = ? WHERE id = ?", (utcnow(), ticket_id))

    def activity(self, limit: int = 12) -> list[sqlite3.Row]:
        return self.fetchall("SELECT * FROM activity ORDER BY id DESC LIMIT ?", (limit,))

    def log(self, kind: str, message: str) -> None:
        self.execute(
            "INSERT INTO activity(kind, message, created_at) VALUES (?, ?, ?)",
            (kind, message, utcnow()),
        )

    def type_counts(self) -> list[tuple[str, int]]:
        rows = self.fetchall("SELECT type, COUNT(*) AS n FROM devices GROUP BY type ORDER BY n DESC")
        return [(r["type"], int(r["n"])) for r in rows]

    def ticket_priority_counts(self) -> list[tuple[str, int]]:
        rows = self.fetchall(
            "SELECT priority, COUNT(*) AS n FROM tickets WHERE status != 'closed' GROUP BY priority"
        )
        return [(r["priority"], int(r["n"])) for r in rows]

    def os_counts(self) -> list[tuple[str, int]]:
        rows = self.fetchall(
            """SELECT COALESCE(NULLIF(os, ''), 'Unknown') AS os, COUNT(*) AS n
               FROM devices GROUP BY 1 ORDER BY n DESC LIMIT 8"""
        )
        return [(r["os"], int(r["n"])) for r in rows]

    def reset_demo(self) -> None:
        tables = (
            "deployment_targets",
            "deployments",
            "package_steps",
            "schedules",
            "packages",
            "collection_filters",
            "collection_members",
            "collections",
            "comments",
            "tickets",
            "software",
            "hotfixes",
            "services",
            "disks",
            "nics",
            "local_users",
            "shares",
            "printers",
            "startup_items",
            "device_groups",
            "devices",
            "ad_ous",
            "ad_groups",
            "people",
            "activity",
            "meta",
        )
        with self.transaction():
            for table in tables:
                self.execute(f"DELETE FROM {table}")

    def ensure_builtin(self) -> None:
        if not self.fetchone("SELECT id FROM scan_profiles LIMIT 1"):
            self.execute("INSERT INTO scan_profiles(name) VALUES ('Default')")
        if self.get_meta("builtins") == "1":
            return
        if not self.fetchone("SELECT id FROM collections LIMIT 1"):
            workstations = self.add_collection(
                "Windows workstations",
                "dynamic",
                "Operating system contains Windows and is not a server.",
                "all",
            )
            self.add_filter(workstations, "os", "contains", "Windows")
            self.add_filter(workstations, "os", "not_contains", "Server")
            servers = self.add_collection(
                "Windows servers",
                "dynamic",
                "Operating system contains Server.",
                "all",
            )
            self.add_filter(servers, "os", "contains", "Server")
            offline = self.add_collection("Offline", "dynamic", "Last status was offline.", "all")
            self.add_filter(offline, "status", "equals", "offline")
            failed = self.add_collection("Scan failed", "dynamic", "The last inventory scan failed.", "all")
            self.add_filter(failed, "scan_status", "equals", "failed")
        if not self.fetchone("SELECT id FROM packages LIMIT 1"):
            package_id = self.add_package(
                "Helix connectivity check",
                "1",
                "Prints a line on the target. Use it to prove WinRM, or run it on this Linux console.",
                120,
            )
            self.add_step(
                package_id,
                kind="command",
                name="Echo",
                payload="echo Helix connectivity check",
                success_codes="0",
            )
        self.set_meta("builtins", "1")

    def scan_profile(self) -> sqlite3.Row:
        row = self.fetchone("SELECT * FROM scan_profiles ORDER BY id LIMIT 1")
        if row:
            return row
        self.execute("INSERT INTO scan_profiles(name) VALUES ('Default')")
        return self.fetchone("SELECT * FROM scan_profiles ORDER BY id LIMIT 1")

    def update_scan_profile(self, **fields: Any) -> None:
        profile = self.scan_profile()
        assignments = ", ".join(f"{key} = ?" for key in fields)
        self.execute(
            f"UPDATE scan_profiles SET {assignments} WHERE id = ?",
            (*fields.values(), profile["id"]),
        )

    def replace_device_rows(self, table: str, device_id: int, rows: list[dict[str, Any]]) -> None:
        columns = CHILD_COLUMNS[table]
        placeholders = ", ".join("?" for _ in ("device_id", *columns))
        names = ", ".join(("device_id", *columns))
        with self.transaction():
            self.execute(f"DELETE FROM {table} WHERE device_id = ?", (device_id,))
            payload = []
            for row in rows:
                payload.append(tuple([device_id, *[row.get(column) for column in columns]]))
            if payload:
                self.executemany(
                    f"INSERT INTO {table}({names}) VALUES ({placeholders})",
                    payload,
                )

    def child_rows(self, table: str, device_id: int) -> list[sqlite3.Row]:
        if table not in CHILD_COLUMNS:
            raise KeyError(table)
        return self.fetchall(
            f"SELECT * FROM {table} WHERE device_id = ? ORDER BY id",
            (device_id,),
        )

    def inventory_facts(self) -> list[dict[str, Any]]:
        software: dict[int, set[str]] = defaultdict(set)
        hotfixes: dict[int, set[str]] = defaultdict(set)
        groups: dict[int, set[str]] = defaultdict(set)
        for row in self.fetchall("SELECT device_id, name FROM software"):
            if row["name"]:
                software[int(row["device_id"])].add(str(row["name"]).lower())
        for row in self.fetchall("SELECT device_id, hotfix_id FROM hotfixes"):
            if row["hotfix_id"]:
                hotfixes[int(row["device_id"])].add(str(row["hotfix_id"]).lower())
        for row in self.fetchall("SELECT device_id, group_dn, group_name FROM device_groups"):
            bucket = groups[int(row["device_id"])]
            if row["group_name"]:
                bucket.add(str(row["group_name"]).lower())
            if row["group_dn"]:
                bucket.add(str(row["group_dn"]).lower())
        from helix_it.collections import TEXT_FIELDS

        facts = []
        for device in self.devices():
            text = {}
            for field in TEXT_FIELDS:
                try:
                    value = device[field]
                except (KeyError, IndexError):
                    value = ""
                text[field] = "" if value is None else str(value)
            device_id = int(device["id"])
            facts.append(
                {
                    "id": device_id,
                    "text": text,
                    "lists": {
                        "software": software[device_id],
                        "hotfix": hotfixes[device_id],
                        "group": groups[device_id],
                    },
                }
            )
        return facts

    def fact_for(self, device_id: int) -> dict[str, Any] | None:
        for fact in self.inventory_facts():
            if fact["id"] == device_id:
                return fact
        return None

    def collections(self) -> list[sqlite3.Row]:
        return self.fetchall("SELECT * FROM collections ORDER BY name COLLATE NOCASE")

    def collection(self, collection_id: int) -> sqlite3.Row | None:
        return self.fetchone("SELECT * FROM collections WHERE id = ?", (collection_id,))

    def add_collection(self, name: str, kind: str, description: str, match_mode: str) -> int:
        cur = self.execute(
            "INSERT INTO collections(name, kind, description, match_mode) VALUES (?, ?, ?, ?)",
            (name, kind, description, match_mode),
        )
        self.log("collection", f"Created collection {name}")
        return int(cur.lastrowid)

    def update_collection(self, collection_id: int, **fields: Any) -> None:
        assignments = ", ".join(f"{key} = ?" for key in fields)
        self.execute(
            f"UPDATE collections SET {assignments} WHERE id = ?",
            (*fields.values(), collection_id),
        )

    def delete_collection(self, collection_id: int) -> None:
        row = self.collection(collection_id)
        self.execute("DELETE FROM schedules WHERE collection_id = ?", (collection_id,))
        self.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
        if row:
            self.log("collection", f"Removed collection {row['name']}")

    def collection_filters(self, collection_id: int) -> list[sqlite3.Row]:
        return self.fetchall(
            "SELECT * FROM collection_filters WHERE collection_id = ? ORDER BY id",
            (collection_id,),
        )

    def add_filter(self, collection_id: int, field: str, op: str, value: str) -> int:
        cur = self.execute(
            "INSERT INTO collection_filters(collection_id, field, op, value) VALUES (?, ?, ?, ?)",
            (collection_id, field, op, value),
        )
        return int(cur.lastrowid)

    def delete_filter(self, filter_id: int) -> None:
        self.execute("DELETE FROM collection_filters WHERE id = ?", (filter_id,))

    def add_member(self, collection_id: int, device_id: int) -> None:
        self.execute(
            "INSERT OR IGNORE INTO collection_members(collection_id, device_id) VALUES (?, ?)",
            (collection_id, device_id),
        )

    def remove_member(self, collection_id: int, device_id: int) -> None:
        self.execute(
            "DELETE FROM collection_members WHERE collection_id = ? AND device_id = ?",
            (collection_id, device_id),
        )

    def static_member_ids(self, collection_id: int) -> set[int]:
        rows = self.fetchall(
            "SELECT device_id FROM collection_members WHERE collection_id = ?",
            (collection_id,),
        )
        return {int(row["device_id"]) for row in rows}

    def collection_device_ids(self, collection_id: int) -> list[int]:
        from helix_it.collections import select_ids

        col = self.collection(collection_id)
        if not col:
            return []
        filters = [(row["field"], row["op"], row["value"]) for row in self.collection_filters(collection_id)]
        return select_ids(
            col["kind"],
            col["match_mode"],
            filters,
            self.static_member_ids(collection_id),
            self.inventory_facts(),
        )

    def collection_devices(self, collection_id: int) -> list[sqlite3.Row]:
        ids = set(self.collection_device_ids(collection_id))
        return [row for row in self.devices() if int(row["id"]) in ids]

    def packages(self) -> list[sqlite3.Row]:
        return self.fetchall("SELECT * FROM packages ORDER BY name COLLATE NOCASE")

    def package(self, package_id: int) -> sqlite3.Row | None:
        return self.fetchone("SELECT * FROM packages WHERE id = ?", (package_id,))

    def add_package(self, name: str, version: str, description: str, timeout_sec: int = 3600) -> int:
        cur = self.execute(
            "INSERT INTO packages(name, version, description, timeout_sec, created_at) VALUES (?, ?, ?, ?, ?)",
            (name, version, description, timeout_sec, utcnow()),
        )
        self.log("deploy", f"Created package {name}")
        return int(cur.lastrowid)

    def update_package(self, package_id: int, **fields: Any) -> None:
        assignments = ", ".join(f"{key} = ?" for key in fields)
        self.execute(f"UPDATE packages SET {assignments} WHERE id = ?", (*fields.values(), package_id))

    def delete_package(self, package_id: int) -> str | None:
        used = self.fetchone("SELECT COUNT(*) FROM deployments WHERE package_id = ?", (package_id,))
        if used and int(used[0]):
            return "This package has deployment history, so it stays in the library."
        row = self.package(package_id)
        self.execute("DELETE FROM schedules WHERE package_id = ?", (package_id,))
        self.execute("UPDATE package_steps SET nested_package_id = NULL WHERE nested_package_id = ?", (package_id,))
        self.execute("DELETE FROM packages WHERE id = ?", (package_id,))
        if row:
            self.log("deploy", f"Removed package {row['name']}")
        return None

    def package_steps(self, package_id: int) -> list[sqlite3.Row]:
        return self.fetchall(
            "SELECT * FROM package_steps WHERE package_id = ? ORDER BY position, id",
            (package_id,),
        )

    def add_step(self, package_id: int, **fields: Any) -> int:
        position = fields.pop("position", None)
        if position is None:
            row = self.fetchone(
                "SELECT COALESCE(MAX(position), 0) FROM package_steps WHERE package_id = ?",
                (package_id,),
            )
            position = int(row[0]) + 1
        columns = ["package_id", "position", *fields.keys()]
        values = [package_id, position, *fields.values()]
        placeholders = ", ".join("?" for _ in columns)
        cur = self.execute(
            f"INSERT INTO package_steps({', '.join(columns)}) VALUES ({placeholders})",
            tuple(values),
        )
        return int(cur.lastrowid)

    def update_step(self, step_id: int, **fields: Any) -> None:
        assignments = ", ".join(f"{key} = ?" for key in fields)
        self.execute(f"UPDATE package_steps SET {assignments} WHERE id = ?", (*fields.values(), step_id))

    def delete_step(self, step_id: int) -> None:
        row = self.fetchone("SELECT package_id FROM package_steps WHERE id = ?", (step_id,))
        self.execute("DELETE FROM package_steps WHERE id = ?", (step_id,))
        if not row:
            return
        steps = self.package_steps(int(row["package_id"]))
        for index, step in enumerate(steps, start=1):
            self.execute("UPDATE package_steps SET position = ? WHERE id = ?", (index, step["id"]))

    def move_step(self, step_id: int, direction: int) -> None:
        row = self.fetchone("SELECT * FROM package_steps WHERE id = ?", (step_id,))
        if not row:
            return
        steps = self.package_steps(int(row["package_id"]))
        index = next(i for i, step in enumerate(steps) if int(step["id"]) == step_id)
        swap = index + direction
        if swap < 0 or swap >= len(steps):
            return
        current = steps[index]
        other = steps[swap]
        with self.transaction():
            self.execute("UPDATE package_steps SET position = ? WHERE id = ?", (other["position"], current["id"]))
            self.execute("UPDATE package_steps SET position = ? WHERE id = ?", (current["position"], other["id"]))

    def deployments(self, limit: int = 40) -> list[sqlite3.Row]:
        return self.fetchall(
            """SELECT d.*, p.name AS package_name
               FROM deployments d JOIN packages p ON p.id = d.package_id
               ORDER BY d.id DESC LIMIT ?""",
            (limit,),
        )

    def deployment(self, deployment_id: int) -> sqlite3.Row | None:
        return self.fetchone(
            """SELECT d.*, p.name AS package_name, p.timeout_sec
               FROM deployments d JOIN packages p ON p.id = d.package_id
               WHERE d.id = ?""",
            (deployment_id,),
        )

    def create_deployment(
        self,
        package_id: int,
        name: str,
        device_ids: list[int],
        credential: str | None,
        schedule_id: int | None = None,
    ) -> int:
        with self.transaction():
            cur = self.execute(
                """INSERT INTO deployments(package_id, name, status, schedule_id, credential, created_at)
                   VALUES (?, ?, 'queued', ?, ?, ?)""",
                (package_id, name, schedule_id, credential, utcnow()),
            )
            deployment_id = int(cur.lastrowid)
            self.executemany(
                "INSERT INTO deployment_targets(deployment_id, device_id, status, log) VALUES (?, ?, 'queued', '')",
                [(deployment_id, device_id) for device_id in device_ids],
            )
        return deployment_id

    def deployment_targets(self, deployment_id: int) -> list[sqlite3.Row]:
        return self.fetchall(
            """SELECT t.*, d.name AS device_name, d.hostname, d.ip
               FROM deployment_targets t JOIN devices d ON d.id = t.device_id
               WHERE t.deployment_id = ? ORDER BY d.name COLLATE NOCASE""",
            (deployment_id,),
        )

    def update_target(self, target_id: int, **fields: Any) -> None:
        assignments = ", ".join(f"{key} = ?" for key in fields)
        self.execute(
            f"UPDATE deployment_targets SET {assignments} WHERE id = ?",
            (*fields.values(), target_id),
        )

    def requeue_failed(self, deployment_id: int) -> int:
        row = self.fetchone(
            "SELECT COUNT(*) FROM deployment_targets WHERE deployment_id = ? AND status = 'failed'",
            (deployment_id,),
        )
        self.execute(
            """UPDATE deployment_targets
               SET status = 'queued', finished_at = NULL, exit_code = NULL
               WHERE deployment_id = ? AND status = 'failed'""",
            (deployment_id,),
        )
        self.execute(
            "UPDATE deployments SET status = 'queued', finished_at = NULL WHERE id = ?",
            (deployment_id,),
        )
        return int(row[0]) if row else 0

    def package_succeeded(self, package_id: int, device_id: int) -> bool:
        row = self.fetchone(
            """SELECT 1 FROM deployment_targets t
               JOIN deployments d ON d.id = t.deployment_id
               WHERE d.package_id = ? AND t.device_id = ? AND t.status = 'success' LIMIT 1""",
            (package_id, device_id),
        )
        return row is not None

    def schedules(self) -> list[sqlite3.Row]:
        return self.fetchall("SELECT * FROM schedules ORDER BY name COLLATE NOCASE")

    def schedule(self, schedule_id: int) -> sqlite3.Row | None:
        return self.fetchone("SELECT * FROM schedules WHERE id = ?", (schedule_id,))

    def add_schedule(self, **fields: Any) -> int:
        columns = ", ".join(fields)
        placeholders = ", ".join("?" for _ in fields)
        cur = self.execute(
            f"INSERT INTO schedules({columns}) VALUES ({placeholders})",
            tuple(fields.values()),
        )
        return int(cur.lastrowid)

    def update_schedule(self, schedule_id: int, **fields: Any) -> None:
        assignments = ", ".join(f"{key} = ?" for key in fields)
        self.execute(f"UPDATE schedules SET {assignments} WHERE id = ?", (*fields.values(), schedule_id))

    def delete_schedule(self, schedule_id: int) -> None:
        self.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))

    def due_schedules(self, now_iso: str) -> list[sqlite3.Row]:
        return self.fetchall(
            """SELECT * FROM schedules
               WHERE enabled = 1 AND trigger != 'heartbeat'
                 AND (next_run IS NULL OR next_run <= ?)
               ORDER BY id""",
            (now_iso,),
        )

    def heartbeat_schedules(self) -> list[sqlite3.Row]:
        return self.fetchall(
            "SELECT * FROM schedules WHERE enabled = 1 AND trigger = 'heartbeat' AND kind = 'deploy'"
        )

    def rollup_deployment(self, deployment_id: int) -> str:
        rows = self.fetchall(
            "SELECT status FROM deployment_targets WHERE deployment_id = ?",
            (deployment_id,),
        )
        states = {row["status"] for row in rows}
        if not rows or "failed" in states:
            status = "failed" if rows else "failed"
        elif states <= {"success"}:
            status = "success"
        elif "queued" in states or "running" in states or "copying" in states:
            status = "running"
        else:
            status = "failed"
        if not rows:
            status = "failed"
        finished = None if status == "running" else utcnow()
        self.execute(
            "UPDATE deployments SET status = ?, finished_at = ? WHERE id = ?",
            (status, finished, deployment_id),
        )
        return status

    def scan_status_counts(self) -> list[tuple[str, int]]:
        rows = self.fetchall(
            """SELECT COALESCE(NULLIF(scan_status, ''), 'never') AS scan_status, COUNT(*) AS n
               FROM devices GROUP BY 1 ORDER BY n DESC"""
        )
        return [(row["scan_status"], int(row["n"])) for row in rows]

    def deployment_status_counts(self) -> list[tuple[str, int]]:
        rows = self.fetchall(
            "SELECT status, COUNT(*) AS n FROM deployment_targets GROUP BY status ORDER BY n DESC"
        )
        return [(row["status"], int(row["n"])) for row in rows]

    def directory_counts(self) -> dict[str, int]:
        def count(sql: str) -> int:
            return int(self.fetchone(sql)[0])

        return {
            "ous": count("SELECT COUNT(*) FROM ad_ous"),
            "groups": count("SELECT COUNT(*) FROM ad_groups"),
            "computers": count("SELECT COUNT(*) FROM devices WHERE IFNULL(dn, '') != ''"),
        }

    def upsert_ad_computer(self, rec: dict[str, Any], seen: str) -> int:
        row = None
        if rec.get("ad_guid"):
            row = self.fetchone("SELECT id FROM devices WHERE ad_guid = ?", (rec["ad_guid"],))
        if row is None and rec.get("hostname"):
            row = self.fetchone(
                "SELECT id FROM devices WHERE lower(hostname) = lower(?)",
                (rec["hostname"],),
            )
        if row is None and rec.get("name"):
            row = self.fetchone("SELECT id FROM devices WHERE lower(name) = lower(?)", (rec["name"],))
        fields = {
            "hostname": rec.get("hostname") or rec.get("name"),
            "dn": rec.get("dn"),
            "ou": rec.get("ou"),
            "ad_guid": rec.get("ad_guid"),
            "os": rec.get("os"),
            "os_version": rec.get("os_version"),
            "description": rec.get("description"),
            "domain": rec.get("domain"),
            "ad_disabled": int(rec.get("ad_disabled") or 0),
            "ad_seen": seen,
            "type": rec.get("type") or "computer",
        }
        if row:
            cleaned = {
                key: value
                for key, value in fields.items()
                if value is not None and not (value == "" and key != "ad_seen")
            }
            self.update_device(int(row["id"]), **cleaned)
            return int(row["id"])
        fields["name"] = rec.get("name") or rec.get("hostname") or "computer"
        fields["status"] = "unknown"
        fields["discovered"] = 0
        return self.add_device(**fields)

    def replace_ous(self, rows: list[tuple[str, str, str | None]]) -> None:
        self.execute("DELETE FROM ad_ous")
        if rows:
            self.executemany("INSERT INTO ad_ous(dn, name, parent_dn) VALUES (?, ?, ?)", rows)

    def replace_groups(self, rows: list[tuple[str, str, str | None]]) -> None:
        self.execute("DELETE FROM ad_groups")
        if rows:
            self.executemany(
                "INSERT INTO ad_groups(dn, name, description) VALUES (?, ?, ?)",
                rows,
            )

    def replace_device_groups(self, device_id: int, groups: list[tuple[str, str]]) -> None:
        self.execute("DELETE FROM device_groups WHERE device_id = ?", (device_id,))
        if groups:
            self.executemany(
                "INSERT INTO device_groups(device_id, group_dn, group_name) VALUES (?, ?, ?)",
                [(device_id, dn, name) for dn, name in groups],
            )

    def clear_device_groups(self) -> None:
        self.execute("DELETE FROM device_groups")

    def upsert_directory_user(self, rec: dict[str, Any]) -> None:
        row = None
        if rec.get("ad_guid"):
            row = self.fetchone("SELECT id FROM people WHERE ad_guid = ?", (rec["ad_guid"],))
        if row is None and rec.get("email"):
            row = self.fetchone(
                "SELECT id FROM people WHERE lower(email) = lower(?)",
                (rec["email"],),
            )
        if row:
            self.execute(
                """UPDATE people SET name = ?, email = ?, department = ?, title = ?, ad_dn = ?, ad_guid = ?
                   WHERE id = ?""",
                (
                    rec.get("name") or "Directory user",
                    rec.get("email"),
                    rec.get("department"),
                    rec.get("title"),
                    rec.get("ad_dn"),
                    rec.get("ad_guid"),
                    row["id"],
                ),
            )
            return
        self.execute(
            """INSERT INTO people(name, email, department, title, ad_dn, ad_guid)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                rec.get("name") or "Directory user",
                rec.get("email"),
                rec.get("department"),
                rec.get("title"),
                rec.get("ad_dn"),
                rec.get("ad_guid"),
            ),
        )

    def delete_stale_directory_computers(self) -> int:
        token = self.get_meta("ad_sync_token")
        if not token:
            return 0
        rows = self.fetchall(
            "SELECT id FROM devices WHERE ad_guid IS NOT NULL AND IFNULL(ad_seen, '') != ?",
            (token,),
        )
        for row in rows:
            self.delete_device(int(row["id"]))
        return len(rows)
