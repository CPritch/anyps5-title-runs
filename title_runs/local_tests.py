"""Local tests: pull requests the tester picks on a project they don't run tests for (upstream AnyPS5), and optionally
the open pull requests of people they follow, each head tested once against the project's main, within the tester's
testing (the Off, On schedule, Now switch), with nothing posted anywhere. Results stay on this computer, each with a
report in the project's own form that the tester may post themselves.

Trust is the tester's: a head runs only when the PR's own author pushed it (the PR's earliest workflow run for that
head names its pusher), and every test builds and runs in the sandbox as a queued one does. Main is pinned for
PIN_HOURS, so the PRs tested together are measured against the same main and that side builds and warms up once.

  state/client/local-tests.json          the list: {"repository", "pinned": {"main", "base", "fixes", "at"}, "prs", "fixes",
                                         "entries": [...], "removed", "paused"}
  state/local-tests/<night>.md           a summary per night
  state/local-tests/drafts/<job>.md       the report per test, as written when it ran
  state/local-tests/attach/<job>/        its traces under the report's names, for the tester to drag into the comment

Fixes (the [local] fixes setting) are pull requests merged onto main for both sides, for a main that can't run the
tester's games without them; a fix main already has is left out. Posting is the tester's: a result is marked posted
by hand, and one not posted goes stale (stale) when the PR moves on.
"""

import datetime
import json
import os
import re
import shutil
import threading
from pathlib import Path

from . import formats, gh, job, locks, protocol, sandbox, sources, verdict
from .client import clean

PIN_HOURS = 12  # a pin older than this starts a new night
STALE_HOURS = 48  # a result not posted for this long is stale: main has moved on too far for it to say much
STATE_HOURS = 6  # how often a listed pull request whose head hasn't moved is asked whether it closed
COMMENT_LIMIT = 65536  # GitHub's longest comment, in characters


def night_of(at):
    """The night a time belongs to: the date the evening before (01:00 on the 22nd is the night of the 21st)."""
    local = at.astimezone()
    return (local - datetime.timedelta(hours=12)).date().isoformat()


class Hold(RuntimeError):
    """Local tests can't start: a fix to carry is not usable, or the base doesn't start the game."""


