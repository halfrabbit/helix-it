from __future__ import annotations

from helix_it import secrets
from helix_it.collections import FIELDS, OPS
from helix_it.deployer import default_codes
from helix_it.web.html import Ctx, h, select

KINDS = ("install", "command", "powershell", "copy", "reboot", "sleep", "message", "nested")
TYPES = ("computer", "server", "network", "printer", "other")
PROFILE_FLAGS = (
    ("software", "Applications"),
    ("hotfixes", "Hotfixes"),
    ("services", "Services"),
    ("hardware", "Hardware, disks, and NICs"),
    ("users", "Local users"),
    ("shares", "Shares"),
    ("printers", "Printers"),
    ("startup", "Startup programs"),
)


def _badge(status: str | None) -> str:
    value = status or "unknown"
    return f'<span class="badge {h(value)}">{h(value)}</span>'


def _tabs(panels: list[tuple[str, str]]) -> str:
    controls = []
    pages = []
    for index, (label, body) in enumerate(panels):
        checked = " checked" if index == 0 else ""
        controls.append(f'<input type="radio" name="detail" id="tab{index}"{checked}>')
        controls.append(f'<label for="tab{index}">{h(label)}</label>')
        pages.append(f'<div class="tabpage" data-tab="{index}">{body}</div>')
    return f'<div class="tabs">{"".join(controls)}{"".join(pages)}</div>'


def _bars(rows: list[tuple[str, int]]) -> str:
    peak = max((value for _, value in rows), default=1) or 1
    lines = []
    for label, value in rows:
        width = max(4, int(100 * value / peak))
        lines.append(
            f'<div class="bar-row"><span>{h(label)}</span><span class="bar" style="width:{width}%"></span><span>{value}</span></div>'
        )
    return "".join(lines) or "<p class='muted'>Nothing recorded.</p>"


def dashboard(ctx: Ctx) -> str:
    stats = ctx.store.stats()
    cards = (
        ("Devices", stats["devices"], f"{stats['online']} online"),
        ("Directory", stats["directory"], f"{stats['windows']} Windows"),
        ("Open tickets", stats["open_tickets"], f"{stats['critical']} critical"),
        ("Needs attention", stats["scan_failed"] + stats["deploy_failed"], f"{stats['deploy_failed']} deploy failures"),
    )
    card_html = "".join(
        f'<div class="card"><span>{h(label)}</span><b>{h(value)}</b><p class="muted">{h(hint)}</p></div>'
        for label, value, hint in cards
    )
    activity = "".join(f"<li>{h(row['message'])}</li>" for row in ctx.store.activity(8)) or "<li class='muted'>No activity yet.</li>"
    tickets = []
    for row in ctx.store.tickets(status="active")[:6]:
        tickets.append(f"<li>{_badge(row['status'])} <a href='/tickets/{row['id']}'>#{h(row['number'])} {h(row['title'])}</a></li>")
    return f"""
    <p class="muted">{h(ctx.store.get_meta('org_name') or 'Helix IT')} · several agents share this console.</p>
    <div class="cards">{card_html}</div>
    <div class="split">
      <section class="panel"><h2>Open tickets</h2><ul>{''.join(tickets) or '<li class="muted">None open.</li>'}</ul></section>
      <section class="panel"><h2>Activity</h2><ul>{activity}</ul></section>
    </div>"""


def inventory(ctx: Ctx) -> str:
    query = ctx.query.get("q", "")
    kind = ctx.query.get("type", "all")
    collection = ctx.query.get("collection", "")
    rows = ctx.store.devices(None if kind in {"", "all"} else kind, query)
    if collection.isdigit():
        allowed = set(ctx.store.collection_device_ids(int(collection)))
        rows = [row for row in rows if int(row["id"]) in allowed]
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td><a href='/inventory/{row['id']}'>{h(row['name'])}</a></td>"
            f"<td>{_badge(row['status'])}</td>"
            f"<td>{h(row['ip'] or '')}</td>"
            f"<td>{h(row['os'] or '')}</td>"
            f"<td>{h(row['ou'] or row['type'] or '')}</td>"
            f"<td>{h(row['scan_status'] or '')}</td>"
            "</tr>"
        )
    type_pairs = [("all", "All types"), *((item, item) for item in TYPES)]
    collections = [("", "All computers")] + [(row["id"], row["name"]) for row in ctx.store.collections()]
    command = f"""
    <div class="commandbar">
      <form class="row" method="get" action="/inventory">
        <label>Find <input name="q" value="{h(query)}" placeholder="Name, IP, OS, OU"></label>
        <label>Type {select("type", type_pairs, kind)}</label>
        <label>Collection {select("collection", collections, collection)}</label>
        <button type="submit">Apply</button>
      </form>
      <form method="post" action="/act/scan-windows">{ctx.hidden()}
        <button class="primary" type="submit">Scan</button>
      </form>
    </div>"""
    table = (
        "<div class='gridwrap'><table class='grid'><thead><tr>"
        "<th>Name</th><th>Status</th><th>IP address</th><th>Operating system</th><th>OU</th><th>Scan</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
        + f"<p class='gridcount'>{len(rows)} computers</p>"
    )
    if not body:
        table = "<p class='muted'>No computers match.</p>"
    add = f"""
    <details class="drawer"><summary>Add a computer</summary>
    <form class="stack" method="post" action="/act/device-save">{ctx.hidden()}
      <label>Name <input name="name" required></label>
      <label>Hostname <input name="hostname"></label>
      <label>IP <input name="ip"></label>
      <label>OS <input name="os"></label>
      <label>Type {select("type", [(item, item) for item in TYPES], "computer")}</label>
      <button class="primary" type="submit">Add</button>
    </form></details>"""
    return command + table + add


