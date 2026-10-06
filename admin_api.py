"""Page Administration: etat des services (lecture seule, sans sudo)."""

import json
import logging
import re
import socket
import time
import urllib.request
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from auth import verify_step_up_totp
from config import OLLAMA_URL
from security import audit
from system_monitor import get_docker, run_command

logger = logging.getLogger("hyperflo")

router = APIRouter(prefix="/api/admin")

ONLINE = "ONLINE"
OFFLINE = "OFFLINE"
ERROR = "ERROR"

# Services systemd suivis: (identifiant, libelle, unite).
SYSTEMD_SERVICES = [
    ("hyperflo", "Hyperflo Control", "hyperflo-control.service"),
    ("docker", "Docker", "docker.service"),
    ("playit", "Playit", "playit.service"),
    ("cloudflared", "Cloudflared", "cloudflared.service"),
    ("ssh", "SSH", "ssh.service"),
]

# Actions autorisees (le script hyperflo-service-action fait foi; cette liste
# sert a afficher les boutons et a refuser au plus tot).
SERVICE_ACTIONS = {
    "playit": ["start", "stop", "restart"],
    "cloudflared": ["restart"],
    "hyperflo": ["restart"],
}
# Conteneurs: actions via /api/docker (Minecraft passe par son script dedie).
CONTAINER_ACTIONS = ["start", "stop", "restart"]

# Sources de logs journald (script hyperflo-service-logs).
LOG_SOURCES = {"hyperflo", "playit", "cloudflared", "ssh", "docker"}

# Conteneurs suivis: (identifiant, libelle, conteneur). Ollama est en plus
# interroge en HTTP pour verifier qu'il repond vraiment.
CONTAINERS = [
    ("ollama", "Ollama", "ollama"),
    ("minecraft", "Minecraft", "minecraft"),
]


def systemd_states(units: list[str]) -> dict[str, dict]:
    """Etat de plusieurs unites en un seul appel a systemctl (sans sudo)."""
    result = run_command(
        [
            "/usr/bin/systemctl",
            "show",
            *units,
            "--property=Id,ActiveState,SubState,Result,ActiveEnterTimestamp",
            "--timestamp=unix",
            "--no-pager",
        ],
        timeout=5,
    )
    states = {}
    if result["code"] != 0:
        return states

    for block in result["stdout"].split("\n\n"):
        values = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        if "Id" in values:
            states[values["Id"]] = values
    return states


def _since(values: dict) -> int | None:
    match = re.fullmatch(r"@(\d+)", values.get("ActiveEnterTimestamp", ""))
    return int(match.group(1)) if match else None


def systemd_status(values: dict | None) -> dict:
    if not values:
        return {"state": ERROR, "detail": "État inconnu"}

    active = values.get("ActiveState", "")
    sub = values.get("SubState", "")

    if active == "active":
        return {"state": ONLINE, "detail": sub, "since": _since(values)}
    if active in {"activating", "reloading"}:
        return {"state": ONLINE, "detail": "démarrage"}
    if active == "failed" or values.get("Result", "success") != "success":
        return {"state": ERROR, "detail": f"échec ({values.get('Result', active)})"}
    return {"state": OFFLINE, "detail": "arrêté"}


def container_status(container: dict | None) -> dict:
    if container is None:
        return {"state": ERROR, "detail": "Conteneur introuvable"}

    status = str(container.get("Status", ""))
    if container.get("State") != "running":
        # "Exited (0)" = arret volontaire; autre code = plantage.
        match = re.search(r"Exited \((\d+)\)", status)
        if match and match.group(1) != "0":
            return {"state": ERROR, "detail": status}
        return {"state": OFFLINE, "detail": status or "arrêté"}

    if "(unhealthy)" in status:
        return {"state": ERROR, "detail": status}
    if "(health: starting)" in status:
        return {"state": ONLINE, "detail": "démarrage"}
    return {"state": ONLINE, "detail": status}


def ollama_responds() -> str | None:
    """Version d'Ollama si l'API repond, sinon None."""
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/version", timeout=2) as response:
            return str(json.loads(response.read()).get("version", "")) or "?"
    except Exception:
        return None


