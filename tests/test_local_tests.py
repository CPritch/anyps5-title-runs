"""Local tests (local_tests.py): heads of the listed pull requests and of the listed people's, each tested once, only
when the author pushed it; main pinned for the night; the result kept here with a draft comment and a summary; Stop
puts the head back on the list. Nothing is posted: GitHub is only read."""

import contextlib
import datetime
import json
import re
import types
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401
from helpers import INFO, fake_results, make_config

from title_runs import client, config as configs, configfile, formats, job, local_tests, verdict

A, B = "a" * 40, "b" * 40


def pull(number, head, author="Celegans12", state="open", title="perf(agc): a change"):
    return {"number": number, "title": title, "author": author, "head": head, "head_ref": "x", "state": state, "labels": []}


def github(heads, pushers, people=()):
    """GitHub as local tests read it: the heads from git (sources.pull_heads), and the API (gh.GitHubRepo) for a pull
    request, who pushed a head, and a person's open pull requests (people). Returns the patch and the fake API."""
    repo = mock.Mock()
    repo.repository = "boykopovar/AnyPS5"
    repo.pull.side_effect = lambda n: dict(heads[n])
    repo.workflow_runs.side_effect = lambda head_sha=None: ([{"event": "pull_request", "actor": pushers[head_sha], "created_at": "x"}]
                                                              if pushers.get(head_sha) else [])
    repo.open_pulls_by.side_effect = lambda login: [p for p in people if p["author"].lower() == login.lower()]
    patches = contextlib.ExitStack()
    patches.enter_context(mock.patch("title_runs.gh.GitHubRepo", return_value=repo))
    patches.enter_context(mock.patch("title_runs.sources.pull_heads", side_effect=lambda remote: {n: p["head"] for n, p in heads.items()}))
    return patches, repo


class List(unittest.TestCase):
    def setUp(self):
        self.config = make_config(machine="laptop", local_repository="boykopovar/AnyPS5", local_prs=[8104, 9289], local_people=[])
        self.night = local_tests.LocalTests(self.config, log=lambda *_: None)
        self.heads = {8104: pull(8104, A), 9289: pull(9289, B, author="Celegans12")}
        self.pushers = {A: "Celegans12", B: "somebody-else"}

    def github(self, people=()):
        patches, self.repo = github(self.heads, self.pushers, people)
        return patches

    def test_only_heads_their_authors_pushed(self):
        with self.github():
            self.night.refresh()
        entries = {e["pr"]: e for e in self.night.read()["entries"]}
        self.assertEqual(entries[8104]["status"], "queued")
        self.assertEqual((entries[9289]["status"], entries[9289]["reason"]), ("skipped", "somebody-else pushed this commit, not the author"))

    def test_a_new_head_replaces_the_queued_one_and_a_tested_head_is_not_added_again(self):
        with self.github():
            self.night.refresh()
            self.heads[8104] = pull(8104, "c" * 40)
            self.pushers["c" * 40] = "Celegans12"
            self.night.refresh()
            self.night.refresh()
        heads = [(e["head"][:1], e["status"]) for e in self.night.read()["entries"] if e["pr"] == 8104]
        self.assertEqual(heads, [("a", "replaced"), ("c", "queued")])

    def test_the_listed_peoples_open_prs(self):
        self.config.local_prs, self.config.local_people = [], ["celegans12"]
        people = [{"number": 8104, "author": "Celegans12", "draft": False}, {"number": 9289, "author": "Celegans12", "draft": True}]
        with self.github(people):
            self.night.refresh()
        self.assertEqual([e["pr"] for e in self.night.read()["entries"]], [8104])

    def test_the_api_is_asked_only_what_git_cant_tell(self):
        now = formats.parse_time("2026-10-23T20:00:00Z")
        with self.github():
            self.night.refresh(now)
            self.assertEqual((self.repo.pull.call_count, self.repo.workflow_runs.call_count), (2, 2))  # two new heads
            self.night.refresh(now + datetime.timedelta(minutes=15))
            self.assertEqual((self.repo.pull.call_count, self.repo.workflow_runs.call_count), (2, 2))  # nothing moved: git only
            self.heads[8104] = pull(8104, "c" * 40)
            self.pushers["c" * 40] = "Celegans12"
            self.night.refresh(now + datetime.timedelta(minutes=30))
            self.assertEqual((self.repo.pull.call_count, self.repo.workflow_runs.call_count), (3, 3))  # 8104's new head
            self.heads[9289] = pull(9289, B, author="Celegans12", state="closed")
            self.night.refresh(now + datetime.timedelta(hours=7))  # every 6 hours: did it close?
            self.assertEqual(self.repo.pull.call_count, 5)
        self.assertEqual(self.night.read()["prs"]["9289"]["state"], "closed")

    def test_a_used_up_limit_is_waited_out(self):
        from title_runs import engine, gh
        reset = formats.now() + datetime.timedelta(minutes=20)
        tester = engine.Engine(self.config)
        with self.github():
            self.repo.pull.side_effect = gh.RateLimited("used up", reset)
            tester.refresh_local(force=True)
            self.assertEqual(tester.github_wait, reset)
            self.assertIn("GitHub's hourly limit is used up", tester.local_notice())
            calls = self.repo.pull.call_count
            tester.refresh_local(force=True)  # not before the reset
            self.assertEqual(self.repo.pull.call_count, calls)

    def test_the_list_and_results_of_tonights_list_move_to_local_tests(self):
        (self.config.state_dir / "client").mkdir(parents=True, exist_ok=True)
        (self.config.state_dir / "client" / "overnight.json").write_text('{"repository": "boykopovar/AnyPS5", "entries": [{"pr": 1}]}')
        (self.config.state_dir / "overnight" / "drafts").mkdir(parents=True)
        moved = local_tests.LocalTests(self.config, log=lambda *_: None)
        self.assertEqual(moved.read()["entries"], [{"pr": 1}])
        self.assertTrue((self.config.state_dir / "local-tests" / "drafts").is_dir())

    def test_a_config_with_the_old_section_name_still_reads(self):
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        path = self.config.state_dir / "old.toml"
        path.write_text(f'state_dir = "{self.config.state_dir}"\n[overnight]\nrepository = "boykopovar/AnyPS5"\nprs = [8104]\nauthors = ["Celegans12"]\n')
        old = configs.load(path)
        self.assertEqual((old.local_repository, old.local_prs, old.local_people), ("boykopovar/AnyPS5", [8104], ["Celegans12"]))
        self.assertEqual(configfile.config_data(old)["local"], {"repository": "boykopovar/AnyPS5", "prs": [8104], "people": ["Celegans12"], "fixes": []})

    def test_main_is_pinned_for_the_night(self):
        now = formats.parse_time("2026-10-22T00:30:00Z")
        with mock.patch("title_runs.sources.main_tip", side_effect=["1" * 40, "2" * 40]):
            self.assertEqual(self.night.pin(now), "1" * 40)
            self.assertEqual(self.night.pin(now + datetime.timedelta(hours=5)), "1" * 40)
            self.assertEqual(self.night.pin(now + datetime.timedelta(hours=13)), "2" * 40)  # the next night


