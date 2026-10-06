"""Faux serveur Ollama pour les tests (modeles + chat en streaming).

- Un message contenant "long" produit une longue reponse (pour tester Stop).
- GET /_test/aborted renvoie le nombre de generations interrompues par le
  client (connexion fermee pendant le streaming).
"""

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

aborted = 0
aborted_lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    # Comme le vrai Ollama: HTTP/1.1, reponse en "chunked", keep-alive.
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _chunk(self, data: bytes):
        self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
        self.wfile.flush()

    def _json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/_test/aborted":
            self._json({"aborted": aborted})
        else:
            self._json({"models": [{"name": "fake:latest"}]})

    def do_POST(self):
        global aborted
        payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        long_answer = any("long" in message.get("content", "") for message in payload["messages"])
        words = [f"mot{index} " for index in range(40)] if long_answer else ["Bon", "jour", " !"]

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        try:
            for word in words:
                chunk = {"message": {"role": "assistant", "content": word}, "done": False}
                self._chunk((json.dumps(chunk) + "\n").encode())
                time.sleep(0.3 if not long_answer else 0.15)
            self._chunk(b'{"done":true}\n')
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            with aborted_lock:
                aborted += 1


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
