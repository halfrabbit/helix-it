from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from helix_it import ad, collections, deployer, remote, scanner, schedules, secrets
from helix_it.db import Store


OLD_DEVICES = """
CREATE TABLE devices (
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
    owner_id INTEGER,
    discovered INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT,
    department TEXT,
    title TEXT
);
"""


class EngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.store = Store(Path(self._dir.name) / "helix.db")

    def tearDown(self) -> None:
        self.store.close()
        self._dir.cleanup()

    def test_directory_helpers(self) -> None:
        self.assertEqual(ad.base_dn_from_domain("shop.local"), "DC=shop,DC=local")
        dn = r"CN=Smith\, John,OU=Finance,OU=People,DC=shop,DC=local"
        self.assertEqual(ad.cn_from_dn(dn), "Smith, John")
        self.assertEqual(ad.ou_from_dn(dn), "People/Finance")
        self.assertIsNone(ad.windows_time(0))
        self.assertTrue(ad.windows_time(116444736000000000).startswith("1970-01-01"))
        raw = bytes.fromhex("00112233445566778899aabbccddeeff")
        text = ad.guid_text(raw)
        self.assertEqual(len(text), 36)
        self.assertEqual(ad.is_disabled(2), 1)
        self.assertEqual(ad.is_disabled(512), 0)

    def test_migration_adds_directory_columns(self) -> None:
        self.store.close()
        path = Path(self._dir.name) / "old.db"
        conn = sqlite3.connect(path)
        conn.executescript(OLD_DEVICES)
        conn.commit()
        conn.close()
        upgraded = Store(path)
        names = {row["name"] for row in upgraded.conn.execute("PRAGMA table_info(devices)")}
        self.assertIn("ou", names)
        self.assertIn("ad_guid", names)
        self.assertIn("scan_status", names)
        people = {row["name"] for row in upgraded.conn.execute("PRAGMA table_info(people)")}
        self.assertIn("ad_dn", people)
        self.assertTrue(upgraded.collections())
        upgraded.close()

    def test_transaction_rolls_back(self) -> None:
        self.store.add_person("Ava", "ava@example.com", "IT", "Admin")
        with self.assertRaises(RuntimeError):
            with self.store.transaction():
                self.store.add_person("Bad", "bad@example.com", "IT", "Temp")
                raise RuntimeError("stop")
        names = [row["name"] for row in self.store.people()]
        self.assertIn("Ava", names)
        self.assertNotIn("Bad", names)

    def test_collections_match_windows_and_software(self) -> None:
        workstation = self.store.add_device(name="ws-a", os="Windows 11 Pro", type="computer", status="online")
        server = self.store.add_device(name="srv", os="Windows Server 2022", type="server", status="offline")
        windows = self.store.fetchone("SELECT id FROM collections WHERE name = ?", ("Windows workstations",))
        ids = self.store.collection_device_ids(int(windows["id"]))
        self.assertIn(workstation, ids)
        self.assertNotIn(server, ids)
        self.store.execute(
            "INSERT INTO software(device_id, name, version, publisher) VALUES (?, ?, ?, ?)",
            (workstation, "Google Chrome", "120", "Google"),
        )
        missing = self.store.add_collection("Missing Chrome", "dynamic", "", "all")
        self.store.add_filter(missing, "software", "missing", "chrome")
        missing_ids = self.store.collection_device_ids(missing)
        self.assertNotIn(workstation, missing_ids)
        self.assertIn(server, missing_ids)
        pinned = self.store.add_collection("Pinned", "static", "", "all")
        self.store.add_member(pinned, server)
        self.assertEqual(self.store.collection_device_ids(pinned), [server])

    def test_save_inventory_replaces_software(self) -> None:
        device_id = self.store.add_device(name="ws-b", os="Windows 11 Pro", type="computer", status="unknown")
        self.store.execute(
            "INSERT INTO software(device_id, name, version, publisher) VALUES (?, ?, ?, ?)",
            (device_id, "Old", "1", "Old"),
        )
        scanner.save_inventory(
            self.store,
            device_id,
            {
                "computer": {"os": "Windows 11 Pro", "architecture": "64-bit", "ram_gb": 16},
                "software": [{"name": "7-Zip", "version": "24", "publisher": "Igor Pavlov"}],
                "hotfixes": [{"hotfix_id": "KB1", "description": "Update", "installed_on": "2026-01-01"}],
            },
        )
        names = [row["name"] for row in self.store.device_software(device_id)]
        self.assertEqual(names, ["7-Zip"])
        device = self.store.device(device_id)
        self.assertEqual(device["scan_status"], "ok")
        self.assertEqual(device["status"], "online")
        self.assertEqual(device["architecture"], "64-bit")
        hotfixes = self.store.child_rows("hotfixes", device_id)
        self.assertEqual(hotfixes[0]["hotfix_id"], "KB1")

    def test_inventory_script_respects_profile(self) -> None:
        script = scanner.inventory_script({"software": False, "hardware": True, "services": False})
        self.assertIn("ConvertTo-Json", script)
        self.assertNotIn("Uninstall", script)
        self.assertIn("Win32_LogicalDisk", script)

    def test_local_scan_and_deploy(self) -> None:
        device_id = self.store.add_device(
            name="console",
            hostname="console",
            type="computer",
            os="Linux",
            status="online",
            discovered=2,
        )
        outcome = scanner.scan_one(self.store, device_id)
        self.assertTrue(outcome.ok, outcome.message)
        device = self.store.device(device_id)
        self.assertEqual(device["scan_status"], "ok")
        self.assertTrue(device["os"])
        package = self.store.fetchone("SELECT id FROM packages WHERE name = ?", ("Helix connectivity check",))
        deployment_id = deployer.create_deployment(self.store, int(package["id"]), [device_id], None)
        status = deployer.run_deployment(self.store, deployment_id)
        self.assertEqual(status, "success")
        target = self.store.deployment_targets(deployment_id)[0]
        self.assertIn("Helix connectivity check", target["log"])

    def test_expand_install_and_schedule(self) -> None:
        device = {"name": "ws-a", "hostname": "ws-a.shop.local", "ip": "10.0.0.5", "ou": "Finance", "domain": "shop.local", "os": "Windows 11"}
        self.assertIn("10.0.0.5", deployer.expand("ping $(IP)", device))
        argv = deployer._install_argv(r"C:\Windows\Temp\Helix\app.msi", "")
        self.assertEqual(argv[0], "msiexec.exe")
        self.assertIn("/qn", argv)
        self.assertTrue(remote.RemoteResult(0, "", "").succeeded("0,3010"))
        self.assertFalse(remote.RemoteResult(1, "", "").succeeded("0"))
        now = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
        nxt = schedules.compute_next("interval", 15, None, now)
        self.assertEqual(nxt, (now + timedelta(minutes=15)).isoformat())
        daily = schedules.compute_next("daily", None, "02:00", now)
        self.assertTrue(daily.endswith("02:00:00+00:00"))
        self.assertIsNone(schedules.compute_next("heartbeat", None, None, now))

    def test_secrets_file_mode(self) -> None:
        path = Path(self._dir.name) / "secrets.json"
        secrets.set_directory({"server": "dc.shop.local", "password": "secret", "dns_domain": "shop.local"}, path)
        secrets.set_directory({"server": "dc.shop.local", "password": ""}, path)
        self.assertEqual(secrets.directory(path)["password"], "secret")
        secrets.upsert_credential({"name": "Scan", "username": "svc", "domain": "SHOP", "password": "pw"}, path)
        self.assertEqual(secrets.account_name(secrets.get_credential("Scan", path)), r"SHOP\svc")
        mode = os.stat(path).st_mode & 0o777
        self.assertEqual(mode, 0o600)


if __name__ == "__main__":
    unittest.main()
