"""The client: nothing runs before the walkthrough and the sign-in; the sign-in (GitHub's device flow, slow_down, a
sign-in kept for another App); and the source trees a job builds."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import INFO, make_config
from history import History, git

from title_runs import auth, client, config as configs, configfile, sources


class Ready(unittest.TestCase):
    def setUp(self):
        self.config = make_config(github_app="Iv1.x")
        self.client = client.Client(self.config, log=lambda *_: None, info=INFO)

    def sign_in(self, client_id="Iv1.x"):
        self.client.flow().store({"login": "CPritch", "access_token": "t", "client_id": client_id})

    def test_nothing_runs_before_the_walkthrough_and_the_sign_in(self):
        self.assertEqual(self.client.ready(), (False, "the first-run walkthrough is not done"))
        self.client.finish_onboarding({})
        self.assertEqual(self.client.ready(), (False, "not signed in"))
        self.assertEqual(self.client.allowed_now(), (False, "not signed in"))
        self.sign_in()
        self.assertEqual(self.client.ready(), (True, ""))

    def test_a_sign_in_through_another_app_is_not_used(self):
        self.sign_in("Iv1.another")
        self.assertIsNone(self.client.tester())
        data = self.client.flow().stored()
        del data["client_id"]  # as round 3 stored them
        self.client.flow().store(data)
        self.assertIsNone(self.client.tester())

    def test_slow_down_lengthens_the_wait(self):
        flow = auth.DeviceFlow("Iv1.x", Path(tempfile.mkdtemp()) / "token.json")
        device = {"device_code": "d", "interval": 5}
        with mock.patch.object(flow, "_post", return_value={"error": "slow_down", "interval": 10}):
            self.assertIsNone(flow.poll(device))
        self.assertEqual(auth.DeviceFlow.interval(device), 11)
        waits = []
        replies = iter([{"error": "slow_down", "interval": 15}, {"error": "authorization_pending"}, {"access_token": "t", "expires_in": 28800}])
        with mock.patch.object(flow, "_post", side_effect=lambda url, fields: next(replies)), \
                mock.patch("title_runs.gh.GitHubRepo.login", return_value="CPritch"):
            self.assertEqual(flow.wait(device, sleep=waits.append)["login"], "CPritch")
        self.assertEqual(waits, [11, 16, 16])  # first wait before the first poll; then GitHub's new interval, plus a second


class TheApp(unittest.TestCase):
    """The App testers sign in with: the tool's own unless [github] app names another; [results] app before 2026-10-23."""

    def test_the_tools_app_unless_the_config_names_one(self):
        path = Path(tempfile.mkdtemp()) / "config.toml"
        path.write_text("")
        self.assertEqual(configs.load(path).github_app, configs.DEFAULT_APP)
        path.write_text('[results]\nurl = ""\napp = "Iv23old"\n')
        self.assertEqual(configs.load(path).github_app, "Iv23old")
        path.write_text('[github]\napp = "Iv23new"\n[results]\napp = "Iv23old"\n')
        config = configs.load(path)
        self.assertEqual(config.github_app, "Iv23new")
        configfile.save(config)
        self.assertNotIn("[results]", path.read_text())
        self.assertEqual(configs.load(path).github_app, "Iv23new")


class Sources(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.history = History(self.root)
        self.clone = self.root / "clone"
        git(self.root, "clone", "-q", str(self.history.dir), str(self.clone))

    def test_a_submodule_added_after_the_clone_was_made(self):
        """Upstream adds a submodule; the tester's clone has no checkout of it. The job clones its own bare copy from the
        url in .gitmodules (relative to the project's remote) and fills the worktree from that."""
        lib = self.root / "vgmstream"
        git(self.root, "init", "-q", "-b", "main", str(lib))
        (lib / "lib.c").write_text("int vgm;\n")
        git(lib, "add", "-A")
        git(lib, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "lib")
        pin = git(lib, "rev-parse", "HEAD")
        upstream = self.history.dir
        git(upstream, "-c", "protocol.file.allow=always", "-c", "user.name=t", "-c", "user.email=t@t", "submodule", "add", "-q", "../vgmstream",
            "3rdparty/vgmstream")
        git(upstream, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "add vgmstream")
        main = git(upstream, "rev-parse", "HEAD")
        base = sources.fetch_pinned(self.clone, str(upstream), main, main)
        tree = self.root / "tree"
        sources.worktree(self.clone, tree, base)
        self.assertFalse((self.clone / "3rdparty" / "vgmstream").exists())
        pins = sources.submodules(self.clone, tree, base, str(upstream))
        self.assertEqual(pins, {"3rdparty/vgmstream": pin})
        self.assertEqual((tree / "3rdparty" / "vgmstream" / "lib.c").read_text(), "int vgm;\n")

    def test_a_head_merged_onto_main_the_same_on_every_machine(self):
        h = self.history
        main = sources.fetch_head(self.clone, "origin", h.A)
        self.assertEqual(main, h.m2)
        merges = []
        for name in ("one", "two"):
            tree = sources.worktree(self.clone, self.root / name, main)
            merges.append(sources.merge_onto(tree, main, h.A))
        self.assertEqual(merges[0], merges[1])
        self.assertEqual(git(self.root / "one", "rev-parse", "HEAD^2"), h.A)

    def test_a_conflict_is_reported(self):
        h = self.history
        main = sources.fetch_head(self.clone, "origin", h.D)
        tree = sources.worktree(self.clone, self.root / "c", main)
        with self.assertRaises(sources.SourceError) as raised:
            sources.merge_onto(tree, main, h.D)
        self.assertIn("conflicts in core/c.cpp", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
