import hashlib
import re
from html import escape

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from config import BASE_DIR

router = APIRouter()

STATIC_DIR = BASE_DIR / "static"

# Cloudflare impose un cache navigateur de 4 h sur /static. Chaque reference
# recoit donc l'empreinte du fichier (?v=...): quand il change, l'URL change.
ASSET_REFERENCE = re.compile(r'((?:src|href)="/static/)([^"?#]+)(")')
_asset_versions: dict[str, tuple[int, int, str]] = {}


def asset_version(relative_path: str) -> str:
    path = (STATIC_DIR / relative_path).resolve()
    if not path.is_relative_to(STATIC_DIR.resolve()) or not path.is_file():
        return ""

    stat = path.stat()
    cached = _asset_versions.get(relative_path)
    if cached and cached[:2] == (stat.st_mtime_ns, stat.st_size):
        return cached[2]

    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    _asset_versions[relative_path] = (stat.st_mtime_ns, stat.st_size, digest)
    return digest


def add_asset_versions(html: str) -> str:
    def replace(match: re.Match) -> str:
        version = asset_version(match.group(2))
        if not version:
            return match.group(0)
        return f"{match.group(1)}{match.group(2)}?v={version}{match.group(3)}"

    return ASSET_REFERENCE.sub(replace, html)


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
    html = html.replace(NAV_MARKER, render_nav(name), 1)
    return HTMLResponse(add_asset_versions(html))


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
