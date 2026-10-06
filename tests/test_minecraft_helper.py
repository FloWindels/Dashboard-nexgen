"""Tests des scripts sudo Minecraft/Docker, avec de faux docker et systemctl.

Une copie du script est lancee avec les chemins /usr/bin/docker,
/usr/bin/systemctl et /usr/bin/logger remplaces par des faux qui notent leurs
appels: le vrai conteneur et le vrai playit.service ne sont jamais touches.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SBIN = ROOT / "deploy" / "sbin"

FAKE_DOCKER = """#!/bin/sh
echo "docker $*" >> "$STATE/calls"
case "$1" in
  inspect)
    [ -f "$STATE/running" ] && echo true || echo false ;;
  start|restart)
    [ -f "$STATE/fail_docker" ] && { echo "erreur docker" >&2; exit 1; }
    touch "$STATE/running" ;;
  stop)
    [ -f "$STATE/fail_docker" ] && { echo "erreur docker" >&2; exit 1; }
    rm -f "$STATE/running" ;;
esac
"""

FAKE_SYSTEMCTL = """#!/bin/sh
echo "systemctl $*" >> "$STATE/calls"
case "$1" in
  is-active)
    [ -f "$STATE/playit" ] ;;
  start|restart)
    touch "$STATE/playit" ;;
  stop)
    rm -f "$STATE/playit" ;;
