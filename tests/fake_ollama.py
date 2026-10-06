"""Faux serveur Ollama pour les tests (modeles + chat en streaming)."""

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = json.dumps({"models": [{"name": "fake:latest"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for word in ("Bon", "jour", " !"):
            chunk = {"message": {"role": "assistant", "content": word}, "done": False}
            self.wfile.write((json.dumps(chunk) + "\n").encode())
            self.wfile.flush()
            time.sleep(0.3)
        self.wfile.write(b'{"done":true}\n')


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
