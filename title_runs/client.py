"""The tester's client: read the queue from the public results repository, choose a job by the score, claim it with a
comment on the job's issue, build and run it (job.run), report the result with another comment. The tray and the
window read its status file and write its requests (pause, stop).

Nothing runs until the tester has been through the walkthrough, signed in through the App and a maintainer has
approved the machine (ready()). Approval is per commit: the client builds the queue entry's SHA merged onto main,
asks the queue again just before building and between runs, and stops when the entry has moved on. A head the queue
has not approved runs only after the trust dialog, and its result is marked "tester".
"""

import datetime
import json
import os
import re
import shutil
import time
from pathlib import Path

from . import auth, config as configs, formats, gh, job, locks, platform_info, schedule, store, trust, verdict

VERSION = "anyps5-title-runs 0.3"
STALE_HOURS = 1  # the relay workflow last ran longer ago than this: warn
RENEW_MINUTES = 45
LOCAL_ONLY = "local tests only"  # ready()'s reason with no results repository: everything a local test needs is set up
UNSAFE = re.compile(r"[<>`|\r\n\x00-\x08\x0b-\x1f]")
STAGE = re.compile(r"^(?:[AB]: |#\d+: |not built)")  # job.run's stage lines (merge, submodules, builds): shown as progress


def clean(text, limit=120):
    return UNSAFE.sub(" ", str(text or ""))[:limit].strip()


class Status:
    """status.json: what the client does now, for the tray and the window; requests from them (pause, stop) too."""

    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        try:
            return json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return {"state": "idle", "line": "Idle"}

    def update(self, **values):
        with locks.held(self.path):  # the window, the command line and the running test all write it
            data = self.read()
            data.update(values, updated=formats.iso(formats.now()))
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, indent=1))
            os.replace(temporary, self.path)
            return data


def machine_line(results):
    """"GPU, driver D, OS" from the job's first timed run's summary line, else its boot runs."""
    for entry in results.get("titles", {}).values():
        for run in entry.get("ab", {}).get("runs", []):
            s = run.get("summary")
            if s:
                return f"{s.get('gpu', '?')}, driver {s.get('driver', '?')}, {s.get('os', '?')}"
        for summary in (entry.get("boot") or {}).values():
            if summary:
                m = summary.get("machine", {})
                return f"{m.get('gpu', '?')}, driver {m.get('driver', '?')}, {m.get('os', '?')}"
    return "?"


def to_result(results, head, machine, tester, info, trust_mark):
    """A job's results (job.run) as the results file (FORMATS.md), every text cleaned of markup characters."""
    titles = {}
    for title_id, entry in results.get("titles", {}).items():
        v = entry.get("verdict") or {}
        sides = v.get("sides", {})
        ab = entry.get("ab") or {}
        counted = [r for r in ab.get("runs", []) if r.get("counts") and r.get("summary")]
        titles[title_id] = {
            "name": clean(entry.get("name", ""), 80), "version": clean(entry.get("version", ""), 20), "scene": clean(entry.get("scene", "")),
            "outcome": {key: clean(entry.get("outcome", {}).get(key, "not run")) for key in ("A", "B")},
            "verdict": {k: v.get(k) for k in ("verdict", "diff", "diff_pct", "spread", "gpu_diff")} if v else None,
            "sides": {key: {m: sides[key].get(m, []) for m in formats.SIDE_KEYS} for key in sides},
            "summary_lines": {key: [json.dumps(r["summary"], separators=(",", ":")).replace("```", "'''") for r in counted if r["side"] == key]
                              for key in ("A", "B")},
            "not_counted": [clean(f"{r['run']}: {r.get('capture', '')}", 300) for r in ab.get("runs", []) if not r.get("counts")]}
        if entry.get("scenario"):
            titles[title_id]["scenario"] = entry["scenario"]
    data = {"format": formats.FORMAT, "job": formats.job_id(results["pr"], head), "pr": results["pr"], "head": head,
            "base": results.get("base", ""), "merge": results.get("merge", ""), "machine": machine, "tester": tester, "class": info,
            "machine_line": clean(machine_line(results) if titles else f"{info['gpu']}, {info['os']}", 160), "trust": trust_mark,
            "sandbox": results.get("sandbox", "bwrap"), "status": results.get("status", "failed"), "started": formats.iso(formats.parse_time(results["started"])),
            "finished": formats.iso(formats.parse_time(results.get("finished", results["started"]))), "titles": titles}
    if results.get("error") or results.get("detail"):
        data["error"] = clean(results.get("error") or results.get("detail"), 300)
    for key in ("base", "merge"):
        if not data[key]:
            del data[key]
    return formats.check_result(data, formats.result_path(data["job"], machine))