class GitHubLimit(unittest.TestCase):
    """GitHub's answer when its limit is used up: a 403 or 429 with no requests left (until X-RateLimit-Reset) or with
    Retry-After; any other 403 is just an error."""

    def error(self, code, headers):
        import urllib.error
        return urllib.error.HTTPError("https://api.github.com/x", code, "", headers, None)

    def test_used_up_until_the_reset(self):
        from title_runs import gh
        now = formats.parse_time("2026-10-23T20:00:00Z")
        limited = gh.limited(self.error(403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int(now.timestamp()) + 1200)}), now)
        self.assertEqual(limited.reset, now + datetime.timedelta(minutes=20))
        self.assertEqual(gh.limited(self.error(429, {"Retry-After": "60"}), now).reset, now + datetime.timedelta(minutes=1))
        self.assertIsNone(gh.limited(self.error(403, {"X-RateLimit-Remaining": "12"}), now))
        self.assertIsNone(gh.limited(self.error(404, {}), now))


class Run(unittest.TestCase):
    def setUp(self):
        self.config = make_config(machine="laptop", local_repository="boykopovar/AnyPS5", local_prs=[8104])
        self.night = local_tests.LocalTests(self.config, log=lambda *_: None)
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
        self.assertRegex(entry["verdict"], r"^main \d+\.\d fps, PR \d+\.\d fps: no difference \([+-]\d+\.\d\d ms a frame, ")
        job = self.config.state_dir / "jobs" / entry["job"]
        job.mkdir(parents=True)
        (job / "results.json").write_text(json.dumps(fake_results(8104, A)))
        self.assertEqual(self.night.words({**entry, "verdict": "No difference (+0.13 ms, +0.2 %)"}), entry["verdict"])  # rebuilt
        self.assertEqual(self.night.words({**entry, "head": "b" * 40, "verdict": "kept"}), "kept")  # another head's results
        draft = (self.config.state_dir / "local-tests" / "drafts" / f"8104-{A[:12]}.md").read_text()
        self.assertTrue(draft.startswith("Ran this on Grand Theft Auto V (PPSA04263 01.010.002), Linux 7.2.8, NVIDIA GeForce RTX 5060 Laptop GPU"))
        self.assertIn("main ddddddddd against main + #8104 at aaaaaaaaa, same machine and session, two runs each in the order A B A B.", draft)
        self.assertNotIn("@", draft)  # a report mentions nobody
        summary = (self.config.state_dir / "local-tests" / "2026-10-21.md").read_text()
        self.assertIn("#8104 `aaaaaaaaa` perf(agc): stage (Celegans12): main ", summary)
        self.assertTrue(self.client.status.read()["recent"][0]["local"])

    def test_the_result_names_the_jobs_own_folder(self):
        results = dict(fake_results(8104, A), job=f"8104-{A[:12]}-franklins-house")  # a job in a scenario has its own folder
        with mock.patch("title_runs.job.run", return_value=results):
            self.night.run(self.night.queued()[0], self.client)
        self.assertEqual(self.night.read()["entries"][0]["job"], f"8104-{A[:12]}-franklins-house")

    def test_test_again_keeps_the_earlier_result(self):
        def run(config, state_dir, pr, head, log, **kwargs):  # job.run's folder and results, with the PR faster the second time
            folder = job.job_folder(Path(state_dir) / "jobs", f"{pr}-{head[:12]}")
            results = dict(fake_results(pr, head), job=folder.name)
            for one in results["titles"]["PPSA04263"]["ab"]["runs"]:
                one["summary"]["frame_ms"]["p50"] = 74 if one["side"] == "B" and folder.name.endswith("-2") else 78
            (folder / "results.json").write_text(json.dumps(results))
            return results
        with mock.patch("title_runs.job.run", side_effect=run), mock.patch("title_runs.sources.main_tip", return_value="d" * 40), \
                mock.patch("title_runs.sources.carry", return_value=("d" * 40, [], [])):
            self.night.run(self.night.queued()[0], self.client)
            self.night.again(8104)
            self.night.run(self.night.queued()[0], self.client)
        done = [e for e in self.night.read()["entries"] if e["status"] == "done"]
        self.assertEqual([e["job"] for e in done], [f"8104-{A[:12]}", f"8104-{A[:12]}-2"])
        self.assertEqual([Path(e["draft"]).name for e in done], [f"8104-{A[:12]}.md", f"8104-{A[:12]}-2.md"])
        first, second = (self.night.report(e) for e in done)
        self.assertIn("with #8104 78.0, 78.0 ms", first)  # the first test's own numbers, not the second's
        self.assertIn("with #8104 74.0, 74.0 ms", second)

    def test_a_job_folder_per_finished_test(self):
        import tempfile
        jobs = Path(tempfile.mkdtemp())
        first = job.job_folder(jobs, "4287-7aea3fe29ff7-prologue")
        self.assertEqual(first, jobs / "4287-7aea3fe29ff7-prologue")
        self.assertEqual(job.job_folder(jobs, "4287-7aea3fe29ff7-prologue"), first)  # nothing finished in it: used again
        (first / "results.json").write_text("{}")
        self.assertEqual(job.job_folder(jobs, "4287-7aea3fe29ff7-prologue"), jobs / "4287-7aea3fe29ff7-prologue-2")

    def crashed(self, side):
        runs = self.config.state_dir / "runs" / "PPSA04263"
        (runs / f"{side}-warm").mkdir(parents=True)
        (runs / f"{side}-warm" / "game.log").write_text("[libc] unhandled exception 'St11logic_error'\n"
                                                          "  what():  sceVoiceSetThreadsParams: worker priority and affinity are not implemented\n")
        results = fake_results(8104, A)
        title = results["titles"]["PPSA04263"]
        title.update(ab={"warm": {side: {"run": f"{side}-warm", "reached": False}}, "runs": [], "error": f"side {side}: the warm-up did not reach the scene"},
                     runs_dir=str(runs))
        title["verdict"] = {"verdict": "not enough counted runs"}
        return results

    def test_a_main_that_crashes_the_game_pauses_the_night(self):
        with mock.patch("title_runs.job.run", return_value=self.crashed("A")):
            self.assertIsNone(self.night.run(self.night.queued()[0], self.client))
        data = self.night.read()
        self.assertEqual(data["entries"][0]["status"], "queued")  # not this change's fault
        self.assertEqual(data["paused"]["reason"], "main ddddddddd doesn't start the game: sceVoiceSetThreadsParams: worker priority and affinity are not implemented")
        self.assertEqual(self.night.held()["main"], "d" * 40)
        self.assertNotIn("paused_until", self.client.status.read())
        self.assertIn("**Paused**", (self.config.state_dir / "local-tests" / "2026-10-21.md").read_text())
        with mock.patch("title_runs.sources.main_tip", return_value="e" * 40):
            self.assertIsNotNone(self.night.held(formats.now() + datetime.timedelta(hours=11)))
            self.assertIsNone(self.night.held(formats.now() + datetime.timedelta(hours=13)))  # a new pin is due: try again
            self.night.unpin()
            self.assertIsNone(self.night.held())
            self.assertEqual(self.night.pin(), "e" * 40)

    def test_a_change_that_crashes_the_game_is_failed_with_the_crash(self):
        with mock.patch("title_runs.job.run", return_value=self.crashed("B")):
            self.night.run(self.night.queued()[0], self.client)
        entry = self.night.read()["entries"][0]
        self.assertEqual(entry["status"], "failed")
        self.assertEqual(entry["verdict"], "the change doesn't start the game: sceVoiceSetThreadsParams: worker priority and affinity are not implemented")

    def test_stop_puts_the_head_back_on_the_list(self):
        def stopped(*args, **kwargs):
            self.client.status.update(stop_requested=True)
            return fake_results(8104, A, status="superseded")
        with mock.patch("title_runs.job.run", side_effect=stopped):
            self.assertIsNone(self.night.run(self.night.queued()[0], self.client))
        self.assertEqual(self.night.read()["entries"][0]["status"], "queued")


