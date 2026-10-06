import asyncio
import hmac
import threading
import time
from collections import deque

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocketClose

from config import (
    HYPERFLO_PASSWORD_HASH,
    HYPERFLO_TOTP_SECRET,
    HYPERFLO_USER,
    LOGIN_MAX_FAILURES_GLOBAL,
    LOGIN_MAX_FAILURES_PER_IP,
    LOGIN_WINDOW,
    SESSION_MAX_AGE,
)
from pages import render_page
from security import (
    AUDIT_EVENTS,
    BodySizeLimitMiddleware,
    SecurityHeadersMiddleware,
    audit,
    get_client_ip,
    origin_allowed,
)
from sessions import CSRF_COOKIE, SESSION_COOKIE, Session, sessions

router = APIRouter()
password_hasher = PasswordHasher()

# argon2 est volontairement couteux: on limite les verifications simultanees
# pour qu'une rafale de tentatives ne sature pas le CPU.
ARGON2_SLOTS = asyncio.Semaphore(2)

PUBLIC_PATHS = {
    "/login",
    "/api/auth/login",
    "/static/login.css",
    "/static/login.js",
}

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_HEADER = "X-Hyperflo-CSRF"
# Envoye par les rafraichissements automatiques: ne prolonge pas la session.
POLL_HEADER = "X-Hyperflo-Poll"


# ---------------------------------------------------------------------------
# Anti brute-force
# ---------------------------------------------------------------------------

class LoginGuard:
    """Limite les echecs par IP et au total.

    La limite globale protege contre une attaque distribuee sur le code TOTP:
    au-dela, plus aucune connexion n'est acceptee jusqu'a la fin de la fenetre.
    Une session deja ouverte peut lever le blocage depuis la page admin.
    """

    MAX_TRACKED_IPS = 10_000

    def __init__(self) -> None:
        self._per_ip: dict[str, deque[float]] = {}
        self._global: deque[float] = deque()
        self._lock = threading.Lock()

    @staticmethod
    def _prune(attempts: deque[float], now: float) -> None:
        while attempts and now - attempts[0] >= LOGIN_WINDOW:
            attempts.popleft()

    def blocked(self, ip: str) -> str | None:
        now = time.time()
        with self._lock:
            self._prune(self._global, now)
            if len(self._global) >= LOGIN_MAX_FAILURES_GLOBAL:
                return "global"

            attempts = self._per_ip.get(ip)
            if attempts is not None:
                self._prune(attempts, now)
                if len(attempts) >= LOGIN_MAX_FAILURES_PER_IP:
                    return "ip"
        return None

    def failure(self, ip: str) -> None:
        now = time.time()
        with self._lock:
            if ip not in self._per_ip and len(self._per_ip) >= self.MAX_TRACKED_IPS:
                for key in list(self._per_ip):
                    self._prune(self._per_ip[key], now)
                    if not self._per_ip[key]:
                        del self._per_ip[key]
                if len(self._per_ip) >= self.MAX_TRACKED_IPS:
                    self._per_ip.pop(next(iter(self._per_ip)))

            self._per_ip.setdefault(ip, deque()).append(now)
            self._global.append(now)

    def success(self, ip: str) -> None:
        with self._lock:
            self._per_ip.pop(ip, None)

    def reset(self) -> None:
        with self._lock:
            self._per_ip.clear()
            self._global.clear()

    def overview(self) -> dict:
        now = time.time()
        with self._lock:
            self._prune(self._global, now)
            blocked_ips = []
            for ip, attempts in self._per_ip.items():
                self._prune(attempts, now)
                if len(attempts) >= LOGIN_MAX_FAILURES_PER_IP:
                    blocked_ips.append(
                        {"ip": ip, "until": int(attempts[0] + LOGIN_WINDOW)}
                    )
            return {
                "window": LOGIN_WINDOW,
                "global_failures": len(self._global),
                "global_limit": LOGIN_MAX_FAILURES_GLOBAL,
                "global_locked": len(self._global) >= LOGIN_MAX_FAILURES_GLOBAL,
                "per_ip_limit": LOGIN_MAX_FAILURES_PER_IP,
                "blocked_ips": blocked_ips,
            }


login_guard = LoginGuard()


# ---------------------------------------------------------------------------
# Verification des facteurs
# ---------------------------------------------------------------------------

_totp = pyotp.TOTP(HYPERFLO_TOTP_SECRET)
_totp_lock = threading.Lock()
_last_totp_counter = 0


