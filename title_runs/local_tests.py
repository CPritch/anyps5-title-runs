"""Local tests: pull requests the tester picks on a project they don't run tests for (upstream AnyPS5), and optionally
the open pull requests of people they follow, each head tested once against the project's main, within the tester's
testing (the Off, On schedule, Now switch), with nothing posted anywhere. Results stay on this computer, each with a
report in the project's own form that the tester may post themselves.

Trust is the tester's: a head runs only when the PR's own author pushed it (the PR's earliest workflow run for that
head names its pusher), and every test builds and runs in the sandbox as a queued one does. Main is pinned for
PIN_HOURS, so the PRs tested together are measured against the same main and that side builds and warms up once.

  state/client/local-tests.json          the list: {"repository", "pinned": {"main", "at"}, "entries": [...]}
  state/local-tests/<night>.md           a summary per night
  state/local-tests/drafts/<pr>-<head>.md   the report per tested head
"""

import datetime
import json
from pathlib import Path

from . import formats, gh, job, sandbox, sources, verdict
from .relay import render

PIN_HOURS = 12  # a pin older than this starts a new night


def night_of(at):
    """The night a time belongs to: the date the evening before (01:00 on the 22nd is the night of the 21st)."""
    local = at.astimezone()
    return (local - datetime.timedelta(hours=12)).date().isoformat()