class NotReady(RuntimeError):
    pass


class Client:
    def __init__(self, config, log=print, info=None):
        self.config = config
        self.dir = Path(config.state_dir) / "client"

        def both(text):
            # The window's Logs box reads client.log, whether the client runs in the window or on the command line.
            self.dir.mkdir(parents=True, exist_ok=True)
            with open(self.dir / "client.log", "a") as stream:
                stream.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {text}\n")
            log(text)

        self.log = both
        # Local tests only: a folder that never exists, so no checkout of another testing setup sharing this state
        # folder is read (its maintainers, its relay's last run, its registrations).
        self.repo = store.ResultsRepo(config.results_url, self.dir / ("no-results" if self.local_only() else "results"))
        self.endpoint = config.results_github
        self.trust = trust.TrustStore(self.dir / "trust.json")
        self.status = Status(self.dir / "status.json")
        self.info = info or config.machine_info or platform_info.machine_info()
        self.machine_class = formats.machine_class(self.info["gpu"], self.info["os"], self.info.get("driver", ""))
        self._flow = None

    # -- sign-in, registration, the walkthrough -----------------------------------------------------------------------

    def local_only(self):
        """No results repository and an App to sign in with (results.app): the project hasn't set up testing with this
        tool, so only the tester's local tests run, and nothing is registered. Without either, a new tester hasn't joined
        a results repository yet."""
        return not self.config.results_url and bool(self.config.results_app)

    def flow(self):
        if self._flow is None:
            client_id = (self.config.results_app if self.local_only() else
                         (self.repo.read("config.json", {}).get("app") or {}).get("client_id", ""))
            self._flow = auth.DeviceFlow(client_id, self.dir / "github-token.json", self.endpoint)
        return self._flow

    def use(self, location, github=None):
        """Switch to another results repository (OWNER/NAME, a URL or, for the stand-in, a path): the checkout starts
        afresh, the registration is the new repository's, and the sign-in is kept only when the new repository names the
        same App. Returns the URL. The caller saves the config."""
        url = configs.results_location(location)
        if not url:
            raise ValueError("no results repository given")
        fresh = store.ResultsRepo(url, self.dir / "results-new")
        shutil.rmtree(fresh.dir, ignore_errors=True)
        fresh.sync()  # raises when it cannot be read; nothing has changed then
        fresh.config()
        shutil.rmtree(self.dir / "results", ignore_errors=True)
        fresh.dir.rename(self.dir / "results")
        self.config.results_url = url
        if github is not None:
            self.config.results_github = github
        elif url.startswith("https://github.com/"):
            self.config.results_github = "github"
        self.endpoint = self.config.results_github
        self.repo = store.ResultsRepo(url, self.dir / "results")
        self._flow = None
        self.log(f"results repository: {url} ({self.repo.read('config.json', {}).get('results_repository', '?')})")
        return url

    def tester(self):
        return self.flow().login()

    def maintainer(self):
        return bool(self.tester()) and self.tester() in self.repo.read("config.json", {}).get("maintainers", [])

    def github(self):
        """The results repository as the signed-in tester."""
        return auth.repo_as_tester(self.endpoint, self.repo.config()["results_repository"], self.flow())

    def onboarded(self):
        return (self.dir / "onboarding.json").exists()

    def finish_onboarding(self, answers):
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "onboarding.json").write_text(json.dumps({"completed": formats.iso(formats.now()), **answers}, indent=1))

    def registration(self):
        """("approved" | "pending" | "declined" | "not registered", the registry's record or None)."""
        login = self.tester()
        if not login:
            return "not registered", None
        key = formats.machine_key(login, self.config.machine)
        registry = self.repo.registry()
        for state in ("machines", "pending", "declined"):
            if key in registry.get(state, {}):
                return {"machines": "approved", "pending": "pending", "declined": "declined"}[state], registry[state][key]
        mine = (self.dir / "registration.json")
        if mine.exists():
            record = json.loads(mine.read_text())
            if record.get("repository", self.results_repository()) == self.results_repository():
                return "pending", record
        return "not registered", None

    def results_repository(self):
        return self.repo.read("config.json", {}).get("results_repository", "")

    def register(self):
        """Open the machine's registration issue in the results repository (as the tester)."""
        login = self.tester()
        if not formats.MACHINE.fullmatch(self.config.machine or ""):
            raise ValueError(f"the machine name {self.config.machine!r} is not 1 to 32 letters, digits and hyphens, starting with a letter or digit")
        data = {"format": formats.FORMAT, "tester": login, "machine": self.config.machine, "class": self.machine_class,
                "titles": sorted(self.config.titles)}
        body = formats.payload_body("register", data, f"Registration of {login}/{self.config.machine}: {self.info['gpu']}, "
                                    f"{self.info.get('driver', '')}, {self.info['os']}. A maintainer approves it by adding the label `approved`.")
        number = self.github().create_issue(f"Machine: {login}/{self.config.machine}", body)
        (self.dir / "registration.json").write_text(json.dumps({"issue": number, "opened": formats.iso(formats.now()),
                                                                "repository": self.results_repository()}))
        self.log(f"registration issue #{number} opened for {login}/{self.config.machine}")
        return number

    def ready(self):
        """(True, "") once the tester has been through the walkthrough, is signed in and the machine is approved."""
        if not self.onboarded():
            return False, "the first-run walkthrough is not done"
        if not self.config.titles:
            return False, "no titles are set up"
        if not self.tester():
            return False, "not signed in"
        if self.local_only():
            return False, LOCAL_ONLY
        state, _ = self.registration()
        if state != "approved":
            return False, {"pending": "waiting for a maintainer to approve this machine", "declined": "a maintainer declined this machine",
                           "not registered": "this machine is not registered"}[state]
        return True, ""

    def stale(self):
        """Hours since the relay workflow last ran, when that is more than STALE_HOURS (GitHub can drop scheduled runs,
        and disables a schedule after 60 days without activity)."""
        last = self.repo.cursors().get("last_run")
        if not last:
            return None
        hours = (formats.now() - formats.parse_time(last)).total_seconds() / 3600
        return hours if hours > STALE_HOURS else None

    # -- the queue -----------------------------------------------------------------------------------------------------

    def machine(self):
        return schedule.Machine(self.config.machine, self.tester() or self.config.tester, self.machine_class, set(self.config.titles))

    def ranked(self, sync=True):
        if sync:
            self.repo.sync()
        return schedule.rank(self.repo.queue(), self.machine(), self.repo.claims(), self.repo.results(),
                             rules=verdict.settings(self.repo.read("config.json", {})))

    def next_job(self, sync=True):
        best = next(iter(self.ranked(sync)), None)
        return best if best is not None and best.score > 0 else None

    def allowed_now(self, at=None):
        """(True, "") when work may start now: ready, and the schedule allows it."""
        ready, why = self.ready()
        if not ready:
            return False, why
        at = at or datetime.datetime.now().astimezone()
        rules = self.config.schedule
        paused = self.status.read().get("paused_until")
        if paused == "indefinitely" or (paused and formats.parse_time(paused) > at):
            return False, "paused" if paused == "indefinitely" else f"paused until {formats.parse_time(paused).astimezone():%H:%M}"
        first, last = rules.get("hours", [0, 24])
        if not first <= at.hour < last:
            return False, f"outside the hours {first:02d}-{last:02d}"
        if rules.get("mains_only", True) and platform_info.on_mains() is False:
            return False, "on battery"
        busy = platform_info.running(rules.get("pause_for", [])) + (["a fullscreen program"] if rules.get("pause_fullscreen", True) and platform_info.fullscreen() else [])
        if busy:
            return False, f"{', '.join(busy)} is running"
        if rules.get("idle_only", True) and platform_info.idle_detection()[0]:
            idle = platform_info.idle_seconds()
            if idle is not None and idle < 60 * rules.get("idle_minutes", 10):
                return False, f"in use (idle {idle / 60:.0f} of {rules.get('idle_minutes', 10)} min)"
        return True, ""

    # -- claims and results, as comments -----------------------------------------------------------------------------

    def live_claims(self, issue):
        """{machine: claim with its comment} on a job issue, read fresh from GitHub: withdrawn, reported and expired
        claims out (a machine that has reported no longer stands in the way of another machine of its class)."""
        claims = {}
        for note in self.github().comments(issue=issue):
            kind, data = formats.payload(note["body"])
            if kind == "claim" and isinstance(data, dict) and data.get("tester") == note["user"]:
                claims[data.get("machine")] = {**data, "comment": note["id"], "at": note["created_at"]}
            elif kind in ("withdraw", "result") and isinstance(data, dict):
                if claims.get(data.get("machine"), {}).get("tester") == note["user"]:
                    del claims[data["machine"]]
        return {m: c for m, c in claims.items() if not formats.claim_expired(c)}

    def withdraw(self, issue, claim, reason):
        self.github().create_comment(issue, formats.payload_body("withdraw", {"machine": claim["machine"], "job": claim["job"]},
                                                                  f"{claim['machine']} withdraws its claim: {reason}."))
        self.log(f"withdrew the claim on #{issue}: {reason}")

    def recheck(self, pr, head, trust_mark):
        """None while head may still run, else why not: the queue moved on, the job issue closed, or the tester's trust
        was revoked."""
        if self.status.read().get("stop_requested"):
            return "stopped by the tester"
        self.repo.sync()
        if trust_mark == "queue":
            entry = next((e for e in self.repo.queue()["entries"] if e["pr"] == pr), None)
            if entry is None:
                return f"#{pr} is no longer queued"
            if entry["head"] != head:
                return f"the queue now approves {entry['head'][:9]}, not {head[:9]}"
            return None
        author = self.status.read().get("job", {}).get("author", "")
        return None if self.trust.allows(pr, author, head) else f"the trust for {head[:9]} was revoked"

    def run(self, pr, head, trust_mark="queue", title="", author=""):
        """Claim, build, run, report. Returns the result, or None when the job stopped before anything was built."""
        ready, why = self.ready()
        if not ready:
            raise NotReady(why)
        self.repo.sync()
        login = self.tester()
        job_id = formats.job_id(pr, head)
        if trust_mark == "queue":
            entry = next((e for e in self.repo.queue()["entries"] if e["pr"] == pr), None)
            if entry is None or entry["head"] != head:
                raise RuntimeError(f"not claimed: #{pr} at {head[:9]} is not what the queue approves")
            issue = entry.get("issue")
            if not issue:
                raise RuntimeError(f"not claimed: the workflow has not opened #{pr}'s job issue yet")
            key = verdict.class_of(self.machine_class)
            rivals = {m: c for m, c in self.live_claims(issue).items() if m != self.config.machine and verdict.class_of(c["class"]) == key}
            if rivals:
                raise RuntimeError(f"not claimed: {', '.join(rivals)} ({key}) claimed it first")
            claim = formats.make_claim(job_id, self.config.machine, login, self.machine_class, set(self.config.titles), head=head, client=VERSION)
            mine = self.github().create_comment(issue, formats.payload_body("claim", claim, f"{login}/{self.config.machine} claims {job_id}."))
            first = sorted((c for m, c in self.live_claims(issue).items() if verdict.class_of(c["class"]) == key), key=lambda c: (c["at"], c["comment"]))
            if first and first[0]["comment"] != mine:
                self.withdraw(issue, claim, f"{first[0]['machine']} claimed it first")
                raise RuntimeError(f"not claimed: {first[0]['machine']} claimed it first")
        else:
            if not self.trust.allows(pr, author, head):
                raise RuntimeError(f"not claimed: no trust for {author}'s #{pr} at {head[:9]}")
            issue = self.repo.cursors().get("tester_trust_issue")
            claim = None
        self.status.update(state="running", line=f"Running: #{pr} · {', '.join(self.config.titles)} · starting", progress="starting", stop_requested=False,
                           job={"pr": pr, "head": head, "title": title, "author": author, "trust": trust_mark, "issue": issue})
        self.log(f"claimed {job_id} on #{issue}" if claim else f"running {job_id} on the tester's trust")

        def progress(text):
            self.status.update(line=f"Running: #{pr} · {', '.join(self.config.titles)} · {text}", progress=text)

        def note(text):
            self.log(text)
            if STAGE.match(text):
                progress(text)

        results = job.run(self.config, self.config.state_dir, pr, head, note,
                          recheck=lambda: self.recheck(pr, head, trust_mark), progress=progress, should_stop=lambda: self.recheck(pr, head, trust_mark))
        if self.status.read().get("stop_requested"):
            # The tester stopped it: whatever the killed run left is not a result. Nothing is posted.
            if claim:
                self.withdraw(issue, claim, "stopped by the tester")
            self.status.update(state="idle", line=f"Stopped #{pr}", job={}, progress="")
            return None
        if results["status"] == "superseded" and not results.get("titles"):
            if claim:
                self.withdraw(issue, claim, results["detail"])
            self.status.update(state="idle", line=f"Stopped #{pr}: {results['detail']}", job={})
            return None
        data = to_result(results, head, self.config.machine, login, self.machine_class, trust_mark)
        if issue is None:
            raise RuntimeError("the results repository has no issue for runs on testers' trust yet")
        comment_id = self.github().create_comment(issue, formats.payload_body("result", data, f"{login}/{self.config.machine}: {data['status']}."))
        recent = [{"pr": pr, "head": head, "status": data["status"], "at": formats.iso(formats.now()), "issue": issue, "comment": comment_id}] \
            + self.status.read().get("recent", [])[:9]
        self.status.update(state="error" if data["status"] == "failed" else "idle", line=f"Reported #{pr}: {data['status']}", job={}, recent=recent)
        self.log(f"reported {job_id} on #{issue} ({data['status']})")
        return data

    def run_next(self):
        """Run the best-scoring job, if the client is ready and the schedule allows it now, and no other process is
        testing on this computer (the runner lock: then the status file is theirs)."""
        runner = locks.Runner(self.config.state_dir)
        holder = runner.holder()
        if holder not in (None, os.getpid()):
            return f"another title-runs process (pid {holder}) is testing on this computer"
        allowed, why = self.allowed_now()
        if not allowed:
            self.status.update(state="idle", line=f"Waiting: {why}")
            return why
        best = self.next_job()
        if best is None:
            self.status.update(state="idle", line="Idle: nothing in the queue for this machine")
            return "nothing to do"
        entry = best.entry
        self.status.update(next={"pr": entry["pr"], "priority": entry["priority"], "reasons": best.reasons})
        try:
            with runner.hold(self.status, platform_info.stop_children):
                self.run(entry["pr"], entry["head"], "queue", entry.get("title", ""), entry.get("author", ""))
        except locks.Busy as error:
            return str(error)
        return f"ran {entry['job']}"

    def daemon(self, every=60):
        while True:
            try:
                self.log(self.run_next())
            except Exception as error:  # noqa: BLE001  (the tray shows it; the loop goes on)
                self.status.update(state="error", line=f"Error: {clean(error, 200)}")
                self.log(f"error: {error}")
            time.sleep(every)
