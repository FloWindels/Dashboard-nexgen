"""Tests du terminal Web contre un faux serveur SSH (tests/fake_sshd.py).

Le dernier test (test_z_...) deconnecte la session partagee: il doit rester
le dernier du module, et ce module le dernier de la suite.
"""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from tests import helpers
from tests.helpers import BASE_URL, SESSION_COOKIE, shared_session

try:
    from websockets.exceptions import ConnectionClosed, InvalidStatus
    from websockets.sync.client import connect
except ImportError:  # check.sh verifie que websockets est installe
    connect = None

WS_URL = BASE_URL.replace("http://", "ws://") + "/api/terminal/ws"


def open_ws(session=None, origin=BASE_URL):
    headers = {}
    if session is not None:
        headers["Cookie"] = f"{SESSION_COOKIE}={session.token}"
    return connect(WS_URL, origin=origin, additional_headers=headers, open_timeout=10)


def send_login(ws, session, username="alice", password="secret-pass", csrf=None, cols=100, rows=30):
    ws.send(json.dumps({
        "type": "login",
        "csrf": session.csrf if csrf is None else csrf,
        "username": username,
        "password": password,
        "cols": cols,
        "rows": rows,
    }))


def read_messages(ws, until, timeout=8.0):
    """Lit jusqu'a ce que until(messages, texte) soit vrai ou la connexion fermee."""
    messages, text = [], ""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            data = ws.recv(timeout=max(0.1, deadline - time.time()))
        except TimeoutError:
            break
        except ConnectionClosed:
            break
        if isinstance(data, bytes):
            text += data.decode(errors="replace")
        else:
            messages.append(json.loads(data))
        if until(messages, text):
            break
    return messages, text


def errors(messages):
    return [message["message"] for message in messages if message.get("type") == "error"]


def connected(messages):
    return any(m.get("type") == "status" and m.get("state") == "connected" for m in messages)


@unittest.skipIf(connect is None, "websockets n'est pas installe")
class TerminalAccessTests(unittest.TestCase):
    def test_rejected_without_session(self):
        with self.assertRaises(InvalidStatus) as context:
            open_ws()
        self.assertEqual(context.exception.response.status_code, 403)

    def test_rejected_from_other_origin(self):
        with self.assertRaises(InvalidStatus) as context:
            open_ws(shared_session(), origin="https://evil.example")
        self.assertEqual(context.exception.response.status_code, 403)

    def test_rejected_with_bad_csrf(self):
        session = shared_session()
        with open_ws(session) as ws:
            send_login(ws, session, csrf="mauvais")
            messages, _ = read_messages(ws, lambda m, t: errors(m))
        self.assertIn("Jeton CSRF invalide.", errors(messages))

    def test_root_is_refused(self):
        session = shared_session()
        with open_ws(session) as ws:
            send_login(ws, session, username="root")
            messages, _ = read_messages(ws, lambda m, t: errors(m))
        self.assertTrue(any("root" in error for error in errors(messages)))
        self.assertFalse(connected(messages))

    def test_wrong_password(self):
        session = shared_session()
        with open_ws(session) as ws:
            send_login(ws, session, password="faux")
            messages, _ = read_messages(ws, lambda m, t: errors(m))
        self.assertIn("Identifiants Linux incorrects.", errors(messages))

    def test_password_never_logged(self):
        # Le journal d'audit contient l'echec, jamais le mot de passe.
        session = shared_session()
        with open_ws(session) as ws:
            send_login(ws, session, password="mot-de-passe-temoin")
            read_messages(ws, lambda m, t: errors(m))
        overview = session.get("/api/security/overview").body
        self.assertIn(b"terminal_login_failure", overview)
        self.assertNotIn(b"mot-de-passe-temoin", overview)


class HostKeyTests(unittest.TestCase):
    """Verification de l'identite du serveur SSH (dans le processus de test)."""

    def _open(self, host_keys):
        import asyncio
        import terminal_api

        original = terminal_api.TERMINAL_HOST_KEYS
        terminal_api.TERMINAL_HOST_KEYS = host_keys
        try:
            async def attempt():
                connection, process = await terminal_api.open_ssh("alice", "secret-pass", 80, 24)
                process.close()
                connection.close()
            asyncio.run(attempt())
        finally:
            terminal_api.TERMINAL_HOST_KEYS = original

    def test_expected_host_key_is_accepted(self):
        self._open(os.environ["HYPERFLO_TERMINAL_HOST_KEYS"])

    def test_unexpected_host_key_is_refused(self):
        import asyncssh
        import terminal_api

        with tempfile.TemporaryDirectory() as directory:
            other = Path(directory) / "other.pub"
            asyncssh.generate_private_key("ssh-ed25519").write_public_key(str(other))
            with self.assertRaises(terminal_api.TerminalError) as context:
                self._open(str(other))
        self.assertIn("Clé d'hôte", str(context.exception))

    def test_no_host_key_is_refused(self):
        import terminal_api

        with self.assertRaises(terminal_api.TerminalError):
            self._open("/nonexistent/*.pub")


@unittest.skipIf(connect is None, "websockets n'est pas installe")
class TerminalSessionTests(unittest.TestCase):
    def test_interactive_session(self):
        session = shared_session()
        with open_ws(session) as ws:
            send_login(ws, session, cols=100, rows=30)
            messages, text = read_messages(ws, lambda m, t: "bienvenue" in t)
            self.assertTrue(connected(messages), messages)
            self.assertIn("bienvenue alice term=xterm-256color size=100x30", text)

            ws.send(b"ls -la\r")
            _, text = read_messages(ws, lambda m, t: "echo:ls -la" in t)
            self.assertIn("echo:ls -la", text)

            ws.send(json.dumps({"type": "resize", "cols": 120, "rows": 40}))
            _, text = read_messages(ws, lambda m, t: "resize 120x40" in t)
            self.assertIn("resize 120x40", text)

            # Ctrl+D: le shell se termine, le serveur ferme le terminal.
            ws.send(b"\x04")
            messages, _ = read_messages(
                ws, lambda m, t: any(x.get("state") == "closed" for x in m)
            )
        closed = [m for m in messages if m.get("state") == "closed"]
        self.assertEqual(closed[0]["reason"], "shell terminé")

    def test_limit_per_session(self):
        session = shared_session()
        sockets = [open_ws(session) for _ in range(3)]
        try:
            with open_ws(session) as fourth:
                messages, _ = read_messages(fourth, lambda m, t: errors(m))
            self.assertTrue(any("Maximum 3" in error for error in errors(messages)))
        finally:
            for ws in sockets:
                ws.close()


@unittest.skipIf(connect is None, "websockets n'est pas installe")
class TerminalZLogoutTests(unittest.TestCase):
    # "Z": unittest trie les classes par nom; celle-ci doit passer en dernier.
    def test_z_logout_closes_terminal(self):
        session = shared_session()
        # Laisse aux terminaux du test precedent le temps de se liberer.
        time.sleep(0.5)
        with open_ws(session) as ws:
            send_login(ws, session)
            messages, _ = read_messages(ws, lambda m, t: connected(m))
            self.assertTrue(connected(messages), messages)

            self.assertEqual(session.post("/api/auth/logout").status, 200)
            messages, _ = read_messages(
                ws, lambda m, t: any(x.get("state") == "closed" for x in m)
            )
        closed = [m for m in messages if m.get("state") == "closed"]
        self.assertEqual(closed[0]["reason"], "session Hyperflo fermee")


if __name__ == "__main__":
    unittest.main()
