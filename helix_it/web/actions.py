from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from helix_it import secrets
from helix_it.ad import base_dn_from_domain
from helix_it.db import data_dir, utcnow
from helix_it.deployer import create_deployment, default_codes
from helix_it.schedules import compute_next
from helix_it.seed import seed
from helix_it.web import auth
from helix_it.web.form import Form
from helix_it.web.html import Ctx


def go(path: str, **params: str) -> str:
    if not params:
        return path
    query = "&".join(f"{key}={quote(value)}" for key, value in params.items() if value)
    return f"{path}?{query}"


def _num(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _save_upload(files: dict[str, tuple[str, bytes]]) -> str:
    if "file" not in files:
        return ""
    filename, data = files["file"]
    if not filename or not data:
        return ""
    safe = Path(filename).name.replace("\\", "").strip()
    if not safe or safe in {".", ".."}:
        raise RuntimeError("Choose a file name.")
    folder = data_dir() / "packages"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / safe
    path.write_bytes(data)
    os.chmod(path, 0o644)
    return str(path)


def _directory_from(form: Form) -> dict:
    use_ssl = form.get("use_ssl") in {"on", "yes", "true"}
    try:
        port = int(form.get("port") or (636 if use_ssl else 389))
    except ValueError:
        port = 636 if use_ssl else 389
    payload = {
        "server": form.get("server").strip(),
        "port": port,
        "use_ssl": use_ssl,
        "dns_domain": form.get("dns_domain").strip(),
        "netbios": form.get("netbios").strip(),
        "base_dn": form.get("base_dn").strip(),
        "username": form.get("username").strip(),
        "password": form.get("password"),
    }
    if not payload["base_dn"] and payload["dns_domain"]:
        payload["base_dn"] = base_dn_from_domain(payload["dns_domain"])
    return payload


def device_save(ctx: Ctx, form: Form, _files) -> str:
    payload = {
        "name": form.get("name").strip() or "Unnamed",
        "hostname": form.get("hostname").strip() or None,
        "ip": form.get("ip").strip() or None,
        "os": form.get("os").strip() or None,
        "notes": form.get("notes").strip() or None,
        "type": form.get("type").strip() or "computer",
    }
    device_id = _num(form.get("device_id"))
    if device_id:
        ctx.store.update_device(device_id, **payload)
        return go(f"/inventory/{device_id}", notice="Saved")
    new_id = ctx.store.add_device(status="unknown", **payload)
    return go(f"/inventory/{new_id}", notice="Computer added")


def device_delete(ctx: Ctx, form: Form, _files) -> str:
    device_id = _num(form.get("device_id"))
    if device_id:
        ctx.store.delete_device(device_id)
    return go("/inventory", notice="Computer removed")


def scan(ctx: Ctx, form: Form, _files) -> str:
    ids: list[int] = []
    device_id = _num(form.get("device_id"))
    collection_id = _num(form.get("collection_id"))
    if collection_id:
        ids.extend(ctx.store.collection_device_ids(collection_id))
    if device_id:
        ids.append(device_id)
    error = ctx.hub.scan(ids)
    target = f"/inventory/{device_id}" if device_id and not collection_id else "/inventory"
    if collection_id and not device_id:
        target = f"/collections/{collection_id}"
    return go(target, error=error or "", notice="" if error else "Scan started")


def scan_windows(ctx: Ctx, _form: Form, _files) -> str:
    from helix_it import scanner

    error = ctx.hub.scan(scanner.scannable_ids(ctx.store))
    return go("/inventory", error=error or "", notice="" if error else "Scan started")


def tool(ctx: Ctx, form: Form, _files) -> str:
    device_id = _num(form.get("device_id")) or 0
    kind = form.get("kind") or "command"
    error = ctx.hub.tool(device_id, kind, form.get("payload"))
    return go(f"/inventory/{device_id}", error=error or "", notice="" if error else "Command started")


def wake(ctx: Ctx, form: Form, _files) -> str:
    from helix_it import remote

    device_id = _num(form.get("device_id")) or 0
    device = ctx.store.device(device_id)
    if not device or not device["mac"]:
        return go(f"/inventory/{device_id}", error="This computer has no MAC address.")
    try:
        remote.wake_on_lan(device["mac"])
    except Exception as exc:
        return go(f"/inventory/{device_id}", error=str(exc))
    return go(f"/inventory/{device_id}", notice=f"Sent Wake-on-LAN to {device['name']}")


def deploy(ctx: Ctx, form: Form, _files) -> str:
    package_id = _num(form.get("package_id"))
    if not package_id:
        return go("/deploy", error="Choose a package.")
    ids: list[int] = []
    collection_id = _num(form.get("collection_id"))
    device_id = _num(form.get("device_id"))
    if collection_id:
        ids.extend(ctx.store.collection_device_ids(collection_id))
    if device_id:
        ids.append(device_id)
    try:
        deployment_id = create_deployment(ctx.store, package_id, ids, form.get("credential") or None)
    except Exception as exc:
        return go("/deploy", error=str(exc))
    error = ctx.hub.deploy(deployment_id)
    return go("/deploy", error=error or "", notice="" if error else "Deployment started")


def collection_create(ctx: Ctx, form: Form, _files) -> str:
    name = form.get("name").strip()
    if not name:
        return go("/collections", error="Collection needs a name.")
    try:
        collection_id = ctx.store.add_collection(name, form.get("kind") or "dynamic", "", "all")
    except Exception as exc:
        return go("/collections", error=str(exc))
    return go(f"/collections/{collection_id}", notice="Collection created")


def collection_save(ctx: Ctx, form: Form, _files) -> str:
    collection_id = _num(form.get("collection_id")) or 0
    ctx.store.update_collection(
        collection_id,
        name=form.get("name").strip() or "Collection",
        description=form.get("description").strip(),
        kind=form.get("kind") or "dynamic",
        match_mode=form.get("match_mode") or "all",
    )
    return go(f"/collections/{collection_id}", notice="Saved")


def collection_delete(ctx: Ctx, form: Form, _files) -> str:
    collection_id = _num(form.get("collection_id"))
    if collection_id:
        ctx.store.delete_collection(collection_id)
    return go("/collections", notice="Collection removed")


def filter_add(ctx: Ctx, form: Form, _files) -> str:
    collection_id = _num(form.get("collection_id")) or 0
    ctx.store.add_filter(collection_id, form.get("field") or "name", form.get("op") or "contains", form.get("value").strip())
    return go(f"/collections/{collection_id}", notice="Filter added")


def filter_delete(ctx: Ctx, form: Form, _files) -> str:
    collection_id = _num(form.get("collection_id")) or 0
    filter_id = _num(form.get("filter_id"))
    if filter_id:
        ctx.store.delete_filter(filter_id)
    return go(f"/collections/{collection_id}")


def member_add(ctx: Ctx, form: Form, _files) -> str:
    collection_id = _num(form.get("collection_id")) or 0
    device_id = _num(form.get("device_id"))
    if device_id:
        ctx.store.add_member(collection_id, device_id)
    return go(f"/collections/{collection_id}", notice="Pinned")


def member_remove(ctx: Ctx, form: Form, _files) -> str:
    collection_id = _num(form.get("collection_id")) or 0
    device_id = _num(form.get("device_id"))
    if device_id:
        ctx.store.remove_member(collection_id, device_id)
    return go(f"/collections/{collection_id}")


def package_save(ctx: Ctx, form: Form, _files) -> str:
    name = form.get("name").strip()
    if not name:
        return go("/deploy", error="Package needs a name.")
    try:
        timeout = int(form.get("timeout_sec") or "3600")
    except ValueError:
        timeout = 3600
    package_id = _num(form.get("package_id"))
    if package_id:
        ctx.store.update_package(
            package_id,
            name=name,
            version=form.get("version").strip(),
            description=form.get("description").strip(),
            timeout_sec=timeout,
        )
    else:
        package_id = ctx.store.add_package(name, form.get("version").strip(), form.get("description").strip(), timeout)
    return go("/deploy", package=str(package_id), notice="Package saved")


def package_delete(ctx: Ctx, form: Form, _files) -> str:
    package_id = _num(form.get("package_id"))
    if not package_id:
        return go("/deploy")
    message = ctx.store.delete_package(package_id)
    if message:
        return go("/deploy", package=str(package_id), error=message)
    return go("/deploy", notice="Package removed")


def step_save(ctx: Ctx, form: Form, files) -> str:
    package_id = _num(form.get("package_id")) or 0
    kind = form.get("kind") or "command"
    try:
        payload = _save_upload(files) or form.get("payload").strip()
    except Exception as exc:
        return go("/deploy", package=str(package_id), error=str(exc))
    nested = _num(form.get("nested_package_id"))
    ctx.store.add_step(
        package_id,
        kind=kind,
        name=form.get("name").strip() or kind,
        payload=payload,
        args=form.get("args").strip(),
        success_codes=form.get("success_codes").strip() or default_codes(kind),
        condition_field=form.get("condition_field") or None,
        condition_op=form.get("condition_op") or "contains",
        condition_value=form.get("condition_value").strip(),
        continue_on_error=1 if form.get("continue_on_error") or kind == "message" else 0,
        nested_package_id=nested if kind == "nested" else None,
    )
    return go("/deploy", package=str(package_id), notice="Step added")


def step_delete(ctx: Ctx, form: Form, _files) -> str:
    package_id = form.get("package_id")
    step_id = _num(form.get("step_id"))
    if step_id:
        ctx.store.delete_step(step_id)
    return go("/deploy", package=package_id)


def step_move(ctx: Ctx, form: Form, _files) -> str:
    step_id = _num(form.get("step_id"))
    direction = _num(form.get("direction")) or 0
    if step_id:
        ctx.store.move_step(step_id, direction)
    return go("/deploy", package=form.get("package_id"))


def retry(ctx: Ctx, form: Form, _files) -> str:
    deployment_id = _num(form.get("deployment_id")) or 0
    error = ctx.hub.retry(deployment_id)
    return go("/deploy", error=error or "", notice="" if error else "Retry started")


def schedule_save(ctx: Ctx, form: Form, _files) -> str:
    name = form.get("name").strip()
    if not name:
        return go("/deploy", error="Schedule needs a name.")
    trigger = form.get("trigger") or "interval"
    try:
        minutes = int(form.get("interval_minutes") or "60")
    except ValueError:
        minutes = 60
    now = datetime.now(timezone.utc)
    ctx.store.add_schedule(
        name=name,
        kind=form.get("kind") or "deploy",
        trigger=trigger,
        package_id=_num(form.get("package_id")),
        collection_id=_num(form.get("collection_id")),
        interval_minutes=minutes,
        time_of_day=form.get("time_of_day").strip() or "02:00",
        credential=form.get("credential") or None,
        enabled=1,
        next_run=compute_next(trigger, minutes, form.get("time_of_day").strip() or "02:00", now),
    )
    return go("/deploy", notice="Schedule saved")


def schedule_delete(ctx: Ctx, form: Form, _files) -> str:
    schedule_id = _num(form.get("schedule_id"))
    if schedule_id:
        ctx.store.delete_schedule(schedule_id)
    return go("/deploy", notice="Schedule removed")


def ticket_save(ctx: Ctx, form: Form, _files) -> str:
    title = form.get("title").strip()
    if not title:
        return go("/tickets", error="Ticket needs a title.")
    ticket_id = ctx.store.add_ticket(
        title,
        form.get("description").strip(),
        form.get("priority") or "medium",
        _num(form.get("requester_id")),
        form.get("assignee").strip(),
        _num(form.get("device_id")),
    )
    return go(f"/tickets/{ticket_id}", notice="Ticket opened")


def ticket_status(ctx: Ctx, form: Form, _files) -> str:
    ticket_id = _num(form.get("ticket_id")) or 0
    ctx.store.update_ticket(ticket_id, status=form.get("status") or "open")
    return go(f"/tickets/{ticket_id}", notice="Status updated")


def ticket_comment(ctx: Ctx, form: Form, _files) -> str:
    ticket_id = _num(form.get("ticket_id")) or 0
    body = form.get("body").strip()
    if body:
        ctx.store.add_comment(ticket_id, ctx.user["display_name"] or ctx.user["username"], body)
    return go(f"/tickets/{ticket_id}", notice="Comment added")


def person_save(ctx: Ctx, form: Form, _files) -> str:
    name = form.get("name").strip()
    if not name:
        return go("/people", error="A person needs a name.")
    ctx.store.add_person(name, form.get("email").strip(), form.get("department").strip(), form.get("title").strip())
    return go("/people", notice="Person added")


def shop_save(ctx: Ctx, form: Form, _files) -> str:
    ctx.store.set_meta("org_name", form.get("org_name").strip() or "Helix IT")
    ctx.store.set_meta("tech_name", form.get("tech_name").strip() or "IT Desk")
    return go("/settings", notice="Shop saved")


def directory_save(ctx: Ctx, form: Form, _files) -> str:
    secrets.set_directory(_directory_from(form))
    return go("/settings", notice="Directory settings saved")


def directory_test(ctx: Ctx, form: Form, _files) -> str:
    secrets.set_directory(_directory_from(form))
    error = ctx.hub.test_directory()
    return go("/settings", error=error or "", notice="" if error else "Testing the directory…")


def directory_sync(ctx: Ctx, form: Form, _files) -> str:
    secrets.set_directory(_directory_from(form))
    error = ctx.hub.sync_directory()
    return go("/settings", error=error or "", notice="" if error else "Directory sync started")


def directory_stale(ctx: Ctx, form: Form, _files) -> str:
    if form.get("confirm") != "yes":
        return go("/settings", error="Check the box to delete computers missing from the last sync.")
    count = ctx.store.delete_stale_directory_computers()
    return go("/settings", notice=f"Removed {count} computers missing from the last sync")


def credential_save(ctx: Ctx, form: Form, _files) -> str:
    try:
        secrets.upsert_credential(
            {
                "name": form.get("name").strip(),
                "username": form.get("username").strip(),
                "domain": form.get("domain").strip(),
                "password": form.get("password"),
            }
        )
    except ValueError as exc:
        return go("/settings", error=str(exc))
    return go("/settings", notice="Account saved")


def credential_delete(ctx: Ctx, form: Form, _files) -> str:
    name = form.get("name").strip()
    if name:
        secrets.delete_credential(name)
    return go("/settings", notice="Account removed")


def winrm_save(ctx: Ctx, form: Form, _files) -> str:
    try:
        port = int(form.get("port") or "5985")
    except ValueError:
        port = 5985
    secrets.set_winrm(
        {
            "transport": form.get("transport") or "ntlm",
            "port": port,
            "use_ssl": form.get("use_ssl") in {"on", "yes", "true"},
            "credential": form.get("credential") or "",
        }
    )
    return go("/settings", notice="WinRM saved")


def profile_save(ctx: Ctx, form: Form, _files) -> str:
    fields = {key: 1 if form.get(key) else 0 for key, _label in (
        ("software", ""),
        ("hotfixes", ""),
        ("services", ""),
        ("hardware", ""),
        ("users", ""),
        ("shares", ""),
        ("printers", ""),
        ("startup", ""),
    )}
    fields["custom_script"] = form.get("custom_script").strip()
    ctx.store.update_scan_profile(**fields)
    return go("/settings", notice="Scan profile saved")


def sample_reset(ctx: Ctx, form: Form, _files) -> str:
    if form.get("confirm") != "yes":
        return go("/settings", error="Check the box to reload sample data.")
    seed(ctx.store)
    return go("/", notice="Sample data loaded")


def lan_scan(ctx: Ctx, _form: Form, _files) -> str:
    error = ctx.hub.lan()
    return go("/network", error=error or "", notice="" if error else "LAN scan started")


def agent_save(ctx: Ctx, form: Form, _files) -> str:
    username = form.get("username").strip()
    password = form.get("password")
    if not username or not password:
        return go("/agents", error="Username and password are required.")
    try:
        ctx.store.execute(
            "INSERT INTO agents(username, display_name, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (
                username,
                form.get("display_name").strip() or username,
                auth.hash_password(password),
                utcnow(),
            ),
        )
    except Exception as exc:
        return go("/agents", error=str(exc))
    return go("/agents", notice="Agent added")


