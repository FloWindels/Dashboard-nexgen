import json
import threading
import time
import unittest

from tests.helpers import shared_session


class StatusTests(unittest.TestCase):
    def test_status_shape(self):
        response = shared_session().get("/api/status")
        self.assertEqual(response.status, 200)
        data = response.json()
        for key in ("hostname", "uptime", "cpu", "memory", "network", "disks", "gpu", "docker"):
            self.assertIn(key, data)


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


if __name__ == "__main__":
    unittest.main()