def device(ctx: Ctx, device_id: int) -> str:
    row = ctx.store.device(device_id)
    if not row:
        return "<p class='muted'>That computer is gone.</p>"
    fields = (
        ("hostname", "Hostname"),
        ("ip", "IP"),
        ("mac", "MAC"),
        ("domain", "Domain"),
        ("ou", "OU"),
        ("dn", "DN"),
        ("os", "OS"),
        ("os_version", "OS version"),
        ("architecture", "Architecture"),
        ("cpu", "CPU"),
        ("current_user", "Current user"),
        ("last_scan", "Last scan"),
        ("scan_error", "Scan error"),
        ("notes", "Notes"),
    )
    facts = "".join(f"<tr><th>{h(label)}</th><td>{h(row[key] or '—')}</td></tr>" for key, label in fields)
    if row["ram_gb"]:
        facts += f"<tr><th>RAM</th><td>{h(row['ram_gb'])} GB</td></tr>"
    apps = ctx.store.device_software(device_id)
    app_rows = "".join(
        f"<tr><td>{h(item['name'])}</td><td>{h(item['version'] or '')}</td><td>{h(item['publisher'] or '')}</td></tr>"
        for item in apps[:200]
    )
    app_html = (
        "<table class='grid'><thead><tr><th>Name</th><th>Version</th><th>Publisher</th></tr></thead><tbody>"
        + (app_rows or "<tr><td colspan='3'>None recorded.</td></tr>")
        + "</tbody></table>"
    )
    if len(apps) > 200:
        app_html += f"<p class='muted'>Showing 200 of {len(apps)}.</p>"
    hotfix_rows = "".join(
        f"<tr><td>{h(item['hotfix_id'])}</td><td>{h(item['installed_on'] or '')}</td></tr>"
        for item in ctx.store.child_rows("hotfixes", device_id)[:80]
    )
    hotfixes = (
        "<table class='grid'><thead><tr><th>Hotfix</th><th>Installed</th></tr></thead><tbody>"
        + (hotfix_rows or "<tr><td colspan='2'>None recorded.</td></tr>")
        + "</tbody></table>"
    )
    service_rows = "".join(
        f"<tr><td>{h(item['name'])}</td><td>{h(item['status'] or '')}</td></tr>"
        for item in ctx.store.child_rows("services", device_id)[:80]
    )
    services = (
        "<table class='grid'><thead><tr><th>Service</th><th>Status</th></tr></thead><tbody>"
        + (service_rows or "<tr><td colspan='2'>None recorded.</td></tr>")
        + "</tbody></table>"
    )
    packages = [(item["id"], item["name"]) for item in ctx.store.packages()]
    creds = [("", "Default scan account")] + [(item["name"], item["name"]) for item in secrets.credentials()]
    actions = f"""
    <form class="stack" method="post" action="/act/deploy">{ctx.hidden()}
      <input type="hidden" name="device_id" value="{device_id}">
      <label>Package {select("package_id", packages, "")}</label>
      <label>Account {select("credential", creds, "")}</label>
      <button type="submit">Deploy to this computer</button>
    </form>
    <form class="stack" method="post" action="/act/tool">{ctx.hidden()}
      <input type="hidden" name="device_id" value="{device_id}">
      <label>Tool {select("kind", [("command", "Command"), ("powershell", "PowerShell")], "command")}</label>
      <label>Command or script <textarea name="payload"></textarea></label>
      <button type="submit">Run</button>
    </form>"""
    edit = f"""
    <form class="stack" method="post" action="/act/device-save">{ctx.hidden()}
      <input type="hidden" name="device_id" value="{device_id}">
      <label>Name <input name="name" value="{h(row['name'])}"></label>
      <label>Hostname <input name="hostname" value="{h(row['hostname'])}"></label>
      <label>IP <input name="ip" value="{h(row['ip'])}"></label>
      <label>OS <input name="os" value="{h(row['os'])}"></label>
      <label>Notes <input name="notes" value="{h(row['notes'])}"></label>
      <label>Type {select("type", [(item, item) for item in TYPES], row['type'])}</label>
      <button type="submit">Save</button>
    </form>
    <form method="post" action="/act/device-delete">{ctx.hidden()}
      <input type="hidden" name="device_id" value="{device_id}">
      <button class="danger" type="submit">Remove from inventory</button>
    </form>"""
    return f"""
    <div class="commandbar">
      <span>{_badge(row['status'])} {_badge(row['scan_status'] or 'never')}</span>
      <form method="post" action="/act/scan">{ctx.hidden()}<input type="hidden" name="device_id" value="{device_id}"><button class="primary" type="submit">Scan</button></form>
      <form method="post" action="/act/wake">{ctx.hidden()}<input type="hidden" name="device_id" value="{device_id}"><button type="submit">Wake</button></form>
      <form method="post" action="/act/tool">{ctx.hidden()}<input type="hidden" name="device_id" value="{device_id}"><input type="hidden" name="kind" value="reboot"><button class="danger" type="submit">Reboot</button></form>
    </div>
    {_tabs([
        ("Computer", f"<table class='props'>{facts}</table>"),
        ("Applications", app_html),
        ("Hotfixes", hotfixes),
        ("Services", services),
        ("Tools", actions + edit),
    ])}"""