class LocalTests:
    def __init__(self, config, log=print):
        self.config, self.log = config, log
        self.dir = Path(config.state_dir)
        self.path = self.dir / "client" / "local-tests.json"
        self.out = self.dir / "local-tests"
        self.lock = threading.RLock()  # the worker and the window both change the list
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

    def change(self, edit):
        """Read, edit(data), write, under the lock (this process's threads, and other title-runs processes); returns what
        edit returned."""
        with self.lock, locks.held(self.path):
            data = self.read()
            out = edit(data)
            self.write(data)
            return out

    def remote(self):
        return f"https://github.com/{self.config.local_repository}.git"

    def pull_url(self, number):
        return f"https://github.com/{self.config.local_repository}/pull/{number}"

    def refresh(self, now=None):
        """Bring the list up to date from GitHub (read only, without a sign-in). Every pull request's head comes from git
        in one call; the API is asked only what git can't tell: a head new to the list (the pull request's title, author
        and state, and who pushed it), whether a listed pull request closed (every STATE_HOURS), and the listed people's
        open pull requests (its search). A head not yet on the list is added if its author pushed it; one the list has
        tested is left alone. A PR the tester removed stays off it. Raises gh.RateLimited when GitHub's limit is used up."""
        if not self.enabled():
            return []
        now = now or formats.now()
        repo = gh.GitHubRepo(self.config.local_repository)
        heads = sources.pull_heads(self.remote())
        known = self.read()
        removed = set(known.get("removed", []))
        numbers = set(self.config.local_prs)
        for login in self.config.local_people:
            numbers.update(pull["number"] for pull in repo.open_pulls_by(login) if not pull["draft"] and pull["number"] not in removed)
        seen, fixes_seen = known.get("prs") or {}, known.get("fixes") or {}
        pulls, pushers = {}, {}

        def due(number):
            old = seen.get(str(number))
            if not old or old.get("head") != heads.get(number):
                return True
            if old.get("state") == "merged":
                return False
            checked = old.get("checked")
            return not checked or now - formats.parse_time(checked) >= datetime.timedelta(hours=STATE_HOURS)

        for number in sorted(numbers | set(self.config.local_fixes)):
            if not due(number):
                pulls[number] = {**seen[str(number)], "fresh": False}
                continue
            try:
                pulls[number] = {**repo.pull(number), "fresh": True}
            except gh.RateLimited:
                raise
            except gh.GitHubError as error:
                self.log(f"local tests: #{number}: {error}")

        def pusher_of(pull):
            if pull["head"] not in pushers:
                runs = [r for r in repo.workflow_runs(head_sha=pull["head"]) if r["event"] in ("pull_request", "pull_request_target")]
                pushers[pull["head"]] = runs[0]["actor"] if runs else None
            return pushers[pull["head"]]

        tested = {(e["pr"], e["head"]) for e in known["entries"]}
        for number in numbers:  # the network outside the lock: who pushed each new head
            pull = pulls.get(number)
            if pull and pull["state"] == "open" and (number, pull["head"]) not in tested:
                pusher_of(pull)
        for number in self.config.local_fixes:
            pull, old = pulls.get(number), fixes_seen.get(str(number)) or {}
            if pull is None:
                continue
            if old.get("head") == pull["head"] and "pusher" in old:
                pushers.setdefault(pull["head"], old["pusher"])
            else:
                pusher_of(pull)

        def apply(data):
            stamp = formats.iso(now)
            added = []
            prs = data.setdefault("prs", {})
            for number, pull in pulls.items():
                old = prs.get(str(number)) or {}
                prs[str(number)] = {"head": pull["head"], "state": pull["state"], "title": pull["title"][:200], "author": pull["author"],
                                    "checked": stamp if pull["fresh"] else old.get("checked", stamp)}
            fixes = {}
            for number in self.config.local_fixes:
                pull = pulls.get(number)
                if pull is None:
                    continue
                pusher = pushers.get(pull["head"])
                problem = ("" if pusher and pusher.lower() == pull["author"].lower() else
                           f"its latest commit {pull['head'][:9]} was pushed by {pusher}, not its author" if pusher else
                           f"GitHub doesn't show who pushed its latest commit {pull['head'][:9]}")
                fixes[str(number)] = {"head": pull["head"], "title": pull["title"][:200], "author": pull["author"], "state": pull["state"],
                                      "pusher": pusher, "problem": problem}
            data["fixes"] = fixes
            for number in sorted(numbers):
                pull = pulls.get(number)
                if pull is None or pull["state"] != "open" or number in data.get("removed", []):
                    continue
                if any(e["pr"] == number and e["head"] == pull["head"] for e in data["entries"]):
                    continue
                pusher = pushers.get(pull["head"])
                entry = {"pr": number, "head": pull["head"], "title": pull["title"][:200], "author": pull["author"], "added": stamp,
                         "status": "queued", "pusher": pusher}
                if pusher is None:
                    entry.update(status="skipped", reason="GitHub doesn't show who pushed this commit")
                elif pusher.lower() != pull["author"].lower():
                    entry.update(status="skipped", reason=f"{pusher} pushed this commit, not the author")
                # An older head of the same PR still queued is replaced: only the newest is worth testing.
                for old in data["entries"]:
                    if old["pr"] == number and old["status"] == "queued":
                        old.update(status="replaced", reason=f"{pull['head'][:9]} was pushed")
                data["entries"].append(entry)
                added.append(entry)
                self.log(f"local tests: #{number} {pull['head'][:9]} by {pull['author']}: {entry['status']}"
                         f"{' (' + entry.get('reason', '') + ')' if entry.get('reason') else ''}")
            return added

        return self.change(apply)

    def queued(self):
        return [e for e in self.read()["entries"] if e["status"] == "queued"]

    # -- what the tester does on the Local tests page -----------------------------------------------------------------

    def parse(self, text):
        """A pull request number from "8104", "#8104" or its GitHub link. Returns (number, "") or (None, why not)."""
        text = text.strip()
        found = re.fullmatch(r"#?(\d+)", text) or re.fullmatch(r"(?:https?://)?github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)\S*", text)
        if not found:
            return None, "Type a pull request number, or paste its link."
        if len(found.groups()) == 2:
            if found.group(1).lower() != self.config.local_repository.lower():
                return None, f"That's a pull request of {found.group(1)}; this list tests {self.config.local_repository or 'no project yet'}."
            return int(found.group(2)), ""
        return int(found.group(1)), ""

    def added(self, number):
        """A PR the tester (re)added: no longer removed."""
        self.change(lambda data: data["removed"].remove(number) if number in data.setdefault("removed", []) else None)

    def remove(self, number):
        """Off the list: its waiting test is dropped and a followed person's PR isn't added again. Results stay."""
        def edit(data):
            if number not in data.setdefault("removed", []):
                data["removed"].append(number)
            for entry in data["entries"]:
                if entry["pr"] == number and entry["status"] == "queued":
                    entry.update(status="removed", reason="removed from the list")
        self.change(edit)

    def again(self, number):
        """Test the PR's latest tested head again (against main as it is pinned then). Returns the head, or None."""
        def edit(data):
            latest = self.latest(data, number)
            if latest is None or latest["status"] == "queued":
                return None
            data["entries"].append({key: latest[key] for key in ("pr", "head", "title", "author", "pusher") if key in latest}
                                   | {"added": formats.iso(formats.now()), "status": "queued", "again": True})
            return latest["head"]
        return self.change(edit)

    def mark_posted(self, number, head, posted=True, at=None):
        """The tester posted (or took back) the report of a result: the PR's latest for head, or the one tested at at."""
        def edit(data):
            for entry in reversed(data["entries"]):
                if entry["pr"] == number and entry["head"] == head and entry["status"] in ("done", "failed") and at in (None, entry.get("at")):
                    if posted:
                        entry["posted"] = {"at": formats.iso(formats.now())}
                    else:
                        entry.pop("posted", None)
                    return True
            return False
        return self.change(edit)

    @staticmethod
    def latest(data, number):
        """The PR's newest entry that says something: a test waiting, a result, or why it was skipped."""
        return next((e for e in reversed(data["entries"]) if e["pr"] == number and e["status"] not in ("replaced", "removed")), None)

    def rows(self, now=None):
        """The Local tests page: one row per pull request, waiting ones first, then the newest results:
        [{"pr", "title", "author", "entry" (the newest), "stale" (why, or ""), "earlier" [older results], "removed"}]."""
        data = self.read()
        removed = set(data.get("removed", []))
        rows = {}
        for entry in data["entries"]:
            if entry["status"] in ("replaced", "removed"):
                continue
            row = rows.setdefault(entry["pr"], {"pr": entry["pr"], "title": entry["title"], "author": entry["author"], "entry": None, "earlier": []})
            if row["entry"] is not None and row["entry"]["status"] in ("done", "failed"):
                row["earlier"].insert(0, row["entry"])
            row["entry"] = entry
            row["title"] = entry["title"]
        out = []
        for row in rows.values():
            if row["pr"] in removed and row["entry"]["status"] not in ("done", "failed"):
                continue
            row["stale"] = stale(row["entry"], data, now)
            row["removed"] = row["pr"] in removed
            out.append(row)
        waiting = [r for r in out if r["entry"]["status"] == "queued"]
        rest = sorted((r for r in out if r["entry"]["status"] != "queued"), key=lambda r: r["entry"].get("at") or r["entry"].get("added", ""), reverse=True)
        return waiting + rest

    # -- main, and the fixes carried on both sides ---------------------------------------------------------------------

    def held(self, now=None):
        """Why local tests wait although some are queued: the pinned base didn't start the game (every change on it would
        fail the same way), or a fix can't be carried. {"at", "main", "fixes", "reason"} until main is pinned again
        (PIN_HOURS on, or unpin) or the fixes change; else None."""
        paused = self.read().get("paused")
        if not paused or paused.get("fixes", []) != sorted(self.config.local_fixes):
            return None
        if (now or formats.now()) - formats.parse_time(paused["at"]) >= datetime.timedelta(hours=PIN_HOURS):
            return None
        return paused

    def hold(self, main, reason):
        def edit(data):
            data["paused"] = {"at": formats.iso(formats.now()), "main": main, "fixes": sorted(self.config.local_fixes), "reason": reason}
        self.change(edit)
        self.log(f"local tests: paused: {reason}")

    def unpin(self):
        """Measure the next local test against main as it is then (and try again after a main that didn't start)."""
        def edit(data):
            data["pinned"] = None
            data.pop("paused", None)
        self.change(edit)

    def pinned(self, now=None):
        """The pin the next local test uses, or None when it will pin main afresh (none yet, too old, fixes changed)."""
        pinned = self.read().get("pinned")
        if (pinned and pinned.get("fix_numbers", []) == sorted(self.config.local_fixes)
                and (now or formats.now()) - formats.parse_time(pinned["at"]) < datetime.timedelta(hours=PIN_HOURS)):
            return pinned
        return None

    def pin(self, now=None):
        """The base local tests are measured against: main with the fixes to carry merged onto it, pinned at the first
        test and kept for PIN_HOURS or until the fixes change. Returns the base; raises Hold when a fix can't be used."""
        now = now or formats.now()
        data = self.read()
        wanted = sorted(self.config.local_fixes)
        pinned = self.pinned(now)
        if pinned:
            return pinned.get("base") or pinned["main"]
        heads = []
        for number in wanted:
            fix = (data.get("fixes") or {}).get(str(number))
            if not fix:
                raise Hold(f"fix #{number} hasn't been read from GitHub yet")
            if fix.get("problem"):
                raise Hold(f"fix #{number} can't be used: {fix['problem']}")
            heads.append((number, fix["head"]))
        main = sources.main_tip(self.remote())  # the network and git outside the lock: the window waits on it
        try:
            base, carried, in_main = sources.carry(self.config.repo_dir, self.remote(), main, heads)
        except sources.SourceError as error:
            raise Hold(str(error)) from error

        def edit(data):
            data["pinned"] = {"main": main, "base": base, "fixes": carried, "in_main": in_main, "fix_numbers": wanted,
                              "at": formats.iso(now), "night": night_of(now)}
            data.pop("paused", None)
        self.change(edit)
        self.log(f"local tests: pinned main {main[:9]}" + "".join(f" + #{f['pr']} {f['head'][:9]}" for f in carried)
                 + (f" (main has {', '.join('#' + str(n) for n in in_main)})" if in_main else ""))
        return base

    # -- a test --------------------------------------------------------------------------------------------------------

    def run(self, entry, client):
        """Build and run one head against the pinned base, with the client's sandbox, status and Stop. Nothing is posted."""
        pr, head = entry["pr"], entry["head"]
        try:
            base = self.pin()
        except (Hold, sources.SourceError) as error:
            self.hold("?", str(error))
            client.status.update(state="idle", line=f"Local tests paused: {str(error)[:160]}", job={}, progress="")
            return None
        pinned = self.read()["pinned"]
        main, fixes = pinned["main"], pinned.get("fixes", [])
        client.status.update(state="running", line=f"Testing #{pr} (a local test)", progress="starting", stop_requested=False,
                             job={"pr": pr, "head": head, "title": entry["title"], "author": entry["author"], "trust": "local"})

        def stopped():
            return "stopped by the tester" if client.status.read().get("stop_requested") else None

        def progress(text):
            client.status.update(progress=text)

        results = job.run(self.config, self.config.state_dir, pr, head, lambda text: (self.log(text), progress(text) if text[:2] in ("A:", "B:") else None),
                          recheck=stopped, progress=progress, should_stop=stopped, remote=self.remote(), main=base)
        side, reason = failure(results)
        result = result_of(results) if side != "A" else None

        def record(data):
            match = [e for e in data["entries"] if e["pr"] == pr and e["head"] == head]
            entry_now = next((e for e in reversed(match) if e["status"] == "queued"), match[-1] if match else entry)
            if client.status.read().get("stop_requested"):
                entry_now.update(status="queued")  # Stop: tried again later
                return None
            if side == "A":
                # The base itself doesn't start the game: not this PR's fault, and every other PR would fail the same way.
                # Local tests hold (held) until main is pinned again.
                entry_now.update(status="queued")
                data["paused"] = {"at": formats.iso(formats.now()), "main": main, "fixes": sorted(self.config.local_fixes),
                                  "reason": f"main {main[:9]}{''.join(' + #' + str(f['pr']) for f in fixes)} doesn't start the game: {reason}"}
                return None
            counted = side is None and result["status"] == "done" and all((t.get("sides") or {}) for t in result["titles"].values())
            entry_now.update(status="done" if counted else "failed", at=formats.iso(formats.now()), main=main, fixes=fixes, base=base,
                             display=sandbox.game_display(), job=results.get("job") or f"{pr}-{head[:12]}",
                             verdict=summary_words(result, verdict.DEFAULT) if side is None else f"the change doesn't start the game: {reason}")
            return entry_now

        done = self.change(record)
        if done is None:
            stopped_here = client.status.read().get("stop_requested")
            client.status.update(state="idle", job={}, progress="",
                                 line=f"Stopped #{pr}" if stopped_here else f"Local tests paused: main doesn't start the game ({reason[:120]})")
            self.write_summary()
            return None
        draft = self.write_report(done, results)

        def note(data):
            for e in data["entries"]:
                if e.get("job") == done["job"] and e.get("at") == done["at"]:
                    e["draft"] = str(draft)
        self.change(note)
        self.write_summary()
        recent = [{"pr": pr, "head": head, "status": result["status"], "at": done["at"], "local": True}] + client.status.read().get("recent", [])[:9]
        client.status.update(state="idle", line=f"Tested #{pr}: {done['verdict']}", job={}, progress="", recent=recent)
        return result

    # -- what the tester reads -----------------------------------------------------------------------------------------

    def results_of(self, entry):
        """A result's job results, while they are here and of its head; else None."""
        try:
            results = json.loads((self.dir / "jobs" / entry.get("job", "-") / "results.json").read_text())
        except (OSError, ValueError):
            return None
        return results if results.get("head") == entry.get("head") else None

    def report(self, entry):
        """The report of a result, for the tester to post on the PR: built again from its job's results when they are
        here (so it follows this code), else the one written when it ran."""
        results = self.results_of(entry)
        if results:
            return report_text(results, entry, self.graphics(results))
        try:
            return Path(entry["draft"]).read_text()
        except (OSError, KeyError):
            return ""

    def attach(self, entry):
        """(folder, files): the result's traces (attachments()), linked into local-tests/attach/<job>/ under the report's
        names for the tester to drag into the comment. A trace over GitHub's limit is listed but left out of the folder."""
        results = self.results_of(entry)
        files = attachments(results) if results else []
        folder = self.out / "attach" / entry.get("job", "-")
        if files:
            folder.mkdir(parents=True, exist_ok=True)
            for old in folder.iterdir():
                old.unlink()
            for item in files:
                if item["path"] and item["fits"]:
                    item["file"] = folder / item["name"]
                    try:
                        os.link(item["path"], item["file"])  # the same file, no second copy on disk
                    except OSError:
                        shutil.copy2(item["path"], item["file"])
        return folder, files

    def graphics(self, results):
        return {title_id: getattr(self.config.titles.get(title_id), "graphics_mode", "") for title_id in results.get("titles", {})}

    def write_report(self, entry, results):
        drafts = self.out / "drafts"
        drafts.mkdir(parents=True, exist_ok=True)
        path = drafts / f"{entry.get('job') or str(entry['pr']) + '-' + entry['head'][:12]}.md"
        path.write_text(report_text(results, entry, self.graphics(results)))
        return path

    def write_summary(self):
        data = self.read()
        pinned = data.get("pinned") or {}
        night = pinned.get("night") or night_of(formats.now())
        self.out.mkdir(parents=True, exist_ok=True)
        base = f"main `{(pinned.get('main') or '?')[:9]}`" + "".join(f" + #{f['pr']} `{f['head'][:9]}`" for f in pinned.get("fixes", []))
        lines = [f"# Local tests, the night of {night}", "", f"{data['repository']}, {base}.", ""]
        for e in data["entries"]:
            if e["status"] in ("done", "failed") and (e.get("at") or "") >= (pinned.get("at") or ""):
                shown = " (the game ran as X11)" if e.get("display") == "x11" else ""  # whether the app took it in is the app's, not the job's
                lines.append(f"- #{e['pr']} `{e['head'][:9]}` {e['title']} ({e['author']}): {e.get('verdict', e['status'])}{shown}.")
        if data.get("paused"):
            lines += ["", f"**Paused** at {data['paused']['at']}: {data['paused']['reason']}"]
        waiting = [e for e in data["entries"] if e["status"] == "queued"]
        skipped = [e for e in data["entries"] if e["status"] == "skipped"]
        if waiting:
            lines += ["", f"Not reached: {', '.join('#' + str(e['pr']) for e in waiting)}."]
        if skipped:
            lines += ["", "Skipped:"] + [f"- #{e['pr']} `{e['head'][:9]}`: {e['reason']}" for e in skipped]
        path = self.out / f"{night}.md"
        path.write_text("\n".join(lines) + "\n")
        return path


