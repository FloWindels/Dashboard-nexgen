import unittest

from docker_api import normalize_container, normalize_stats


class DockerParsingTests(unittest.TestCase):
    def test_normalize_container(self):
        raw = {
            "ID": "0123456789abcdef",
            "Names": "minecraft",
            "Image": "itzg/minecraft-server",
            "State": "running",
            "Status": "Up 2 hours",
            "Ports": "127.0.0.1:25565->25565/tcp, 127.0.0.1:25575->25575/tcp",
        }
        container = normalize_container(raw)
        self.assertEqual(container["id"], "0123456789ab")
        self.assertEqual(container["name"], "minecraft")
        self.assertEqual(
            container["ports"],
            ["127.0.0.1:25565->25565/tcp", "127.0.0.1:25575->25575/tcp"],
        )

    def test_normalize_container_without_ports(self):
        self.assertEqual(normalize_container({"Names": "x", "Ports": ""})["ports"], [])

    def test_normalize_stats(self):
        raw = {
            "Name": "ollama",
            "CPUPerc": "12.34%",
            "MemUsage": "1.5GiB / 15.02GiB",
            "MemPerc": "9.99%",
            "NetIO": "1kB / 2kB",
            "BlockIO": "0B / 0B",
            "PIDs": "17",
        }
        stats = normalize_stats(raw)
        self.assertAlmostEqual(stats["cpu_percent"], 12.34)
        self.assertAlmostEqual(stats["mem_percent"], 9.99)
        self.assertEqual(stats["mem_usage"], "1.5GiB / 15.02GiB")

    def test_invalid_percent(self):
        self.assertIsNone(normalize_stats({"Name": "x", "CPUPerc": "--"})["cpu_percent"])


if __name__ == "__main__":
    unittest.main()
