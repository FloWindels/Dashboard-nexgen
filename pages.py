from html import escape

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from config import BASE_DIR

router = APIRouter()

# Menu commun a toutes les pages authentifiees. Il est insere a la place du
# marqueur NAV_MARKER pour ne pas etre recopie dans chaque fichier HTML.
NAV_MARKER = "<!-- hyperflo:nav -->"

NAV_ITEMS = [
    ("dashboard", "/", "🏠 Dashboard"),
    ("docker", "/docker", "🐳 Docker"),
    ("ollama", "/ollama", "🤖 Ollama"),
    ("admin", "/admin", "⚙️ Administration"),
]


def render_nav(active: str) -> str:
    links = []
    for key, href, label in NAV_ITEMS:
        if key == active:
            links.append(
                f'<a href="{href}" class="nav-link active" aria-current="page">'
                f"{escape(label)}</a>"
            )
        else:
            links.append(f'<a href="{href}" class="nav-link">{escape(label)}</a>')

    return (
        '<nav class="sidebar" aria-label="Navigation principale">'
        '<div class="logo">⚡ Hyperflo</div>'
        + "".join(links)
        + '<a href="/login" class="nav-link nav-logout" data-logout>🚪 Déconnexion</a>'
        "</nav>"
    )


def render_page(name: str) -> HTMLResponse:
    html = (BASE_DIR / "pages" / f"{name}.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace(NAV_MARKER, render_nav(name), 1))


@router.get("/")
def homepage():
    return render_page("dashboard")


@router.get("/dashboard")
def dashboard_page():
    return render_page("dashboard")


@router.get("/docker")
def docker_page():
    return render_page("docker")


@router.get("/ollama")
def ollama_page():
    return render_page("ollama")


@router.get("/admin")
def admin_page():
    return render_page("admin")
