"""Terminal Web: navigateur <-> WebSocket <-> FastAPI <-> SSH vers la machine.

Le shell est une vraie session SSH sur 127.0.0.1 avec un compte Linux et son
mot de passe: il a exactement les droits de ce compte (sudo demande le mot de
passe comme d'habitude). Le compte root est refuse.

Protocole WebSocket:
- trames binaires: donnees du terminal (clavier -> shell, shell -> ecran);
- trames texte JSON: controle.
    client -> serveur: {"type": "login", "csrf", "username", "password", "cols", "rows"}
                       {"type": "resize", "cols", "rows"}
    serveur -> client: {"type": "status", "state": "connected"|"closed", ...}
                       {"type": "error", "message"}

Le mot de passe Linux n'est ni stocke, ni journalise, ni renvoye: il ne sert
qu'a l'authentification SSH puis la reference est supprimee.
"""

import asyncio
import glob
import hmac
import json
import logging
import pwd
import re
import secrets
import time
from collections import deque

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from config import (
    LOGIN_WINDOW,
    TERMINAL_HOST_KEYS,
    TERMINAL_IDLE_TIMEOUT,
    TERMINAL_MAX_LOGIN_FAILURES,
    TERMINAL_MAX_PER_SESSION,
    TERMINAL_MAX_TOTAL,
    TERMINAL_SSH_HOST,
    TERMINAL_SSH_PORT,
)
from security import audit, get_client_ip
from sessions import Session, sessions

try:
    import asyncssh
except ImportError:  # dependance optionnelle: le reste du dashboard fonctionne
    asyncssh = None

router = APIRouter(prefix="/api/terminal")
logger = logging.getLogger("hyperflo")

LINUX_USERNAME = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
LOGIN_TIMEOUT = 20
MAX_INPUT_FRAME = 64 * 1024
# Verification periodique: session Hyperflo revoquee/expiree, inactivite.
WATCH_INTERVAL = 15
# Une frappe prolonge la session Hyperflo au plus une fois par minute.
SESSION_TOUCH_INTERVAL = 60


class TerminalError(Exception):
    """Erreur affichable telle quelle a l'utilisateur."""


# ---------------------------------------------------------------------------
# Registre des terminaux ouverts
# ---------------------------------------------------------------------------

class Terminal:
    def __init__(self, websocket: WebSocket, owner: Session, ip: str) -> None:
        self.id = secrets.token_hex(6)
        self.websocket = websocket
        self.owner = owner
        self.ip = ip
        self.linux_user = ""
        self.opened = time.time()
        self.last_input = time.monotonic()
        self.last_touch = 0.0
        self.close_reason: str | None = None
        self._closed = asyncio.Event()
        self._loop = asyncio.get_running_loop()

    def request_close(self, reason: str) -> None:
        """Peut etre appele depuis n'importe quel thread."""
        def close():
            if self.close_reason is None:
                self.close_reason = reason
            self._closed.set()
        self._loop.call_soon_threadsafe(close)

    async def wait_closed(self) -> None:
        await self._closed.wait()


class TerminalRegistry:
    def __init__(self) -> None:
        self._terminals: dict[str, Terminal] = {}
        self._failures: dict[str, deque[float]] = {}

    def add(self, terminal: Terminal) -> str | None:
        """Enregistre le terminal; renvoie un message si une limite est atteinte."""
        if len(self._terminals) >= TERMINAL_MAX_TOTAL:
            return "Trop de terminaux ouverts sur le serveur."
        mine = [t for t in self._terminals.values() if t.owner is terminal.owner]
        if len(mine) >= TERMINAL_MAX_PER_SESSION:
            return f"Maximum {TERMINAL_MAX_PER_SESSION} terminaux par session."
        self._terminals[terminal.id] = terminal
        return None

    def remove(self, terminal: Terminal) -> None:
        self._terminals.pop(terminal.id, None)

    def close_for_session(self, session: Session, reason: str) -> None:
        for terminal in list(self._terminals.values()):
            if terminal.owner is session:
                terminal.request_close(reason)

    # Echecs de connexion SSH par session Hyperflo.
    def _recent_failures(self, session: Session) -> deque[float]:
        attempts = self._failures.setdefault(session.public_id, deque())
        now = time.time()
        while attempts and now - attempts[0] >= LOGIN_WINDOW:
            attempts.popleft()
        return attempts

    def login_blocked(self, session: Session) -> bool:
        return len(self._recent_failures(session)) >= TERMINAL_MAX_LOGIN_FAILURES

    def login_failed(self, session: Session) -> None:
        self._recent_failures(session).append(time.time())

    def count(self) -> int:
        return len(self._terminals)