def agent_delete(ctx: Ctx, form: Form, _files) -> str:
    agent_id = _num(form.get("agent_id"))
    count = int(ctx.store.fetchone("SELECT COUNT(*) FROM agents")[0])
    if count <= 1:
        return go("/agents", error="Keep at least one agent who can sign in.")
    if agent_id:
        ctx.store.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
    return go("/agents", notice="Agent removed")


def password_save(ctx: Ctx, form: Form, _files) -> str:
    if not auth.verify_password(form.get("current"), ctx.user["password_hash"]):
        return go("/agents", error="Current password does not match.")
    password = form.get("password")
    if len(password) < 8:
        return go("/agents", error="Use at least 8 characters.")
    ctx.store.execute(
        "UPDATE agents SET password_hash = ? WHERE id = ?",
        (auth.hash_password(password), ctx.user["id"]),
    )
    return go("/agents", notice="Password updated")


HANDLERS = {
    "device-save": device_save,
    "device-delete": device_delete,
    "scan": scan,
    "scan-windows": scan_windows,
    "tool": tool,
    "wake": wake,
    "deploy": deploy,
    "collection-create": collection_create,
    "collection-save": collection_save,
    "collection-delete": collection_delete,
    "filter-add": filter_add,
    "filter-delete": filter_delete,
    "member-add": member_add,
    "member-remove": member_remove,
    "package-save": package_save,
    "package-delete": package_delete,
    "step-save": step_save,
    "step-delete": step_delete,
    "step-move": step_move,
    "retry": retry,
    "schedule-save": schedule_save,
    "schedule-delete": schedule_delete,
    "ticket-save": ticket_save,
    "ticket-status": ticket_status,
    "ticket-comment": ticket_comment,
    "person-save": person_save,
    "shop-save": shop_save,
    "directory-save": directory_save,
    "directory-test": directory_test,
    "directory-sync": directory_sync,
    "directory-stale": directory_stale,
    "credential-save": credential_save,
    "credential-delete": credential_delete,
    "winrm-save": winrm_save,
    "profile-save": profile_save,
    "sample-reset": sample_reset,
    "lan-scan": lan_scan,
    "agent-save": agent_save,
    "agent-delete": agent_delete,
    "password-save": password_save,
}
