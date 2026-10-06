import ipaddress
import logging
import sys
import time
import urllib.parse
from collections import deque

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from config import ALLOWED_ORIGINS, MAX_BODY_BYTES, MAX_CHAT_BODY_BYTES, TRUST_CF_CONNECTING_IP

# ---------------------------------------------------------------------------
# Journal d'audit
# ---------------------------------------------------------------------------
# Ecrit sur stderr (donc dans journald via systemd) et garde les derniers
# evenements en memoire pour la page d'administration.

audit_logger = logging.getLogger("hyperflo.audit")
audit_logger.setLevel(logging.INFO)
audit_logger.propagate = False
if not audit_logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("hyperflo-audit %(message)s"))
    audit_logger.addHandler(_handler)

AUDIT_EVENTS: deque[dict] = deque(maxlen=500)


def _clean(value) -> str:
    # Pas de retour a la ligne ni d'espaces dans le journal: une ligne = un evenement.
    text = str(value).replace("\n", " ").replace("\r", " ")
    return text[:200]


def audit(event: str, request: Request | None = None, **fields) -> None:
    record = {"time": int(time.time()), "event": event}
    if request is not None:
        record["ip"] = get_client_ip(request)
    record.update({key: _clean(value) for key, value in fields.items()})
    AUDIT_EVENTS.append(record)

    parts = [f"event={event}"]
    for key, value in record.items():
        if key in {"time", "event"}:
            continue
        parts.append(f'{key}="{_clean(value)}"')
    audit_logger.info(" ".join(parts))


# ---------------------------------------------------------------------------
# IP du client
# ---------------------------------------------------------------------------

def get_client_ip(request: Request) -> str:
    peer = request.client.host if request.client else ""

    # Uvicorn ecoute sur 127.0.0.1 et cloudflared tourne en local: on ne fait
    # confiance a CF-Connecting-IP que si la connexion vient de la machine.
    if TRUST_CF_CONNECTING_IP and peer in {"127.0.0.1", "::1"}:
        header = request.headers.get("CF-Connecting-IP", "").strip()
        if header:
            try:
                return str(ipaddress.ip_address(header))
            except ValueError:
                pass

    return peer or "unknown"


# ---------------------------------------------------------------------------
# Origine des WebSockets
# ---------------------------------------------------------------------------

def origin_allowed(origin: str | None, host: str | None) -> bool:
    """Un WebSocket doit venir d'une page de Hyperflo lui-meme.

    Les navigateurs envoient toujours l'en-tete Origin pour un WebSocket;
    sans ce controle, n'importe quel site pourrait ouvrir le terminal avec le
    cookie de l'utilisateur (Cross-Site WebSocket Hijacking).
    """
    if not origin or origin == "null":
        return False

    origin = origin.rstrip("/")
    if origin in ALLOWED_ORIGINS:
        return True

    parsed = urllib.parse.urlsplit(origin)
    return parsed.scheme in {"https", "http"} and bool(host) and parsed.netloc == host


# ---------------------------------------------------------------------------
# En-tetes de securite
# ---------------------------------------------------------------------------

CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)

# xterm.js genere ses couleurs et dimensions dans des balises <style>: la
# page du terminal (et elle seule) autorise les styles en ligne. Les scripts
# restent limites aux fichiers du serveur.
TERMINAL_CONTENT_SECURITY_POLICY = CONTENT_SECURITY_POLICY.replace(
    "style-src 'self'", "style-src 'self' 'unsafe-inline'"
)
INLINE_STYLE_PATHS = {"/terminal"}

SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (
        b"permissions-policy",
        b"camera=(), microphone=(), geolocation=(), usb=(), payment=(), interest-cohort=()",
    ),
    (b"strict-transport-security", b"max-age=31536000"),
]


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        is_static = scope["path"].startswith("/static/")
        csp = (
            TERMINAL_CONTENT_SECURITY_POLICY
            if scope["path"] in INLINE_STYLE_PATHS
            else CONTENT_SECURITY_POLICY
        )

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != b"cache-control" or is_static
                ]
                headers.append((b"content-security-policy", csp.encode()))
                headers.extend(SECURITY_HEADERS)
                if is_static:
                    headers.append((b"cache-control", b"no-cache"))
                else:
                    # Donnees sensibles: jamais en cache (navigateur ou proxy).
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


# ---------------------------------------------------------------------------
# Taille maximale des requetes
# ---------------------------------------------------------------------------

class BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope["path"].startswith("/api/ollama/"):
            limit = MAX_CHAT_BODY_BYTES
        else:
            limit = MAX_BODY_BYTES

        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    too_large = int(value) > limit
                except ValueError:
                    too_large = True
                if too_large:
                    await _payload_too_large(scope, receive, send)
                    return

        received = 0
        response_started = False

        async def receive_wrapper() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise BodyTooLarge()
            return message

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive_wrapper, send_wrapper)
        except BodyTooLarge:
            if not response_started:
                await _payload_too_large(scope, receive, send)


async def _payload_too_large(scope: Scope, receive: Receive, send: Send) -> None:
    response = JSONResponse({"detail": "Requete trop volumineuse"}, status_code=413)
    await response(scope, receive, send)
