"""The tester's client: read the queue from the results repository, choose a job by the score, claim it, build and run
it (job.run), push the result. The tray and the window read its status file and write its requests (pause, stop).

Approval is per commit: the client builds the queue entry's SHA merged onto main, asks the queue again just before
building (job.run's recheck) and between runs, and stops when the entry has moved on. A head the queue has not
approved runs only after the trust dialog, and its result is marked "tester".
"""

import datetime
import json
import os
import re
import time
from pathlib import Path

from . import formats, job, platform_info, report, schedule, store, trust

VERSION = "anyps5-title-runs 0.2"
RENEW_MINUTES = 45
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
        data = self.read()
        data.update(values, updated=formats.iso(formats.now()))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=1))
        os.replace(temporary, self.path)
        return data


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
    data = {"format": formats.FORMAT, "job": formats.job_id(results["pr"], head), "pr": results["pr"], "head": head,
            "base": results.get("base", ""), "merge": results.get("merge", ""), "machine": machine, "tester": tester, "class": info,
            "machine_line": clean(report.machine_line(results) if titles else f"{info['gpu']}, {info['os']}", 160), "trust": trust_mark,
            "sandbox": results.get("sandbox", "bwrap"), "status": results.get("status", "failed"), "started": formats.iso(formats.parse_time(results["started"])),
            "finished": formats.iso(formats.parse_time(results.get("finished", results["started"]))), "titles": titles}
    if results.get("error") or results.get("detail"):
        data["error"] = clean(results.get("error") or results.get("detail"), 300)
    for key in ("base", "merge"):
        if not data[key]:
            del data[key]
    return formats.check_result(data, formats.result_path(data["job"], machine))


class Client:
    def __init__(self, config, log=print, info=None):
        self.config, self.log = config, log
        self.dir = Path(config.state_dir) / "client"
        token_file = self.dir / "results-token"
        if config.results_token_env and not os.environ.get(config.results_token_env) and token_file.exists():
            # The token the setup window saved (mode 0600); git gets it through the credential helper (store.py).
            os.environ[config.results_token_env] = token_file.read_text().strip()
        self.repo = store.ResultsRepo(config.results_url, self.dir / "results", config.results_token_env, config.state_branch,
                                      author=(config.tester or "tester", f"{config.tester or 'tester'}@users.noreply.github.com"))
        self.trust = trust.TrustStore(self.dir / "trust.json")
        self.status = Status(self.dir / "status.json")
        self.info = info or config.machine_info or platform_info.machine_info()
        self.machine_class = formats.machine_class(self.info["gpu"], self.info["os"])

    # -- the queue -----------------------------------------------------------------------------------------------------

    def machine(self):
        return schedule.Machine(self.config.machine, self.config.tester, self.machine_class, set(self.config.titles))

    def ranked(self, sync=True):
        if sync:
            self.repo.sync()
        return schedule.rank(self.repo.queue(), self.machine(), self.repo.claims(), self.repo.results())

    def next_job(self, sync=True):
        best = next(iter(self.ranked(sync)), None)
        return best if best is not None and best.score > 0 else None

    def allowed_now(self, at=None):
        """(True, "") when the schedule lets work start now, else (False, why)."""
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
        games = platform_info.running(rules.get("pause_for", []))
        if games:
            return False, f"{', '.join(games)} is running"
        if rules.get("idle_only", True):
            idle = platform_info.idle_seconds()
            if idle is not None and idle < 60 * rules.get("idle_minutes", 10):
                return False, f"in use (idle {idle / 60:.0f} of {rules.get('idle_minutes', 10)} min)"
        return True, ""

    # -- a job ---------------------------------------------------------------------------------------------------------

    def recheck(self, pr, head, trust_mark):
        """None while head may still run, else why not: the queue moved on, or the tester's trust was revoked."""
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

    def renew(self, claim):
        if formats.parse_time(claim["expires"]) - formats.now() < datetime.timedelta(minutes=RENEW_MINUTES):
            fresh = formats.make_claim(claim["job"], claim["machine"], claim["tester"], claim["class"], claim["titles"], head=claim["head"], client=VERSION)
            claim.update(fresh)
            self.repo.write({formats.claim_path(claim["job"], claim["machine"]): claim}, f"renew claim {claim['job']} ({claim['machine']})")

    def run(self, pr, head, trust_mark="queue", title="", author=""):
        """Claim, build, run, push the result. Returns the result file's data, or None when the job stopped before
        anything was built (its claim is then withdrawn)."""
        if trust_mark == "queue":
            stop = self.recheck(pr, head, "queue")
            if stop:
                raise RuntimeError(f"not claimed: {stop}")
        elif not self.trust.allows(pr, author, head):
            raise RuntimeError(f"not claimed: no trust for {author}'s #{pr} at {head[:9]}")
        self.repo.sync()
        job_id = formats.job_id(pr, head)
        claim = formats.make_claim(job_id, self.config.machine, self.config.tester, self.machine_class, set(self.config.titles),
                                   head=head, client=VERSION)
        self.repo.write({formats.claim_path(job_id, self.config.machine): claim}, f"claim {job_id} ({self.config.machine})")
        self.status.update(state="running", line=f"Running: #{pr} · {', '.join(self.config.titles)} · starting", progress="starting", stop_requested=False,
                           job={"pr": pr, "head": head, "title": title, "author": author, "trust": trust_mark, "claimed": claim["claimed"]})
        self.log(f"claimed {job_id}")

        def progress(text):
            self.status.update(line=f"Running: #{pr} · {', '.join(self.config.titles)} · {text}", progress=text)

        def should_stop():
            reason = self.recheck(pr, head, trust_mark)
            if not reason:
                self.renew(claim)
            return reason

        def note(text):
            self.log(text)
            if STAGE.match(text):
                progress(text)

        results = job.run(self.config, self.config.state_dir, pr, head, note,
                          recheck=lambda: self.recheck(pr, head, trust_mark), progress=progress, should_stop=should_stop)
        if results["status"] == "superseded" and not results.get("titles"):
            self.repo.sync()
            self.repo.write({formats.claim_path(job_id, self.config.machine): None}, f"withdraw claim {job_id}: {results['detail'][:80]}")
            self.status.update(state="idle", line=f"Stopped #{pr}: {results['detail']}", job={})
            self.log(f"withdrew the claim: {results['detail']}")
            return None
        data = to_result(results, head, self.config.machine, self.config.tester, self.machine_class, trust_mark)
        self.repo.sync()
        self.repo.write({formats.result_path(job_id, self.config.machine): data}, f"result {job_id} ({self.config.machine}): {data['status']}")
        recent = [{"pr": pr, "head": head, "status": data["status"], "at": formats.iso(formats.now())}] + self.status.read().get("recent", [])[:9]
        self.status.update(state="error" if data["status"] == "failed" else "idle", line=f"Posted #{pr}: {data['status']}", job={}, recent=recent)
        self.log(f"pushed {formats.result_path(job_id, self.config.machine)} ({data['status']})")
        return data

    def run_next(self):
        """Run the best-scoring job, if the schedule allows one now. Returns what happened, for the log."""
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
        self.run(entry["pr"], entry["head"], "queue", entry.get("title", ""), entry.get("author", ""))
        return f"ran {entry['job']}"

    def daemon(self, every=60):
        while True:
            try:
                self.log(self.run_next())
            except Exception as error:  # noqa: BLE001  (the tray shows it; the loop goes on)
                self.status.update(state="error", line=f"Error: {clean(error, 200)}")
                self.log(f"error: {error}")
            time.sleep(every)