def collections(ctx: Ctx) -> str:
    rows = []
    for row in ctx.store.collections():
        count = len(ctx.store.collection_device_ids(int(row["id"])))
        rows.append(f"<tr><td><a href='/collections/{row['id']}'>{h(row['name'])}</a></td><td>{h(row['kind'])}</td><td>{count}</td></tr>")
    create = f"""
    <form class="stack" method="post" action="/act/collection-create">{ctx.hidden()}
      <label>Name <input name="name" required></label>
      <label>Kind {select("kind", [("dynamic", "dynamic"), ("static", "static"), ("mixed", "mixed")], "dynamic")}</label>
      <button class="primary" type="submit">Create collection</button>
    </form>"""
    table = "<table><tr><th>Collection</th><th>Kind</th><th>Computers</th></tr>" + "".join(rows) + "</table>"
    return table + "<h2>New collection</h2>" + create


def collection_detail(ctx: Ctx, collection_id: int) -> str:
    row = ctx.store.collection(collection_id)
    if not row:
        return "<p class='muted'>That collection is gone.</p>"
    filters = []
    for item in ctx.store.collection_filters(collection_id):
        filters.append(
            f"<li>{h(item['field'])} {h(item['op'])} {h(item['value'])} "
            f"<form style='display:inline' method='post' action='/act/filter-delete'>{ctx.hidden()}"
            f"<input type='hidden' name='filter_id' value='{item['id']}'><input type='hidden' name='collection_id' value='{collection_id}'>"
            f"<button type='submit'>Remove</button></form></li>"
        )
    members = ctx.store.collection_devices(collection_id)
    member_html = "".join(f"<li><a href='/inventory/{item['id']}'>{h(item['name'])}</a> · {h(item['os'] or '')}</li>" for item in members[:100])
    pinned = ctx.store.static_member_ids(collection_id)
    names = {int(item["id"]): item["name"] for item in ctx.store.devices()}
    pin_rows = []
    for device_id in sorted(pinned):
        pin_rows.append(
            f"<li>{h(names.get(device_id, device_id))} "
            f"<form style='display:inline' method='post' action='/act/member-remove'>{ctx.hidden()}"
            f"<input type='hidden' name='collection_id' value='{collection_id}'><input type='hidden' name='device_id' value='{device_id}'>"
            f"<button type='submit'>Unpin</button></form></li>"
        )
    free = [(item["id"], item["name"]) for item in ctx.store.devices() if int(item["id"]) not in pinned]
    return f"""
    <form class="stack" method="post" action="/act/collection-save">{ctx.hidden()}
      <input type="hidden" name="collection_id" value="{collection_id}">
      <label>Name <input name="name" value="{h(row['name'])}"></label>
      <label>Description <input name="description" value="{h(row['description'])}"></label>
      <label>Kind {select("kind", [("dynamic", "dynamic"), ("static", "static"), ("mixed", "mixed")], row['kind'])}</label>
      <label>Filters {select("match_mode", [("all", "Match all"), ("any", "Match any")], row['match_mode'])}</label>
      <button type="submit">Save collection</button>
    </form>
    <div class="row">
      <form method="post" action="/act/scan">{ctx.hidden()}<input type="hidden" name="collection_id" value="{collection_id}"><button type="submit">Scan members</button></form>
      <form method="post" action="/act/collection-delete">{ctx.hidden()}<input type="hidden" name="collection_id" value="{collection_id}"><button class="danger" type="submit">Delete</button></form>
    </div>
    <h2>Filters</h2><ul>{''.join(filters) or '<li class="muted">No filters.</li>'}</ul>
    <form class="row" method="post" action="/act/filter-add">{ctx.hidden()}
      <input type="hidden" name="collection_id" value="{collection_id}">
      {select("field", FIELDS, "os")}
      {select("op", OPS, "contains")}
      <input name="value" placeholder="Value">
      <button type="submit">Add filter</button>
    </form>
    <h2>Members ({len(members)})</h2><ul>{member_html or '<li class="muted">No computers match.</li>'}</ul>
    <h2>Pinned</h2><ul>{''.join(pin_rows) or '<li class="muted">None pinned.</li>'}</ul>
    <form class="row" method="post" action="/act/member-add">{ctx.hidden()}
      <input type="hidden" name="collection_id" value="{collection_id}">
      {select("device_id", free, "")}
      <button type="submit">Pin computer</button>
    </form>"""