def stale(entry, data, now=None):
    """Why a result not posted is no longer worth posting as it stands, or "": the PR has a newer head, it closed, or
    the result is over STALE_HOURS old (main has moved on). A posted result is never stale."""
    if entry.get("posted") or entry["status"] not in ("done", "failed"):
        return ""
    pull = (data.get("prs") or {}).get(str(entry["pr"])) or {}
    if pull.get("state") in ("merged", "closed"):
        return f"the pull request was {pull['state']}"
    if pull.get("head") and pull["head"] != entry["head"]:
        return f"the pull request has newer commits ({pull['head'][:9]})"
    if entry.get("at") and (now or formats.now()) - formats.parse_time(entry["at"]) > datetime.timedelta(hours=STALE_HOURS):
        return f"tested over {STALE_HOURS // 24} days ago, and main has moved on since"
    return ""


def summary_line(run, runs_dir):
    """A timed run's summary line as AnyPS5 wrote it (its own number formatting), else as the job read it."""
    path = Path(runs_dir or ".") / run.get("run", "-") / "aps5-summary.jsonl"
    try:
        lines = [line.strip() for line in path.read_text().splitlines() if line.startswith("{")]
    except OSError:
        lines = []
    text = lines[-1] if lines else json.dumps(run["summary"], separators=(",", ":"))
    return re.sub(r'"(/|[A-Za-z]:\\\\)[^"]*"', '"<path>"', text)  # no local paths, as AnyPS5 already does for its own


