from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from auth import router as auth_router
from auth import setup_auth
from config import BASE_DIR, validate_auth_config
from docker_api import router as docker_router
from ollama_api import router as ollama_router
from pages import router as pages_router
from system_monitor import router as system_router

validate_auth_config()

app = FastAPI(
    title="Hyperflo Control",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# Authentification et sessions.
setup_auth(app)

# Fichiers statiques. Le middleware d'auth laisse passer uniquement
# login.css/login.js sans session; le reste reste protege.
app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)

app.include_router(auth_router)
app.include_router(pages_router)
app.include_router(system_router)
app.include_router(docker_router)
app.include_router(ollama_router)