def _verify_password(password: str) -> bool:
    try:
        return password_hasher.verify(HYPERFLO_PASSWORD_HASH, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _match_totp(code: str) -> int | None:
    """Retourne le pas de temps du code s'il est valide (tolerance +/- 1 pas)."""
    if len(code) != _totp.digits or not code.isdigit():
        return None

    current = int(time.time()) // _totp.interval
    for counter in (current - 1, current, current + 1):
        if hmac.compare_digest(_totp.generate_otp(counter), code):
            return counter
    return None


def _consume_totp(counter: int) -> bool:
    """Empeche la reutilisation d'un code (ou d'un code plus ancien)."""
    global _last_totp_counter
    with _totp_lock:
        if counter <= _last_totp_counter:
            return False
        _last_totp_counter = counter
        return True


# ---------------------------------------------------------------------------
# Cookies
# ---------------------------------------------------------------------------

def _set_session_cookies(response, token: str, session: Session) -> None:
    common = {
        "max_age": SESSION_MAX_AGE,
        "path": "/",
        "secure": True,
        "samesite": "strict",
    }
    response.set_cookie(SESSION_COOKIE, token, httponly=True, **common)
    # Lisible par le JS pour etre renvoye dans l'en-tete X-Hyperflo-CSRF.
    response.set_cookie(CSRF_COOKIE, session.csrf_token, httponly=False, **common)


def _clear_session_cookies(response) -> None:
    for name, httponly in ((SESSION_COOKIE, True), (CSRF_COOKIE, False)):
        response.delete_cookie(
            name,
            path="/",
            secure=True,
            httponly=httponly,
            samesite="strict",
        )
    # Ancien cookie signe (SessionMiddleware), plus utilise.
    response.delete_cookie("hyperflo_session", path="/")


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

def current_session(request: Request) -> Session:
    session = getattr(request.state, "session", None)
    if session is None:
        raise HTTPException(status_code=401, detail="Authentification requise")
    return session


class HyperfloAuthMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            await self._websocket(scope, receive, send)
            return

        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        path = request.url.path
        method = request.method.upper()
        unsafe = method not in SAFE_METHODS
        is_api = path.startswith("/api/")

        # Les navigateurs indiquent l'origine de la requete. On refuse tout appel
        # d'API ou toute modification venant d'un autre site (y compris un autre
        # sous-domaine du meme domaine).
        fetch_site = request.headers.get("Sec-Fetch-Site", "")
        if fetch_site in {"cross-site", "same-site"} and (is_api or unsafe):
            audit("cross_site_blocked", request, path=path, method=method)
            response = JSONResponse({"detail": "Requete refusee"}, status_code=403)
            await response(scope, receive, send)
            return

        if path in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        token = request.cookies.get(SESSION_COOKIE)
        touch = request.headers.get(POLL_HEADER) != "1"
        session = sessions.get(token, touch=touch)

        if session is None:
            if is_api:
                response = JSONResponse(
                    {"detail": "Authentification requise"},
                    status_code=401,
                )
            else:
                response = RedirectResponse(url="/login", status_code=303)
            if token:
                _clear_session_cookies(response)
            await response(scope, receive, send)
            return

        if unsafe:
            sent = request.headers.get(CSRF_HEADER, "")
            if not sent or not hmac.compare_digest(sent, session.csrf_token):
                audit("csrf_rejected", request, path=path, method=method)
                response = JSONResponse({"detail": "Jeton CSRF invalide"}, status_code=403)
                await response(scope, receive, send)
                return

        scope.setdefault("state", {})["session"] = session
        await self.app(scope, receive, send)


    async def _websocket(self, scope: Scope, receive: Receive, send: Send) -> None:
        """WebSocket: session valide et Origin de Hyperflo obligatoires.

        Le jeton CSRF est verifie ensuite par la route (premier message), pour
        ne jamais apparaitre dans une URL ni dans les journaux.
        """
        # HTTPConnection: Request(scope) n'accepte que le type "http".
        request = HTTPConnection(scope)
        origin = request.headers.get("Origin")
        host = request.headers.get("Host")

        if not origin_allowed(origin, host):
            audit("websocket_origin_rejected", request, path=scope["path"], origin=origin or "", host=host or "")
            await WebSocketClose(code=1008)(scope, receive, send)
            return

        session = sessions.get(request.cookies.get(SESSION_COOKIE), touch=False)
        if session is None:
            await WebSocketClose(code=1008)(scope, receive, send)
            return

        scope.setdefault("state", {})["session"] = session
        await self.app(scope, receive, send)


def setup_auth(app: FastAPI) -> None:
    # Starlette construit les middlewares en ordre inverse de leur ajout:
    # en-tetes de securite (exterieur) -> limite de taille -> authentification.
    app.add_middleware(HyperfloAuthMiddleware)
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

class LoginBody(BaseModel):
    username: str = Field(default="", max_length=128)
    password: str = Field(default="", max_length=1024)
    totp: str = Field(default="", max_length=16)


@router.get("/login")
def login_page(request: Request):
    if sessions.get(request.cookies.get(SESSION_COOKIE), touch=False):
        return RedirectResponse(url="/", status_code=303)
    return render_page("login")


@router.post("/api/auth/login")
async def login(body: LoginBody, request: Request):
    ip = get_client_ip(request)
    username = body.username.strip()
    totp_code = body.totp.replace(" ", "").strip()

    blocked = login_guard.blocked(ip)
    if blocked:
        audit("login_blocked", request, username=username, scope=blocked)
        return JSONResponse(
            {"detail": "Trop de tentatives. Reessaie dans quelques minutes."},
            status_code=429,
        )

    valid_user = hmac.compare_digest(username.encode(), HYPERFLO_USER.encode())

    # Le mot de passe est toujours verifie, meme si l'utilisateur est faux,
    # pour ne pas reveler par le temps de reponse si le nom est correct.
    async with ARGON2_SLOTS:
        valid_password = await run_in_threadpool(_verify_password, body.password)

    counter = _match_totp(totp_code)
    valid_totp = counter is not None

    ok = valid_user and valid_password and valid_totp
    replay = False
    if ok and not _consume_totp(counter):
        ok = False
        replay = True

    if not ok:
        login_guard.failure(ip)
        # Le detail reste dans le journal serveur. Un mot de passe correct
        # avec un TOTP faux indique que le mot de passe a peut-etre fuite.
        audit(
            "login_failure",
            request,
            username=username,
            user_ok=valid_user,
            password_ok=valid_password,
            totp_ok=valid_totp,
            totp_replay=replay,
        )
        return JSONResponse(
            {"detail": "Identifiants ou code incorrects"},
            status_code=401,
        )

    login_guard.success(ip)
    user_agent = request.headers.get("User-Agent", "")
    token, session = sessions.create(HYPERFLO_USER, ip, user_agent)
    audit("login_success", request, username=HYPERFLO_USER, session=session.public_id)

    response = JSONResponse({"ok": True})
    _set_session_cookies(response, token, session)
    return response


@router.post("/api/auth/logout")
async def logout(request: Request):
    session = sessions.revoke_token(request.cookies.get(SESSION_COOKIE))
    if session:
        audit("logout", request, session=session.public_id)
    response = JSONResponse({"ok": True})
    _clear_session_cookies(response)
    return response


@router.get("/api/auth/me")
async def auth_me(request: Request):
    session = current_session(request)
    return {
        "authenticated": True,
        "username": session.username,
        "session": session.to_public(current=True),
    }


@router.get("/api/auth/sessions")
async def list_sessions(request: Request):
    me = current_session(request)
    return {
        "sessions": [
            session.to_public(current=session is me)
            for session in sessions.list()
        ]
    }


@router.post("/api/auth/sessions/revoke-others")
async def revoke_other_sessions(request: Request):
    me = current_session(request)
    count = sessions.revoke_all_except(me)
    audit("sessions_revoked", request, count=count, kept=me.public_id)
    return {"ok": True, "revoked": count}


@router.post("/api/auth/sessions/{public_id}/revoke")
async def revoke_session(public_id: str, request: Request):
    me = current_session(request)
    session = sessions.revoke_public_id(public_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session introuvable")

    audit("session_revoked", request, session=session.public_id)
    response = JSONResponse({"ok": True, "current": session is me})
    if session is me:
        _clear_session_cookies(response)
    return response


@router.get("/api/security/overview")
async def security_overview(request: Request, limit: int = 100):
    current_session(request)
    limit = max(1, min(limit, len(AUDIT_EVENTS) or 1))
    events = list(AUDIT_EVENTS)[-limit:]
    events.reverse()
    return {
        "login_guard": login_guard.overview(),
        "events": events,
    }


@router.post("/api/security/unblock")
async def security_unblock(request: Request):
    current_session(request)
    login_guard.reset()
    audit("login_guard_reset", request)
    return {"ok": True}
