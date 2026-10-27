from __future__ import annotations

import threading

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib

from helix_it import ad, deployer, remote, scanner, schedules
from helix_it.db import Store


class Jobs:
    """Background inventory, directory, and deploy work. UI callbacks run on the GTK thread."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self._busy = threading.Lock()

    def _ui(self, fn, *args) -> None:
        if fn is None:
            return

        def wrapper():
            fn(*args)
            return False

        GLib.idle_add(wrapper)

    def _thread(self, work) -> bool:
        if not self._busy.acquire(blocking=False):
            return False

        def runner():
            try:
                work()
            finally:
                self._busy.release()

        threading.Thread(target=runner, daemon=True).start()
        return True

    def scan(self, device_ids: list[int], on_progress, on_done) -> None:
        if not device_ids:
            self._ui(on_done, "No computers selected.")
            return

        def work():
            try:
                outcomes = scanner.scan_many(
                    self.store,
                    device_ids,
                    progress=lambda message: self._ui(on_progress, message),
                    on_success=lambda device_id: schedules.heartbeat(self.store, device_id),
                )
                failed = [item for item in outcomes if not item.ok]
                self.store.log("scan", f"Scanned {len(outcomes)} computers, {len(failed)} failed")
                self._ui(on_done, None)
            except Exception as exc:
                self._ui(on_done, str(exc))

        if not self._thread(work):
            self._ui(on_done, "Another inventory or deploy job is still running.")

    def deploy(self, deployment_id: int, on_progress, on_done) -> None:
        def work():
            try:
                deployer.run_deployment(
                    self.store,
                    deployment_id,
                    progress=lambda message: self._ui(on_progress, message),
                )
                self._ui(on_done, None)
            except Exception as exc:
                self._ui(on_done, str(exc))

        if not self._thread(work):
            self._ui(on_done, "Another inventory or deploy job is still running.")

    def retry(self, deployment_id: int, on_progress, on_done) -> None:
        count = self.store.requeue_failed(deployment_id)
        if not count:
            self._ui(on_done, "No failed computers to retry.")
            return
        self.deploy(deployment_id, on_progress, on_done)

    def sync_directory(self, on_progress, on_done) -> None:
        def work():
            try:
                self._ui(on_progress, "Reading the directory…")
                result = ad.sync(self.store)
                message = (
                    f"Synced {result['computers']} computers, {result['ous']} OUs, "
                    f"{result['groups']} groups, {result['users']} users."
                )
                self._ui(on_done, message, None)
            except Exception as exc:
                self.store.set_meta("ad_status", str(exc)[:300])
                self._ui(on_done, None, str(exc))

        if not self._thread(work):
            self._ui(on_done, None, "Another inventory or deploy job is still running.")

    def test_directory(self, on_done) -> None:
        def work():
            try:
                self._ui(on_done, ad.test_directory(), None)
            except Exception as exc:
                self._ui(on_done, None, str(exc))

        if not self._thread(work):
            self._ui(on_done, None, "Another inventory or deploy job is still running.")

    def tool(self, device_id: int, kind: str, payload: str, on_done) -> None:
        def work():
            try:
                device = self.store.device(device_id)
                if not device:
                    raise RuntimeError("Computer is gone.")
                if kind == "reboot":
                    result = remote.reboot(device)
                    text = result.stdout or result.stderr or "Reboot command sent."
                elif kind == "powershell":
                    text = _tool_text(remote.run_powershell(device, payload))
                else:
                    text = _tool_text(remote.run_command(device, payload))
                self.store.log("tool", f"{kind} on {device['name']}")
                self._ui(on_done, text, None)
            except Exception as exc:
                self._ui(on_done, None, str(exc))

        if not self._thread(work):
            self._ui(on_done, None, "Another inventory or deploy job is still running.")

    def kick_schedules(self, on_done) -> None:
        def work():
            try:
                ran = schedules.run_due(self.store)
            except Exception as exc:
                self.store.log("schedule", f"Schedule failed: {exc}")
                ran = False
            if ran:
                self._ui(on_done)

        self._thread(work)


def _tool_text(result) -> str:
    text = "\n".join(part for part in (result.stdout, result.stderr) if part)
    if result.exit_code not in {0}:
        raise RuntimeError(text or f"Exit {result.exit_code}")
    return text or "(no output)"
