import re
import unittest
from pathlib import Path

from tests.helpers import request, shared_session

ROOT = Path(__file__).resolve().parent.parent
PAGES = {
    "/": "dashboard",
    "/docker": "docker",
    "/ollama": "ollama",
    "/admin": "admin",
}


class PageTests(unittest.TestCase):
    def test_pages_render_with_shared_nav(self):
        session = shared_session()
        for path, name in PAGES.items():
            with self.subTest(page=path):
                response = session.get(path)
                self.assertEqual(response.status, 200)
                html = response.body.decode()
                self.assertNotIn("hyperflo:nav", html)
                self.assertEqual(html.count('class="sidebar"'), 1)
                self.assertIn(f'href="{path}" class="nav-link active"', html)
                self.assertIn("data-logout", html)

    def test_referenced_assets_exist(self):
        session = shared_session()
        for path in PAGES:
            html = session.get(path).body.decode()
            for asset in re.findall(r'(?:src|href)="(/static/[^"]+)"', html):
                with self.subTest(page=path, asset=asset):
                    self.assertEqual(session.get(asset).status, 200)

    def test_assets_are_versioned(self):
        # Cloudflare garde /static 4 h en cache navigateur: chaque reference
        # doit porter l'empreinte du fichier.
        session = shared_session()
        for path in list(PAGES) + ["/login"]:
            client = request if path == "/login" else session.get
            html = client(path).body.decode()
            references = re.findall(r'(?:src|href)="(/static/[^"]+)"', html)
            with self.subTest(page=path):
                self.assertTrue(references)
                for reference in references:
                    self.assertRegex(reference, r"\?v=[0-9a-f]{12}$")

    def test_security_headers(self):
        response = shared_session().get("/")
        csp = response.headers.get("content-security-policy", "")
        self.assertIn("script-src 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertEqual(response.headers.get("x-frame-options"), "DENY")
        self.assertEqual(response.headers.get("cache-control"), "no-store")
        self.assertNotIn("server", response.headers)

    def test_login_page_redirects_when_authenticated(self):
        response = shared_session().get("/login")
        self.assertEqual(response.status, 303)
        self.assertEqual(request("/login").status, 200)


class FrontendLintTests(unittest.TestCase):
    """Constructions que la CSP bloquerait sans erreur visible."""

    def test_no_inline_code_in_html(self):
        for page in (ROOT / "pages").glob("*.html"):
            html = page.read_text(encoding="utf-8")
            with self.subTest(page=page.name):
                self.assertIsNone(re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), "script inline")
                self.assertIsNone(re.search(r"<style\b", html), "balise style")
                self.assertIsNone(re.search(r"\son[a-z]+\s*=", html), "gestionnaire inline")
                self.assertIsNone(re.search(r'\sstyle\s*=\s*"', html), "attribut style")
                self.assertNotIn("javascript:", html)

    def test_no_inline_style_or_handlers_in_js_templates(self):
        for script in (ROOT / "static").glob("*.js"):
            code = script.read_text(encoding="utf-8")
            with self.subTest(script=script.name):
                self.assertIsNone(re.search(r'\sstyle\s*=\s*["\']', code), "attribut style dans du HTML genere")
                self.assertIsNone(re.search(r'\son[a-z]+\s*=\s*["\']', code), "gestionnaire inline dans du HTML genere")

    def test_js_element_ids_exist_in_page(self):
        # Un id mal orthographie ferait planter la page sans erreur serveur.
        pattern = re.compile(r'(?:getElementById|setText|setBar)\(\s*"([^"]+)"')
        for page in (ROOT / "pages").glob("*.html"):
            html = page.read_text(encoding="utf-8")
            ids = set(re.findall(r'\bid="([^"]+)"', html))
            script = ROOT / "static" / f"{page.stem}.js"
            if not script.exists():
                continue
            code = script.read_text(encoding="utf-8")
            # ids crees par le script lui-meme (HTML genere ou element.id = ...)
            ids |= set(re.findall(r'\bid\s*=\s*"([^"]+)"', code))
            for element_id in pattern.findall(code):
                with self.subTest(page=page.name, id=element_id):
                    self.assertIn(element_id, ids)

    def test_js_brackets_are_balanced(self):
        # Verification grossiere en l'absence de Node.js: parentheses,
        # crochets et accolades equilibres hors chaines, regex et commentaires.
        for script in (ROOT / "static").glob("*.js"):
            with self.subTest(script=script.name):
                error = check_js_delimiters(script.read_text(encoding="utf-8"))
                self.assertIsNone(error, error)