def deploy(ctx: Ctx) -> str:
    selected = ctx.query.get("package", "")
    package_rows = []
    for row in ctx.store.packages():
        package_rows.append(
            f"<li class='{'picked' if str(row['id']) == selected else ''}'>"
            f"<a href='/deploy?package={row['id']}'>{h(row['name'])}</a> "
            f"<span class='muted'>{h(row['version'] or '')}</span></li>"
        )
    steps = ""
    editor = ""
    if selected.isdigit():
        package = ctx.store.package(int(selected))
        if package:
            step_rows = []
            for step in ctx.store.package_steps(int(selected)):
                step_rows.append(
                    f"<li>{h(step['position'])}. {h(step['kind'])} — {h(step['name'])} "
                    f"<form style='display:inline' method='post' action='/act/step-move'>{ctx.hidden()}"
                    f"<input type='hidden' name='step_id' value='{step['id']}'><input type='hidden' name='package_id' value='{selected}'><input type='hidden' name='direction' value='-1'><button type='submit'>Up</button></form> "
                    f"<form style='display:inline' method='post' action='/act/step-move'>{ctx.hidden()}"
                    f"<input type='hidden' name='step_id' value='{step['id']}'><input type='hidden' name='package_id' value='{selected}'><input type='hidden' name='direction' value='1'><button type='submit'>Down</button></form> "
                    f"<form style='display:inline' method='post' action='/act/step-delete'>{ctx.hidden()}"
                    f"<input type='hidden' name='step_id' value='{step['id']}'><input type='hidden' name='package_id' value='{selected}'><button type='submit'>Remove</button></form></li>"
                )
            others = [(item["id"], item["name"]) for item in ctx.store.packages() if str(item["id"]) != selected]
            steps = f"<h2>{h(package['name'])}</h2><ul>{''.join(step_rows) or '<li class=\"muted\">No steps.</li>'}</ul>"
            editor = f"""
            <form class="stack" method="post" action="/act/step-save" enctype="multipart/form-data">{ctx.hidden()}
              <input type="hidden" name="package_id" value="{selected}">
              <label>Kind {select("kind", [(item, item) for item in KINDS], "command")}</label>
              <label>Name <input name="name" placeholder="Step name"></label>
              <label>Command, script, seconds, or a path on the server <textarea name="payload"></textarea></label>
              <label>Or upload an installer <input type="file" name="file"></label>
              <label>Install arguments <input name="args" placeholder="/qn /norestart"></label>
              <label>Success codes <input name="success_codes" placeholder="{h(default_codes('command'))}"></label>
              <label class="checks"><input type="checkbox" name="continue_on_error"> Continue on error</label>
              <label>Condition {select("condition_field", [("", "Always run"), *FIELDS], "")}</label>
              {select("condition_op", OPS, "contains")}
              <input name="condition_value" placeholder="Condition value">
              <label>Nested package {select("nested_package_id", [("", "None"), *others], "")}</label>
              <button type="submit">Add step</button>
            </form>
            <form class="stack" method="post" action="/act/package-save">{ctx.hidden()}
              <input type="hidden" name="package_id" value="{selected}">
              <label>Package name <input name="name" value="{h(package['name'])}"></label>
              <label>Version <input name="version" value="{h(package['version'])}"></label>
              <label>Description <input name="description" value="{h(package['description'])}"></label>
              <label>Timeout seconds <input name="timeout_sec" value="{h(package['timeout_sec'])}"></label>
              <button type="submit">Save package</button>
            </form>
            <form method="post" action="/act/package-delete">{ctx.hidden()}<input type="hidden" name="package_id" value="{selected}"><button class="danger" type="submit">Delete package</button></form>"""
    collections = [(row["id"], row["name"]) for row in ctx.store.collections()]
    computers = [(row["id"], row["name"]) for row in ctx.store.devices()]
    packages = [(row["id"], row["name"]) for row in ctx.store.packages()]
    creds = [("", "Default scan account")] + [(item["name"], item["name"]) for item in secrets.credentials()]
    launch = f"""
    <h2>Deploy now</h2>
    <form class="stack" method="post" action="/act/deploy">{ctx.hidden()}
      <label>Package {select("package_id", packages, selected)}</label>
      <label>Collection {select("collection_id", [("", "No collection"), *collections], "")}</label>
      <label>One computer {select("device_id", [("", "No single computer"), *computers], "")}</label>
      <label>Account {select("credential", creds, "")}</label>
      <button class="primary" type="submit">Deploy</button>
    </form>"""
    history = []
    for row in ctx.store.deployments(20):
        targets = ctx.store.deployment_targets(int(row["id"]))
        lines = "".join(
            f"<li>{_badge(item['status'])} {h(item['device_name'])}<pre>{h(item['log'] or '')}</pre></li>" for item in targets
        )
        history.append(
            f"<section class='panel'><h3>{_badge(row['status'])} {h(row['package_name'])} · {h(row['created_at'])}</h3><ul>{lines}</ul>"
            f"<form method='post' action='/act/retry'>{ctx.hidden()}<input type='hidden' name='deployment_id' value='{row['id']}'><button type='submit'>Retry failed</button></form></section>"
        )
    schedules = []
    for row in ctx.store.schedules():
        schedules.append(
            f"<li>{h(row['name'])} · {h(row['kind'])} · {h(row['trigger'])} · next {h(row['next_run'] or 'heartbeat')} "
            f"<form style='display:inline' method='post' action='/act/schedule-delete'>{ctx.hidden()}<input type='hidden' name='schedule_id' value='{row['id']}'><button type='submit'>Delete</button></form></li>"
        )
    schedule_form = f"""
    <form class="stack" method="post" action="/act/schedule-save">{ctx.hidden()}
      <label>Name <input name="name" required></label>
      <label>Kind {select("kind", [("scan", "Scan"), ("deploy", "Deploy")], "deploy")}</label>
      <label>When {select("trigger", [("interval", "Interval"), ("daily", "Daily UTC"), ("heartbeat", "Heartbeat")], "interval")}</label>
      <label>Interval minutes <input name="interval_minutes" value="60"></label>
      <label>Daily time UTC <input name="time_of_day" value="02:00"></label>
      <label>Package {select("package_id", [("", "None"), *packages], "")}</label>
      <label>Collection {select("collection_id", [("", "All scannable computers"), *collections], "")}</label>
      <label>Account {select("credential", creds, "")}</label>
      <button type="submit">Save schedule</button>
    </form>"""
    new_package = f"""
    <form class="stack" method="post" action="/act/package-save">{ctx.hidden()}
      <label>New package <input name="name" required></label>
      <label>Version <input name="version"></label>
      <label>Description <input name="description"></label>
      <button type="submit">Create package</button>
    </form>"""
    return f"""
    <div class="split">
      <section class="library"><h2>Packages</h2><ul>{''.join(package_rows) or '<li class="muted">None yet.</li>'}</ul>{new_package}{steps}{editor}</section>
      <section>{launch}</section>
    </div>
    <h2>History</h2>{''.join(history) or '<p class="muted">No deployments yet.</p>'}
    <h2>Schedules</h2>
    <p class="muted">Interval and daily schedules run while this service is up. Daily times are UTC. Heartbeat deploys after a successful scan when the computer is in the collection and has never succeeded for that package.</p>
    <ul>{''.join(schedules) or '<li class="muted">No schedules.</li>'}</ul>
    {schedule_form}"""


