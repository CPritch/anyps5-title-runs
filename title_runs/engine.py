"""The tester's engine, without the window: local tests, the testing switch, the schedule, the listing and what the
window and the command line show, from the state directory and the config. The window (ui/app.py) and the command
line (cli.py) both drive it; neither needs the other.

Its worker (start()) runs local tests on a thread of its own, when the testing switch and the schedule let one start.
"""

import datetime
import os
import queue as queues
import subprocess
import threading
from pathlib import Path

from . import client as clients, config as configs, configfile, formats, gh, listing as listings, locks, platform_info, sandbox, scenarios
from .ui import model


class Engine:
    def __init__(self, config, listing=None, auto=False):
        self.config = config
        if auto:
            config.testing = "schedule"
        self.quitting = False
        self.thread = None
        self.dir = Path(config.state_dir) / "client"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.client = clients.Client(config, log=lambda text: None)
        from . import local_tests
        self.local = local_tests.LocalTests(config, log=self.log)
        self._local_checked = None
        self.github_wait = None  # GitHub's limit is used up until then (gh.RateLimited)
        self.listing_file = Path(listing) if listing else None
        self.window = None
        self.work = queues.Queue()
        self.dumps = {}
        for title_id, title in config.titles.items():
            found = platform_info.find_dumps(title.dump, depth=0)
            if found:
                self.dumps[title_id] = found[0]
        self.names = model.title_names(config, list(self.dumps.values()))
        self._config_lock = threading.Lock()
        self._config_base, self._config_mtime = configfile.snapshot(config), self._config_time()
        self.runner = locks.Runner(config.state_dir)

    # -- data for the UI -----------------------------------------------------------------------------------------------

    def log(self, text):
        with open(self.dir / "client.log", "a") as stream:
            stream.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {text}\n")

    def log_dir(self):
        return self.dir

    def log_tail(self, lines=12):
        """The client log's last lines, and the latest job's own log."""
        path = self.dir / "client.log"
        out = path.read_text().splitlines()[-lines:] if path.exists() else []
        jobs = sorted(Path(self.config.state_dir).glob("jobs/*/job.log"), key=lambda p: p.stat().st_mtime)
        if jobs:
            out += [f"--- {jobs[-1].parent.name}/job.log"] + jobs[-1].read_text().splitlines()[-lines:]
        return "\n".join(out)

    def status(self):
        return self.client.status.read()

    def readiness(self):
        """(ready, why, the button that fixes it or "")."""
        ready, why = self.client.ready()
        if ready:
            return True, "", ""
        fix = {"the first-run walkthrough is not done": "Finish the walkthrough", "no titles are set up": "Finish the walkthrough",
               "not signed in": "Sign in…"}.get(why, "")
        return False, why, fix

    def local_notice(self):
        """What the tester should know about local tests: paused because their main doesn't start the game, or GitHub's
        limit used up, so new heads show up late."""
        notes = []
        paused = self.local.held() if self.local.enabled() else None
        if paused:
            notes.append(f"<b>Local tests are paused</b>: {paused['reason'][:240]}. They try again with the next main, or when you change "
                         f"the fixes on the Local tests page.")
        if self.github_wait and formats.now() < self.github_wait:
            notes.append(f"<b>GitHub's limit for reading without a sign-in is used up</b> until {self.github_wait.astimezone():%H:%M}, so "
                         f"new pushes show up after that.")
        return "<br>".join(notes)

    @property
    def repository(self):
        """The project local tests come from, OWNER/NAME."""
        return self.config.local_repository

    def pull_url(self, number):
        return f"https://github.com/{self.repository}/pull/{number}"

    def open_url(self, url):
        """A GitHub link in the browser. The window opens it through the desktop."""
        if url.startswith("https://"):
            import webbrowser
            webbrowser.open(url)

    def listing_store(self):
        """The listing of the local tests' project."""
        if self.listing_file:
            return listings.Listing(self.listing_file)
        return listings.Listing.of(self.config.state_dir, self.repository)

    def listing(self):
        store = self.listing_store()
        if store.data.get("repository", self.repository) != self.repository:
            return []
        return store.open()

    def listing_note(self):
        store = self.listing_store()
        when = store.refreshed()
        note = (f"Pull requests of {self.repository}, listed {formats.parse_time(when).astimezone():%H:%M}" if when
                else f"Pull requests of {self.repository}: not listed yet, Refresh reads them")
        if self.github_wait and formats.now() < self.github_wait:
            note += f" (GitHub's limit is used up until {self.github_wait.astimezone():%H:%M})"
        return note

    def refresh_listing(self):
        """Read the project's open pull requests again (the worker thread only, when the tester presses Refresh)."""
        if self.listing_file or "/" not in (self.repository or ""):
            return
        if self.github_wait and formats.now() < self.github_wait:
            return
        try:
            count = self.listing_store().refresh(gh.GitHubRepo(self.repository))
            self.log(f"listed {count} open pull requests of {self.repository}")
        except gh.RateLimited as error:
            self.limited(error)
        except Exception as error:  # noqa: BLE001 (the listing is a convenience; local tests do not depend on it)
            self.log(f"could not list the pull requests of {self.repository}: {error}")

    def sections(self, query=""):
        return model.pr_sections(self.listing(), set(self.config.local_prs), self.names, query)

    def waiting(self):
        return model.waiting_for_you(self.sections())

    def tray_view(self):
        waiting = self.waiting()
        state, lines = model.tray_view(self.status(), self.up_next_rows(), waiting, self.config.testing)
        ready, why, _ = self.readiness()
        if not ready:
            lines = [f"Doesn't test yet: {why}"] + [line for line in lines[1:]]
            state = "waiting" if state == "idle" else state
        return state, lines, waiting

    def titles(self):
        rows = []
        for title_id, title in self.config.titles.items():
            dump = self.dumps.get(title_id, {})
            found = scenarios.available(title_id)
            choices = [{"id": key, "name": s["name"], "scene": s["scene"], "save": scenarios.save_words(s)} for key, s in found.items()]
            current = title.scenario or next((key for key, s in found.items() if s.get("default")), "")
            rows.append({"on": True, "title_id": title_id, "name": dump.get("name", "?"), "version": dump.get("version", "?"),
                         "check": "Full test" if title.route or choices else "Start-up check", "seeds": f"{len(title.seed)} file(s)" if title.seed else "none",
                         "seed_paths": [str(p) for p in title.seed], "path": str(title.dump), "scenario": current, "scenarios": choices})
        return rows

    def set_scenario(self, title_id, scenario_id):
        """The Titles page's Scenario: the next tests of this title run in it (a scenario's runs and warm-ups are its own)."""
        self.config.titles[title_id].scenario = scenario_id
        self.save_config()

    def allowed_now(self):
        return self.client.allowed_now()

    # -- the main screen -----------------------------------------------------------------------------------------------

    def up_next_rows(self):
        """The heads waiting to be tested, in the order they will be, without the one running."""
        job = self.status().get("job") or {}
        rows = []
        for entry in self.local.queued() if self.local.enabled() else []:
            if job.get("pr") == entry["pr"] and job.get("head") == entry["head"]:
                continue
            rows.append({"number": entry["pr"], "title": entry["title"], "author": entry["author"], "head": entry["head"],
                         "added": entry["added"], "why": "Waiting to be tested again" if entry.get("again") else "Waiting to be tested"})
        return rows

    def recent_rows(self):
        """The results, newest first, each with its report's state."""
        if not self.local.enabled():
            return []
        data = self.local.read()
        done = [e for e in data["entries"] if e["status"] in ("done", "failed")]
        return [{"number": e["pr"], "head": e["head"], "at": e.get("at", ""), "status": e["status"], "verdict": e.get("verdict", e["status"]),
                 "report": report_state(e, data)} for e in reversed(done)]

    # -- local tests (ui/local.py) ---------------------------------------------------------------------------------------

    def local_rows(self):
        data = self.local.read()
        rows = self.local.rows()
        for row in rows:
            row["report"] = report_state(row["entry"], data) if row["entry"]["status"] in ("done", "failed") else ""
        return rows

    def local_results(self, number):
        """The PR's results, newest first, each {"entry", "text" (its report), "stale", "link"}."""
        data = self.local.read()
        done = [e for e in reversed(data["entries"]) if e["pr"] == number and e["status"] in ("done", "failed")]
        from .local_tests import stale
        return [{"entry": e, "text": self.local.report(e), "stale": stale(e, data), "link": self.local.pull_url(number)} for e in done]

    def local_attachments(self, entry):
        """(folder, files): a result's traces for its report, linked into one folder (LocalTests.attach)."""
        return self.local.attach(entry)

    def local_add(self, text):
        number, why = self.local.parse(text)
        if number is None:
            return why
        if number not in self.config.local_prs:
            self.config.local_prs.append(number)
            self.save_config()
        self.local.added(number)
        self.work.put(("local", None))
        return f"Added #{number}. It's read from GitHub within a minute."

    def local_remove(self, number):
        if number in self.config.local_prs:
            self.config.local_prs.remove(number)
            self.save_config()
        self.local.remove(number)

    def local_again(self, number):
        head = self.local.again(number)
        self.work.put(("wake", None))
        return head

    def local_posted(self, number, head, posted=True, at=None):
        return self.local.mark_posted(number, head, posted, at)

    def local_save(self, repository, people, fixes):
        self.config.local_repository, self.config.local_people, self.config.local_fixes = repository, people, fixes
        self.save_config()
        self.work.put(("local", None))

    def local_unpin(self):
        self.local.unpin()
        self.work.put(("wake", None))

    def local_base(self):
        """What local tests are measured against now, in words."""
        pinned = self.local.pinned() or {}
        if not pinned.get("main"):
            fixes = "".join(f" + #{n}" for n in self.config.local_fixes)
            return f"main as it is when the next test starts{fixes}"
        words_ = f"main {pinned['main'][:9]}" + "".join(f" + #{f['pr']}" for f in pinned.get("fixes", []))
        if pinned.get("in_main"):
            words_ += f" (main already has {', '.join('#' + str(n) for n in pinned['in_main'])})"
        return f"{words_}, since {formats.utc_text(pinned['at'])}"

    def home(self):
        ready, why, _ = self.readiness()
        best = next(iter(self.up_next_rows()), None)
        allowed, allowed_why = self.allowed_now() if ready else (False, why)
        return model.header(self.status(), ready, why, self.config.testing, allowed, allowed_why, best)

    # -- requests from the UI ------------------------------------------------------------------------------------------

    def request_stop(self):
        self.client.status.update(stop_requested=True)

    def running(self):
        return self.status().get("state") == "running"

    def set_testing(self, mode):
        """The switch: off (no test starts), schedule (tests start within the schedule) or now (one after another,
        whatever the schedule says, until switched back). A running test goes on; Stop ends it."""
        if mode not in configs.TESTING:
            raise ValueError(f"testing must be one of {', '.join(configs.TESTING)}, not {mode!r}")
        self.config.testing = mode
        self.save_config()
        self.log(f"testing: {mode}")
        self.work.put(("wake", None))

    def stop(self, quitting=False):
        """Stop the running test at once: its build or game is ended, and the head waits to be tested again. The switch
        goes to Off, so another test doesn't start a minute later."""
        self.client.status.update(stop_requested=True)
        if self.config.testing != "off" and not quitting:
            self.config.testing = "off"
            self.save_config()
        ended = platform_info.stop_children()
        self.log(f"stopped{' (quitting)' if quitting else ''}: {ended} process(es) ended")

    def shutdown(self, wait=20):
        """Quit: nothing keeps running after the app (DESIGN.md). Ends the test, then waits for the worker to finish."""
        self.quitting = True
        if self.running():
            self.stop(quitting=True)
        self.work.put(("quit", None))
        if self.thread is not None:
            self.thread.join(wait)
        platform_info.stop_children(grace=1.0)

    def _config_time(self):
        try:
            return self.config.path.stat().st_mtime_ns
        except OSError:
            return None

    def sync_config(self):
        """Take the settings another process (the command line) changed in the config file since this one last read or
        wrote it, unless this one changed them too; a new testing switch or local tests list wakes the worker. Returns
        the names of the settings taken."""
        if self._config_time() == self._config_mtime:
            return []
        with self._config_lock, locks.held(self.config.path):
            mtime = self._config_time()
            if mtime == self._config_mtime:
                return []
            try:
                disk = configs.load(self.config.path)
            except (OSError, ValueError) as error:  # half-written by hand, say: read it again when it changes
                self.log(f"could not read {self.config.path}: {error}")
                self._config_mtime = mtime
                return []
            taken = configfile.merge(self.config, self._config_base, disk)
            self._config_base, self._config_mtime = configfile.snapshot(disk), mtime
        if taken:
            self.log(f"settings changed in {self.config.path}: {', '.join(taken)}")
            if {"testing", "local_prs", "local_people", "local_fixes", "local_repository"} & set(taken):
                self.work.put(("local" if "testing" not in taken else "wake", None))
        return taken

    def save_config(self):
        """Write the config, keeping what another process changed in the file since this one last read or wrote it."""
        with self._config_lock, locks.held(self.config.path):
            if self._config_time() != self._config_mtime:
                try:
                    configfile.merge(self.config, self._config_base, configs.load(self.config.path))
                except (OSError, ValueError):
                    pass
            configfile.save(self.config)
            self._config_base, self._config_mtime = configfile.snapshot(self.config), self._config_time()
        self.log(f"saved {self.config.path}")

    def sandbox_self_test(self):
        if self.config.sandbox != "bwrap":
            return "The sandbox is off."
        probe = ["python3", "-I", "-c", "import socket; socket.create_connection(('1.1.1.1', 443), 3)"]
        net = subprocess.run(sandbox.build_command("bwrap", probe, "/tmp"), capture_output=True)
        home = subprocess.run(sandbox.build_command("bwrap", ["ls", str(Path.home())], "/tmp"), capture_output=True)
        gpu = subprocess.run(sandbox.command("bwrap", ["sh", "-c", "ls /dev/dri /dev/nvidia0 2>/dev/null | head -1"], "/tmp"), capture_output=True, text=True)
        parts = ["no internet" if net.returncode != 0 else "IT CAN REACH THE INTERNET", "your files out of sight" if home.returncode != 0 else "IT CAN SEE YOUR FILES",
                 "the graphics card available to the game" if gpu.stdout.strip() else "no graphics card inside, so games won't run"]
        ok = net.returncode != 0 and home.returncode != 0
        return ("The sandbox works: " if ok else "The sandbox is NOT working: ") + ", ".join(parts) + "."

    def run_local(self):
        """The next head on the local tests list, if there is one. Returns what was done, or None."""
        if not self.local.enabled():
            return None
        queued = self.local.queued()
        if not queued or self.local.held():
            return None
        with self.testing_here():
            result = self.local.run(queued[0], self.client)
        return f"tested #{queued[0]['pr']} (a local test)" if result else f"stopped #{queued[0]['pr']}"

    def testing_here(self):
        """The runner lock for one test (locks.Runner): raises locks.Busy when another process is testing on this
        computer; a stop asked for by another process ends this one's build or game."""
        return self.runner.hold(self.client.status, platform_info.stop_children)

    def busy_elsewhere(self):
        """Who else is testing on this computer, in words, or ""."""
        holder = self.runner.holder()
        return f"another title-runs process (pid {holder}) is testing on this computer" if holder not in (None, os.getpid()) else ""

    def refresh_local(self, force=False):
        """The local tests list from GitHub every 15 minutes (read only, without a sign-in), unless GitHub's limit is
        used up: then not before its reset."""
        if not self.local.enabled():
            return
        now = formats.now()
        if self.github_wait and now < self.github_wait:
            return
        if not force and self._local_checked and now - self._local_checked < datetime.timedelta(minutes=15):
            return
        self._local_checked = now
        try:
            self.local.refresh()
        except gh.RateLimited as error:
            self.limited(error)
        except Exception as error:  # noqa: BLE001
            self.log(f"could not read the local tests list: {error}")

    def limited(self, error):
        """GitHub's limit is used up: nothing more is read from it until its reset."""
        self.github_wait = error.reset
        self.log(f"GitHub's limit for reading without a sign-in is used up: nothing more is read from it until {error.reset:%H:%M} UTC")

    # -- the worker thread ---------------------------------------------------------------------------------------------

    def adopt_old_pause(self):
        """The tray's Pause, from before the switch, is Off now."""
        if self.status().get("paused_until"):
            self.client.status.update(paused_until=None)
            self.config.testing = "off"
            self.save_config()

    def start(self):
        self.adopt_old_pause()
        self.thread = threading.Thread(target=self.worker, daemon=True)
        self.thread.start()

    def next_test(self, now=None):
        """The next local test, if the switch lets one start now: On schedule within the schedule, Now whatever it says
        (now: True for one test whatever the switch says, as `title-runs run --once`). Returns what was done. While
        another process tests on this computer, nothing starts here and the status file is theirs."""
        busy = self.busy_elsewhere()
        if busy:
            return busy
        now = self.config.testing == "now" if now is None else now
        ready, why = self.client.ready()
        allowed = False
        try:
            if ready:
                allowed, why = (True, "") if now else self.client.allowed_now()
                done = self.run_local() if allowed else None
                if done:
                    return done
        except locks.Busy as error:  # another process took the lock since
            return str(error)
        if ready and allowed:
            why = "nothing to test"
        self.client.status.update(state="idle", line=f"Idle: {why}" if why == "nothing to test" else f"Waiting: {why}")
        return why

    def worker(self):
        while not self.quitting:
            try:
                kind, row = self.work.get(timeout=30)
            except queues.Empty:
                kind, row = None, None
            if self.quitting or kind == "quit":
                break
            try:
                self.sync_config()
                if kind == "listing":
                    self.refresh_listing()
                else:
                    if kind == "local":  # the list changed: read it from GitHub before anything starts
                        self.refresh_local(force=True)
                    if self.config.testing != "off":
                        self.log(self.next_test())
                if kind != "listing" and not self.quitting:
                    self.refresh_local()
            except locks.Busy as error:  # another process is testing here: its status stays as it is
                self.log(str(error))
            except Exception as error:  # noqa: BLE001
                if not self.quitting:
                    self.client.status.update(state="error", line=f"Error: {clients.clean(error, 200)}")
                self.log(f"error: {error}")


def report_state(entry, data):
    """A result's report: Posted, Stale (why) or Not posted."""
    from .local_tests import stale
    if entry.get("posted"):
        return "Posted"
    why = stale(entry, data)
    return f"Stale: {why}" if why else "Not posted"


def new_config(path, state_dir=None):
    """A starting config for the walkthrough to fill: the state directory (the user's data folder unless given), the
    App to sign in with, the schedule and the sandbox."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    data = {"state_dir": str(state_dir or configs.user_dirs()[1]), "github": {"app": configs.DEFAULT_APP},
            "schedule": dict(configs.SCHEDULE), "sandbox": {"mode": "bwrap"}}
    Path(path).write_text("# anyps5-title-runs: written by the title-runs window. config.example.toml explains every key.\n\n" + configfile.dumps(data))
