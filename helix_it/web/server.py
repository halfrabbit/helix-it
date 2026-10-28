from __future__ import annotations

import hmac
import json
import os
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from helix_it.db import Store
from helix_it.seed import seed, upsert_this_machine
from helix_it.web import actions, auth, views
from helix_it.web.form import MAX_BODY, parse_body
from helix_it.web.html import Ctx, login_page, page
from helix_it.web.hub import Hub


def _static_path() -> Path:
    return Path(__file__).parent / "static" / "app.css"


def _cookies(header: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for part in header.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        found[key.strip()] = value.strip()
    return found


def _csrf_ok(got: str, expected: str) -> bool:
    if not got or not expected or len(got) != len(expected):
        return False
    return hmac.compare_digest(got, expected)


def _cookie(token: str) -> str:
    parts = [
        f"helix={token}",
        "HttpOnly",
        "SameSite=Lax",
        "Path=/",
        f"Max-Age={18 * 3600}",
    ]
    if os.environ.get("HELIX_HTTPS") == "1":
        parts.append("Secure")
    return "; ".join(parts)


class Handler(BaseHTTPRequestHandler):
    server_version = "HelixIT"

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} {fmt % args}", flush=True)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path or "/"
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")
        if path == "/health":
            self._bytes(200, b"ok\n", "text/plain; charset=utf-8")
            return
        if path == "/static/app.css":
            try:
                data = _static_path().read_bytes()
            except OSError:
                self._bytes(404, b"missing css\n", "text/plain; charset=utf-8")
                return
            self._bytes(200, data, "text/css; charset=utf-8")
            return
        user, csrf = self._session()
        if path == "/api/status":
            if not user:
                self._bytes(401, b'{"busy":false,"message":"","detail":""}', "application/json")
                return
            snap = self.server.hub.snapshot()
            self._bytes(200, json.dumps(snap).encode("utf-8"), "application/json")
            return
        if path == "/login":
            if user:
                self._redirect("/")
                return
            self._html(200, login_page())
            return
        if not user:
            self._redirect("/login")
            return
        query = {key: values[-1] for key, values in parse_qs(parsed.query, keep_blank_values=True).items()}
        ctx = Ctx(self.server.store, self.server.hub, user, query, csrf or "")
        title, body = self._view(path, ctx)
        if title is None:
            self._html(404, page("Not found", "<p class='muted'>That page is not here.</p>", username=user["display_name"], csrf=ctx.csrf))
            return
        snap = self.server.hub.snapshot()
        self._html(
            200,
            page(
                title,
                body,
                username=user["display_name"] or user["username"],
                csrf=ctx.csrf,
                notice=query.get("notice", ""),
                error=query.get("error", ""),
                job=snap["message"],
                detail=snap["detail"],
                busy=snap["busy"],
                current=path,
            ),
        )

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path or "/"
        length = int(self.headers.get("Content-Length") or "0")
        if length > MAX_BODY:
            self._html(413, login_page("Upload is larger than 512 MB."))
            return
        body = self.rfile.read(length) if length else b""
        try:
            form = parse_body(self.headers.get("Content-Type") or "", body)
        except ValueError as exc:
            self._html(400, login_page(str(exc)))
            return
        if path == "/login":
            self._login(form.get("username"), form.get("password"))
            return
        user, csrf = self._session()
        if not user:
            self._redirect("/login")
            return
        if not path.startswith("/act/"):
            self._html(404, page("Not found", "<p class='muted'>That action is not here.</p>", username=user["display_name"], csrf=csrf or ""))
            return
        if not _csrf_ok(form.get("csrf"), csrf or ""):
            self._html(403, page("Rejected", "<p>That form was missing a valid session token. Reload the page and try again.</p>", username=user["display_name"], csrf=csrf or ""))
            return
        name = path.removeprefix("/act/")
        if name == "logout":
            self._redirect("/login", clear=True)
            return
        handler = actions.HANDLERS.get(name)
        query = {key: values[-1] for key, values in parse_qs(parsed.query, keep_blank_values=True).items()}
        ctx = Ctx(self.server.store, self.server.hub, user, query, csrf or "")
        if not handler:
            self._redirect(actions.go("/", error="Unknown action."))
            return
        try:
            location = handler(ctx, form, form.files)
        except Exception as exc:
            location = actions.go("/", error=str(exc)[:300])
        self._redirect(location)

    def _view(self, path: str, ctx: Ctx) -> tuple[str | None, str]:
        simple = {
            "/": ("Dashboard", views.dashboard),
            "/inventory": ("Inventory", views.inventory),
            "/collections": ("Collections", views.collections),
            "/deploy": ("Deploy", views.deploy),
            "/tickets": ("Help desk", views.tickets),
            "/network": ("Network", views.network),
            "/software": ("Software", views.software),
            "/people": ("People", views.people),
            "/reports": ("Reports", views.reports),
            "/settings": ("Settings", views.settings),
            "/agents": ("Agents", views.agents),
        }
        if path in simple:
            title, fn = simple[path]
            return title, fn(ctx)
        parts = [part for part in path.split("/") if part]
        if len(parts) == 2 and parts[1].isdigit():
            item_id = int(parts[1])
            if parts[0] == "inventory":
                row = self.server.store.device(item_id)
                return (row["name"] if row else "Computer"), views.device(ctx, item_id)
            if parts[0] == "collections":
                row = self.server.store.collection(item_id)
                return (row["name"] if row else "Collection"), views.collection_detail(ctx, item_id)
            if parts[0] == "tickets":
                row = self.server.store.ticket(item_id)
                title = f"#{row['number']} {row['title']}" if row else "Ticket"
                return title, views.ticket_detail(ctx, item_id)
        return None, ""

    def _session(self):
        token = _cookies(self.headers.get("Cookie") or "").get("helix")
        if not token:
            return None, None
        data = auth.loads(token, self.server.session_key)
        if not data:
            return None, None
        row = self.server.store.fetchone("SELECT * FROM agents WHERE username = ?", (data.get("user"),))
        if not row:
            return None, None
        return row, str(data.get("csrf") or "")

    def _login(self, username: str, password: str) -> None:
        user = auth.authenticate(self.server.store, username, password)
        if not user:
            self._html(200, login_page("That username or password does not match."))
            return
        csrf = secrets.token_urlsafe(18)
        token = auth.issue_session(user["username"], csrf, self.server.session_key)
        self._redirect("/", cookie=_cookie(token))

    def _redirect(self, location: str, cookie: str | None = None, clear: bool = False) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        if clear:
            self.send_header("Set-Cookie", "helix=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _html(self, status: int, body: str) -> None:
        self._bytes(status, body.encode("utf-8"), "text/html; charset=utf-8")

    def _bytes(self, status: int, data: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


class HelixServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, store: Store, hub: Hub, bind: str, port: int) -> None:
        super().__init__((bind, port), Handler)
        self.store = store
        self.hub = hub
        self.session_key = auth.session_secret()


def prepare() -> tuple[Store, Hub]:
    store = Store()
    if not store.get_meta("seeded"):
        if os.environ.get("HELIX_SAMPLE") == "1":
            seed(store)
        else:
            upsert_this_machine(store)
            store.set_meta("org_name", (os.environ.get("HELIX_ORG") or "Helix IT").strip() or "Helix IT")
            store.set_meta("tech_name", (os.environ.get("HELIX_TECH") or "IT Desk").strip() or "IT Desk")
            store.set_meta("seeded", "1")
    auth.ensure_admin(store)
    hub = Hub(store)
    hub.start_ticker()
    return store, hub


def make_server(bind: str | None = None, port: int | None = None) -> HelixServer:
    store, hub = prepare()
    host = bind if bind is not None else (os.environ.get("HELIX_BIND") or "0.0.0.0")
    listen = port if port is not None else int(os.environ.get("HELIX_PORT") or "8080")
    return HelixServer(store, hub, host, listen)


def main() -> None:
    httpd = make_server()
    host, port = httpd.server_address[:2]
    shown = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    print(f"Helix IT web console at http://{shown}:{port}/", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("Stopping.", flush=True)
    finally:
        httpd.hub.stop()
        httpd.server_close()