def tickets(ctx: Ctx) -> str:
    status = ctx.query.get("status", "active")
    query = ctx.query.get("q", "")
    rows = []
    for row in ctx.store.tickets(status if status != "all" else None, query):
        rows.append(
            f"<tr><td><a href='/tickets/{row['id']}'>#{h(row['number'])} {h(row['title'])}</a></td>"
            f"<td>{_badge(row['status'])}</td><td>{_badge(row['priority'])}</td><td>{h(row['requester'] or '')}</td></tr>"
        )
    people = [(row["id"], row["name"]) for row in ctx.store.people()]
    devices = [(row["id"], row["name"]) for row in ctx.store.devices()]
    form = f"""
    <form class="row" method="get" action="/tickets">
      {select("status", [("active", "Active"), ("all", "All"), ("open", "Open"), ("waiting", "Waiting"), ("closed", "Closed")], status)}
      <input name="q" value="{h(query)}" placeholder="Search">
      <button type="submit">Filter</button>
    </form>
    <h2>New ticket</h2>
    <form class="stack" method="post" action="/act/ticket-save">{ctx.hidden()}
      <label>Title <input name="title" required></label>
      <label>Description <textarea name="description"></textarea></label>
      <label>Priority {select("priority", [(item, item) for item in ("low", "medium", "high", "critical")], "medium")}</label>
      <label>Requester {select("requester_id", [("", "None"), *people], "")}</label>
      <label>Computer {select("device_id", [("", "None"), *devices], "")}</label>
      <label>Assignee <input name="assignee" value="{h(ctx.user['display_name'])}"></label>
      <button class="primary" type="submit">Open ticket</button>
    </form>"""
    table = "<table><tr><th>Ticket</th><th>Status</th><th>Priority</th><th>Requester</th></tr>" + "".join(rows) + "</table>"
    return form + (table if rows else "<p class='muted'>No tickets.</p>")