def count(a, b):
    """"two runs each", or "two and three runs" when the sides differ."""
    words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}
    if len(a) == len(b):
        return f"{words.get(len(a), len(a))} run{'s' if len(a) > 1 else ''} each"
    return f"{words.get(len(a), len(a))} and {words.get(len(b), len(b))} runs"


def ms(values):
    return ", ".join(f"{v:.1f}" for v in values)


def attachments(results):
    """The traces a report asks to be attached, in the order of its summary lines (each title's runs of main, then with
    the PR): [{"title_id", "side", "number", "words" ("main, run 1"), "name", "path", "size", "fits", "digest"}]. The
    name is AnyPS5's with the title and the run added, aps5-trace-<commit>-<pid>-<TITLE ID>-main-1.json.gz: the game is
    the same process ID in every sandboxed run, so a side's two traces would have the same name."""
    out = []
    for title_id, title in sorted(results.get("titles", {}).items()):
        runs = [r for r in (title.get("ab") or {}).get("runs", []) if r.get("counts") and r.get("summary")]
        for side, label, words in (("A", "main", "main"), ("B", "pr", f"with #{results.get('pr')}")):
            for number, run in enumerate((r for r in runs if r["side"] == side), 1):
                folder = Path(title.get("runs_dir") or ".") / run["run"]
                trace = next(iter(sorted(folder.glob("aps5-trace-*.json.gz"))), None)
                stem = trace.name.removesuffix(".json.gz") if trace else f"aps5-trace-{run['summary'].get('commit', '')}"
                try:
                    digest = (folder / "digest.txt").read_text().strip().replace(str(Path.home()), "~")
                except OSError:
                    digest = ""
                if "Traceback (most recent call last)" in digest:
                    digest = ""  # trace_digest.py failed on it: nothing for the report
                size = trace.stat().st_size if trace else None
                out.append({"title_id": title_id, "side": side, "number": number, "words": f"{words}, run {number}",
                            "name": f"{stem}-{title_id}-{label}-{number}.json.gz", "path": trace, "size": size,
                            "fits": size is not None and size <= protocol.ATTACH_LIMIT, "digest": digest})
    return out


