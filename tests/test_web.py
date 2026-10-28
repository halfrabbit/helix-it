import http.client
import os
import re
import tempfile
import threading
import time
import unittest
from urllib.parse import urlencode

from helix_it.web import auth
from helix_it.web.form import parse_body
from helix_it.web.server import make_server


class PasswordTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        stored = auth.hash_password("shop-secret")
        self.assertTrue(auth.verify_password("shop-secret", stored))
        self.assertFalse(auth.verify_password("other", stored))
        self.assertFalse(auth.verify_password("shop-secret", "not-a-hash"))


class MultipartTests(unittest.TestCase):
    def test_fields_and_file(self) -> None:
        body = (
            b"--bound\r\n"
            b'Content-Disposition: form-data; name="name"\r\n\r\n'
            b"Echo\r\n"
            b"--bound\r\n"
            b'Content-Disposition: form-data; name="file"; filename="setup.msi"\r\n'
            b"Content-Type: application/octet-stream\r\n\r\n"
            b"MSI\r\n"
            b"--bound--\r\n"
        )
        form = parse_body("multipart/form-data; boundary=bound", body)
        self.assertEqual(form.get("name"), "Echo")
        self.assertEqual(form.files["file"], ("setup.msi", b"MSI"))


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["HELIX_DATA"] = self.tmp.name
        os.environ["HELIX_ADMIN_USER"] = "admin"
        os.environ["HELIX_ADMIN_PASSWORD"] = "shop-secret"
        os.environ["HELIX_SAMPLE"] = "0"
        self.httpd = make_server("127.0.0.1", 0)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.port = int(self.httpd.server_address[1])

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.httpd.hub.stop()
        self.httpd.store.close()
        self.tmp.cleanup()

    def request(self, method: str, path: str, body: bytes | None = None, cookie: str | None = None, content_type: str = "application/x-www-form-urlencoded"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        headers = {}
        if cookie:
            headers["Cookie"] = cookie
        if body is not None:
            headers["Content-Type"] = content_type
            headers["Content-Length"] = str(len(body))
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        payload = response.read()
        headers_out = {key.lower(): value for key, value in response.getheaders()}
        conn.close()
        return response.status, headers_out, payload

    def login(self) -> str:
        status, headers, _payload = self.request(
            "POST",
            "/login",
            urlencode({"username": "admin", "password": "shop-secret"}).encode(),
        )
        self.assertEqual(status, 303)
        self.assertEqual(headers["location"], "/")
        cookie = headers["set-cookie"].split(";", 1)[0]
        self.assertTrue(cookie.startswith("helix="))
        return cookie

    def csrf(self, cookie: str, path: str = "/agents") -> str:
        status, _headers, payload = self.request("GET", path, cookie=cookie)
        self.assertEqual(status, 200)
        match = re.search(r'name="csrf" value="([^"]+)"', payload.decode())
        self.assertIsNotNone(match)
        return match.group(1)

    def test_login_failure_and_success(self) -> None:
        status, _headers, payload = self.request(
            "POST",
            "/login",
            urlencode({"username": "admin", "password": "nope"}).encode(),
        )
        self.assertEqual(status, 200)
        self.assertIn(b"does not match", payload)
        cookie = self.login()
        status, _headers, payload = self.request("GET", "/", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn(b"Dashboard", payload)
        status, headers, _payload = self.request("GET", "/inventory")
        self.assertEqual(status, 303)
        self.assertEqual(headers["location"], "/login")

    def test_two_clients(self) -> None:
        cookie = self.login()
        results: list[int] = []

        def fetch() -> None:
            status, _headers, payload = self.request("GET", "/inventory", cookie=cookie)
            results.append(status)
            self.assertIn(b"Inventory", payload)

        threads = [threading.Thread(target=fetch) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(results, [200, 200])

    def test_csrf_and_last_agent(self) -> None:
        cookie = self.login()
        status, _headers, payload = self.request(
            "POST",
            "/act/shop-save",
            urlencode({"org_name": "Shop"}).encode(),
            cookie=cookie,
        )
        self.assertEqual(status, 403)
        self.assertIn(b"session token", payload)
        token = self.csrf(cookie)
        status, headers, _payload = self.request(
            "POST",
            "/act/agent-delete",
            urlencode({"csrf": token, "agent_id": "1"}).encode(),
            cookie=cookie,
        )
        self.assertEqual(status, 303)
        self.assertIn("error=", headers["location"])
        self.assertEqual(self.httpd.store.fetchone("SELECT COUNT(*) FROM agents")[0], 1)

    def test_pages_render(self) -> None:
        cookie = self.login()
        for path in (
            "/",
            "/inventory",
            "/collections",
            "/deploy",
            "/tickets",
            "/network",
            "/software",
            "/people",
            "/reports",
            "/settings",
            "/agents",
            "/about",
            "/health",
            "/static/app.css",
        ):
            status, _headers, payload = self.request("GET", path, cookie=cookie)
            self.assertEqual(status, 200, path)
            self.assertTrue(payload, path)
        device = self.httpd.store.fetchone("SELECT id FROM devices LIMIT 1")
        if device:
            status, _headers, payload = self.request("GET", f"/inventory/{int(device['id'])}", cookie=cookie)
            self.assertEqual(status, 200)
            self.assertIn(b"Scan", payload)

    def test_about_page(self) -> None:
        from helix_it import __version__
        from helix_it.about import commits_behind_master

        cookie = self.login()
        status, _headers, payload = self.request("GET", "/about", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn(__version__.encode(), payload)
        self.assertIn(b"Commits behind master", payload)
        count, ref = commits_behind_master()
        self.assertIsNotNone(count)
        self.assertIn(str(count).encode(), payload)
        self.assertIn(ref.encode(), payload)

    def test_add_agent(self) -> None:
        cookie = self.login()
        token = self.csrf(cookie)
        status, headers, _payload = self.request(
            "POST",
            "/act/agent-save",
            urlencode({"csrf": token, "username": "riley", "display_name": "Riley", "password": "second-agent"}).encode(),
            cookie=cookie,
        )
        self.assertEqual(status, 303)
        self.assertIn("notice=", headers["location"])
        status, _headers, payload = self.request("GET", "/agents", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn(b"Riley", payload)
        self.assertEqual(self.httpd.store.fetchone("SELECT COUNT(*) FROM agents")[0], 2)

    def test_second_job_is_refused(self) -> None:
        first = self.httpd.hub.start(lambda: time.sleep(0.4))
        self.assertIsNone(first)
        second = self.httpd.hub.start(lambda: None)
        self.assertIn("still running", second or "")
        time.sleep(0.5)


if __name__ == "__main__":
    unittest.main()
