import secrets
import time

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from config import (
    BASE_DIR,
    HYPERFLO_PASSWORD_HASH,
    HYPERFLO_SESSION_SECRET,
    HYPERFLO_TOTP_SECRET,
    HYPERFLO_USER,
)

router = APIRouter()
password_hasher = PasswordHasher()

LOGIN_FAILURES: dict[str, list[float]] = {}
LOGIN_WINDOW = 10 * 60
LOGIN_MAX_FAILURES = 5

PUBLIC_PATHS = {
    "/login",
    "/api/auth/login",
    "/static/login.css",
    "/static/login.js",
}


def get_client_ip(request: Request) -> str:
    # Le service Uvicorn est lie a 127.0.0.1 et publie via Cloudflare Tunnel.
    # CF-Connecting-IP permet donc de limiter par IP du client final.
    cloudflare_ip = request.headers.get("CF-Connecting-IP")
    if cloudflare_ip:
        return cloudflare_ip

    if request.client:
        return request.client.host

    return "unknown"


def login_rate_key(request: Request, username: str) -> str:
    return f"{get_client_ip(request)}:{username.lower()}"


def _recent_attempts(key: str) -> list[float]:
    now = time.time()
    attempts = [
        timestamp
        for timestamp in LOGIN_FAILURES.get(key, [])
        if now - timestamp < LOGIN_WINDOW
    ]
    LOGIN_FAILURES[key] = attempts
    return attempts


def login_is_blocked(key: str) -> bool:
    return len(_recent_attempts(key)) >= LOGIN_MAX_FAILURES


def register_login_failure(key: str) -> None:
    attempts = _recent_attempts(key)
    attempts.append(time.time())
    LOGIN_FAILURES[key] = attempts


def clear_login_failures(key: str) -> None:
    LOGIN_FAILURES.pop(key, None)


class HyperfloAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if path in PUBLIC_PATHS:
            return await call_next(request)

        if request.session.get("authenticated") is True:
            return await call_next(request)

        if path.startswith("/api/"):
            return JSONResponse(
                {"detail": "Authentification requise"},
                status_code=401,
            )

        return RedirectResponse(url="/login", status_code=303)


def setup_auth(app: FastAPI) -> None:
    # Starlette construit les middlewares en ordre inverse de leur ajout.
    # SessionMiddleware est donc ajoute en dernier afin d'envelopper le middleware
    # d'authentification et de rendre request.session disponible dans celui-ci.
    app.add_middleware(HyperfloAuthMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=HYPERFLO_SESSION_SECRET,
        session_cookie="hyperflo_session",
        max_age=12 * 60 * 60,
        same_site="strict",
        https_only=True,
    )


@router.get("/login")
def login_page():
    return FileResponse(BASE_DIR / "pages" / "login.html")


@router.post("/api/auth/login")
async def login(request: Request):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"detail": "Requete invalide"}, status_code=400)

    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    totp_code = str(data.get("totp", "")).replace(" ", "").strip()

    key = login_rate_key(request, username)

    if login_is_blocked(key):
        return JSONResponse(
            {"detail": "Trop de tentatives. Reessaie dans quelques minutes."},
            status_code=429,
        )

    valid_user = secrets.compare_digest(username, HYPERFLO_USER)

    valid_password = False
    try:
        valid_password = password_hasher.verify(HYPERFLO_PASSWORD_HASH, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        valid_password = False

    valid_totp = pyotp.TOTP(HYPERFLO_TOTP_SECRET).verify(
        totp_code,
        valid_window=1,
    )

    if not (valid_user and valid_password and valid_totp):
        register_login_failure(key)
        return JSONResponse(
            {"detail": "Identifiants ou code incorrects"},
            status_code=401,
        )

    clear_login_failures(key)
    request.session.clear()
    request.session["authenticated"] = True
    request.session["username"] = HYPERFLO_USER
    request.session["login_time"] = int(time.time())

    return {"ok": True}


@router.post("/api/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/api/auth/me")
async def auth_me(request: Request):
    return {
        "authenticated": True,
        "username": request.session.get("username"),
    }
