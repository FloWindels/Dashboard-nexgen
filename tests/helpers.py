"""Outils communs aux tests.

Les tests parlent a une instance de test lancee par check.sh (port temporaire,
identifiants factices), jamais au service en production.
"""

import json
import os
import time
import urllib.error
import urllib.request

import pyotp

BASE_URL = os.environ.get("HYPERFLO_TEST_URL", "http://127.0.0.1:8099")
USERNAME = os.environ["HYPERFLO_USER"]
PASSWORD = os.environ["HYPERFLO_TEST_PASSWORD"]
TOTP = pyotp.TOTP(os.environ["HYPERFLO_TOTP_SECRET"])

SESSION_COOKIE = "__Host-hyperflo_session"
CSRF_COOKIE = "__Host-hyperflo_csrf"


class Response:
    def __init__(self, status, headers, cookies, body):
        self.status = status
        self.headers = headers
        self.cookies = cookies
        self.body = body

    def json(self):
        return json.loads(self.body)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def request(path, method="GET", body=None, raw=None, headers=None, cookies=None, timeout=20):
    all_headers = dict(headers or {})
    data = None

    if body is not None:
        data = json.dumps(body).encode()
        all_headers["Content-Type"] = "application/json"
    if raw is not None:
        data = raw
        all_headers["Content-Type"] = "application/json"
    if cookies:
        all_headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())

    req = urllib.request.Request(BASE_URL + path, data=data, headers=all_headers, method=method)
    try:
        resp = _opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as error:
        resp = error

    headers = {key.lower(): value for key, value in resp.headers.items()}
    cookies = resp.headers.get_all("Set-Cookie") or []
    return Response(resp.status, headers, cookies, resp.read())


def parse_cookies(set_cookie_headers):
    cookies = {}
    for header in set_cookie_headers:
        name, value = header.split(";", 1)[0].split("=", 1)
        cookies[name] = value
    return cookies


class Session:
    """Session authentifiee: cookie + jeton CSRF."""

    def __init__(self, cookies):
        self.token = cookies[SESSION_COOKIE]
        self.csrf = cookies[CSRF_COOKIE]

    @property
    def cookies(self):
        return {SESSION_COOKIE: self.token}

    def get(self, path, **kwargs):
        return request(path, cookies=self.cookies, **kwargs)

    def post(self, path, body=None, headers=None, **kwargs):
        all_headers = {"X-Hyperflo-CSRF": self.csrf}
        all_headers.update(headers or {})
        return request(path, "POST", body=body, headers=all_headers, cookies=self.cookies, **kwargs)


def login(code=None, ip=None):
    headers = {"Sec-Fetch-Site": "same-origin", "User-Agent": "hyperflo-tests"}
    if ip:
        headers["CF-Connecting-IP"] = ip
    return request(
        "/api/auth/login",
        "POST",
        body={"username": USERNAME, "password": PASSWORD, "totp": code or TOTP.now()},
        headers=headers,
    )


# Un code TOTP ne sert qu'une fois: les tests partagent une session et en
# ouvrent au plus une seconde avec le code du pas de temps suivant.
_shared = None
shared_code = None


def shared_session():
    global _shared, shared_code
    if _shared is None:
        shared_code = TOTP.now()
        response = login(shared_code)
        assert response.status == 200, response.body
        _shared = Session(parse_cookies(response.cookies))
    return _shared


def next_totp_code():
    return TOTP.at(time.time() + TOTP.interval)
