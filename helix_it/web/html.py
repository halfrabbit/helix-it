from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any


NAV = (
    ("/", "Dashboard"),
    ("/inventory", "Inventory"),
    ("/collections", "Collections"),
    ("/deploy", "Deploy"),
    ("/tickets", "Help desk"),
    ("/network", "Network"),
    ("/software", "Software"),
    ("/people", "People"),
    ("/reports", "Reports"),
    ("/settings", "Settings"),
    ("/agents", "Agents"),
)


def h(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


@dataclass
class Ctx:
    store: Any
    hub: Any
    user: Any
    query: dict[str, str]
    csrf: str

    def hidden(self) -> str:
        return f'<input type="hidden" name="csrf" value="{h(self.csrf)}">'


def select(name: str, pairs: list[tuple[Any, Any]], current: Any = "") -> str:
    options = []
    for value, label in pairs:
        selected = " selected" if str(value) == str(current if current is not None else "") else ""
        options.append(f'<option value="{h(value)}"{selected}>{h(label)}</option>')
    return f'<select name="{h(name)}">{"".join(options)}</select>'


def page(title: str, body: str, *, username: str, csrf: str = "", notice: str = "", error: str = "", job: str = "", detail: str = "", busy: bool = False) -> str:
    links = []
    for href, label in NAV:
        links.append(f'<a href="{href}">{h(label)}</a>')
    banner = ""
    if error:
        banner += f'<p class="banner bad">{h(error)}</p>'
    if notice:
        banner += f'<p class="banner ok">{h(notice)}</p>'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{h(title)} · Helix IT</title>
  <link rel="stylesheet" href="/static/app.css">
</head>
<body data-busy="{"1" if busy else "0"}">
  <aside>
    <p class="mark">HELIX IT</p>
    <p class="brand">Shared console</p>
    <nav>{"".join(links)}</nav>
    <form method="post" action="/act/logout" class="logout">
      <input type="hidden" name="csrf" value="{h(csrf)}">
      <p>{h(username)}</p>
      <button type="submit">Sign out</button>
    </form>
  </aside>
  <main>
    <header>
      <h1>{h(title)}</h1>
      <p id="job">{h(job or "Idle")}</p>
      <pre id="job-detail">{h(detail)}</pre>
    </header>
    {banner}
    {body}
  </main>
  <script>
    let wasBusy = document.body.dataset.busy === "1";
    async function poll() {{
      try {{
        const data = await (await fetch("/api/status")).json();
        const job = document.getElementById("job");
        const detail = document.getElementById("job-detail");
        if (job) job.textContent = data.message || "Idle";
        if (detail) detail.textContent = data.detail || "";
        if (wasBusy && !data.busy) location.reload();
        wasBusy = !!data.busy;
        setTimeout(poll, data.busy ? 1200 : 5000);
      }} catch (err) {{
        setTimeout(poll, 5000);
      }}
    }}
    poll();
  </script>
</body>
</html>"""


def login_page(error: str = "") -> str:
    banner = f'<p class="banner bad">{h(error)}</p>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sign in · Helix IT</title>
  <link rel="stylesheet" href="/static/app.css">
</head>
<body class="login-body">
  <form class="login" method="post" action="/login">
    <p class="mark">HELIX IT</p>
    <h1>Sign in</h1>
    <p class="muted">Shared inventory and deploy for the shop. Each agent uses their own login.</p>
    {banner}
    <label>Username <input name="username" autocomplete="username" required></label>
    <label>Password <input name="password" type="password" autocomplete="current-password" required></label>
    <button type="submit">Sign in</button>
  </form>
</body>
</html>"""