def megabytes(size):
    return f"{size / 1e6:.1f} MB"


def traces_text(files, digests=True):
    """The report's Traces (the tester drops the files under its first line) and each trace's digest, folded."""
    if not any(f["path"] for f in files):
        return []
    out = []
    if any(f["fits"] for f in files):
        out += ["Traces, one per run in the order of the summary lines (AnyPS5's file names with the title and the run added):", ""]
    too_big = [f for f in files if f["path"] and not f["fits"]]
    if too_big:
        named = "; ".join(f"{f['words']} ({megabytes(f['size'])})" for f in too_big)
        limit = f"GitHub's {protocol.ATTACH_LIMIT // 1_000_000} MB for a file"
        out += [(f"Traces: not attached, as each is over {limit}: " if len(too_big) == len(files) else
                 f"Not attached, as {'it is' if len(too_big) == 1 else 'they are'} over {limit}: ") + named + ".", ""]
    missing = [f["words"] for f in files if not f["path"]]
    if missing:
        out += [f"No trace kept: {', '.join(missing)}.", ""]
    for f in files if digests else []:
        if f["digest"]:
            out += [f"<details><summary>Digest, {f['words']} (python3 tools/trace_digest.py)</summary>", "", f["digest"], "", "</details>", ""]
    return out


def report_text(results, entry, graphics=None):
    """The report of one local test, in the form of the project's performance reports (its issue form and the comments
    reviewers asked for): what ran where, main against main + the PR in A B A B order, p50, GPU busy and p99 per run,
    what wasn't tested, the summary lines, the traces to attach and their digests. Plain text the tester reads, may edit,
    and posts themselves; the digests are left out of a report that would be longer than GitHub takes."""
    text = report_lines(results, entry, graphics, digests=True)
    if len(text) > COMMENT_LIMIT:
        text = report_lines(results, entry, graphics, digests=False)
        text += f"\nThe digests are left out because with them this comment would be over GitHub's limit of {COMMENT_LIMIT:,} characters.\n"
    return text