def summary(commit, p50, p99, gpu):
    return {"commit": commit, "dirty": False, "env": {"APS5_PAD_INPUT_FILE": "<path>", "APS5_TRACE_EVENTS": "4194304", "APS5_TRACE_FRAMES": "3300:700"},
            "gpu": "NVIDIA GeForce RTX 5060 Laptop GPU", "driver": "NVIDIA 615.71.09", "os": "Linux 7.2.8-zen1-2-zen", "title_id": "PPSA04263",
            "title": "Grand Theft Auto V", "content_version": "01.010.002", "window": {"spec": "frames 3300:700", "first_present": 3300},
            "frame_ms": {"p50": p50, "p99": p99}, "gpu_busy_ms_per_present": gpu}


class Report(unittest.TestCase):
    """The report is the form of the project's performance reports, from the numbers of the #4287 run of 2026-10-22."""

    def results(self, runs_dir):
        runs = [("A1", "A", summary("c49fa17ee046", 79.112, 104.717, 62.912)), ("B1", "B", summary("08a87661ab9a", 73.822, 107.245, 58.883)),
                ("A2", "A", summary("c49fa17ee046", 79.046, 113.019, 62.574)), ("B2", "B", summary("08a87661ab9a", 74.042, 113.053, 58.572))]
        quiet = "quiet: yes, no pipeline phase in the last 6 summaries"
        self.warm = {"A": {"warm": "already"}, "B": {"quiet": quiet}}  # main warmed by an earlier test of the same build
        return {"pr": 4287, "head": "7aea3fe29ff7b0c4240363ab722e12265439bb1f", "base": "c" * 40,
                "titles": {"PPSA04263": {"name": "Grand Theft Auto V", "version": "01.010.002", "scene": "Story Mode, Resume Story: the loaded scene (the bank)",
                                         "runs_dir": str(runs_dir),
                                         "ab": {"warm": self.warm,
                                                "runs": [{"run": run, "side": side, "counts": True, "summary": data,
                                                          "capture": "capture: frames 3300:700; counts; no pipeline builds"} for run, side, data in runs]}}}}

    def two_scenarios(self):
        """The game in two scenarios, each with its own runs folder and traces."""
        one, other = self.results(self.traces([19_000_000] * 4))["titles"]["PPSA04263"], self.results(self.traces([18_000_000] * 4))["titles"]["PPSA04263"]
        one.update(title_id="PPSA04263", scenario="bank-scene", scenario_name="Bank Scene", input="with input recorded from a controller")
        other.update(title_id="PPSA04263", scenario="window", scenario_name="Walk to window", scene="Franklin's house", input="with a set 7 s of input")
        results = self.results(self.traces([1] * 4))
        results["titles"] = {"PPSA04263 bank-scene": one, "PPSA04263 window": other}
        return results

    def test_one_report_for_a_game_in_two_scenarios(self):
        text = local_tests.report_text(self.two_scenarios(), {"pr": 4287, "head": "7" * 40, "main": "4" * 40})
        lines = text.splitlines()
        self.assertEqual(sum(line.startswith("Ran this on ") for line in lines), 1)  # the machine once
        self.assertIn(", in 2 scenarios: main 444444444 against main + #4287 at 777777777, same machine and session, in each scenario "
                      "two runs a side in the order A B A B.", lines[0])
        sections = [line.split("**")[1] for line in lines if re.match(r"^\*\*[^*]+\*\*: ", line)]
        self.assertEqual(sections, ["Bank Scene", "Walk to window"])
        self.assertEqual(sum(line.startswith("Frame p50: ") for line in lines), 2)
        self.assertEqual(sum(line == "Summary lines (main, then with #4287):" for line in lines), 2)
        self.assertEqual((lines.count("Not tested: other scenes, other GPUs."), lines.count(local_tests.TOOL_LINE)), (1, 1))
        self.assertEqual(lines[-1], local_tests.TOOL_LINE)
        names = [f["name"] for f in local_tests.attachments(self.two_scenarios())]
        self.assertEqual(names[0], "aps5-trace-c49fa17ee046-3-PPSA04263-bank-scene-main-1.json.gz")
        self.assertEqual(len(set(names)), 8)  # a trace per run of each scenario, none named twice
        self.assertIn("<details><summary>Digest, Walk to window, with #4287, run 2 (python3 tools/trace_digest.py)</summary>", lines)

    def test_the_results_key_of_a_game_in_several_scenarios(self):
        house, bank = {"id": "franklins-house"}, {"id": "bank-scene"}
        self.assertEqual(job.results_key("PPSA04263", house, [house]), "PPSA04263")
        self.assertEqual(job.results_key("PPSA04263", bank, [house, bank]), "PPSA04263 bank-scene")
        self.assertEqual(job.results_key("PPSA01325", None, [None]), "PPSA01325")

    def test_the_result_line_names_each_scenario(self):
        results = self.two_scenarios()
        for entry in results["titles"].values():
            entry["verdict"] = {"sides": {"A": {"p50": [79.1, 79.0]}, "B": {"p50": [73.8, 74.0]}}}
        words = local_tests.summary_words(local_tests.result_of(dict(results, status="done")), verdict.DEFAULT)
        self.assertRegex(words, r"^Bank Scene: main 12\.7 fps, PR 13\.5 fps: faster .*; Walk to window: main 12\.7 fps, PR 13\.5 fps: faster ")

    def test_main_with_a_fix_on_both_sides(self):
        import tempfile
        runs_dir = Path(tempfile.mkdtemp())
        (runs_dir / "A1").mkdir()
        (runs_dir / "A1" / "aps5-summary.jsonl").write_text('{"early": 1}\n{"commit":"c49fa17ee046","window":{"ms":56318.040},"log":"/home/someone/aps5.log"}\n')
        entry = {"pr": 4287, "head": "7aea3fe29ff7b0c4240363ab722e12265439bb1f", "main": "4777caca343bf09a3fe245830acd9e9f433e8e18",
                 "fixes": [{"pr": 9730, "head": "ed8a900caf92bbc7f5de356d1cdd727361b184d8"}]}
        text = local_tests.report_text(self.results(runs_dir), entry, {"PPSA04263": "Performance"})
        lines = text.splitlines()
        self.assertEqual(lines[0], "Ran this on Grand Theft Auto V (PPSA04263 01.010.002), Linux 7.2.8-zen1-2-zen, NVIDIA GeForce RTX 5060 Laptop GPU, "
                                   "NVIDIA 615.71.09, Graphics Mode Performance, Story Mode, Resume Story: the loaded scene (the bank), with no input.")
        self.assertEqual(lines[1], "main 4777caca3 + #9730 at ed8a900ca, against that + #4287 at 7aea3fe29 (#9730 on both sides), same machine and session, "
                                   "two runs each in the order A B A B, window frames 3300:700, APS5_TRACE_EVENTS=4194304. "
                                   "Each side was warmed until it stopped building pipelines, and no timed run built one.")
        self.assertEqual(lines[3], "Frame p50: main 79.1, 79.0 ms, with #4287 73.8, 74.0 ms (-5.1 ms, -6.5 %). GPU busy per present: 62.9, 62.6 -> 58.9, 58.6 ms.")
        self.assertEqual(lines[4], "p99: main 104.7, 113.0 ms, with #4287 107.2, 113.1 ms.")
        self.assertIn("Summary lines (main + #9730 at ed8a900ca, then with #4287):", lines)
        # the run's own line, as AnyPS5 wrote it (56318.040), without the local path; the others as the job read them
        self.assertIn('{"commit":"c49fa17ee046","window":{"ms":56318.040},"log":"<path>"}', lines)
        self.assertEqual(sum(1 for line in lines if line.startswith("{")), 4)
        self.assertNotIn("@", text)

    def traces(self, sizes):
        """A runs folder with each run's trace (sparse, of the given size) and digest, as the protocol leaves them."""
        import tempfile
        runs_dir = Path(tempfile.mkdtemp())
        for (run, commit), size in zip((("A1", "c49fa17ee046"), ("B1", "08a87661ab9a"), ("A2", "c49fa17ee046"), ("B2", "08a87661ab9a")), sizes):
            (runs_dir / run).mkdir()
            with open(runs_dir / run / f"aps5-trace-{commit}-3.json.gz", "wb") as trace:
                trace.truncate(size)
            (runs_dir / run / "digest.txt").write_text(f"**frames 3300:380** of {run}\n")
        return runs_dir

    def test_the_traces_to_attach_named_by_run(self):
        files = local_tests.attachments(self.results(self.traces([19_400_000, 19_100_000, 26_000_000, 19_000_000])))
        self.assertEqual([f["name"] for f in files], ["aps5-trace-c49fa17ee046-3-PPSA04263-main-1.json.gz", "aps5-trace-c49fa17ee046-3-PPSA04263-main-2.json.gz",
                                                     "aps5-trace-08a87661ab9a-3-PPSA04263-pr-1.json.gz", "aps5-trace-08a87661ab9a-3-PPSA04263-pr-2.json.gz"])
        self.assertEqual([f["words"] for f in files], ["main, run 1", "main, run 2", "with #4287, run 1", "with #4287, run 2"])
        self.assertEqual([f["fits"] for f in files], [True, False, True, True])  # main's second trace is over GitHub's 25 MB

    def test_the_report_has_the_traces_and_their_digests(self):
        text = local_tests.report_text(self.results(self.traces([19_400_000, 19_100_000, 26_000_000, 19_000_000])), {"pr": 4287, "head": "7" * 40, "main": "4" * 40})
        lines = text.splitlines()
        at = lines.index("Traces, one per run in the order of the summary lines (AnyPS5's file names with the title and the run added):")
        self.assertLess(lines.index("Summary lines (main, then with #4287):"), at)
        self.assertEqual(lines[at + 1], "")  # where the tester drops the files
        self.assertEqual(lines[at + 2], "Not attached, as it is over GitHub's 25 MB for a file: main, run 2 (26.0 MB).")
        summaries = [line for line in lines if line.startswith("<details><summary>Digest, ")]
        self.assertEqual(summaries, [f"<details><summary>Digest, {words} (python3 tools/trace_digest.py)</summary>"
                                     for words in ("main, run 1", "main, run 2", "with #4287, run 1", "with #4287, run 2")])
        self.assertEqual(lines[lines.index(summaries[2]) + 2], "**frames 3300:380** of B1")

    def test_traces_none_of_which_can_be_attached(self):
        text = local_tests.report_text(self.results(self.traces([35_600_000, 34_100_000, 35_300_000, 34_800_000])), {"pr": 4287, "head": "7" * 40, "main": "4" * 40})
        self.assertNotIn("Traces, one per run", text)
        self.assertIn("Traces: not attached, as each is over GitHub's 25 MB for a file: main, run 1 (35.6 MB); main, run 2 (35.3 MB); "
                      "with #4287, run 1 (34.1 MB); with #4287, run 2 (34.8 MB).", text.splitlines())

    def test_a_report_too_long_for_a_comment_leaves_the_digests_out(self):
        runs_dir = self.traces([19_000_000] * 4)
        for run in ("A1", "B1", "A2", "B2"):
            (runs_dir / run / "digest.txt").write_text("x" * 17000)
        text = local_tests.report_text(self.results(runs_dir), {"pr": 4287, "head": "7" * 40, "main": "4" * 40})
        self.assertLess(len(text), local_tests.COMMENT_LIMIT)
        self.assertNotIn("<details><summary>Digest", text)
        self.assertIn("The digests are left out because with them this comment would be over GitHub's limit of 65,536 characters.", text)

    def test_the_files_to_drag_are_linked_into_one_folder(self):
        import tempfile
        config = make_config(machine="laptop", local_repository="boykopovar/AnyPS5")
        config.state_dir = Path(tempfile.mkdtemp())
        results = self.results(self.traces([19_400_000, 19_100_000, 26_000_000, 19_000_000]))
        job_dir = config.state_dir / "jobs" / "4287-7aea3fe29ff7-prologue"
        job_dir.mkdir(parents=True)
        (job_dir / "results.json").write_text(json.dumps(results))
        local = local_tests.LocalTests(config, log=lambda *_: None)
        folder, files = local.attach({"pr": 4287, "head": results["head"], "job": "4287-7aea3fe29ff7-prologue"})
        self.assertEqual(folder, config.state_dir / "local-tests" / "attach" / "4287-7aea3fe29ff7-prologue")
        self.assertEqual(sorted(p.name for p in folder.iterdir()), sorted(f["name"] for f in files if f["fits"]))
        self.assertEqual(folder.joinpath(files[0]["name"]).stat().st_ino, files[0]["path"].stat().st_ino)  # a link, not a copy
        self.assertNotIn("file", files[1])  # over the limit: listed, not in the folder
        self.assertEqual(local.attach({"pr": 4287, "head": "0" * 40, "job": "4287-7aea3fe29ff7-prologue"})[1], [])  # another head's job

    def test_a_change_that_does_not_start_the_game(self):
        results = self.results("/nowhere")
        title = results["titles"]["PPSA04263"]
        title["ab"] = {"runs": [], "error": "side B: the warm-up did not reach the scene"}
        text = local_tests.report_text(results, {"pr": 4287, "head": "7" * 40, "main": "4" * 40})
        self.assertIn("main 444444444 starts the game; with #4287 at 777777777 merged onto it, the game doesn't reach the scene:", text)


