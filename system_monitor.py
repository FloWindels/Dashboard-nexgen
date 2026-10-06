import csv
import io
import json
import os
import socket
import subprocess
import time

import psutil
from fastapi import APIRouter

router = APIRouter()


def run_command(command: list[str], timeout: int = 3) -> dict:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "code": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except subprocess.TimeoutExpired:
        return {"code": 124, "stdout": "", "stderr": "timeout"}
    except Exception as exc:
        return {"code": 1, "stdout": "", "stderr": str(exc)}


def get_cpu_temperature():
    try:
        temperatures = psutil.sensors_temperatures(fahrenheit=False)
        coretemp = temperatures.get("coretemp", [])
        values = [
            sensor.current
            for sensor in coretemp
            if sensor.current is not None
        ]
        if values:
            return round(max(values), 1)
    except Exception:
        pass

    return None


def get_gpu() -> dict:
    result = run_command(
        [
            "/usr/bin/nvidia-smi",
            "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ],
        timeout=3,
    )

    if result["code"] != 0:
        return {
            "available": False,
            "error": result["stderr"] or "nvidia-smi unavailable",
        }

    try:
        reader = csv.reader(io.StringIO(result["stdout"]))
        row = next(reader)
        return {
            "available": True,
            "name": row[0].strip(),
            "temperature": float(row[1]),
            "utilization": float(row[2]),
            "memory_used": float(row[3]),
            "memory_total": float(row[4]),
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def get_docker() -> dict:
    result = run_command(
        [
            "/usr/bin/sudo",
            "-n",
            "/usr/local/sbin/hyperflo-docker-list",
        ],
        timeout=3,
    )

    if result["code"] != 0:
        return {
            "available": False,
            "error": result["stderr"],
            "containers": [],
        }

    containers = []
    for line in result["stdout"].splitlines():
        if not line.strip():
            continue
        try:
            containers.append(json.loads(line))
        except json.JSONDecodeError:
            pass

    return {"available": True, "containers": containers}


def get_disk(path: str):
    try:
        usage = psutil.disk_usage(path)
        return {
            "path": path,
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "percent": usage.percent,
        }
    except Exception:
        return None


@router.get("/api/status")
def status():
    memory = psutil.virtual_memory()
    uptime = int(time.time() - psutil.boot_time())

    disks = []
    root_disk = get_disk("/")
    if root_disk:
        disks.append(root_disk)

    if os.path.ismount("/srv/storage"):
        storage = get_disk("/srv/storage")
        if storage:
            disks.append(storage)

    network = psutil.net_io_counters()

    return {
        "hostname": socket.gethostname(),
        "uptime": uptime,
        "cpu": {
            "usage": psutil.cpu_percent(interval=0.2),
            "cores": psutil.cpu_count(logical=False),
            "threads": psutil.cpu_count(logical=True),
            "temperature": get_cpu_temperature(),
            "load": os.getloadavg(),
        },
        "memory": {
            "total": memory.total,
            "used": memory.used,
            "available": memory.available,
            "percent": memory.percent,
        },
        "network": {
            "received": network.bytes_recv,
            "sent": network.bytes_sent,
        },
        "disks": disks,
        "gpu": get_gpu(),
        "docker": get_docker(),
    }