def ticket_detail(ctx: Ctx, ticket_id: int) -> str:
    row = ctx.store.ticket(ticket_id)
    if not row:
        return "<p class='muted'>That ticket is gone.</p>"
    comments = "".join(
        f"<li><b>{h(item['author'])}</b> · {h(item['created_at'])}<br>{h(item['body'])}</li>" for item in ctx.store.comments(ticket_id)
    )
    buttons = []
    for status in ("open", "waiting", "closed"):
        buttons.append(
            f"<form method='post' action='/act/ticket-status'>{ctx.hidden()}<input type='hidden' name='ticket_id' value='{ticket_id}'>"
            f"<input type='hidden' name='status' value='{status}'><button type='submit'>{status}</button></form>"
        )
    return f"""
    <p>{_badge(row['status'])} {_badge(row['priority'])}</p>
    <p>{h(row['description'] or '')}</p>
    <p class="muted">Requester {h(row['requester'] or '—')} · Computer {h(row['device_name'] or '—')} · Assignee {h(row['assignee'] or '—')}</p>
    <div class="row">{''.join(buttons)}</div>
    <h2>Comments</h2><ul>{comments or '<li class="muted">No comments.</li>'}</ul>
    <form class="stack" method="post" action="/act/ticket-comment">{ctx.hidden()}
      <input type="hidden" name="ticket_id" value="{ticket_id}">
      <label>Comment <textarea name="body" required></textarea></label>
      <button type="submit">Add comment</button>
    </form>"""


def network(ctx: Ctx) -> str:
    from helix_it import network as net

    ifaces = []
    for iface in net.list_interfaces():
        ifaces.append(
            f"<li><b>{h(iface.name)}</b> {h(iface.operstate)}<br><span class='muted'>{h(', '.join(iface.cidrs) or 'no address')} · {h(iface.mac or '')}</span></li>"
        )
    neighbors = []
    for item in net.list_neighbors():
        neighbors.append(f"<li>{h(item.ip)} {h(item.mac or '')} ({h(item.iface or '')})</li>")
    return f"""
    <form method="post" action="/act/lan-scan">{ctx.hidden()}<button class="primary" type="submit">Scan local subnets</button></form>
    <p class="muted">Ping sweep only covers private addresses on this host. In Docker, use host networking so those are the shop subnets.</p>
    <div class="split">
      <section class="panel"><h2>Interfaces</h2><ul>{''.join(ifaces) or '<li class="muted">None.</li>'}</ul></section>
      <section class="panel"><h2>Neighbors</h2><ul>{''.join(neighbors) or '<li class="muted">None yet.</li>'}</ul></section>
    </div>"""