terminals = TerminalRegistry()
# Logout ou revocation d'une session Hyperflo: ses terminaux sont fermes.
sessions.on_revoke(lambda session: terminals.close_for_session(session, "session Hyperflo fermee"))


# ---------------------------------------------------------------------------
# SSH
# ---------------------------------------------------------------------------

def load_host_keys() -> list:
    """Cles publiques de sshd: la connexion echoue si le serveur ne les presente pas."""
    keys = []
    for path in sorted(glob.glob(TERMINAL_HOST_KEYS)):
        try:
            keys.append(asyncssh.read_public_key(path))
        except (OSError, ValueError, asyncssh.KeyImportError) as exc:
            logger.warning("Cle d'hote illisible %s: %s", path, exc)
    return keys


def check_linux_username(username: str) -> None:
    if not LINUX_USERNAME.fullmatch(username):
        raise TerminalError("Nom d'utilisateur Linux invalide.")
    if username == "root":
        raise TerminalError("La connexion root n'est pas autorisée depuis le terminal Web.")
    try:
        if pwd.getpwnam(username).pw_uid == 0:
            raise TerminalError("La connexion root n'est pas autorisée depuis le terminal Web.")
    except KeyError:
        # Compte inconnu: SSH refusera, avec le meme message qu'un mauvais mot de passe.
        pass


async def open_ssh(username: str, password: str, cols: int, rows: int):
    host_keys = load_host_keys()
    if not host_keys:
        raise TerminalError("Clés d'hôte SSH introuvables: connexion refusée.")

    try:
        connection = await asyncio.wait_for(
            asyncssh.connect(
                TERMINAL_SSH_HOST,
                port=TERMINAL_SSH_PORT,
                username=username,
                password=password,
                # Identite du serveur verifiee; aucune cle, agent ni fichier
                # de configuration du compte hyperflo.
                known_hosts=(host_keys, [], []),
                client_keys=None,
                agent_path=None,
                # Liste vide: aucun fichier lu. La valeur par defaut d'asyncssh,
                # (), chargerait ~/.ssh/config et ~/.ssh/ca-bundle.crt.
                config=[],
                x509_trusted_certs=None,
                preferred_auth="password",
                keepalive_interval=30,
            ),
            timeout=LOGIN_TIMEOUT,
        )
    except asyncssh.PermissionDenied as exc:
        raise TerminalError("Identifiants Linux incorrects.") from exc
    except asyncssh.HostKeyNotVerifiable as exc:
        logger.error("Terminal: cle d'hote SSH non reconnue: %s", exc)
        raise TerminalError("Clé d'hôte SSH inattendue: connexion refusée.") from exc
    except (asyncio.TimeoutError, OSError, asyncssh.Error) as exc:
        logger.warning("Terminal: connexion SSH impossible: %s", exc)
        raise TerminalError("Connexion SSH impossible.") from exc

    try:
        process = await connection.create_process(
            term_type="xterm-256color",
            term_size=(cols, rows),
            encoding=None,
        )
    except asyncssh.Error as exc:
        connection.close()
        raise TerminalError("Impossible d'ouvrir le shell.") from exc

    return connection, process


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

def _size(value, default: int, maximum: int) -> int:
    try:
        return max(2, min(int(value), maximum))
    except (TypeError, ValueError):
        return default


async def _send_json(websocket: WebSocket, data: dict) -> None:
    if websocket.application_state == WebSocketState.CONNECTED:
        try:
            await websocket.send_text(json.dumps(data))
        except (RuntimeError, OSError, WebSocketDisconnect):
            pass


async def _receive_login(websocket: WebSocket, session: Session) -> dict:
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=60)
        message = json.loads(raw)
    except WebSocketDisconnect:
        raise
    except (asyncio.TimeoutError, ValueError, KeyError) as exc:
        raise TerminalError("Demande de connexion invalide.") from exc

    if not isinstance(message, dict) or message.get("type") != "login":
        raise TerminalError("Demande de connexion invalide.")

    csrf = str(message.get("csrf", ""))
    if not csrf or not hmac.compare_digest(csrf, session.csrf_token):
        raise TerminalError("Jeton CSRF invalide.")

    return message


