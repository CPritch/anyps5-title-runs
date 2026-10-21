"""The client against the stand-in (a bare results repository with its publish hook, the fake AnyPS5), with job.run
replaced by a fake that records what it was asked to build and calls the client's last check before "building"."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import make_config
from relay_helpers import History, git

from title_runs import client, formats, sources, standin

INFO = {"gpu": "NVIDIA GeForce RTX 5060 Laptop GPU", "driver": "NVIDIA 615.71.09", "os": "Linux 7.2.8"}


def fake_results(pr, head, status="done"):
    return {"pr": pr, "head": head, "started": "2026-10-21T12:00:00+00:00", "finished": "2026-10-21T12:50:00+00:00", "status": status,
            "sandbox": "bwrap", "base": "d" * 40, "merge": "e" * 40,
            "titles": {"PPSA04263": {"name": "Grand Theft Auto V", "version": "01.010.002", "scene": "the bank",
                                     "outcome": {"A": "rendering", "B": "rendering"},
                                     "verdict": {"verdict": "no difference beyond the spread", "diff": -0.3, "diff_pct": -0.4, "spread": 0.4, "gpu_diff": 0.1,
                                                 "sides": {"A": {"p50": [78.2, 77.9], "p90": [87.6, 89.1], "p99": [108.9, 114.4], "gpu": [63.0, 62.6]},
                                                           "B": {"p50": [77.9, 77.5], "p90": [87.9, 88.0], "p99": [109.5, 105.9], "gpu": [63.0, 62.7]}}},
                                     "ab": {"runs": [{"run": f"r{i}", "side": s, "counts": True, "summary": {"gpu": INFO["gpu"], "driver": INFO["driver"],
                                                                                                         "os": INFO["os"], "frame_ms": {"p50": 78}}}
                                                     for i, s in enumerate("ABAB")]}}}}


class Setup(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.history = History(self.root)
        self.stand = standin.create(self.root / "standin", ["CPritch"], self.history.dir, self.history.m2,
                                    [{"number": 8104, "title": "perf(agc): stage", "author": "Celegans12", "head": self.history.A, "head_ref": "perf/staging"}],
                                    {"CPritch": "admin", "Celegans12": "read"})
        for name in ("B", "R"):
            git(self.stand.anyps5_git, "update-ref", f"refs/heads/keep-{name}", getattr(self.history, name))
        self.config = make_config(results_url=str(self.stand.results_git), results_github=self.stand.endpoint, machine="box",
                                  repo_dir=self.history.dir, remote=str(self.stand.anyps5_git))
        self.client = client.Client(self.config, log=lambda *_: None, info=INFO)
        self.built = []

    def onboard(self, approve=True):
        self.client.repo.sync()
        self.client.finish_onboarding({"idle": "hours"})
        flow = self.client.flow()
        device = flow.start()
        self.assertIsNone(flow.poll(device))
        self.stand.authorize(device["user_code"], "CPritch")
        self.assertEqual(flow.poll(device)["login"], "CPritch")
        issue = self.client.register()
        self.stand.tick()
        if approve:
            self.stand.approve(issue, "CPritch")
            self.stand.tick()
        self.client.repo.sync()
        return issue

    def fake_run(self, before_build=None):
        def run(config, state_dir, pr, head, log, recheck=None, progress=None, should_stop=None):
            if before_build:
                before_build()
            stop = recheck() if recheck else None
            if stop:
                return {"pr": pr, "head": head, "started": "2026-10-21T12:00:00+00:00", "status": "superseded", "detail": stop, "titles": {}}
            self.built.append(head)
            return fake_results(pr, head)
        return mock.patch("title_runs.job.run", side_effect=run)

    def bodies(self):
        return [p.read_text() for p in sorted((self.stand.root / "outbox").glob("*.md")) if "-title-runs-devbot-" in p.name]


class Ready(Setup):
    def test_nothing_runs_before_the_walkthrough_sign_in_and_approval(self):
        self.client.repo.sync()
        self.assertEqual(self.client.ready(), (False, "the first-run walkthrough is not done"))
        self.client.finish_onboarding({})
        self.assertEqual(self.client.ready(), (False, "not signed in"))
        with self.assertRaises(client.NotReady):
            self.client.run(8104, self.history.A)
        self.onboard(approve=False)
        self.assertEqual(self.client.ready(), (False, "waiting for a maintainer to approve this machine"))
        self.assertEqual(self.client.registration()[0], "pending")
        with mock.patch.object(client.Client, "allowed_now", wraps=self.client.allowed_now):
            self.assertEqual(self.client.run_next(), "waiting for a maintainer to approve this machine")

    def test_ready_once_approved(self):
        self.onboard()
        self.assertEqual(self.client.ready(), (True, ""))
        self.assertEqual(self.client.registration()[0], "approved")

    def test_a_testers_writes_reach_the_outbox(self):
        self.onboard()
        self.assertTrue(list((self.stand.root / "outbox").glob("*-CPritch-create-issue.json")))


class Switching(Setup):
    """One setting switches the results repository (DESIGN.md, round 4 decision 1): the checkout and the registration
    are the new repository's, and the sign-in is kept only when it names the same App."""

    def other(self, name, client_id):
        return standin.create(self.root / name, ["maintainer2"], self.history.dir, self.history.m2,
                              [{"number": 8104, "title": "perf(agc): stage", "author": "Celegans12", "head": self.history.A, "head_ref": "perf/staging"}],
                              {"maintainer2": "admin"}, client_id=client_id, results=f"maintainer2/{name}")

    def test_the_same_app_keeps_the_sign_in_and_needs_a_new_registration(self):
        self.onboard()
        other = self.other("results-same-app", "Iv1.standin")
        self.client.use(str(other.results_git), github=other.endpoint)
        self.assertEqual(self.client.results_repository(), "maintainer2/results-same-app")
        self.assertEqual(self.client.tester(), "CPritch")  # the same App: still signed in
        self.assertEqual(self.client.registration()[0], "not registered")
        self.assertEqual(self.client.ready(), (False, "this machine is not registered"))
        self.client.register()
        other.tick()
        self.client.repo.sync()
        self.assertEqual(self.client.registration()[0], "pending")
        self.assertIn("CPritch/box", self.client.repo.registry()["pending"])

    def test_another_app_needs_a_new_sign_in(self):
        self.onboard()
        self.assertEqual(self.client.tester(), "CPritch")
        other = self.other("results-moved", "Iv1.maintainers-app")
        self.client.use(str(other.results_git), github=self.stand.endpoint)  # the same GitHub, another App
        self.assertIsNone(self.client.tester())
        self.assertEqual(self.client.ready(), (False, "not signed in"))

    def test_a_repository_that_cannot_be_read_changes_nothing(self):
        self.onboard()
        before = (self.config.results_url, self.client.results_repository())
        with self.assertRaises(Exception):
            self.client.use(str(self.root / "no-such-repository.git"))
        self.assertEqual((self.config.results_url, self.client.results_repository()), before)
        self.assertEqual(self.client.ready(), (True, ""))

    def test_a_sign_in_that_names_no_app_is_not_used(self):
        self.onboard()
        flow = self.client.flow()
        data = flow.stored()
        del data["client_id"]  # as round 3 stored them
        flow.store(data)
        self.assertIsNone(self.client.tester())

    def test_a_hostname_registers_and_a_bad_name_is_refused_before_github(self):
        self.client.repo.sync()
        self.client.finish_onboarding({})
        flow = self.client.flow()
        device = flow.start()
        self.stand.authorize(device["user_code"], "CPritch")
        flow.poll(device)
        self.config.machine = "Legion5a laptop"
        with self.assertRaises(ValueError):
            self.client.register()
        self.assertEqual(self.client.registration()[0], "not registered")
        self.config.machine = "Legion5a-Laptop"
        self.client.register()
        self.stand.tick()
        self.client.repo.sync()
        self.assertIn("CPritch/Legion5a-Laptop", self.client.repo.registry()["pending"])

    def test_slow_down_lengthens_the_wait(self):
        from unittest import mock
        from title_runs import auth
        flow = auth.DeviceFlow("Iv1.x", self.root / "token.json")
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

    def test_owner_name_is_the_github_url(self):
        from title_runs import config as configs
        for text in ("CPritch/anyps5-title-runs-results", "https://github.com/CPritch/anyps5-title-runs-results",
                     "https://github.com/CPritch/anyps5-title-runs-results.git", " CPritch/anyps5-title-runs-results/ "):
            self.assertEqual(configs.results_location(text), "https://github.com/CPritch/anyps5-title-runs-results.git")
        self.assertEqual(configs.results_location("/home/x/standin/results.git"), "/home/x/standin/results.git")


