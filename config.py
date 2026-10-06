from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent

HYPERFLO_USER = os.environ.get("HYPERFLO_USER", "")
HYPERFLO_PASSWORD_HASH = os.environ.get("HYPERFLO_PASSWORD_HASH", "")
HYPERFLO_TOTP_SECRET = os.environ.get("HYPERFLO_TOTP_SECRET", "")
HYPERFLO_SESSION_SECRET = os.environ.get("HYPERFLO_SESSION_SECRET", "")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "")


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