class Carry(unittest.TestCase):
    """Fixes merged onto main for both sides, in a real repository: the same base from the same heads, a fix main has
    left out, a conflict refused."""

    def setUp(self):
        import subprocess
        import tempfile
        self.repo = Path(tempfile.mkdtemp())

        def git(*args):
            return subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, text=True, check=True,
                                  env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
                                       "PATH": "/usr/bin:/bin", "HOME": str(self.repo)}).stdout.strip()
        self.git = git
        git("init", "-q", "-b", "main")
        (self.repo / "voice.cpp").write_text("throw\n")
        (self.repo / "other.cpp").write_text("a\n")
        git("add", "."), git("commit", "-q", "-m", "m1")
        self.m1 = git("rev-parse", "HEAD")
        git("switch", "-q", "-c", "fix")
        (self.repo / "voice.cpp").write_text("return 0\n")
        git("commit", "-qam", "fix(voice)")
        self.fix = git("rev-parse", "HEAD")
        git("switch", "-q", "-c", "clash", self.m1)
        (self.repo / "other.cpp").write_text("b\n")
        git("commit", "-qam", "clash")
        self.clash = git("rev-parse", "HEAD")
        git("switch", "-q", "main")
        (self.repo / "other.cpp").write_text("c\n")
        git("commit", "-qam", "m2")
        self.main = git("rev-parse", "HEAD")

    def test_carry(self):
        from title_runs import sources
        base, carried, in_main = sources.carry(self.repo, "unused", self.main, [(9730, self.fix), (1, self.m1)])
        self.assertEqual((carried, in_main), ([{"pr": 9730, "head": self.fix}], [1]))
        self.assertEqual(self.git("show", f"{base}:voice.cpp"), "return 0")
        self.assertEqual(self.git("rev-list", "--parents", "-n", "1", base).split()[1:], [self.main, self.fix])
        self.assertEqual(sources.carry(self.repo, "unused", self.main, [(9730, self.fix)])[0], base)  # the same base again
        self.assertEqual(sources.carry(self.repo, "unused", self.main, []), (self.main, [], []))
        with self.assertRaisesRegex(sources.SourceError, "#5 .* does not merge onto main"):
            sources.carry(self.repo, "unused", self.main, [(5, self.clash)])


