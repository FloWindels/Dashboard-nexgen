import http.client
import json
import os
import socket
import threading
import time
import unittest
import urllib.parse
import urllib.request
import uuid

from tests.helpers import BASE_URL, SESSION_COOKIE, shared_session


def fake_ollama_aborted() -> int:
    url = os.environ["OLLAMA_URL"] + "/_test/aborted"
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read())["aborted"]


def wait_for_aborted(minimum: int, timeout: float = 3.0) -> int:
    deadline = time.time() + timeout
    while True:
        count = fake_ollama_aborted()
        if count >= minimum or time.time() > deadline:
            return count
        time.sleep(0.1)


class StatusTests(unittest.TestCase):
    def test_status_shape(self):
        response = shared_session().get("/api/status")
        self.assertEqual(response.status, 200)
        data = response.json()
        for key in ("hostname", "uptime", "system", "cpu", "memory", "network", "disks", "gpu", "docker"):
            self.assertIn(key, data)

        self.assertIn("os", data["system"])
        self.assertIn("kernel", data["system"])
        self.assertIn("model", data["cpu"])
        self.assertEqual(len(data["cpu"]["load"]), 3)
        for key in ("total", "used", "available", "percent", "swap_total", "swap_used"):
            self.assertIn(key, data["memory"])
        for key in ("received", "sent", "rx_rate", "tx_rate", "interfaces"):
            self.assertIn(key, data["network"])
        for interface in data["network"]["interfaces"]:
            self.assertFalse(interface["name"].startswith(("lo", "veth", "docker", "br-")))
        for disk in data["disks"]:
            for key in ("path", "total", "used", "free", "percent"):
                self.assertIn(key, disk)


class DockerValidationTests(unittest.TestCase):
    def test_invalid_container_name(self):
        response = shared_session().get("/api/docker/-rf/logs")
        self.assertEqual(response.status, 400)

    def test_path_traversal_name(self):
        response = shared_session().post(
            "/api/docker/..%2Fetc/restart",
            headers={"X-Hyperflo-Action": "1"},
        )
        self.assertIn(response.status, (400, 404))

    def test_unknown_action(self):
        response = shared_session().post(
            "/api/docker/foo/kill",
            headers={"X-Hyperflo-Action": "1"},
        )
        self.assertEqual(response.status, 400)

    def test_containers_and_stats_endpoints(self):
        # Dans l'instance de test, sudo est refuse: les deux routes doivent
        # le signaler proprement, sans erreur 500.
        session = shared_session()
        containers = session.get("/api/docker/containers")
        self.assertIn(containers.status, (200, 502))
        stats = session.get("/api/docker/stats")
        self.assertEqual(stats.status, 200)
        self.assertIn("available", stats.json())
        self.assertIn("stats", stats.json())

    def test_action_header_required(self):
        response = shared_session().post("/api/docker/foo/restart")
        self.assertEqual(response.status, 403)


class OllamaTests(unittest.TestCase):
    def test_models(self):
        response = shared_session().get("/api/ollama/models")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.json(), {"models": ["fake:latest"]})

    def test_invalid_model_name(self):
        response = shared_session().post(
            "/api/ollama/chat/stream",
            body={"model": "x; rm", "messages": []},
        )
        self.assertEqual(response.status, 422)

    def test_invalid_role(self):
        response = shared_session().post(
            "/api/ollama/chat/stream",
            body={"model": "fake:latest", "messages": [{"role": "tool", "content": "x"}]},
        )
        self.assertEqual(response.status, 422)

    def test_stream_does_not_block_other_requests(self):
        session = shared_session()
        latencies = []

        def poll():
            for _ in range(3):
                start = time.time()
                session.get("/api/auth/me")
                latencies.append(time.time() - start)
                time.sleep(0.3)

        thread = threading.Thread(target=poll)
        thread.start()
        response = session.post(
            "/api/ollama/chat/stream",
            body={
                "model": "fake:latest",
                "messages": [{"role": "user", "content": "salut"}],
                "web": False,
            },
        )
        thread.join()

        self.assertEqual(response.status, 200)
        lines = [json.loads(line) for line in response.body.splitlines() if line.strip()]
        text = "".join(line.get("message", {}).get("content", "") for line in lines)
        self.assertEqual(text, "Bonjour !")
        self.assertTrue(lines[-1].get("done"))
        self.assertLess(max(latencies), 0.5, latencies)


class OllamaStopTests(unittest.TestCase):
    def _long_body(self, stream_id):
        return {
            "model": "fake:latest",
            "messages": [{"role": "user", "content": "reponse long"}],
            "stream_id": stream_id,
        }

    def test_stop_generation(self):
        session = shared_session()
        stream_id = "test-" + uuid.uuid4().hex[:12]
        before = fake_ollama_aborted()
        result = {}

        def run():
            result["response"] = session.post(
                "/api/ollama/chat/stream", body=self._long_body(stream_id), timeout=30
            )

        start = time.time()
        thread = threading.Thread(target=run)
        thread.start()
        time.sleep(1.0)

        stop = session.post("/api/ollama/chat/stop", body={"stream_id": stream_id})
        self.assertEqual(stop.status, 200)
        self.assertTrue(stop.json()["stopped"])

        thread.join(10)
        # La reponse complete durerait 6 s.
        self.assertLess(time.time() - start, 4)

        lines = [json.loads(line) for line in result["response"].body.splitlines() if line.strip()]
        self.assertEqual(lines[-1], {"done": True, "stopped": True})
        words = [line for line in lines if line.get("message")]
        self.assertLess(len(words), 40)
        # Ollama a bien vu la connexion se fermer (GPU libere).
        self.assertGreater(wait_for_aborted(before + 1), before)

    def test_stop_unknown_stream(self):
        response = shared_session().post(
            "/api/ollama/chat/stop", body={"stream_id": "inconnu-12345678"}
        )
        self.assertEqual(response.status, 200)
        self.assertFalse(response.json()["stopped"])

    def test_invalid_stream_id(self):
        response = shared_session().post(
            "/api/ollama/chat/stop", body={"stream_id": "../x"}
        )
        self.assertEqual(response.status, 422)

    def test_client_disconnect_aborts_ollama(self):
        # Onglet ferme: la connexion du navigateur disparait en plein streaming.
        session = shared_session()
        before = fake_ollama_aborted()
        url = urllib.parse.urlsplit(BASE_URL)
        connection = http.client.HTTPConnection(url.hostname, url.port, timeout=10)
        connection.request(
            "POST",
            "/api/ollama/chat/stream",
            body=json.dumps(self._long_body("test-" + uuid.uuid4().hex[:12])),
            headers={
                "Content-Type": "application/json",
                "Cookie": f"{SESSION_COOKIE}={session.token}",
                "X-Hyperflo-CSRF": session.csrf,
            },
        )
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        response.readline()
        # shutdown(): la reponse garde une reference au socket, close() seul
        # ne fermerait pas vraiment la connexion.
        connection.sock.shutdown(socket.SHUT_RDWR)
        response.close()
        connection.close()

        self.assertGreater(wait_for_aborted(before + 1, timeout=5), before)


if __name__ == "__main__":
    unittest.main()
