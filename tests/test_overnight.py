"""Tonight's list (overnight.py): heads of the listed pull requests and of the listed people's, each tested once, only
when the author pushed it; main pinned for the night; the result kept here with a draft comment and a summary; Stop
puts the head back on the list. Nothing is posted: GitHub is only read."""

import datetime
import types
import unittest
from unittest import mock

import helpers  # noqa: F401
from helpers import make_config
from test_client import INFO, fake_results

from title_runs import client, formats, overnight

A, B = "a" * 40, "b" * 40


def pull(number, head, author="Celegans12", state="open", title="perf(agc): a change"):
    return {"number": number, "title": title, "author": author, "head": head, "head_ref": "x", "state": state, "labels": []}


class List(unittest.TestCase):
    def setUp(self):
        self.config = make_config(machine="laptop", overnight_repository="boykopovar/AnyPS5", overnight_prs=[8104, 9289], overnight_authors=[])
        self.night = overnight.Overnight(self.config, log=lambda *_: None)
        self.heads = {8104: pull(8104, A), 9289: pull(9289, B, author="Celegans12")}
        self.pushers = {A: "Celegans12", B: "somebody-else"}

    def github(self):
        repo = mock.Mock()
        repo.repository = "boykopovar/AnyPS5"
        repo.pull.side_effect = lambda n: self.heads[n]
        repo.workflow_runs.side_effect = lambda head_sha=None: ([{"event": "pull_request", "actor": self.pushers[head_sha], "created_at": "x"}]
                                                                  if self.pushers.get(head_sha) else [])
        repo.pages.return_value = []
        return mock.patch("title_runs.gh.GitHubRepo", return_value=repo)

    def test_only_heads_their_authors_pushed(self):
        with self.github():
            self.night.refresh("token")
        entries = {e["pr"]: e for e in self.night.read()["entries"]}
        self.assertEqual(entries[8104]["status"], "queued")
        self.assertEqual((entries[9289]["status"], entries[9289]["reason"]), ("skipped", "pushed by somebody-else, not the author"))

    def test_a_new_head_replaces_the_queued_one_and_a_tested_head_is_not_added_again(self):
        with self.github():
            self.night.refresh("token")
            self.heads[8104] = pull(8104, "c" * 40)
            self.pushers["c" * 40] = "Celegans12"
            self.night.refresh("token")
            self.night.refresh("token")
        heads = [(e["head"][:1], e["status"]) for e in self.night.read()["entries"] if e["pr"] == 8104]
        self.assertEqual(heads, [("a", "replaced"), ("c", "queued")])

    def test_the_listed_peoples_open_prs(self):
        self.config.overnight_prs, self.config.overnight_authors = [], ["celegans12"]
        with self.github() as github:
            github.return_value.pages.return_value = [{"number": 8104, "user": {"login": "Celegans12"}, "draft": False},
                                                      {"number": 1, "user": {"login": "someone"}, "draft": False},
                                                      {"number": 9289, "user": {"login": "Celegans12"}, "draft": True}]
            self.night.refresh("token")
        self.assertEqual([e["pr"] for e in self.night.read()["entries"]], [8104])

    def test_main_is_pinned_for_the_night(self):
        now = formats.parse_time("2026-10-22T00:30:00Z")
        with mock.patch("title_runs.sources.main_tip", side_effect=["1" * 40, "2" * 40]):
            self.assertEqual(self.night.pin(now), "1" * 40)
            self.assertEqual(self.night.pin(now + datetime.timedelta(hours=5)), "1" * 40)
            self.assertEqual(self.night.pin(now + datetime.timedelta(hours=13)), "2" * 40)  # the next night


class Run(unittest.TestCase):
    def setUp(self):
        self.config = make_config(machine="laptop", overnight_repository="boykopovar/AnyPS5", overnight_prs=[8104])
        self.night = overnight.Overnight(self.config, log=lambda *_: None)
        self.night.write({"repository": "boykopovar/AnyPS5", "pinned": {"main": "d" * 40, "at": formats.iso(formats.now()), "night": "2026-10-21"},
                          "entries": [{"pr": 8104, "head": A, "title": "perf(agc): stage", "author": "Celegans12", "added": "x", "status": "queued"}]})
        status = client.Status(self.config.state_dir / "client" / "status.json")
        self.client = types.SimpleNamespace(status=status, config=self.config, tester=lambda: "CPritch",
                                            machine_class=formats.machine_class(INFO["gpu"], INFO["os"], INFO["driver"]))

    def test_the_result_stays_here_with_a_draft_and_a_summary(self):
        with mock.patch("title_runs.job.run", return_value=fake_results(8104, A)) as run:
            self.night.run(self.night.queued()[0], self.client)
        kwargs = run.call_args.kwargs
        self.assertEqual((kwargs["remote"], kwargs["main"]), ("https://github.com/boykopovar/AnyPS5.git", "d" * 40))
        entry = self.night.read()["entries"][0]
        self.assertEqual(entry["status"], "done")
        self.assertTrue(entry["verdict"].startswith("No difference ("))
        draft = (self.config.state_dir / "overnight" / "drafts" / f"8104-{A[:12]}.md").read_text()
        self.assertIn("merged onto main `ddddddddd`", draft)
        self.assertNotIn("@", draft)  # a draft mentions nobody
        summary = (self.config.state_dir / "overnight" / "2026-10-21.md").read_text()
        self.assertIn("#8104 `aaaaaaaaa` perf(agc): stage (Celegans12): No difference", summary)
        self.assertTrue(self.client.status.read()["recent"][0]["local"])

    def test_stop_puts_the_head_back_on_the_list(self):
        def stopped(*args, **kwargs):
            self.client.status.update(stop_requested=True)
            return fake_results(8104, A, status="superseded")
        with mock.patch("title_runs.job.run", side_effect=stopped):
            self.assertIsNone(self.night.run(self.night.queued()[0], self.client))
        self.assertEqual(self.night.read()["entries"][0]["status"], "queued")


if __name__ == "__main__":
    unittest.main()
