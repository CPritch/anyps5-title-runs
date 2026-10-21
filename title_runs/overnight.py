"""Overnight testing on the tester's own terms (the [overnight] config): a list of pull requests on a repository the
tester doesn't run (upstream AnyPS5), and optionally the open pull requests of people the tester trusts, each head
tested at most once, within the tester's hours, with nothing posted anywhere. Results stay on this machine: a summary
per night and a draft comment per pull request, which the tester may post themselves.

Trust is the tester's: a head runs only when the PR's own author pushed it (the PR's earliest workflow run for that
head names its pusher), and every test builds and runs in the sandbox as a queued one does. Main is pinned once per
night, so every PR of the night is measured against the same main and that side builds and warms up once.

  state/client/overnight.json     the list: {"repository", "pinned": {"main", "at"}, "entries": [...]}
  state/overnight/<night>.md       the night's summary
  state/overnight/drafts/<pr>-<head>.md   a draft comment per tested head
"""

import datetime
import json
from pathlib import Path

from . import formats, gh, job, sources, verdict
from .relay import render

PIN_HOURS = 12  # a pin older than this starts a new night


def night_of(at):
    """The night a time belongs to: the date the evening before (01:00 on the 22nd is the night of the 21st)."""
    local = at.astimezone()
    return (local - datetime.timedelta(hours=12)).date().isoformat()


class Overnight:
    def __init__(self, config, log=print):
        self.config, self.log = config, log
        self.dir = Path(config.state_dir)
        self.path = self.dir / "client" / "overnight.json"
        self.out = self.dir / "overnight"

    # -- the list ------------------------------------------------------------------------------------------------------

    def enabled(self):
        return bool(self.config.overnight_repository and (self.config.overnight_prs or self.config.overnight_authors))

    def read(self):
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            data = {}
        if data.get("repository") != self.config.overnight_repository:
            data = {"repository": self.config.overnight_repository, "pinned": None, "entries": []}
        return data

    def write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=1))
        temporary.replace(self.path)

    def remote(self):
        return f"https://github.com/{self.config.overnight_repository}.git"

    def refresh(self, token):
        """Bring the list up to date from GitHub (read only): each listed PR's head, and the open PRs of the listed people.
        A head not yet on the list is added if its author pushed it; one the list has tested is left alone."""
        if not self.enabled():
            return []
        repo = gh.GitHubRepo(self.config.overnight_repository, token=token)
        numbers = set(self.config.overnight_prs)
        authors = {a.lower() for a in self.config.overnight_authors}
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
                self.log(f"overnight: #{number}: {error}")
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
            self.log(f"overnight: #{number} {pull['head'][:9]} by {pull['author']}: {entry['status']}{' (' + entry.get('reason', '') + ')' if entry.get('reason') else ''}")
        self.write(data)
        return added

    def queued(self):
        return [e for e in self.read()["entries"] if e["status"] == "queued"]

    def pin(self, now=None):
        """main for tonight: pinned at the night's first test, kept for PIN_HOURS."""
        now = now or formats.now()
        data = self.read()
        pinned = data.get("pinned")
        if pinned and now - formats.parse_time(pinned["at"]) < datetime.timedelta(hours=PIN_HOURS):
            return pinned["main"]
        main = sources.main_tip(self.remote())
        data["pinned"] = {"main": main, "at": formats.iso(now), "night": night_of(now)}
        self.write(data)
        self.log(f"overnight: main pinned at {main[:9]} for the night of {night_of(now)}")
        return main

    # -- a test --------------------------------------------------------------------------------------------------------

    def run(self, entry, client):
        """Build and run one head against tonight's main, with the client's sandbox, status and Stop. Nothing is posted."""
        main = self.pin()
        pr, head = entry["pr"], entry["head"]
        client.status.update(state="running", line=f"Testing #{pr} (tonight's list)", progress="starting", stop_requested=False,
                             job={"pr": pr, "head": head, "title": entry["title"], "author": entry["author"], "trust": "overnight"})

        def stopped():
            return "stopped by the tester" if client.status.read().get("stop_requested") else None

        def progress(text):
            client.status.update(progress=text)

        results = job.run(self.config, self.config.state_dir, pr, head, lambda text: (self.log(text), progress(text) if text[:2] in ("A:", "B:") else None),
                          recheck=stopped, progress=progress, should_stop=stopped, remote=self.remote(), main=main)
        data = self.read()
        record = next((e for e in data["entries"] if e["pr"] == pr and e["head"] == head), entry)
        if client.status.read().get("stop_requested"):
            record.update(status="queued")  # Stop: tried again later tonight
            client.status.update(state="idle", line=f"Stopped #{pr}", job={}, progress="")
            self.write(data)
            return None
        side, reason = failure(results)
        if side == "A":
            # Tonight's main itself doesn't start the game: not this PR's fault, and every other PR would fail the same way.
            record.update(status="queued")
            data["paused"] = {"at": formats.iso(formats.now()), "main": main, "reason": reason}
            self.write(data)
            self.log(f"overnight: paused: main {main[:9]} doesn't start the game: {reason}")
            client.status.update(state="idle", line=f"Paused: tonight's main doesn't start the game ({reason[:120]})", job={}, progress="",
                                 paused_until="indefinitely")
            self.write_summary()
            return None
        result = report_result(results, head, client)
        counted = side is None and result["status"] == "done" and all((entry.get("sides") or {}) for entry in result["titles"].values())
        record.update(status="done" if counted else "failed", at=formats.iso(formats.now()), main=main,
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
        lines = [f"# Overnight, the night of {night}", "", f"{data['repository']}, main `{((data.get('pinned') or {}).get('main') or '?')[:9]}`.", ""]
        for e in data["entries"]:
            if e["status"] in ("done", "failed"):
                lines.append(f"- #{e['pr']} `{e['head'][:9]}` {e['title']} ({e['author']}): {e.get('verdict', e['status'])}. Draft: {e.get('draft', '-')}")
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
    return to_result(results, head, client.config.machine, client.tester() or client.config.tester or "tester", client.machine_class, "overnight")


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
