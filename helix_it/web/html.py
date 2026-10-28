from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any


GROUPS = (
    ("Inventory", (
        ("/inventory", "Computers"),
        ("/collections", "Collections"),
        ("/software", "Applications"),
        ("/reports", "Reports"),
    )),
    ("Deploy", (
        ("/deploy", "Packages"),
    )),
    ("Directory", (
        ("/people", "Users"),
        ("/network", "Network"),
    )),
    ("Shop", (
        ("/", "Overview"),
        ("/tickets", "Help desk"),
        ("/settings", "Options"),
        ("/agents", "Agents"),
        ("/about", "About"),
    )),
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


def _active(href: str, current: str) -> bool:
    if href == "/":
        return current in {"", "/"}
    return current == href or current.startswith(href + "/")


def page(title: str, body: str, *, username: str, csrf: str = "", notice: str = "", error: str = "", job: str = "", detail: str = "", busy: bool = False, current: str = "") -> str:
    trees = []
    for group, links in GROUPS:
        items = []
        for href, label in links:
            mark = " active" if _active(href, current) else ""
            items.append(f'<a class="{mark.strip()}" href="{href}">{h(label)}</a>')
        trees.append(f'<p class="tree-label">{h(group)}</p><nav>{"".join(items)}</nav>')
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
  <header class="titlebar">
    <span class="mark">HELIX</span>
    <span class="product">Inventory · Deploy</span>
    <span class="spacer"></span>
    <span class="who">{h(username)}</span>
  </header>
  <div class="workspace">
    <aside>
      {"".join(trees)}
      <form method="post" action="/act/logout" class="logout">
        <input type="hidden" name="csrf" value="{h(csrf)}">
        <button type="submit">Sign out</button>
      </form>
    </aside>
    <div class="work">
      <div class="toolbar"><h1>{h(title)}</h1></div>
      <div class="sheet">
        {banner}
        {body}
      </div>
      <footer class="statusbar">
        <span id="job">{h(job or "Ready")}</span>
        <pre id="job-detail">{h(detail)}</pre>
      </footer>
    </div>
  </div>
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
    <header class="titlebar"><span class="mark">HELIX</span><span class="product">Inventory · Deploy</span></header>
    <h1>Sign in</h1>
    <p class="muted">Shop inventory and deploy. Each agent uses their own login.</p>
    {banner}
    <label>Username <input name="username" autocomplete="username" required></label>
    <label>Password <input name="password" type="password" autocomplete="current-password" required></label>
    <button type="submit">Sign in</button>
  </form>
</body>
</html>"""
