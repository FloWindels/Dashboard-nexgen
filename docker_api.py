import json

from fastapi import APIRouter, HTTPException, Request

from system_monitor import run_command

router = APIRouter(prefix="/api/docker")


@router.post("/{name}/{action}")
def docker_action(name: str, action: str, request: Request):
    if request.headers.get("X-Hyperflo-Action") != "1":
        raise HTTPException(status_code=403, detail="Action header missing")

    if action not in {"start", "stop", "restart"}:
        raise HTTPException(status_code=400, detail="Action non autorisee")

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

    if result["code"] != 0:
        raise HTTPException(
            status_code=400,
            detail=result["stderr"] or "Docker action failed",
        )

    return {"ok": True, "container": name, "action": action}


@router.get("/{name}/details")
def docker_details(name: str):
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
            detail=result["stderr"] or "Impossible de lire le conteneur",
        )

    try:
        return json.loads(result["stdout"])
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="Reponse Docker invalide") from exc


@router.get("/{name}/logs")
def docker_logs(name: str, lines: int = 200):
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
            detail=result["stderr"] or "Impossible de lire les logs",
        )

    return {"container": name, "logs": result["stdout"]}