class PushAfterLabel(Setup):
    def test_a_labelled_pr_is_run_and_reported(self):
        self.onboard()
        self.stand.label(8104, "CPritch")
        self.stand.tick()
        with self.fake_run(), mock.patch.object(client.Client, "allowed_now", return_value=(True, "")):
            self.assertEqual(self.client.run_next(), f"ran {formats.job_id(8104, self.history.A)}")
        self.stand.tick()
        self.assertEqual(self.built, [self.history.A])
        self.client.repo.sync()
        self.assertEqual(list(self.client.repo.results()), [formats.job_id(8104, self.history.A)])
        self.assertIn("| box |", self.bodies()[-1])

    def test_the_push_after_the_label_is_not_built(self):
        self.onboard()
        self.stand.label(8104, "CPritch")
        self.stand.tick()
        self.stand.push(8104, self.history.B, "Celegans12")
        self.stand.tick()
        with self.fake_run(), mock.patch.object(client.Client, "allowed_now", return_value=(True, "")):
            self.assertEqual(self.client.run_next(), "nothing to do")
        self.assertEqual(self.built, [])
        self.assertIn(f"**Approval of `{self.history.A[:9]}` expired**", self.bodies()[-1])
        self.assertNotIn("title-test", self.stand.github().as_(standin.ANYPS5, identity="x").pull(8104)["labels"])

    def test_approval_moving_on_just_before_the_build_stops_the_job(self):
        self.onboard()
        self.stand.label(8104, "CPritch")
        self.stand.tick()

        def push_and_tick():
            self.stand.push(8104, self.history.B, "Celegans12")
            self.stand.tick()

        with self.fake_run(before_build=push_and_tick):
            self.assertIsNone(self.client.run(8104, self.history.A))
        self.assertEqual(self.built, [])
        issue = self.client.repo.jobs()[formats.job_id(8104, self.history.A)]["issue"]
        kinds = [formats.payload(c["body"])[0] for c in self.stand.github().as_(standin.RESULTS, identity="x").comments(issue=issue)]
        self.assertEqual(kinds[:2], ["claim", None] if kinds[1] is None else ["claim", "withdraw"])
        self.assertIn("withdraw", kinds)

    def test_a_claim_by_another_machine_of_the_class_comes_first(self):
        self.onboard()
        self.stand.label(8104, "CPritch")
        self.stand.tick()
        self.client.repo.sync()
        issue = self.client.repo.queue()["entries"][0]["issue"]
        rival = formats.make_claim(formats.job_id(8104, self.history.A), "desk", "someone", self.client.machine_class, {"PPSA04263"}, head=self.history.A)
        self.stand.github().as_(standin.RESULTS, "someone").create_comment(issue, formats.payload_body("claim", rival, "desk claims it."))
        with self.fake_run(), self.assertRaises(RuntimeError) as raised:
            self.client.run(8104, self.history.A)
        self.assertIn("desk", str(raised.exception))
        self.assertEqual(self.built, [])


    def test_a_machine_that_reported_does_not_block_its_class(self):
        self.onboard()
        self.stand.label(8104, "CPritch")
        self.stand.tick()
        self.client.repo.sync()
        issue = self.client.repo.queue()["entries"][0]["issue"]
        job_id = formats.job_id(8104, self.history.A)
        rival = formats.make_claim(job_id, "desk", "someone", self.client.machine_class, {"PPSA04263"}, head=self.history.A)
        github = self.stand.github().as_(standin.RESULTS, "someone")
        github.create_comment(issue, formats.payload_body("claim", rival, "desk claims it."))
        github.create_comment(issue, formats.payload_body("result", {"job": job_id, "machine": "desk"}, "desk: done."))
        with self.fake_run():
            self.assertIsNotNone(self.client.run(8104, self.history.A))
        self.assertEqual(self.built, [self.history.A])


