from pathlib import Path
import base64
import binascii
import logging
import os

BASE_DIR = Path(__file__).resolve().parent

logger = logging.getLogger("hyperflo")


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} doit etre un entier") from exc


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


HYPERFLO_USER = os.environ.get("HYPERFLO_USER", "")
HYPERFLO_PASSWORD_HASH = os.environ.get("HYPERFLO_PASSWORD_HASH", "")
HYPERFLO_TOTP_SECRET = os.environ.get("HYPERFLO_TOTP_SECRET", "")
HYPERFLO_SESSION_SECRET = os.environ.get("HYPERFLO_SESSION_SECRET", "")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "")

# Sessions (stockees cote serveur, en memoire).
SESSION_IDLE_TIMEOUT = _env_int("HYPERFLO_SESSION_IDLE_TIMEOUT", 60 * 60)
SESSION_MAX_AGE = _env_int("HYPERFLO_SESSION_MAX_AGE", 12 * 60 * 60)
SESSION_MAX_COUNT = _env_int("HYPERFLO_SESSION_MAX_COUNT", 10)

# Anti brute-force.
LOGIN_WINDOW = _env_int("HYPERFLO_LOGIN_WINDOW", 15 * 60)
LOGIN_MAX_FAILURES_PER_IP = _env_int("HYPERFLO_LOGIN_MAX_FAILURES_PER_IP", 5)
LOGIN_MAX_FAILURES_GLOBAL = _env_int("HYPERFLO_LOGIN_MAX_FAILURES_GLOBAL", 30)

# Cloudflare Tunnel (cloudflared local) fournit l'IP reelle du client.
TRUST_CF_CONNECTING_IP = _env_bool("HYPERFLO_TRUST_CF_CONNECTING_IP", True)

# Origines autorisees pour les WebSockets, en plus de celle du Host de la
# requete (ex.: "https://admin.example.com"), separees par des virgules.
ALLOWED_ORIGINS = {
    origin.strip().rstrip("/")
    for origin in os.environ.get("HYPERFLO_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
}

# Terminal Web: SSH vers la machine elle-meme.
TERMINAL_SSH_HOST = os.environ.get("HYPERFLO_TERMINAL_SSH_HOST", "127.0.0.1")
TERMINAL_SSH_PORT = _env_int("HYPERFLO_TERMINAL_SSH_PORT", 22)
# Cles publiques d'hote de sshd (verification de l'identite du serveur).
TERMINAL_HOST_KEYS = os.environ.get("HYPERFLO_TERMINAL_HOST_KEYS", "/etc/ssh/ssh_host_*_key.pub")
TERMINAL_IDLE_TIMEOUT = _env_int("HYPERFLO_TERMINAL_IDLE_TIMEOUT", 30 * 60)
TERMINAL_MAX_PER_SESSION = _env_int("HYPERFLO_TERMINAL_MAX_PER_SESSION", 3)
TERMINAL_MAX_TOTAL = _env_int("HYPERFLO_TERMINAL_MAX_TOTAL", 6)
# Echecs de connexion SSH tolerees par session Hyperflo sur LOGIN_WINDOW.
TERMINAL_MAX_LOGIN_FAILURES = _env_int("HYPERFLO_TERMINAL_MAX_LOGIN_FAILURES", 5)

# Taille maximale des corps de requete.
MAX_BODY_BYTES = _env_int("HYPERFLO_MAX_BODY_BYTES", 64 * 1024)
MAX_CHAT_BODY_BYTES = _env_int("HYPERFLO_MAX_CHAT_BODY_BYTES", 16 * 1024 * 1024)


def validate_auth_config() -> None:
    missing = []

    if not HYPERFLO_USER:
        missing.append("HYPERFLO_USER")
    if not HYPERFLO_PASSWORD_HASH:
        missing.append("HYPERFLO_PASSWORD_HASH")
    if not HYPERFLO_TOTP_SECRET:
        missing.append("HYPERFLO_TOTP_SECRET")
    if not HYPERFLO_SESSION_SECRET:
        missing.append("HYPERFLO_SESSION_SECRET")

    if missing:
        raise RuntimeError(
            "Configuration d'authentification Hyperflo incomplete. "
            "Variables manquantes: " + ", ".join(missing)
        )

    if not HYPERFLO_PASSWORD_HASH.startswith("$argon2"):
        raise RuntimeError("HYPERFLO_PASSWORD_HASH doit etre un hash argon2")

    try:
        padded = HYPERFLO_TOTP_SECRET.upper() + "=" * (-len(HYPERFLO_TOTP_SECRET) % 8)
        base64.b32decode(padded)
    except (binascii.Error, ValueError) as exc:
        raise RuntimeError("HYPERFLO_TOTP_SECRET n'est pas un secret base32 valide") from exc

    # Avertissements seulement: un redemarrage ne doit pas casser le service.
    if len(HYPERFLO_SESSION_SECRET) < 32:
        logger.warning("HYPERFLO_SESSION_SECRET fait moins de 32 caracteres")
    if len(HYPERFLO_TOTP_SECRET.rstrip("=")) < 26:
        logger.warning("HYPERFLO_TOTP_SECRET fait moins de 128 bits")
