from fastapi import APIRouter
from fastapi.responses import FileResponse

from config import BASE_DIR

router = APIRouter()


@router.get("/")
def homepage():
    return FileResponse(BASE_DIR / "pages" / "dashboard.html")


@router.get("/dashboard")
def dashboard_page():
    return FileResponse(BASE_DIR / "pages" / "dashboard.html")


@router.get("/docker")
def docker_page():
    return FileResponse(BASE_DIR / "pages" / "docker.html")


@router.get("/ollama")
def ollama_page():
    return FileResponse(BASE_DIR / "pages" / "ollama.html")


@router.get("/admin")
def admin_page():
    return FileResponse(BASE_DIR / "pages" / "admin.html")
