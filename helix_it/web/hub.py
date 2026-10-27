from __future__ import annotations

import threading
from datetime import datetime, timezone

from helix_it import ad, deployer, network, remote, scanner, schedules
from helix_it.db import Store


class Hub:
    """One shared job at a time. Several browsers can read inventory while it runs."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self._busy = threading.Lock()
        self._state = threading.Lock()
        self.message = "Idle"
        self.detail = ""
        self.busy = False
        self._stop = threading.Event()
        self._ticker: threading.Thread | None = None

    def snapshot(self) -> dict:
        with self._state:
            return {"busy": self.busy, "message": self.message, "detail": self.detail}

    def _set(self, message: str, detail: str | None = None, busy: bool | None = None) -> None:
        with self._state:
            self.message = message
            if detail is not None:
                self.detail = detail
            if busy is not None:
                self.busy = busy

    def start(self, work) -> str | None:
        if not self._busy.acquire(blocking=False):
            return "Another inventory or deploy job is still running."
        self._set("Working…", "", True)

        def runner() -> None:
            try:
                work()
            except Exception as exc:
                self._set(f"Failed: {exc}", str(exc))
                self.store.log("job", str(exc)[:300])
            finally:
                with self._state:
                    self.busy = False
                self._busy.release()

        threading.Thread(target=runner, daemon=True).start()
        return None

    def start_ticker(self) -> None:
        if self._ticker and self._ticker.is_alive():
            return

        def loop() -> None:
            while not self._stop.wait(60):
                try:
                    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                    if not self.store.due_schedules(now):
                        continue
                    self.start(self._run_due)
                except Exception as exc:
                    self.store.log("schedule", str(exc)[:300])

        self._ticker = threading.Thread(target=loop, daemon=True)
        self._ticker.start()

    def stop(self) -> None:
        self._stop.set()

    def _run_due(self) -> None:
        self._set("Running a schedule…", busy=True)
        ran = schedules.run_due(self.store, progress=lambda message: self._set(message, busy=True))
        self._set("Schedule finished." if ran else "Idle")

    def scan(self, device_ids: list[int]) -> str | None:
        if not device_ids:
            return "No computers selected."

        def work() -> None:
            outcomes = scanner.scan_many(
                self.store,
                device_ids,
                progress=lambda message: self._set(message, busy=True),
                on_success=lambda device_id: schedules.heartbeat(self.store, device_id),
            )
            failed = [item for item in outcomes if not item.ok]
            text = f"Scanned {len(outcomes)} computers, {len(failed)} failed."
            self.store.log("scan", text)
            self._set(text, "\n".join(item.message for item in failed))

        return self.start(work)

    def deploy(self, deployment_id: int) -> str | None:
        def work() -> None:
            status = deployer.run_deployment(
                self.store,
                deployment_id,
                progress=lambda message: self._set(message, busy=True),
            )
            self._set(f"Deployment {status}.")

        return self.start(work)

    def retry(self, deployment_id: int) -> str | None:
        count = self.store.requeue_failed(deployment_id)
        if not count:
            return "No failed computers to retry."
        return self.deploy(deployment_id)

    def sync_directory(self) -> str | None:
        def work() -> None:
            self._set("Reading the directory…", busy=True)
            result = ad.sync(self.store)
            text = (
                f"Synced {result['computers']} computers, {result['ous']} OUs, "
                f"{result['groups']} groups, {result['users']} users."
            )
            self._set(text)

        return self.start(work)

    def test_directory(self) -> str | None:
        def work() -> None:
            self._set(ad.test_directory())

        return self.start(work)

    def tool(self, device_id: int, kind: str, payload: str) -> str | None:
        def work() -> None:
            device = self.store.device(device_id)
            if not device:
                raise RuntimeError("Computer is gone.")
            self._set(f"{kind} on {device['name']}…", busy=True)
            if kind == "reboot":
                result = remote.reboot(device)
                text = result.stdout or result.stderr or "Reboot command sent."
            elif kind == "powershell":
                text = _tool_text(remote.run_powershell(device, payload))
            else:
                text = _tool_text(remote.run_command(device, payload))
            self.store.log("tool", f"{kind} on {device['name']}")
            self._set(f"{kind} finished on {device['name']}.", text)

        return self.start(work)

    def lan(self) -> str | None:
        def work() -> None:
            self._set("Scanning private subnets…", busy=True)
            alive, total = network.discover_lan(self.store)
            self._set(f"LAN scan: {alive} of {total} addresses answered.")

        return self.start(work)


def _tool_text(result) -> str:
    text = "\n".join(part for part in (result.stdout, result.stderr) if part)
    if result.exit_code not in {0}:
        raise RuntimeError(text or f"Exit {result.exit_code}")
    return text or "(no output)"