class Page(unittest.TestCase):
    """What the Local tests page does: add by number or link, remove (a followed person's PR stays off), test again,
    mark posted; a result not posted goes stale; a fix pushed by someone else holds local tests."""

    def setUp(self):
        self.config = make_config(machine="laptop", local_repository="boykopovar/AnyPS5", local_prs=[8104], local_people=["Celegans12"])
        self.local = local_tests.LocalTests(self.config, log=lambda *_: None)
        self.heads = {8104: pull(8104, A), 9289: pull(9289, B), 9730: pull(9730, "f" * 40, author="dantdmdarealguy", title="fix(voice)")}
        self.pushers = {A: "Celegans12", B: "Celegans12", "f" * 40: "dantdmdarealguy"}

    def refresh(self):
        patches, _ = github(self.heads, self.pushers, [{"number": 9289, "author": "Celegans12", "draft": False}])
        with patches:
            self.local.refresh()

    def test_parse(self):
        self.assertEqual(self.local.parse("#8104"), (8104, ""))
        self.assertEqual(self.local.parse(" 8104 "), (8104, ""))
        self.assertEqual(self.local.parse("https://github.com/boykopovar/AnyPS5/pull/8104/files"), (8104, ""))
        self.assertIsNone(self.local.parse("https://github.com/someone/else/pull/1")[0])
        self.assertIsNone(self.local.parse("the voice one")[0])

    def test_remove_again_and_posted(self):
        self.refresh()
        self.assertEqual(sorted(e["pr"] for e in self.local.queued()), [8104, 9289])
        self.local.remove(9289)
        self.refresh()
        self.assertEqual([e["pr"] for e in self.local.queued()], [8104])  # the followed person's PR stays off
        self.local.added(9289)
        self.assertEqual(self.local.read()["removed"], [])

        def done(data):
            for e in data["entries"]:
                if e["pr"] == 8104:
                    e.update(status="done", at=formats.iso(formats.now()), verdict="Faster (-5.15 ms, -6.5 %)")
        self.local.change(done)
        self.assertEqual(self.local.again(8104), A)
        rows = {r["pr"]: r for r in self.local.rows()}
        self.assertEqual(rows[8104]["entry"]["status"], "queued")
        self.assertEqual([e["verdict"] for e in rows[8104]["earlier"]], ["Faster (-5.15 ms, -6.5 %)"])
        self.assertTrue(self.local.mark_posted(8104, A))
        result = next(e for e in self.local.read()["entries"] if e["pr"] == 8104 and e["status"] == "done")
        self.assertIn("at", result["posted"])
        self.assertTrue(self.local.mark_posted(8104, A, posted=False))
        self.assertNotIn("posted", next(e for e in self.local.read()["entries"] if e["pr"] == 8104 and e["status"] == "done"))

    def test_stale(self):
        now = formats.now()
        entry = {"pr": 8104, "head": A, "status": "done", "at": formats.iso(now - datetime.timedelta(hours=1))}
        data = {"prs": {"8104": {"head": A, "state": "open"}}}
        self.assertEqual(local_tests.stale(entry, data, now), "")
        self.assertEqual(local_tests.stale(entry, {"prs": {"8104": {"head": B, "state": "open"}}}, now), "the pull request has newer commits (bbbbbbbbb)")
        self.assertEqual(local_tests.stale(entry, {"prs": {"8104": {"head": A, "state": "merged"}}}, now), "the pull request was merged")
        self.assertIn("over 2 days ago", local_tests.stale(entry, data, now + datetime.timedelta(days=3)))
        self.assertEqual(local_tests.stale(entry | {"posted": {"at": "x"}}, {"prs": {"8104": {"head": B}}}, now), "")  # posted: never stale

    def test_a_fix_pushed_by_someone_else_holds_local_tests(self):
        self.config.local_fixes = [9730]
        self.pushers["f" * 40] = "somebody-else"
        self.refresh()
        self.assertIn("pushed by somebody-else, not its author", self.local.read()["fixes"]["9730"]["problem"])
        status = client.Status(self.config.state_dir / "client" / "status.json")
        runner = types.SimpleNamespace(status=status, config=self.config)
        with mock.patch("title_runs.sources.main_tip", return_value="4" * 40), mock.patch("title_runs.job.run") as run:
            self.assertIsNone(self.local.run(self.local.queued()[0], runner))
        run.assert_not_called()
        self.assertIn("fix #9730 can't be used", self.local.held()["reason"])
        self.config.local_fixes = []  # changing the fixes lets local tests try again
        self.assertIsNone(self.local.held())

    def test_a_fix_is_carried_and_named_in_the_pin(self):
        self.config.local_fixes = [9730]
        self.refresh()
        with mock.patch("title_runs.sources.main_tip", return_value="4" * 40), \
                mock.patch("title_runs.sources.carry", return_value=("c" * 40, [{"pr": 9730, "head": "f" * 40}], [])) as carry:
            self.assertEqual(self.local.pin(), "c" * 40)
            self.assertEqual(self.local.pin(), "c" * 40)  # kept
        self.assertEqual(carry.call_args.args[2:], ("4" * 40, [(9730, "f" * 40)]))
        self.assertEqual(carry.call_count, 1)
        self.assertEqual(self.local.read()["pinned"]["fixes"], [{"pr": 9730, "head": "f" * 40}])


if __name__ == "__main__":
    unittest.main()
