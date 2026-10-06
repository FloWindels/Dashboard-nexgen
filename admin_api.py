"""Page Administration: etat des services (lecture seule, sans sudo)."""

import json
import re
import time
import urllib.request

from fastapi import APIRouter

from config import OLLAMA_URL
from system_monitor import get_docker, run_command

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
        items.append({"id": key, "name": label, "kind": "systemd", "unit": unit, **systemd_status(units.get(unit))})

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

        items.append({"id": key, "name": label, "kind": "docker", "unit": name, **status})

    return {"checked_at": int(time.time()), "services": items}
