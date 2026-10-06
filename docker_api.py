import json
import logging
import re
import threading
import time

from fastapi import APIRouter, HTTPException, Request

from security import audit
from system_monitor import get_docker, run_command

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


def _parse_percent(value) -> float | None:
    try:
        return float(str(value).strip().rstrip("%"))
    except ValueError:
        return None


def normalize_container(raw: dict) -> dict:
    ports = [port.strip() for port in str(raw.get("Ports", "")).split(",") if port.strip()]
    return {
        "id": str(raw.get("ID", ""))[:12],
        "name": str(raw.get("Names", "")),
        "image": str(raw.get("Image", "")),
        "state": str(raw.get("State", "")),
        "status": str(raw.get("Status", "")),
        "ports": ports,
    }


def normalize_stats(raw: dict) -> dict:
    return {
        "name": str(raw.get("Name", "")),
        "cpu_percent": _parse_percent(raw.get("CPUPerc", "")),
        "mem_usage": str(raw.get("MemUsage", "")),
        "mem_percent": _parse_percent(raw.get("MemPerc", "")),
        "net_io": str(raw.get("NetIO", "")),
        "block_io": str(raw.get("BlockIO", "")),
        "pids": str(raw.get("PIDs", "")),
    }


class StatsCache:
    """docker stats --no-stream prend ~2 s: resultat partage quelques secondes."""

    MAX_AGE = 3
    # Script absent ou refuse: on ne reessaie pas a chaque rafraichissement.
    FAILURE_MAX_AGE = 60

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._time = 0.0
        self._data: dict | None = None

    def get(self) -> dict:
        with self._lock:
            if self._data is None or time.monotonic() - self._time >= self._max_age():
                self._data = self._fetch()
                self._time = time.monotonic()
            return self._data

    def _max_age(self) -> int:
        if self._data is not None and not self._data["available"]:
            return self.FAILURE_MAX_AGE
        return self.MAX_AGE

    @staticmethod
    def _fetch() -> dict:
        result = run_command(
            ["/usr/bin/sudo", "-n", "/usr/local/sbin/hyperflo-docker-stats"],
            timeout=15,
        )
        if result["code"] != 0:
            logger.warning("docker stats: %s", result["stderr"])
            return {"available": False, "stats": {}}

        stats = {}
        for line in result["stdout"].splitlines():
            try:
                item = normalize_stats(json.loads(line))
            except (json.JSONDecodeError, AttributeError):
                continue
            if item["name"]:
                stats[item["name"]] = item
        return {"available": True, "stats": stats}


stats_cache = StatsCache()


@router.get("/containers")
def docker_containers():
    docker = get_docker()
    if not docker["available"]:
        raise HTTPException(status_code=502, detail="Docker indisponible")
    containers = [normalize_container(raw) for raw in docker["containers"]]
    containers.sort(key=lambda container: container["name"])
    return {"containers": containers}


@router.get("/stats")
def docker_stats():
    return stats_cache.get()


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