def software(ctx: Ctx) -> str:
    query = ctx.query.get("q", "")
    rows = []
    for row in ctx.store.software_summary(query):
        rows.append(
            f"<tr><td>{h(row['name'])}</td><td>{h(row['publisher'] or '')}</td><td>{h(row['versions'] or '')}</td><td>{h(row['installs'])}</td></tr>"
        )
    form = f"""<form class="row" method="get" action="/software"><input name="q" value="{h(query)}" placeholder="Search titles"><button type="submit">Search</button></form>"""
    table = "<table><tr><th>Title</th><th>Publisher</th><th>Versions</th><th>Installs</th></tr>" + "".join(rows) + "</table>"
    return form + (table if rows else "<p class='muted'>No software recorded yet.</p>")


def people(ctx: Ctx) -> str:
    query = ctx.query.get("q", "")
    rows = []
    for row in ctx.store.people(query):
        rows.append(
            f"<tr><td>{h(row['name'])}</td><td>{h(row['email'] or '')}</td><td>{h(row['department'] or '')}</td><td>{h(row['title'] or '')}</td><td>{h(row['devices'])}</td></tr>"
        )
    form = f"""
    <form class="row" method="get" action="/people"><input name="q" value="{h(query)}" placeholder="Search people"><button type="submit">Search</button></form>
    <h2>Add a person</h2>
    <form class="stack" method="post" action="/act/person-save">{ctx.hidden()}
      <label>Name <input name="name" required></label>
      <label>Email <input name="email"></label>
      <label>Department <input name="department"></label>
      <label>Title <input name="title"></label>
      <button class="primary" type="submit">Add</button>
    </form>"""
    table = "<table><tr><th>Name</th><th>Email</th><th>Department</th><th>Title</th><th>Devices</th></tr>" + "".join(rows) + "</table>"
    return form + (table if rows else "")


def reports(ctx: Ctx) -> str:
    blocks = (
        ("Devices by type", ctx.store.type_counts()),
        ("Operating systems", ctx.store.os_counts()),
        ("Inventory scans", ctx.store.scan_status_counts()),
        ("Deployment results", ctx.store.deployment_status_counts()),
        ("Open tickets by priority", ctx.store.ticket_priority_counts()),
    )
    sections = "".join(f"<section class='panel'><h2>{h(title)}</h2>{_bars(rows)}</section>" for title, rows in blocks)
    return f"<div class='stack' style='max-width:860px'>{sections}</div>"


