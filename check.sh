#!/bin/bash
# Verifie le projet avant un redemarrage du service.
#
#   ./check.sh
#
# Lance une instance de test sur un port libre, avec des identifiants factices
# et un faux Ollama. Ne lit pas /etc/hyperflo-control.env et ne touche pas au
# service en production. Si une etape echoue: ne pas redemarrer le service.

set -euo pipefail

cd "$(dirname "$0")"
PY="$PWD/venv/bin/python"
export PYTHONDONTWRITEBYTECODE=1

# Python isole (-I) par defaut. HYPERFLO_CHECK_PYTHONPATH permet de tester
# avec des paquets hors du venv (ex.: avant de les installer dans le venv).
PYFLAGS=(-I)
if [ -n "${HYPERFLO_CHECK_PYTHONPATH:-}" ]; then
    export PYTHONPATH="$HYPERFLO_CHECK_PYTHONPATH"
    PYFLAGS=(-s -P)
fi

step() {
    echo
    echo "== $*"
}

step "1/7 Syntaxe Python"
"$PY" "${PYFLAGS[@]}" - *.py tests/*.py deploy/sbin/hyperflo-docker-action deploy/sbin/hyperflo-docker-info deploy/sbin/hyperflo-minecraft-action <<'EOF'
import ast
import sys

for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as source:
        ast.parse(source.read(), path)
print(f"{len(sys.argv) - 1} fichiers OK")
EOF

step "2/7 Syntaxe shell"
bash -n check.sh deploy/install.sh
sh -n deploy/sbin/hyperflo-docker-list
sh -n deploy/sbin/hyperflo-docker-stats
echo "OK"

step "3/7 Droits de lecture pour le service (utilisateur hyperflo)"
# Un fichier cree ou remplace par florent appartient a florent:florent et
# n'est pas lisible par le service (erreur 500 en production).
unreadable=()
while IFS= read -r -d '' path; do
    if [ "$(stat -c %G "$path")" != hyperflo ] \
        && ! getfacl -p "$path" 2>/dev/null | grep -q '^group:hyperflo:r'; then
        unreadable+=("$path")
    fi
done < <(find . -maxdepth 1 -name '*.py' -print0; find pages static -print0)
if [ "${#unreadable[@]}" -ne 0 ]; then
    echo "ECHEC: non lisible par hyperflo:" >&2
    printf '  %s\n' "${unreadable[@]}" >&2
    echo "Corriger avec: setfacl -m g:hyperflo:rX,m::rwX <fichiers>" >&2
    exit 1
fi
echo "OK"

step "4/7 Dependances Python"
if ! "$PY" "${PYFLAGS[@]}" -c "import asyncssh, websockets" 2>/dev/null; then
    echo "ECHEC: asyncssh ou websockets absent du venv (terminal Web)." >&2
    echo "  sudo venv/bin/pip install --only-binary :all: -r requirements.txt" >&2
    echo "  sudo chgrp -R hyperflo venv" >&2
    exit 1
fi
echo "OK"

step "5/7 Identifiants de test"
WORKDIR="$(mktemp -d)"
PIDS=()
cleanup() {
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    rm -rf "$WORKDIR"
}
trap cleanup EXIT

"$PY" "${PYFLAGS[@]}" > "$WORKDIR/env" <<'EOF'
import secrets
import shlex
import socket

import pyotp
from argon2 import PasswordHasher


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


password = secrets.token_urlsafe(16)
values = {
    "HYPERFLO_USER": "testadmin",
    "HYPERFLO_TEST_PASSWORD": password,
    "HYPERFLO_PASSWORD_HASH": PasswordHasher().hash(password),
    "HYPERFLO_TOTP_SECRET": pyotp.random_base32(),
    "HYPERFLO_SESSION_SECRET": secrets.token_urlsafe(48),
    "HYPERFLO_TEST_PORT": str(free_port()),
    "HYPERFLO_FAKE_OLLAMA_PORT": str(free_port()),
    "HYPERFLO_TERMINAL_SSH_PORT": str(free_port()),
    "OLLAMA_API_KEY": "",
}
for key, value in values.items():
    print(f"export {key}={shlex.quote(value)}")
EOF
# shellcheck disable=SC1091
. "$WORKDIR/env"
export OLLAMA_URL="http://127.0.0.1:$HYPERFLO_FAKE_OLLAMA_PORT"
# Faux sshd: cle d'hote generee pour cette verification uniquement.
"$PY" "${PYFLAGS[@]}" -c "
import asyncssh, sys
key = asyncssh.generate_private_key('ssh-ed25519')
key.write_private_key(sys.argv[1])
key.write_public_key(sys.argv[1] + '.pub')
" "$WORKDIR/ssh_host_key"
export HYPERFLO_TERMINAL_HOST_KEYS="$WORKDIR/ssh_host_key.pub"
export HYPERFLO_TEST_URL="http://127.0.0.1:$HYPERFLO_TEST_PORT"
echo "OK (port $HYPERFLO_TEST_PORT)"

step "6/7 Demarrage de l'application de test"
"$PY" "${PYFLAGS[@]}" tests/fake_ollama.py "$HYPERFLO_FAKE_OLLAMA_PORT" &
PIDS+=($!)
"$PY" "${PYFLAGS[@]}" tests/fake_sshd.py "$HYPERFLO_TERMINAL_SSH_PORT" "$WORKDIR/ssh_host_key" &
PIDS+=($!)
"$PWD/venv/bin/uvicorn" app:app \
    --host 127.0.0.1 --port "$HYPERFLO_TEST_PORT" \
    --workers 1 --no-proxy-headers --no-server-header \
    > "$WORKDIR/uvicorn.log" 2>&1 &
PIDS+=($!)

started=0
for _ in $(seq 1 50); do
    if curl -fs -o /dev/null "$HYPERFLO_TEST_URL/login"; then
        started=1
        break
    fi
    sleep 0.2
done
if [ "$started" -ne 1 ]; then
    echo "ECHEC: l'application ne demarre pas." >&2
    cat "$WORKDIR/uvicorn.log" >&2
    exit 1
fi
echo "OK (imports et chargement de FastAPI)"

step "7/7 Tests"
if ! "$PY" "${PYFLAGS[@]}" -m unittest discover -s tests -t . "$@"; then
    echo
    echo "Journal de l'instance de test:" >&2
    tail -n 30 "$WORKDIR/uvicorn.log" >&2
    exit 1
fi

echo
echo "Tout est OK: le redemarrage peut etre propose."
