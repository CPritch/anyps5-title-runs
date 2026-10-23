"""The client: nothing runs before the walkthrough; a sign-in kept from before is removed; and the source trees a job
builds."""

import tempfile
import unittest
from pathlib import Path

from helpers import INFO, make_config
from history import History, git

from title_runs import client, config as configs, configfile, sources


class Ready(unittest.TestCase):
    def setUp(self):
        self.config = make_config()

    def test_nothing_runs_before_the_walkthrough(self):
        tester = client.Client(self.config, log=lambda *_: None, info=INFO)
        self.assertEqual(tester.ready(), (False, "the first-run walkthrough is not done"))
        tester.finish_onboarding({})
        self.assertEqual(tester.ready(), (True, ""))  # nothing to sign in to
        self.config.titles = {}
        self.assertEqual(tester.ready(), (False, "no titles are set up"))

    def test_a_sign_in_kept_from_before_is_removed(self):
        folder = self.config.state_dir / "client"
        folder.mkdir(parents=True)
        (folder / "github-token.json").write_text('{"login": "CPritch", "access_token": "t"}')
        (folder / "github-token.json.lock").write_text("")
        said = []
        client.Client(self.config, log=said.append, info=INFO)
        self.assertEqual(list(folder.glob("github-token*")), [])
        self.assertEqual(said, ["removed the old GitHub sign-in: the tool reads GitHub without one"])


class OldConfig(unittest.TestCase):
    def test_the_sign_in_and_results_sections_are_read_and_dropped(self):
        path = Path(tempfile.mkdtemp()) / "config.toml"
        path.write_text('[github]\napp = "Iv23new"\n[results]\nurl = ""\napp = "Iv23old"\n[tester]\nname = "CPritch"\nmachine = "box"\n')
        config = configs.load(path)
        configfile.save(config)
        text = path.read_text()
        self.assertNotIn("[github]", text)
        self.assertNotIn("[results]", text)
        self.assertNotIn("name =", text)
        self.assertEqual(configs.load(path).machine, "box")


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
