import unittest

from tests import helpers
from tests.helpers import Session, login, parse_cookies, request, shared_session


class AnonymousAccessTests(unittest.TestCase):
    def test_private_page_redirects_to_login(self):
        response = request("/")
        self.assertEqual(response.status, 303)
        self.assertEqual(response.headers.get("location"), "/login")

    def test_private_api_returns_401(self):
        self.assertEqual(request("/api/status").status, 401)

    def test_private_static_redirects(self):
        self.assertEqual(request("/static/dashboard.js").status, 303)

    def test_login_assets_are_public(self):
        self.assertEqual(request("/login").status, 200)
        self.assertEqual(request("/static/login.js").status, 200)
        self.assertEqual(request("/static/login.css").status, 200)

    def test_static_path_traversal(self):
        self.assertIn(request("/static/../config.py").status, (303, 404))


class LoginTests(unittest.TestCase):
    def test_shared_session_works(self):
        session = shared_session()
        self.assertTrue(session.token)
        response = session.get("/api/auth/me")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.json()["username"], helpers.USERNAME)

    def test_cookie_flags(self):
        # Verifie les attributs sur une reponse de connexion reelle.
        shared_session()
        response = login(helpers.next_totp_code())
        self.assertEqual(response.status, 200, response.body)
        for header in response.cookies:
            if header.startswith("__Host-"):
                lower = header.lower()
                self.assertIn("secure", lower)
                self.assertIn("samesite=strict", lower)
                self.assertIn("path=/", lower)
        session_header = next(h for h in response.cookies if h.startswith(helpers.SESSION_COOKIE))
        self.assertIn("httponly", session_header.lower())

        # Deconnexion: le cookie de cette seconde session ne vaut plus rien.
        second = Session(parse_cookies(response.cookies))
        self.assertEqual(second.post("/api/auth/logout").status, 200)
        self.assertEqual(second.get("/api/status").status, 401)

    def test_totp_replay_is_rejected(self):
        shared_session()
        response = login(helpers.shared_code)
        self.assertEqual(response.status, 401)

    def test_invalid_json(self):
        response = request("/api/auth/login", "POST", raw=b"{bad")
        self.assertEqual(response.status, 422)

    def test_body_too_large(self):
        response = request(
            "/api/auth/login",
            "POST",
            raw=b'{"username":"' + b"a" * 200_000 + b'"}',
        )
        self.assertEqual(response.status, 413)

    def test_cross_site_login_blocked(self):
        response = request(
            "/api/auth/login",
            "POST",
            body={"username": "x", "password": "x", "totp": "000000"},
            headers={"Sec-Fetch-Site": "cross-site"},
        )
        self.assertEqual(response.status, 403)


class BruteForceTests(unittest.TestCase):
    def _fail(self, ip):
        return request(
            "/api/auth/login",
            "POST",
            body={"username": helpers.USERNAME, "password": "wrong", "totp": "000000"},
            headers={"CF-Connecting-IP": ip},
        ).status

    def test_ip_is_blocked_after_five_failures(self):
        statuses = [self._fail("203.0.113.7") for _ in range(6)]
        self.assertEqual(statuses[:5], [401] * 5)
        self.assertEqual(statuses[5], 429)
        # Une autre IP n'est pas concernee.
        self.assertEqual(self._fail("203.0.113.8"), 401)

    def test_invalid_cf_header_is_ignored(self):
        self.assertIn(self._fail("not-an-ip"), (401, 429))


class CsrfTests(unittest.TestCase):
    def test_post_without_csrf_token(self):
        session = shared_session()
        response = request(
            "/api/docker/foo/restart",
            "POST",
            headers={"X-Hyperflo-Action": "1"},
            cookies=session.cookies,
        )
        self.assertEqual(response.status, 403)

    def test_post_with_wrong_csrf_token(self):
        session = shared_session()
        response = request(
            "/api/docker/foo/restart",
            "POST",
            headers={"X-Hyperflo-Action": "1", "X-Hyperflo-CSRF": "x" * 43},
            cookies=session.cookies,
        )
        self.assertEqual(response.status, 403)

    def test_same_site_api_call_blocked(self):
        session = shared_session()
        response = session.get("/api/status", headers={"Sec-Fetch-Site": "same-site"})
        self.assertEqual(response.status, 403)


class SessionAdminTests(unittest.TestCase):
    def test_session_list_hides_tokens(self):
        session = shared_session()
        response = session.get("/api/auth/sessions")
        self.assertEqual(response.status, 200)
        sessions = response.json()["sessions"]
        self.assertTrue(any(item["current"] for item in sessions))
        self.assertNotIn(session.token.encode(), response.body)

    def test_security_overview_records_events(self):
        session = shared_session()
        response = session.get("/api/security/overview")
        self.assertEqual(response.status, 200)
        events = {event["event"] for event in response.json()["events"]}
        self.assertIn("login_success", events)


if __name__ == "__main__":
    unittest.main()
