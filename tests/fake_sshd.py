"""Faux serveur SSH pour les tests du terminal (asyncssh).

Compte accepte: alice / secret-pass. Le "shell" affiche le type et la taille
du terminal, renvoie ce qu'il recoit (prefixe "echo:"), signale les
changements de taille et s'arrete sur Ctrl+D.

    python fake_sshd.py <port> <cle_privee_hote>
"""

import asyncio
import sys

import asyncssh

USERNAME = "alice"
PASSWORD = "secret-pass"


class Server(asyncssh.SSHServer):
    def begin_auth(self, username):
        return True

    def password_auth_supported(self):
        return True

    def validate_password(self, username, password):
        return username == USERNAME and password == PASSWORD


async def shell(process):
    width, height = process.get_terminal_size()[:2]
    process.stdout.write(
        f"bienvenue {process.get_extra_info('username')} "
        f"term={process.get_terminal_type()} size={width}x{height}\r\n".encode()
    )
    while True:
        try:
            data = await process.stdin.read(1024)
        except asyncssh.TerminalSizeChanged as change:
            process.stdout.write(f"resize {change.width}x{change.height}\r\n".encode())
            continue
        if not data or data == b"\x04":
            break
        process.stdout.write(b"echo:" + data)
    process.exit(0)


async def main(port, host_key):
    await asyncssh.create_server(
        Server,
        "127.0.0.1",
        port,
        server_host_keys=[host_key],
        process_factory=shell,
        encoding=None,
    )
    await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]), sys.argv[2]))