REGEX_PRECEDERS = set("(,=:[!&|?{};+-*%<>~^")
REGEX_KEYWORDS = {"return", "typeof", "case", "do", "else", "in", "of", "new", "delete", "void", "throw"}
PAIRS = {")": "(", "]": "[", "}": "{"}


def check_js_delimiters(code):
    """Retourne None si les delimiteurs sont equilibres, sinon un message."""
    stack = []          # delimiteurs ouverts; "${" pour une expression de template
    i = 0
    last = ""           # dernier caractere significatif (hors espaces)
    word = ""           # dernier identifiant lu
    line = 1

    def regex_allowed():
        return last == "" or last in REGEX_PRECEDERS or word in REGEX_KEYWORDS

    while i < len(code):
        char = code[i]

        if char == "\n":
            line += 1
        if char.isspace():
            i += 1
            continue

        nxt = code[i + 1] if i + 1 < len(code) else ""

        if char == "/" and nxt == "/":
            end = code.find("\n", i)
            i = len(code) if end < 0 else end
            continue
        if char == "/" and nxt == "*":
            end = code.find("*/", i + 2)
            if end < 0:
                return f"ligne {line}: commentaire non ferme"
            line += code.count("\n", i, end)
            i = end + 2
            continue

        if char in "'\"":
            i += 1
            while i < len(code) and code[i] != char:
                if code[i] == "\n":
                    return f"ligne {line}: chaine non fermee"
                i += 2 if code[i] == "\\" else 1
            last, word = char, ""
            i += 1
            continue

        if char == "`" or (char == "}" and stack and stack[-1] == "${"):
            if char == "}":
                stack.pop()
            i += 1
            while i < len(code):
                if code[i] == "\\":
                    i += 2
                    continue
                if code[i] == "\n":
                    line += 1
                if code[i] == "`":
                    break
                if code[i] == "$" and code[i + 1:i + 2] == "{":
                    stack.append("${")
                    i += 1
                    break
                i += 1
            else:
                return f"ligne {line}: template non ferme"
            last, word = "`", ""
            i += 1
            continue

        if char == "/" and regex_allowed():
            i += 1
            in_class = False
            while i < len(code):
                if code[i] == "\\":
                    i += 2
                    continue
                if code[i] == "\n":
                    return f"ligne {line}: regex non fermee"
                if code[i] == "[":
                    in_class = True
                elif code[i] == "]":
                    in_class = False
                elif code[i] == "/" and not in_class:
                    break
                i += 1
            i += 1
            while i < len(code) and code[i].isalpha():
                i += 1
            last, word = "/", ""
            continue

        if char.isalnum() or char in "_$":
            start = i
            while i < len(code) and (code[i].isalnum() or code[i] in "_$"):
                i += 1
            word = code[start:i]
            last = word[-1]
            continue

        if char in "([{":
            stack.append(char)
        elif char in PAIRS:
            if not stack or stack.pop() != PAIRS[char]:
                return f"ligne {line}: '{char}' inattendu"

        last, word = char, ""
        i += 1

    if stack:
        return f"fin de fichier: {len(stack)} delimiteur(s) non ferme(s)"
    return None

if __name__ == "__main__":
    unittest.main()