@router.get("/services")
def services():
    units = systemd_states([unit for _, _, unit in SYSTEMD_SERVICES])
    items = []

    for key, label, unit in SYSTEMD_SERVICES:
        items.append({
            "id": key,
            "name": label,
            "kind": "systemd",
            "unit": unit,
            "actions": SERVICE_ACTIONS.get(key, []),
            **systemd_status(units.get(unit)),
        })

    docker = get_docker()
    by_name = {str(item.get("Names", "")): item for item in docker["containers"]}

    for key, label, name in CONTAINERS:
        if not docker["available"]:
            status = {"state": ERROR, "detail": "Docker indisponible"}
        else:
            status = container_status(by_name.get(name))

        if key == "ollama" and status["state"] == ONLINE:
            version = ollama_responds()
            if version is None:
                status = {"state": ERROR, "detail": "Conteneur actif mais l'API ne répond pas"}
            else:
                status["detail"] = f"API v{version} · {status['detail']}"

        items.append({
            "id": key,
            "name": label,
            "kind": "docker",
            "unit": name,
            "actions": CONTAINER_ACTIONS if docker["available"] else [],
            **status,
        })

    return {"checked_at": int(time.time()), "hostname": socket.gethostname(), "services": items}


def _require_action_header(request: Request) -> None:
    # En-tete personnalise: impossible a envoyer depuis un formulaire d'un
    # autre site (en plus du jeton CSRF verifie par le middleware).
    if request.headers.get("X-Hyperflo-Action") != "1":
        raise HTTPException(status_code=403, detail="Action header missing")


def _error(result: dict, default: str) -> str:
    return (result["stderr"] or default).strip()[:300]


@router.post("/services/{service}/{action}")
def service_action(service: str, action: str, request: Request):
    _require_action_header(request)
    if action not in SERVICE_ACTIONS.get(service, []):
        raise HTTPException(status_code=400, detail="Action non autorisee pour ce service")

    result = run_command(
        ["/usr/bin/sudo", "-n", "/usr/local/sbin/hyperflo-service-action", action, service],
        timeout=150,
    )
    audit("service_action", request, service=service, action=action, ok=result["code"] == 0)

    if result["code"] != 0:
        logger.warning("service %s %s: %s", action, service, result["stderr"])
        raise HTTPException(status_code=400, detail=_error(result, "Action impossible"))
    return {"ok": True, "service": service, "action": action}


@router.get("/logs")
def service_logs(request: Request, source: str, lines: int = 200, audit_only: bool = False):
    if source not in LOG_SOURCES:
        raise HTTPException(status_code=400, detail="Source de logs non autorisee")
    lines = max(1, min(lines, 1000))

    result = run_command(
        ["/usr/bin/sudo", "-n", "/usr/local/sbin/hyperflo-service-logs", source, str(lines)],
        timeout=30,
    )
    if result["code"] != 0:
        raise HTTPException(status_code=400, detail=_error(result, "Logs indisponibles"))

    text = result["stdout"]
    if audit_only:
        text = "\n".join(line for line in text.splitlines() if "hyperflo-audit" in line)

    audit("service_logs", request, source=source, lines=lines)
    return {"source": source, "logs": text}


class PowerBody(BaseModel):
    action: Literal["reboot", "poweroff"]
    # Nom du serveur retape par l'utilisateur, en plus d'un code TOTP.
    confirm: str = Field(max_length=64)
    totp: str = Field(max_length=16)


@router.post("/power")
async def power(body: PowerBody, request: Request):
    _require_action_header(request)

    if body.confirm.strip() != socket.gethostname():
        raise HTTPException(status_code=400, detail="Nom du serveur incorrect")

    if not verify_step_up_totp(request, body.totp):
        audit("power_denied", request, action=body.action)
        raise HTTPException(status_code=403, detail="Code TOTP invalide")

    audit("power", request, action=body.action)
    # Peut durer jusqu'a ~2 min (arret propre de Minecraft avant).
    result = await run_in_threadpool(
        run_command,
        ["/usr/bin/sudo", "-n", "/usr/local/sbin/hyperflo-power", body.action],
        240,
    )
    if result["code"] != 0:
        logger.warning("power %s: %s", body.action, result["stderr"])
        raise HTTPException(status_code=400, detail=_error(result, "Action impossible"))
    return {"ok": True, "action": body.action}