esac
"""

FAKE_LOGGER = "#!/bin/sh\nexit 0\n"

FAKE_JOURNALCTL = """#!/bin/sh
echo "journalctl $*" >> "$STATE/calls"
echo "ligne de log"
"""

# Faux script Minecraft (appele par hyperflo-power).
FAKE_MINECRAFT_ACTION = """#!/bin/sh
echo "minecraft-action $*" >> "$STATE/calls"
[ -f "$STATE/fail_minecraft" ] && { echo "erreur minecraft" >&2; exit 1; }
rm -f "$STATE/running"
"""


class HelperSandbox:
    def __init__(self, script_name):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.state = self.dir / "state"
        self.state.mkdir()
        (self.state / "calls").touch()

        fakes = {
            "/usr/bin/docker": FAKE_DOCKER,
            "/usr/bin/systemctl": FAKE_SYSTEMCTL,
            "/usr/bin/logger": FAKE_LOGGER,
            "/usr/bin/journalctl": FAKE_JOURNALCTL,
            "/usr/local/sbin/hyperflo-minecraft-action": FAKE_MINECRAFT_ACTION,
        }
        code = (SBIN / script_name).read_text()
        for real_path, content in fakes.items():
            path = self.dir / Path(real_path).name
            path.write_text(content)
            path.chmod(0o755)
            code = code.replace(real_path, str(path))
        self.script = self.dir / script_name
        self.script.write_text(code)

    def set(self, name, enabled=True):
        path = self.state / name
        if enabled:
            path.touch()
        else:
            path.unlink(missing_ok=True)

    def has(self, name):
        return (self.state / name).exists()

    def run(self, *args):
        result = subprocess.run(
            [sys.executable, "-I", str(self.script), *args],
            capture_output=True,
            text=True,
            env={"STATE": str(self.state), "PATH": "/usr/bin:/bin"},
            timeout=30,
        )
        calls = (self.state / "calls").read_text().splitlines()
        # Les lectures d'etat (inspect / is-active) ne changent rien.
        actions = [c for c in calls if " inspect " not in c and " is-active " not in c]
        return result, actions

    def close(self):
        self.tmp.cleanup()


class MinecraftHelperTests(unittest.TestCase):
    def setUp(self):
        self.box = HelperSandbox("hyperflo-minecraft-action")

    def tearDown(self):
        self.box.close()

    def test_start_starts_playit_then_container(self):
        result, actions = self.box.run("start")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(actions, ["systemctl start playit.service", "docker start minecraft"])

    def test_start_keeps_running_playit(self):
        self.box.set("playit")
        result, actions = self.box.run("start")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(actions, ["docker start minecraft"])

    def test_failed_start_stops_playit_again(self):
        self.box.set("fail_docker")
        result, actions = self.box.run("start")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            actions,
            ["systemctl start playit.service", "docker start minecraft", "systemctl stop playit.service"],
        )
        self.assertFalse(self.box.has("playit"))

    def test_stop_waits_for_save_then_stops_playit(self):
        self.box.set("running")
        self.box.set("playit")
        result, actions = self.box.run("stop")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(actions, ["docker stop --time 90 minecraft", "systemctl stop playit.service"])

    def test_failed_stop_keeps_playit(self):
        self.box.set("running")
        self.box.set("playit")
        self.box.set("fail_docker")
        result, actions = self.box.run("stop")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(actions, ["docker stop --time 90 minecraft"])
        self.assertTrue(self.box.has("playit"))

    def test_restart(self):
        self.box.set("running")
        self.box.set("playit")
        result, actions = self.box.run("restart")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(actions, ["docker restart --time 90 minecraft", "systemctl restart playit.service"])

    def test_restart_when_stopped_starts_container(self):
        result, actions = self.box.run("restart")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(actions, ["docker start minecraft", "systemctl restart playit.service"])

    def test_rejects_other_arguments(self):
        for args in ([], ["kill"], ["start", "other"], ["stop; rm -rf /"]):
            with self.subTest(args=args):
                result, actions = self.box.run(*args)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(actions, [])


class DockerActionHelperTests(unittest.TestCase):
    def test_minecraft_is_refused(self):
        box = HelperSandbox("hyperflo-docker-action")
        try:
            result, actions = box.run("stop", "minecraft")
            self.assertEqual(result.returncode, 1)
            self.assertIn("hyperflo-minecraft-action", result.stderr)
            self.assertEqual(actions, [])
        finally:
            box.close()


class ServiceActionHelperTests(unittest.TestCase):
    def setUp(self):
        self.box = HelperSandbox("hyperflo-service-action")

    def tearDown(self):
        self.box.close()

    def test_allowed_actions(self):
        cases = {
            ("start", "playit"): "systemctl start playit.service",
            ("stop", "playit"): "systemctl stop playit.service",
            ("restart", "playit"): "systemctl restart playit.service",
            # Coupent le dashboard: lances sans attendre.
            ("restart", "cloudflared"): "systemctl --no-block restart cloudflared.service",
            ("restart", "hyperflo"): "systemctl --no-block restart hyperflo-control.service",
        }
        for args, expected in cases.items():
            with self.subTest(args=args):
                (self.box.state / "calls").write_text("")
                result, actions = self.box.run(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(actions, [expected])

    def test_refused_actions(self):
        for args in (
            ["stop", "cloudflared"],
            ["stop", "hyperflo"],
            ["restart", "ssh"],
            ["restart", "docker"],
            ["restart", "playit.service"],
            ["kill", "playit"],
            ["restart"],
            ["restart", "playit", "extra"],
        ):
            with self.subTest(args=args):
                result, actions = self.box.run(*args)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(actions, [])


class ServiceLogsHelperTests(unittest.TestCase):
    def setUp(self):
        self.box = HelperSandbox("hyperflo-service-logs")

    def tearDown(self):
        self.box.close()

    def test_reads_allowed_unit(self):
        result, actions = self.box.run("hyperflo", "50")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            actions,
            ["journalctl --unit hyperflo-control.service --lines 50 --no-pager --output short-iso"],
        )
        self.assertIn("ligne de log", result.stdout)

    def test_lines_are_capped(self):
        _, actions = self.box.run("ssh", "999999")
        self.assertIn("--lines 1000", actions[0])

    def test_refused_sources(self):
        for args in (["sudo", "10"], ["../etc", "10"], ["hyperflo", "abc"], ["hyperflo"]):
            with self.subTest(args=args):
                result, actions = self.box.run(*args)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(actions, [])


class PowerHelperTests(unittest.TestCase):
    def setUp(self):
        self.box = HelperSandbox("hyperflo-power")

    def tearDown(self):
        self.box.close()

    def test_stops_minecraft_cleanly_before_reboot(self):
        self.box.set("running")
        result, actions = self.box.run("reboot")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(actions, ["minecraft-action stop", "systemctl reboot"])

    def test_poweroff_without_minecraft_running(self):
        result, actions = self.box.run("poweroff")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(actions, ["systemctl poweroff"])

    def test_aborts_if_minecraft_cannot_stop(self):
        self.box.set("running")
        self.box.set("fail_minecraft")
        result, actions = self.box.run("reboot")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(actions, ["minecraft-action stop"])

    def test_refused_arguments(self):
        for args in ([], ["halt"], ["reboot", "now"]):
            with self.subTest(args=args):
                result, actions = self.box.run(*args)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(actions, [])


if __name__ == "__main__":
    unittest.main()