class LocalTests:
    def __init__(self, config, log=print):
        self.config, self.log = config, log
        self.dir = Path(config.state_dir)
        self.path = self.dir / "client" / "local-tests.json"
        self.out = self.dir / "local-tests"
        for old, new in ((self.dir / "client" / "overnight.json", self.path), (self.dir / "overnight", self.out)):
            if old.exists() and not new.exists():  # first named "tonight's list"
                old.rename(new)

    # -- the list ------------------------------------------------------------------------------------------------------

    def enabled(self):
        return bool(self.config.local_repository and (self.config.local_prs or self.config.local_people))

    def read(self):
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            data = {}
        if data.get("repository") != self.config.local_repository:
            data = {"repository": self.config.local_repository, "pinned": None, "entries": []}
        return data

    def write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=1))
        temporary.replace(self.path)

    def remote(self):
        return f"https://github.com/{self.config.local_repository}.git"

    def refresh(self, token):
        """Bring the list up to date from GitHub (read only): each listed PR's head, and the open PRs of the listed people.
        A head not yet on the list is added if its author pushed it; one the list has tested is left alone."""
        if not self.enabled():
            return []
        repo = gh.GitHubRepo(self.config.local_repository, token=token)
        numbers = set(self.config.local_prs)
        authors = {a.lower() for a in self.config.local_people}
        if authors:
            for issue in repo.pages(f"/repos/{repo.repository}/pulls", {"state": "open"}, limit=10):
                if (issue.get("user") or {}).get("login", "").lower() in authors and not issue.get("draft"):
                    numbers.add(issue["number"])
        data = self.read()
        added = []
        for number in sorted(numbers):
            try:
                pull = repo.pull(number)
            except gh.GitHubError as error:
                self.log(f"local tests: #{number}: {error}")
                continue
            if pull["state"] != "open":
                continue
            if any(e["pr"] == number and e["head"] == pull["head"] for e in data["entries"]):
                continue
            runs = [r for r in repo.workflow_runs(head_sha=pull["head"]) if r["event"] in ("pull_request", "pull_request_target")]
            pusher = runs[0]["actor"] if runs else None
            entry = {"pr": number, "head": pull["head"], "title": pull["title"][:200], "author": pull["author"], "added": formats.iso(formats.now()),
                     "status": "queued", "pusher": pusher}
            if pusher is None:
                entry.update(status="skipped", reason="no workflow run tells who pushed this head")
            elif pusher.lower() != pull["author"].lower():
                entry.update(status="skipped", reason=f"pushed by {pusher}, not the author")
            # An older head of the same PR still queued is replaced: only the newest is worth the night.
            for old in data["entries"]:
                if old["pr"] == number and old["status"] == "queued":
                    old.update(status="replaced", reason=f"{pull['head'][:9]} was pushed")
            data["entries"].append(entry)
            added.append(entry)
            self.log(f"local tests: #{number} {pull['head'][:9]} by {pull['author']}: {entry['status']}{' (' + entry.get('reason', '') + ')' if entry.get('reason') else ''}")
        self.write(data)
        return added

    def queued(self):
        return [e for e in self.read()["entries"] if e["status"] == "queued"]

    def held(self, now=None):
        """Why local tests wait although some are queued: the pinned main didn't start the game, so every change on it
        would fail the same way. {"at", "main", "reason"} while that main is still the pinned one, else None. A new pin
        (PIN_HOURS on, or unpin) ends it."""
        data = self.read()
        paused, pinned = data.get("paused"), data.get("pinned")
        if not paused or not pinned or paused.get("main") != pinned.get("main"):
            return None
        if (now or formats.now()) - formats.parse_time(pinned["at"]) >= datetime.timedelta(hours=PIN_HOURS):
            return None
        return paused

    def unpin(self):
        """Measure the next local test against main as it is then (and try again after a main that didn't start)."""
        data = self.read()
        data["pinned"] = None
        data.pop("paused", None)
        self.write(data)

    def pin(self, now=None):
        """The main local tests are measured against: pinned at the first test, kept for PIN_HOURS."""
        now = now or formats.now()
        data = self.read()
        pinned = data.get("pinned")
        if pinned and now - formats.parse_time(pinned["at"]) < datetime.timedelta(hours=PIN_HOURS):
            return pinned["main"]
        main = sources.main_tip(self.remote())
        data["pinned"] = {"main": main, "at": formats.iso(now), "night": night_of(now)}
        data.pop("paused", None)
        self.write(data)
        self.log(f"local tests: main pinned at {main[:9]} for the night of {night_of(now)}")
        return main

    # -- a test --------------------------------------------------------------------------------------------------------

    def run(self, entry, client):
        """Build and run one head against the pinned main, with the client's sandbox, status and Stop. Nothing is posted."""
        main = self.pin()
        pr, head = entry["pr"], entry["head"]
        client.status.update(state="running", line=f"Testing #{pr} (a local test)", progress="starting", stop_requested=False,
                             job={"pr": pr, "head": head, "title": entry["title"], "author": entry["author"], "trust": "local"})

        def stopped():
            return "stopped by the tester" if client.status.read().get("stop_requested") else None

        def progress(text):
            client.status.update(progress=text)

        results = job.run(self.config, self.config.state_dir, pr, head, lambda text: (self.log(text), progress(text) if text[:2] in ("A:", "B:") else None),
                          recheck=stopped, progress=progress, should_stop=stopped, remote=self.remote(), main=main)
        data = self.read()
        record = next((e for e in data["entries"] if e["pr"] == pr and e["head"] == head), entry)
        if client.status.read().get("stop_requested"):
            record.update(status="queued")  # Stop: tried again later
            client.status.update(state="idle", line=f"Stopped #{pr}", job={}, progress="")
            self.write(data)
            return None
        side, reason = failure(results)
        if side == "A":
            # The pinned main itself doesn't start the game: not this PR's fault, and every other PR would fail the same way.
            # Local tests hold (held) until main is pinned again; the queue's tests, on their own main, go on.
            record.update(status="queued")
            data["paused"] = {"at": formats.iso(formats.now()), "main": main, "reason": reason}
            self.write(data)
            self.log(f"local tests: paused: main {main[:9]} doesn't start the game: {reason}")
            client.status.update(state="idle", line=f"Local tests paused: main doesn't start the game ({reason[:120]})", job={}, progress="")
            self.write_summary()
            return None
        result = report_result(results, head, client)
        counted = side is None and result["status"] == "done" and all((entry.get("sides") or {}) for entry in result["titles"].values())
        record.update(status="done" if counted else "failed", at=formats.iso(formats.now()), main=main, display=sandbox.game_display(),
                      verdict=summary_words(result, verdict.DEFAULT) if side is None else f"the change doesn't start the game: {reason}",
                      job=f"{pr}-{head[:12]}")
        self.write(data)
        draft = self.write_draft(entry, result, main)
        record["draft"] = str(draft)
        self.write(data)
        self.write_summary()
        recent = [{"pr": pr, "head": head, "status": result["status"], "at": record["at"], "local": True, "draft": str(draft)}] \
            + client.status.read().get("recent", [])[:9]
        client.status.update(state="idle", line=f"Tested #{pr}: {record['verdict']}", job={}, progress="", recent=recent)
        return result

    # -- what the tester reads -----------------------------------------------------------------------------------------

    def write_draft(self, entry, result, main):
        """A comment the tester may post on the PR themselves: the A/B on this machine, in the App comment's tables."""
        drafts = self.out / "drafts"
        drafts.mkdir(parents=True, exist_ok=True)
        path = drafts / f"{entry['pr']}-{entry['head'][:12]}.md"
        results = {result["machine"]: result}
        lines = [f"Title runs on one machine of `{entry['head'][:9]}` merged onto main `{main[:9]}`, against that main. "
                 f"Numbers are from one machine and one scene; they are not a review.", ""]
        lines += render.combined_lines(results) + [""]
        lines += render.HEADER + render.rows(results) + [""]
        detail = render.details(results)
        if detail:
            lines += ["<details><summary>The timed runs and summary lines</summary>", ""] + detail + ["</details>", ""]
        path.write_text("\n".join(lines) + "\n")
        return path

    def write_summary(self):
        data = self.read()
        night = (data.get("pinned") or {}).get("night") or night_of(formats.now())
        self.out.mkdir(parents=True, exist_ok=True)
        lines = [f"# Local tests, the night of {night}", "", f"{data['repository']}, main `{((data.get('pinned') or {}).get('main') or '?')[:9]}`.", ""]
        for e in data["entries"]:
            if e["status"] in ("done", "failed"):
                shown = " (the game ran as X11)" if e.get("display") == "x11" else ""  # whether the app took it in is the app's, not the job's
                lines.append(f"- #{e['pr']} `{e['head'][:9]}` {e['title']} ({e['author']}): {e.get('verdict', e['status'])}{shown}. "
                             f"Draft: {e.get('draft', '-')}")
        if data.get("paused"):
            lines += ["", f"**Paused** at {data['paused']['at']}: main `{data['paused']['main'][:9]}` doesn't start the game: "
                          f"{data['paused']['reason']}"]
        waiting = [e for e in data["entries"] if e["status"] == "queued"]
        skipped = [e for e in data["entries"] if e["status"] == "skipped"]
        if waiting:
            lines += ["", f"Not reached: {', '.join('#' + str(e['pr']) for e in waiting)}."]
        if skipped:
            lines += ["", "Skipped:"] + [f"- #{e['pr']} `{e['head'][:9]}`: {e['reason']}" for e in skipped]
        path = self.out / f"{night}.md"
        path.write_text("\n".join(lines) + "\n")
        return path