def report_lines(results, entry, graphics, digests):
    pr, head = entry["pr"], entry["head"]
    main, fixes = entry.get("main") or results.get("base", ""), entry.get("fixes") or []
    carried = "".join(f" + #{f['pr']} at {f['head'][:9]}" for f in fixes)
    on_both = (f" ({' and '.join('#' + str(f['pr']) for f in fixes)} on both sides)" if fixes else "")
    base_words = f"main {main[:9]}{carried}"
    out = []
    for title_id, title in sorted(results.get("titles", {}).items()):
        ab = title.get("ab") or {}
        runs = [r for r in ab.get("runs", []) if r.get("counts") and r.get("summary")]
        a = [r for r in runs if r["side"] == "A"]
        b = [r for r in runs if r["side"] == "B"]
        first = (a or b or [{}])[0].get("summary") or {}
        mode = (graphics or {}).get(title_id) or ""
        where = (f"{first.get('title') or title.get('name', title_id)} ({title_id} {first.get('content_version') or title.get('version', '')}), "
                 f"{first.get('os', '?')}, {first.get('gpu', '?')}, {first.get('driver', '?')}" + (f", Graphics Mode {mode}" if mode else "")
                 + (f", {title['scene']}" if title.get("scene") else "") + f", {title.get('input') or 'with no input'}.")
        if not a or not b:
            side, reason = failure({"titles": {title_id: title}})
            if side == "B":
                out += [f"Ran this on {where}", f"{base_words} starts the game; with #{pr} at {head[:9]} merged onto it{on_both}, the game "
                        f"doesn't reach the scene:", "```", reason, "```"]
            else:
                out += [f"Ran this on {where}", f"Not enough timed runs counted to compare ({', '.join(r.get('capture', '') for r in ab.get('runs', []))})."]
            continue
        order = " ".join(r["side"] for r in runs)
        env = first.get("env") or {}
        window = (first.get("window") or {}).get("spec", "")
        warm = ab.get("warm") or {}
        # warm: this run's warm-up went quiet, or the build was warmed until quiet before ("already", per built commit)
        quiet = (all((warm.get(k) or {}).get("warm") == "already" or (warm.get(k) or {}).get("quiet", "").startswith("quiet: yes") for k in ("A", "B"))
                 and all("no pipeline builds" in r.get("capture", "") for r in runs))
        pa, pb = [r["summary"]["frame_ms"]["p50"] for r in a], [r["summary"]["frame_ms"]["p50"] for r in b]
        ga, gb = [r["summary"].get("gpu_busy_ms_per_present") for r in a], [r["summary"].get("gpu_busy_ms_per_present") for r in b]
        qa, qb = [r["summary"]["frame_ms"].get("p99") for r in a], [r["summary"]["frame_ms"].get("p99") for r in b]
        diff = sum(pb) / len(pb) - sum(pa) / len(pa)
        pct = diff / (sum(pa) / len(pa)) * 100
        against = (f"{base_words}, against that + #{pr} at {head[:9]}{on_both}" if fixes else f"main {main[:9]} against main + #{pr} at {head[:9]}")
        out += [f"Ran this on {where}",
                f"{against}, same machine and session, {count(a, b)} in the order {order}"
                + (f", window {window}" if window else "") + (f", APS5_TRACE_EVENTS={env['APS5_TRACE_EVENTS']}" if env.get("APS5_TRACE_EVENTS") else "") + "."
                + (" Each side was warmed until it stopped building pipelines, and no timed run built one." if quiet else "")
                + (f" {title['save']}" if title.get("save") else ""),
                "",
                f"Frame p50: main {ms(pa)} ms, with #{pr} {ms(pb)} ms ({diff:+.1f} ms, {pct:+.1f} %)."
                + (f" GPU busy per present: {ms(ga)} -> {ms(gb)} ms." if all(v is not None for v in ga + gb) else ""),
                *([f"p99: main {ms(qa)} ms, with #{pr} {ms(qb)} ms."] if all(v is not None for v in qa + qb) else []),
                "Not tested: other scenes, other GPUs.",
                "AI-assisted: yes",
                "",
                f"Summary lines ({'main' + carried if fixes else 'main'}, then with #{pr}):",
                "```"] + [summary_line(r, title.get("runs_dir")) for r in a + b] + ["```", ""]
        out += traces_text(attachments({"pr": pr, "titles": {title_id: title}}), digests)
    return "\n".join(out).rstrip("\n") + "\n"


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


SIDE_KEYS = ("p50", "p90", "p99", "gpu")


def result_of(results):
    """A job's results (job.run) as the verdict reads them: {"status", "titles": {title ID: {"sides", "outcome"}}, and
    "error" when there is one}, every text cleaned of markup characters."""
    titles = {}
    for title_id, entry in results.get("titles", {}).items():
        sides = (entry.get("verdict") or {}).get("sides", {})
        titles[title_id] = {"sides": {key: {m: sides[key].get(m, []) for m in SIDE_KEYS} for key in sides},
                            "outcome": {key: clean(entry.get("outcome", {}).get(key, "not run")) for key in ("A", "B")}}
    out = {"status": results.get("status", "failed"), "titles": titles}
    if results.get("error") or results.get("detail"):
        out["error"] = clean(results.get("error") or results.get("detail"), 300)
    return out


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