@router.websocket("/ws")
async def terminal_websocket(websocket: WebSocket):
    # Le middleware a deja verifie la session Hyperflo et l'Origin.
    session: Session = websocket.state.session
    ip = get_client_ip(websocket)

    await websocket.accept()

    if asyncssh is None:
        await _send_json(websocket, {"type": "error", "message": "Terminal indisponible: asyncssh n'est pas installé."})
        await websocket.close(code=1011)
        return

    terminal = Terminal(websocket, session, ip)
    limit_message = terminals.add(terminal)
    if limit_message:
        await _send_json(websocket, {"type": "error", "message": limit_message})
        await websocket.close(code=1008)
        return

    connection = None
    process = None
    username = ""
    try:
        try:
            message = await _receive_login(websocket, session)
            username = str(message.get("username", "")).strip()
            check_linux_username(username)

            if terminals.login_blocked(session):
                raise TerminalError("Trop d'échecs de connexion SSH. Réessaie plus tard.")

            cols = _size(message.get("cols"), 80, 500)
            rows = _size(message.get("rows"), 24, 200)
            password = str(message.get("password", ""))
            # Le mot de passe ne doit rester nulle part: ni dans le message,
            # ni dans une variable apres l'authentification.
            message.pop("password", None)
            try:
                connection, process = await open_ssh(username, password, cols, rows)
            finally:
                del password
        except TerminalError as exc:
            if username and "Identifiants" in str(exc):
                terminals.login_failed(session)
                audit("terminal_login_failure", websocket, linux_user=username)
            await _send_json(websocket, {"type": "error", "message": str(exc)})
            return

        terminal.linux_user = username
        audit("terminal_open", websocket, linux_user=username, terminal=terminal.id)
        await _send_json(
            websocket,
            {"type": "status", "state": "connected", "user": username, "terminal": terminal.id},
        )

        await _run_terminal(terminal, process)
    except WebSocketDisconnect:
        terminal.close_reason = terminal.close_reason or "onglet fermé"
    finally:
        terminals.remove(terminal)
        if process is not None:
            process.close()
        if connection is not None:
            connection.close()
        if terminal.linux_user:
            reason = terminal.close_reason or "fermé"
            audit(
                "terminal_close",
                websocket,
                linux_user=terminal.linux_user,
                terminal=terminal.id,
                reason=reason,
                duration=int(time.time() - terminal.opened),
            )
            await _send_json(websocket, {"type": "status", "state": "closed", "reason": reason})
        if websocket.application_state == WebSocketState.CONNECTED:
            try:
                await websocket.close()
            except (RuntimeError, OSError):
                pass


async def _run_terminal(terminal: Terminal, process) -> None:
    """Relaie les donnees jusqu'a la fermeture d'un cote ou de l'autre."""
    websocket = terminal.websocket

    async def ssh_to_browser():
        while True:
            data = await process.stdout.read(65536)
            if not data:
                terminal.request_close("shell terminé")
                return
            await websocket.send_bytes(data)

    async def browser_to_ssh():
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                terminal.request_close("onglet fermé")
                return

            if message.get("bytes") is not None:
                data = message["bytes"]
                if len(data) > MAX_INPUT_FRAME:
                    continue
                process.stdin.write(data)
                terminal.last_input = time.monotonic()
                # Taper dans le terminal est une activite Hyperflo.
                if time.monotonic() - terminal.last_touch > SESSION_TOUCH_INTERVAL:
                    sessions.is_active(terminal.owner, touch=True)
                    terminal.last_touch = time.monotonic()
                continue

            try:
                control = json.loads(message.get("text") or "")
            except ValueError:
                continue
            if isinstance(control, dict) and control.get("type") == "resize":
                process.change_terminal_size(
                    _size(control.get("cols"), 80, 500),
                    _size(control.get("rows"), 24, 200),
                )

    async def watchdog():
        while True:
            await asyncio.sleep(WATCH_INTERVAL)
            if not sessions.is_active(terminal.owner):
                terminal.request_close("session Hyperflo expirée")
                return
            if time.monotonic() - terminal.last_input > TERMINAL_IDLE_TIMEOUT:
                terminal.request_close("inactivité")
                return

    tasks = [
        asyncio.create_task(ssh_to_browser()),
        asyncio.create_task(browser_to_ssh()),
        asyncio.create_task(watchdog()),
        asyncio.create_task(terminal.wait_closed()),
    ]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            error = None if task.cancelled() else task.exception()
            if isinstance(error, WebSocketDisconnect):
                terminal.close_reason = terminal.close_reason or "onglet fermé"
            elif error is not None:
                logger.warning("Terminal %s: %s", terminal.id, error)
                terminal.close_reason = terminal.close_reason or "erreur"
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