def settings(ctx: Ctx) -> str:
    directory = secrets.directory()
    winrm = secrets.winrm_config()
    profile = ctx.store.scan_profile()
    checks = []
    for key, label in PROFILE_FLAGS:
        checked = " checked" if int(profile[key] or 0) else ""
        checks.append(f"<label><input type='checkbox' name='{h(key)}'{checked}> {h(label)}</label>")
    cred_rows = []
    for cred in secrets.credentials():
        cred_rows.append(
            f"<li>{h(cred['name'])} · {h(cred.get('domain') or '')}\\{h(cred.get('username') or '')} "
            f"<form style='display:inline' method='post' action='/act/credential-delete'>{ctx.hidden()}"
            f"<input type='hidden' name='name' value='{h(cred['name'])}'><button type='submit'>Delete</button></form></li>"
        )
    cred_names = [("", "First saved account")] + [(item["name"], item["name"]) for item in secrets.credentials()]
    status = " ".join(part for part in (ctx.store.get_meta("ad_status") or "", ctx.store.get_meta("ad_synced_at") or "") if part)
    return f"""
    <p class="muted">Directory passwords stay in the data volume, not in the inventory database. Current directory status: {h(status or 'not synced')}</p>
    <h2>Shop</h2>
    <form class="stack" method="post" action="/act/shop-save">{ctx.hidden()}
      <label>Organization <input name="org_name" value="{h(ctx.store.get_meta('org_name') or '')}"></label>
      <label>Default technician <input name="tech_name" value="{h(ctx.store.get_meta('tech_name') or '')}"></label>
      <button type="submit">Save shop</button>
    </form>
    <h2>Active Directory</h2>
    <p class="muted">Sync reads computers, OUs, groups, and users into this inventory. The directory connection is read-only.</p>
    <form class="stack" method="post" action="/act/directory-save">{ctx.hidden()}
      <label>Domain controller <input name="server" value="{h(directory.get('server') or '')}"></label>
      <label>Port <input name="port" value="{h(directory.get('port') or 389)}"></label>
      <label class="checks"><input type="checkbox" name="use_ssl" {"checked" if directory.get("use_ssl") else ""}> Use LDAPS</label>
      <label>DNS domain <input name="dns_domain" value="{h(directory.get('dns_domain') or '')}"></label>
      <label>NetBIOS <input name="netbios" value="{h(directory.get('netbios') or '')}"></label>
      <label>Base DN <input name="base_dn" value="{h(directory.get('base_dn') or '')}"></label>
      <label>Username <input name="username" value="{h(directory.get('username') or '')}"></label>
      <label>Password <input name="password" type="password" placeholder="{"Saved — type to replace" if directory.get("password") else "Password"}"></label>
      <div class="row">
        <button type="submit">Save directory</button>
        <button type="submit" formaction="/act/directory-test">Test connection</button>
        <button type="submit" formaction="/act/directory-sync">Sync now</button>
      </div>
    </form>
    <form method="post" action="/act/directory-stale">{ctx.hidden()}
      <label class="checks"><input type="checkbox" name="confirm" value="yes"> Remove computers from this inventory that were missing from the last directory sync</label>
      <button class="danger" type="submit">Remove from inventory</button>
    </form>
    <h2>Scan accounts</h2>
    <ul>{''.join(cred_rows) or '<li class="muted">No accounts saved.</li>'}</ul>
    <form class="stack" method="post" action="/act/credential-save">{ctx.hidden()}
      <label>Name <input name="name" required></label>
      <label>Username <input name="username"></label>
      <label>NetBIOS domain <input name="domain"></label>
      <label>Password <input name="password" type="password" placeholder="Leave blank to keep the saved password"></label>
      <button type="submit">Save account</button>
    </form>
    <h2>WinRM</h2>
    <form class="stack" method="post" action="/act/winrm-save">{ctx.hidden()}
      <label>Transport {select("transport", [(item, item) for item in ("ntlm", "kerberos", "basic")], winrm.get("transport") or "ntlm")}</label>
      <label>Port <input name="port" value="{h(winrm.get('port') or 5985)}"></label>
      <label class="checks"><input type="checkbox" name="use_ssl" {"checked" if winrm.get("use_ssl") else ""}> HTTPS</label>
      <label>Default account {select("credential", cred_names, winrm.get("credential") or "")}</label>
      <button type="submit">Save WinRM</button>
    </form>
    <h2>Scan profile</h2>
    <form class="stack" method="post" action="/act/profile-save">{ctx.hidden()}
      <div class="checks">{''.join(checks)}</div>
      <label>Extra PowerShell <textarea name="custom_script">{h(profile['custom_script'] or '')}</textarea></label>
      <button type="submit">Save profile</button>
    </form>
    <h2>Sample data</h2>
    <form method="post" action="/act/sample-reset">{ctx.hidden()}
      <label class="checks"><input type="checkbox" name="confirm" value="yes"> Replace inventory with the Northline Workshop sample</label>
      <button class="danger" type="submit">Reload sample data</button>
    </form>
    <p class="muted">Database file: {h(ctx.store.path)}</p>"""


def agents(ctx: Ctx) -> str:
    rows = []
    for row in ctx.store.fetchall("SELECT id, username, display_name, created_at FROM agents ORDER BY username"):
        rows.append(
            f"<li>{h(row['display_name'])} · {h(row['username'])} "
            f"<form style='display:inline' method='post' action='/act/agent-delete'>{ctx.hidden()}"
            f"<input type='hidden' name='agent_id' value='{row['id']}'><button type='submit'>Remove</button></form></li>"
        )
    return f"""
    <p class="muted">Signed in as {h(ctx.user['display_name'])}. Each person should have their own login. Jobs such as scans and deploys are shared, so a second agent can keep working in the inventory while one deploy runs.</p>
    <ul>{''.join(rows)}</ul>
    <h2>Add an agent</h2>
    <form class="stack" method="post" action="/act/agent-save">{ctx.hidden()}
      <label>Username <input name="username" required></label>
      <label>Display name <input name="display_name"></label>
      <label>Password <input name="password" type="password" required></label>
      <button class="primary" type="submit">Add agent</button>
    </form>
    <h2>Change your password</h2>
    <form class="stack" method="post" action="/act/password-save">{ctx.hidden()}
      <label>Current password <input name="current" type="password" required></label>
      <label>New password <input name="password" type="password" required></label>
      <button type="submit">Update password</button>
    </form>"""
