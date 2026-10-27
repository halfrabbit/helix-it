from __future__ import annotations

from datetime import datetime, timedelta, timezone

from helix_it import deployer, remote, scanner
from helix_it.db import Store


def compute_next(trigger: str, interval_minutes: int | None, time_of_day: str | None, now: datetime) -> str | None:
    if trigger == "heartbeat":
        return None
    if trigger == "daily":
        hour, minute = (time_of_day or "02:00").split(":")
        candidate = now.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate.isoformat()
    minutes = int(interval_minutes or 60)
    return (now + timedelta(minutes=minutes)).replace(microsecond=0).isoformat()


def target_ids(store: Store, schedule) -> list[int]:
    if schedule["collection_id"]:
        return store.collection_device_ids(int(schedule["collection_id"]))
    if schedule["kind"] == "scan":
        return [
            int(row["id"])
            for row in store.devices()
            if remote.is_windows_device(row) or remote.is_local_device(row)
        ]
    return []


def heartbeat(store: Store, device_id: int) -> None:
    try:
        for schedule in store.heartbeat_schedules():
            if not schedule["package_id"] or not schedule["collection_id"]:
                continue
            members = set(store.collection_device_ids(int(schedule["collection_id"])))
            if device_id not in members:
                continue
            if store.package_succeeded(int(schedule["package_id"]), device_id):
                continue
            deployment_id = deployer.create_deployment(
                store,
                int(schedule["package_id"]),
                [device_id],
                schedule["credential"],
                schedule_id=int(schedule["id"]),
            )
            deployer.run_deployment(store, deployment_id)
    except Exception as exc:
        store.log("deploy", f"Heartbeat failed: {exc}")


def run_due(store: Store, progress=None, now: datetime | None = None) -> bool:
    moment = now or datetime.now(timezone.utc).replace(microsecond=0)
    due = store.due_schedules(moment.isoformat())
    if not due:
        return False
    for schedule in due:
        nxt = compute_next(schedule["trigger"], schedule["interval_minutes"], schedule["time_of_day"], moment)
        store.update_schedule(int(schedule["id"]), last_run=moment.isoformat(), next_run=nxt)
        _run(store, schedule, progress)
    return True


def _run(store: Store, schedule, progress) -> None:
    ids = target_ids(store, schedule)
    if schedule["kind"] == "scan":
        scanner.scan_many(
            store,
            ids,
            progress=progress,
            on_success=lambda device_id: heartbeat(store, device_id),
            credential=schedule["credential"],
        )
        return
    if schedule["kind"] == "deploy" and schedule["package_id"] and ids:
        deployment_id = deployer.create_deployment(
            store,
            int(schedule["package_id"]),
            ids,
            schedule["credential"],
            schedule_id=int(schedule["id"]),
        )
        deployer.run_deployment(store, deployment_id, progress=progress)
