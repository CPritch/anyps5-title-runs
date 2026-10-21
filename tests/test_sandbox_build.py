"""Builds in the build sandbox: a small project compiles; a build that reaches for the network fails inside and works
outside. The network is a loopback HTTP server outside the sandbox, which the sandbox's own network namespace cannot
reach."""

import functools
import http.server
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

import helpers  # noqa: F401

from title_runs import build

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@unittest.skipUnless(shutil.which("bwrap") and shutil.which("cmake") and shutil.which("ninja"), "needs bwrap, cmake and ninja")
class SandboxedBuild(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_a_project_compiles_inside(self):
        result = build.build(FIXTURES / "hello", self.dir / "build", ["-G", "Ninja"], self.dir / "log", "0" * 40, "bwrap")
        self.assertEqual(result["sandbox"], "bwrap")
        self.assertEqual(subprocess.run([self.dir / "build" / "hello"], capture_output=True, text=True).stdout.strip(), "built in the sandbox")

    def test_the_source_is_read_only_inside(self):
        plan = [["sh", "-c", f"touch {FIXTURES / 'hello' / 'written'}"]]
        with self.assertRaises(build.BuildError):
            build.build(FIXTURES / "hello", self.dir / "build", [], self.dir / "log", "0" * 40, "bwrap", plan=plan)
        self.assertFalse((FIXTURES / "hello" / "written").exists())

    def test_the_network_is_off_inside(self):
        served = self.dir / "served"
        served.mkdir()
        (served / "file").write_text("from the network\n")
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(served)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_address[1]}/file"
        try:
            outside = build.build(FIXTURES / "netbuild", self.dir / "outside", [f"-DURL={url}"], self.dir / "outside.log", "0" * 40, "none",
                                  plan=[["cmake", "-S", str(FIXTURES / "netbuild"), "-B", str(self.dir / "outside"), f"-DURL={url}"]])
            self.assertEqual(outside["sandbox"], "none")
            self.assertIn("downloaded", (self.dir / "outside.log").read_text())
            with self.assertRaises(build.BuildError) as raised:
                build.build(FIXTURES / "netbuild", self.dir / "inside", [f"-DURL={url}"], self.dir / "inside.log", "0" * 40, "bwrap",
                            plan=[["cmake", "-S", str(FIXTURES / "netbuild"), "-B", str(self.dir / "inside"), f"-DURL={url}"]])
            self.assertIn("failed", str(raised.exception))
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()


class GameDisplay(unittest.TestCase):
    """The app embeds the game only as an X11 window: with TITLE_RUNS_GAME_DISPLAY=x11 the game gets SDL's X11 driver
    and no Wayland socket; otherwise its native display, as every run before."""

    def test_x11_when_the_app_embeds(self):
        import os
        from unittest import mock
        from title_runs import protocol, sandbox
        p = object.__new__(protocol.Protocol)
        p.title = mock.Mock(env={})
        side = mock.Mock(run_env={}, work=__import__("pathlib").Path("/w"), cache_dir=__import__("pathlib").Path("/c"))
        base = {"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-1", "XDG_RUNTIME_DIR": "/run/user/1000", "XDG_SESSION_TYPE": "wayland"}
        with mock.patch.dict(os.environ, base, clear=False):
            os.environ.pop("TITLE_RUNS_GAME_DISPLAY", None)
            native = p.environment(side, None, {})
            self.assertEqual((native.get("WAYLAND_DISPLAY"), native.get("SDL_VIDEODRIVER")), ("wayland-1", None))
            os.environ["TITLE_RUNS_GAME_DISPLAY"] = "x11"
            embedded = p.environment(side, None, {})
            self.assertEqual((embedded.get("WAYLAND_DISPLAY"), embedded["SDL_VIDEODRIVER"], embedded["DISPLAY"]), (None, "x11", ":0"))
            with mock.patch("os.path.exists", return_value=True):
                self.assertFalse(any("wayland" in b for b in sandbox.display_binds()))
