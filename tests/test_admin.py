import unittest

from admin_api import ERROR, OFFLINE, ONLINE, container_status, systemd_status
from tests.helpers import request, shared_session


class ServicesEndpointTests(unittest.TestCase):
    def test_requires_authentication(self):
        self.assertEqual(request("/api/admin/services").status, 401)

    def test_services_shape(self):
        response = shared_session().get("/api/admin/services")
        self.assertEqual(response.status, 200)
        data = response.json()
        ids = {service["id"] for service in data["services"]}
        self.assertTrue({"hyperflo", "docker", "ollama", "minecraft", "playit", "cloudflared"} <= ids)
        for service in data["services"]:
            self.assertIn(service["state"], {ONLINE, OFFLINE, ERROR})


class AdminActionTests(unittest.TestCase):
    def test_services_list_actions(self):
        services = {s["id"]: s for s in shared_session().get("/api/admin/services").json()["services"]}
        self.assertEqual(services["playit"]["actions"], ["start", "stop", "restart"])
        self.assertEqual(services["cloudflared"]["actions"], ["restart"])
        self.assertEqual(services["ssh"]["actions"], [])
        self.assertEqual(services["docker"]["actions"], [])

    def test_action_requires_header(self):
        response = shared_session().post("/api/admin/services/playit/restart")
        self.assertEqual(response.status, 403)

    def test_refused_service_actions(self):
        session = shared_session()
        for path in ("ssh/restart", "cloudflared/stop", "docker/restart", "playit/kill"):
            with self.subTest(path=path):
                response = session.post(
                    f"/api/admin/services/{path}", headers={"X-Hyperflo-Action": "1"}
                )
                self.assertEqual(response.status, 400)

    def test_refused_log_source(self):
        response = shared_session().get("/api/admin/logs?source=auth&lines=10")
        self.assertEqual(response.status, 400)

    def test_power_requires_header(self):
        response = shared_session().post(
            "/api/admin/power", body={"action": "reboot", "confirm": "x", "totp": "000000"}
        )
        self.assertEqual(response.status, 403)

    def test_power_requires_hostname(self):
        response = shared_session().post(
            "/api/admin/power",
            body={"action": "reboot", "confirm": "mauvais-nom", "totp": "000000"},
            headers={"X-Hyperflo-Action": "1"},
        )
        self.assertEqual(response.status, 400)

    def test_power_requires_totp(self):
        session = shared_session()
        hostname = session.get("/api/admin/services").json()["hostname"]
        response = session.post(
            "/api/admin/power",
            body={"action": "poweroff", "confirm": hostname, "totp": "000000"},
            headers={"X-Hyperflo-Action": "1"},
        )
        self.assertEqual(response.status, 403)
        events = [e["event"] for e in session.get("/api/security/overview").json()["events"]]
        self.assertIn("power_denied", events)

    def test_power_rejects_unknown_action(self):
        response = shared_session().post(
            "/api/admin/power",
            body={"action": "halt", "confirm": "x", "totp": "000000"},
            headers={"X-Hyperflo-Action": "1"},
        )
        self.assertEqual(response.status, 422)


class SystemdStatusTests(unittest.TestCase):
    def test_active(self):
        status = systemd_status(
            {"ActiveState": "active", "SubState": "running", "Result": "success", "ActiveEnterTimestamp": "@100"}
        )
        self.assertEqual(status["state"], ONLINE)
        self.assertEqual(status["since"], 100)

    def test_stopped(self):
        status = systemd_status({"ActiveState": "inactive", "SubState": "dead", "Result": "success"})
        self.assertEqual(status["state"], OFFLINE)

    def test_failed(self):
        self.assertEqual(systemd_status({"ActiveState": "failed", "Result": "exit-code"})["state"], ERROR)
        # Arrete apres un plantage.
        self.assertEqual(systemd_status({"ActiveState": "inactive", "Result": "signal"})["state"], ERROR)

    def test_unknown(self):
        self.assertEqual(systemd_status(None)["state"], ERROR)


class ContainerStatusTests(unittest.TestCase):
    def test_running(self):
        self.assertEqual(container_status({"State": "running", "Status": "Up 2 hours"})["state"], ONLINE)

    def test_healthy_and_unhealthy(self):
        self.assertEqual(container_status({"State": "running", "Status": "Up 1 hour (healthy)"})["state"], ONLINE)
        self.assertEqual(container_status({"State": "running", "Status": "Up 1 hour (unhealthy)"})["state"], ERROR)

    def test_clean_stop_is_offline(self):
        self.assertEqual(container_status({"State": "exited", "Status": "Exited (0) 5 minutes ago"})["state"], OFFLINE)

    def test_crash_is_error(self):
        self.assertEqual(container_status({"State": "exited", "Status": "Exited (137) 3 days ago"})["state"], ERROR)

    def test_missing(self):
        self.assertEqual(container_status(None)["state"], ERROR)


if __name__ == "__main__":
    unittest.main()
