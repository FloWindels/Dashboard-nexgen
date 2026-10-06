import json
import logging
import re

from fastapi import APIRouter, HTTPException, Request

from security import audit
from system_monitor import run_command

router = APIRouter(prefix="/api/docker")
logger = logging.getLogger("hyperflo")

# Meme regle que les scripts /usr/local/sbin/hyperflo-docker-*: on refuse
# au plus tot ce qui serait de toute facon refuse par sudo.
CONTAINER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
ALLOWED_ACTIONS = {"start", "stop", "restart"}


def _check_name(name: str) -> None:
    if not CONTAINER_NAME.fullmatch(name):
        raise HTTPException(status_code=400, detail="Nom de conteneur invalide")


def _error_detail(result: dict, default: str) -> str:
    # Les scripts renvoient des messages courts; on borne au cas ou Docker
    # serait plus bavard.
    message = (result["stderr"] or default).strip()
    return message[:300]


@router.post("/{name}/{action}")
def docker_action(name: str, action: str, request: Request):
    if request.headers.get("X-Hyperflo-Action") != "1":
        raise HTTPException(status_code=403, detail="Action header missing")

    if action not in ALLOWED_ACTIONS:
        raise HTTPException(status_code=400, detail="Action non autorisee")

    _check_name(name)

    result = run_command(
        [
            "/usr/bin/sudo",
            "-n",
            "/usr/local/sbin/hyperflo-docker-action",
            action,
            name,
        ],
        timeout=30,
    )

    audit(
        "docker_action",
        request,
        container=name,
        action=action,
        ok=result["code"] == 0,
    )

    if result["code"] != 0:
        logger.warning("docker %s %s: %s", action, name, result["stderr"])
        raise HTTPException(
            status_code=400,
            detail=_error_detail(result, "Docker action failed"),
        )

    return {"ok": True, "container": name, "action": action}


@router.get("/{name}/details")
def docker_details(name: str):
    _check_name(name)

    result = run_command(
        [
            "/usr/bin/sudo",
            "-n",
            "/usr/local/sbin/hyperflo-docker-info",
            "details",
            name,
        ],
        timeout=15,
    )

    if result["code"] != 0:
        raise HTTPException(
            status_code=400,
            detail=_error_detail(result, "Impossible de lire le conteneur"),
        )

    try:
        return json.loads(result["stdout"])
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="Reponse Docker invalide") from exc


@router.get("/{name}/logs")
def docker_logs(name: str, request: Request, lines: int = 200):
    _check_name(name)
    lines = max(1, min(lines, 500))

    result = run_command(
        [
            "/usr/bin/sudo",
            "-n",
            "/usr/local/sbin/hyperflo-docker-info",
            "logs",
            name,
            str(lines),
        ],
        timeout=15,
    )

    if result["code"] != 0:
        raise HTTPException(
            status_code=400,
            detail=_error_detail(result, "Impossible de lire les logs"),
        )

    # Les logs peuvent contenir des secrets: la consultation est tracee.
    audit("docker_logs", request, container=name, lines=lines)
    return {"container": name, "logs": result["stdout"]}