def failure(results):
    """("A" | "B", the crash's own words) when a side's game didn't reach the scene, else (None, ""). The words are
    the game log's last "what():" or unhandled-exception line, when there is one."""
    for entry in results.get("titles", {}).values():
        ab = entry.get("ab") or {}
        error = ab.get("error") or ""
        if not error.startswith("side "):
            continue
        side = error.split()[1].rstrip(":")
        run = ((ab.get("warm") or {}).get(side) or {}).get("run")
        reason = error
        if run and entry.get("runs_dir"):
            log = Path(entry["runs_dir"]) / run / "game.log"
            try:
                lines = [line.strip() for line in log.read_text(errors="replace").splitlines()
                         if "what():" in line or "unhandled exception" in line or "Assertion" in line]
            except OSError:
                lines = []
            if lines:
                reason = lines[-1].replace("what():", "").strip()
        return side, reason
    return None, ""


def report_result(results, head, client):
    from .client import to_result
    return to_result(results, head, client.config.machine, client.tester() or client.config.tester or "tester", client.machine_class, "local")


def summary_words(result, rules):
    """"No difference (+0.13 ms)", "Faster (-2.41 ms)", "didn't merge", for the summary and Home."""
    if result["status"] != "done":
        return result.get("error") or result["status"]
    parts = []
    for title_id, entry in sorted(result["titles"].items()):
        v = verdict.machine(entry.get("sides") or {}, rules)
        if v.get("diff") is None:
            parts.append(f"{title_id}: not enough runs counted ({entry.get('outcome', {}).get('B', '?')})")
        else:
            word = {"faster": "Faster", "slower": "Slower"}.get(v["verdict"], "No difference")
            parts.append(f"{word} ({v['diff']:+.2f} ms, {v['diff_pct']:+.1f} %)" + (", borderline" if v.get("borderline") else ""))
    return "; ".join(parts) or "no titles ran"
