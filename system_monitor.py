import csv
import functools
import io
import json
import os
import platform
import socket
import subprocess
import threading
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


# Capteurs essayes dans l'ordre (Intel, AMD, ARM, ACPI).
CPU_SENSORS = ("coretemp", "k10temp", "cpu_thermal", "acpitz")


def get_cpu_temperature():
    try:
        temperatures = psutil.sensors_temperatures(fahrenheit=False)
    except Exception:
        return None

    for name in CPU_SENSORS:
        values = [
            sensor.current
            for sensor in temperatures.get(name, [])
            if sensor.current is not None
        ]
        if values:
            return round(max(values), 1)

    return None


@functools.cache
def get_system_info() -> dict:
    """Informations qui ne changent pas tant que le serveur tourne."""
    try:
        os_name = platform.freedesktop_os_release().get("PRETTY_NAME", "")
    except OSError:
        os_name = ""

    cpu_model = ""
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as cpuinfo:
            for line in cpuinfo:
                if line.startswith("model name"):
                    cpu_model = " ".join(line.split(":", 1)[1].split())
                    break
    except OSError:
        pass

    return {
        "os": os_name,
        "kernel": platform.release(),
        "cpu_model": cpu_model,
    }


# Interfaces virtuelles masquees (Docker, ponts, boucle locale).
HIDDEN_INTERFACE_PREFIXES = ("lo", "veth", "br-", "docker", "virbr")


def get_interfaces() -> list[dict]:
    addresses = psutil.net_if_addrs()
    interfaces = []

    for name, stats in sorted(psutil.net_if_stats().items()):
        if name.startswith(HIDDEN_INTERFACE_PREFIXES):
            continue
        interfaces.append({
            "name": name,
            "up": stats.isup,
            "speed": stats.speed,
            "ipv4": [
                address.address
                for address in addresses.get(name, [])
                if address.family == socket.AF_INET
            ],
        })

    return interfaces


class NetworkRate:
    """Debit calcule entre deux appels (au moins une seconde d'ecart)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last = None
        self._rates = (0.0, 0.0)

    def update(self, received: int, sent: int) -> tuple[float, float]:
        now = time.monotonic()
        with self._lock:
            if self._last is None:
                self._last = (now, received, sent)
            elif now - self._last[0] >= 1:
                elapsed = now - self._last[0]
                self._rates = (
                    max(0.0, (received - self._last[1]) / elapsed),
                    max(0.0, (sent - self._last[2]) / elapsed),
                )
                self._last = (now, received, sent)
            return self._rates


network_rate = NetworkRate()


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
    swap = psutil.swap_memory()
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
    rx_rate, tx_rate = network_rate.update(network.bytes_recv, network.bytes_sent)
    system = get_system_info()

    return {
        "hostname": socket.gethostname(),
        "uptime": uptime,
        "system": {
            "os": system["os"],
            "kernel": system["kernel"],
        },
        "cpu": {
            "model": system["cpu_model"],
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
            "swap_total": swap.total,
            "swap_used": swap.used,
            "swap_percent": swap.percent,
        },
        "network": {
            "received": network.bytes_recv,
            "sent": network.bytes_sent,
            "rx_rate": rx_rate,
            "tx_rate": tx_rate,
            "interfaces": get_interfaces(),
        },
        "disks": disks,
        "gpu": get_gpu(),
        "docker": get_docker(),
    }