class TesterTrust(Setup):
    def test_unchecked_head_needs_the_tester_trust_and_is_marked(self):
        self.onboard()
        with self.fake_run(), self.assertRaises(RuntimeError):
            self.client.run(8104, self.history.A, "tester", author="Celegans12")
        self.client.trust.grant("head", "Celegans12", 8104, self.history.A)
        self.client.status.update(job={"author": "Celegans12"})
        with self.fake_run():
            data = self.client.run(8104, self.history.A, "tester", author="Celegans12")
        self.assertEqual(data["trust"], "tester")
        self.stand.tick()
        self.assertIn("**Run on the tester's trust**", self.bodies()[-1])


class Sources(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.history = History(self.root)
        self.clone = self.root / "clone"
        git(self.root, "clone", "-q", str(self.history.dir), str(self.clone))

    def test_approved_head_merged_onto_main_the_same_on_every_machine(self):
        h = self.history
        main = sources.fetch_approved(self.clone, "origin", h.A)
        self.assertEqual(main, h.m2)
        merges = []
        for name in ("one", "two"):
            tree = sources.worktree(self.clone, self.root / name, main)
            merges.append(sources.merge_onto(tree, main, h.A))
        self.assertEqual(merges[0], merges[1])
        self.assertEqual(git(self.root / "one", "rev-parse", "HEAD^2"), h.A)

    def test_a_conflict_is_reported(self):
        h = self.history
        main = sources.fetch_approved(self.clone, "origin", h.D)
        tree = sources.worktree(self.clone, self.root / "c", main)
        with self.assertRaises(sources.SourceError) as raised:
            sources.merge_onto(tree, main, h.D)
        self.assertIn("conflicts in core/c.cpp", str(raised.exception))


class Trust(unittest.TestCase):
    def test_scopes_and_revoke(self):
        from title_runs import trust
        store = trust.TrustStore(Path(tempfile.mkdtemp()) / "trust.json")
        at = formats.parse_time("2026-10-21T12:00:00Z")
        store.grant("head", "alice", 1, "a" * 40, at)
        store.grant("pr", "bob", 2, "b" * 40, at)
        store.grant("author", "carol", 3, "c" * 40, at)
        self.assertTrue(store.allows(1, "alice", "a" * 40, at))
        self.assertIsNone(store.allows(1, "alice", "f" * 40, at))
        self.assertTrue(store.allows(2, "bob", "f" * 40, at))
        self.assertIsNone(store.allows(5, "bob", "f" * 40, at))
        self.assertTrue(store.allows(9, "carol", "f" * 40, formats.parse_time("2026-11-19T12:00:00Z")))
        self.assertIsNone(store.allows(9, "carol", "f" * 40, formats.parse_time("2026-11-21T12:00:00Z")))
        store.revoke(0)
        self.assertIsNone(trust.TrustStore(store.path).allows(1, "alice", "a" * 40, at))


if __name__ == "__main__":
    unittest.main()


class BusyCheckout(Setup):
    def test_a_lock_held_by_another_process_is_waited_for(self):
        import threading
        self.client.repo.sync()
        lock = self.client.repo.dir / ".git" / "index.lock"
        lock.write_text("")
        threading.Timer(1.0, lock.unlink).start()  # another git finishes a second later
        self.client.repo.sync()  # resets the index: would fail on the lock
        self.assertFalse(lock.exists())
