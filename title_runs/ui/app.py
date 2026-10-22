"""The client's application: the engine (client.Client on a worker thread), the tray and the window.

  title-runs ui [--config FILE] [--listing FILE] [--auto]       the tray and the window; the walkthrough on first open
  title-runs ui --config NEW --results URL [--github standin:FILE] [--dumps DIR]   a new config, then the walkthrough
  title-runs ui --screenshots DIR [--config FILE] [--listing FILE] [--no-sync]   render the window's screens to DIR (offscreen)

--listing: the PR listing the Pull requests tab shows (default: the listing of the repository the results repository
names, kept in the state directory's cache and refreshed with the tester's sign-in every 15 minutes or on request). --auto: run the queue's jobs when the schedule allows (otherwise only on request).
All git and build work happens on the engine's worker thread; the UI reads the status file and cached data.
"""

import argparse
import datetime
import json
import queue as queues
import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication

from .. import ROOT, client as clients, config as configs, configfile, formats, platform_info, poller, sandbox, store, verdict
from ..relay import overview
from ..relay.render import utc as utc_text
from . import model, words


class Engine(QObject):
    def __init__(self, config, listing=None, auto=False):
        super().__init__()
        self.config = config
        if auto:
            config.automatic = True
        self.quitting = False
        self.thread = None
        self.dir = Path(config.state_dir) / "client"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.client = clients.Client(config, log=lambda text: None)
        from .. import local_tests
        self.local = local_tests.LocalTests(config, log=self.log)
        self._local_checked = None
        words.set_team(self.client.repo.read("config.json", {}).get("team"))  # the walkthrough reads it before the first load
        self.listing_file = Path(listing) if listing else None
        self.window = None
        self.ranked, self.queue, self.repository = [], {"entries": []}, ""  # the results repository names it (load)
        self.comments = {"prs": {}}
        self.work = queues.Queue()
        self.dumps = {}
        for title_id, title in config.titles.items():
            found = platform_info.find_dumps(title.dump, depth=0)
            if found:
                self.dumps[title_id] = found[0]
        self.names = model.title_names(config, list(self.dumps.values()))

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

    def load(self, sync=False):
        """Read the results repository (sync first when asked: the worker thread only)."""
        try:
            self.ranked = self.client.ranked(sync)
            self.queue = self.client.repo.queue()
            self.repository = self.client.repo.config()["repository"]
            self.comments = self.client.repo.comments()
            repo = self.client.repo
            words.set_team(repo.read("config.json", {}).get("team"))
            self.overview_data = overview.view(repo.dir, self.queue, repo.registry(), repo.claims(), repo.jobs(), repo.cursors().get("last_run"),
                                               verdict.settings(repo.read("config.json", {})), repo.cursors().get("ignored"))
        except Exception as error:  # noqa: BLE001 (shown in the tray)
            self.log(f"could not read the results repository: {error}")

    def overview(self):
        return getattr(self, "overview_data", None) or {"entries": [], "machines": [], "pending": [], "expired": [], "refused": [], "last_run": None}

    def readiness(self):
        """(ready, why, the button that fixes it or "")."""
        ready, why = self.client.ready()
        if ready:
            return True, "", ""
        fix = {"the first-run walkthrough is not done": "Finish the walkthrough", "no titles are set up": "Finish the walkthrough",
               "not signed in": "Sign in…", "this machine is not registered": "Register this machine"}.get(why, "")
        return False, why, fix

    def stale_text(self):
        hours = self.client.stale()
        if hours is None:
            return ""
        if self.client.maintainer():
            return (f"<b>The relay workflow last ran {hours:.0f} h ago.</b> GitHub may have delayed or dropped its scheduled runs, or "
                    f"disabled the schedule after 60 days without activity: the results repository's Actions tab, relay, Enable workflow, "
                    f"Run workflow (its README has the steps).")
        return (f"<b>The test list hasn't updated for {hours:.0f} hours</b>, so new tests may show up late. {words.Team()} can restart it.")

    def local_notice(self):
        """Local tests paused because their main doesn't start the game: what the tester should know."""
        paused = self.local.held() if self.local.enabled() else None
        if not paused:
            return ""
        return (f"<b>Local tests are paused</b>: AnyPS5's main ({paused['main'][:9]}) crashes the game before it starts, so every change "
                f"on it would fail. The game said: {paused['reason'][:200]}")

    def ignored_mine(self):
        """The workflow answers nothing it does not use; the tester's own ignored comments are in its public cursors."""
        login = self.client.tester()
        if not login:
            return ""
        registry = self.client.repo.registry()
        settled = {m.get("issue") for state in ("machines", "pending", "declined") for m in registry.get(state, {}).values()
                   if m.get("tester") == login}
        day_ago = formats.now() - datetime.timedelta(days=1)
        # Only what still stands: not a day old, and not on a registration the workflow has since taken.
        mine = [r for r in (self.client.repo.cursors().get("ignored") or {}).get("recent", [])
                if r.get("user") == login and r.get("issue") not in settled and formats.parse_time(r["at"]) > day_ago]
        if not mine:
            return ""
        last = mine[-1]
        detail = f" ({last.get('detail') or last['reason']})" if self.config.view == "advanced" else ""
        return (f"<b>Your last report wasn't accepted</b> ({utc_text(last['at'])}){detail}. If it happens again, tell {words.team()}.")

    def results_repository(self):
        return self.client.repo.read("config.json", {}).get("results_repository", "?")

    def label(self):
        return self.client.repo.read("config.json", {}).get("label", "title-test")

    def overview_issue(self):
        return self.client.repo.cursors().get("overview_issue")

    def issue_url(self, number):
        return f"https://github.com/{self.results_repository()}/issues/{number}" if number else ""

    def pull_url(self, number):
        return f"https://github.com/{self.repository}/pull/{number}"

    def open_url(self, url):
        if url.startswith("https://") and self.config.results_url.startswith(("https://", "git@", "ssh://")):
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl(url))

    def queue_pr(self, number):
        """A maintainer queues a pull request: the label on it on GitHub, added with their own sign-in (the same as adding
        it there). The workflow picks it up on its next run."""
        if not self.client.maintainer():
            return "Only the people running this testing can queue tests."
        try:
            from .. import auth
            auth.repo_as_tester(self.client.endpoint, self.repository, self.client.flow()).add_labels(number, [self.label()])
        except Exception as error:  # noqa: BLE001
            return f"Could not queue #{number}: {error}"
        self.log(f"queued #{number} (label added)")
        return f"Queued #{number}. It shows in the queue after the workflow's next run, within a few minutes."

    def decide_registration(self, issue, label):
        """A maintainer's Approve or Decline: the label on the registration issue, added with their own sign-in."""
        if not self.client.maintainer():
            return "Only a maintainer can approve or decline machines."
        try:
            self.client.github().add_labels(issue, [label])
        except Exception as error:  # noqa: BLE001
            return f"Could not add the label {label} to #{issue}: {error}"
        self.log(f"added {label} to registration #{issue}")
        return ""

    LISTING_MINUTES = 15

    def listing_store(self):
        """The listing of the repository the results repository names (not the config's own [github] repo)."""
        if self.listing_file:
            return poller.Listing(self.listing_file)
        return poller.Listing.of(self.config.state_dir, self.repository)

    def listing(self):
        store = self.listing_store()
        if store.data.get("repository", self.repository) != self.repository:
            return []
        return store.open()

    def listing_note(self):
        store = self.listing_store()
        when = store.refreshed()
        return (f"Pull requests of {self.repository}, listed {formats.parse_time(when).astimezone():%H:%M}" if when
                else f"Pull requests of {self.repository}: not listed yet")

    def refresh_listing(self, force=False):
        """Bring the listing up to date with the tester's sign-in (the worker thread only)."""
        if self.listing_file or not self.client.tester() or "/" not in (self.repository or ""):
            return
        store = self.listing_store()
        when = store.refreshed()
        if not force and when and formats.now() - formats.parse_time(when) < datetime.timedelta(minutes=self.LISTING_MINUTES):
            return
        from ..github import GraphQL
        owner, name = self.repository.split("/")
        try:
            store.refresh(GraphQL(client="token", token=self.client.flow().token, reserve=200), owner, name, max_pages=20)
            store.save()
        except Exception as error:  # noqa: BLE001 (the listing is a convenience; the queue does not depend on it)
            self.log(f"could not list the pull requests of {self.repository}: {error}")

    def sections(self, query=""):
        return model.pr_sections(self.listing(), self.queue, self.names, query)

    def waiting(self):
        return model.waiting_for_you(self.sections())

    def queue_view(self):
        return model.queue_view(self.ranked, self.status(), self.names)

    def tray_view(self):
        waiting = self.waiting()
        state, lines = model.tray_view(self.status(), self.queue_view(), waiting, self.status().get("paused_until"))
        ready, why, _ = self.readiness()
        if not ready:
            lines = [f"Takes no jobs yet: {why}"] + [line for line in lines[1:]]
            state = "waiting" if state == "idle" else state
        if self.client.stale() is not None:
            lines.append(f"The results workflow last ran {self.client.stale():.0f} h ago")
        return state, lines, waiting

    def titles(self):
        rows = []
        for title_id, title in self.config.titles.items():
            dump = self.dumps.get(title_id, {})
            rows.append({"on": True, "title_id": title_id, "name": dump.get("name", "?"), "version": dump.get("version", "?"),
                         "check": "Full test" if title.route else "Start-up check", "seeds": f"{len(title.seed)} file(s)" if title.seed else "none",
                         "seed_paths": [str(p) for p in title.seed], "path": str(title.dump)})
        return rows

    def allowed_now(self):
        return self.client.allowed_now()

    # -- the main screen -----------------------------------------------------------------------------------------------

    def up_next_rows(self):
        rows = model.up_next(self.ranked, self.status())
        job = self.status().get("job") or {}
        for entry in self.local.queued() if self.local.enabled() else []:
            if job.get("pr") == entry["pr"] and job.get("head") == entry["head"]:
                continue
            rows.append({"number": entry["pr"], "title": entry["title"], "author": entry["author"], "head": entry["head"], "queued_by": "",
                         "queued_at": entry["added"], "score": 0.5, "why": "A local test (the result stays on this computer)", "reasons": [],
                         "local": True})
        return rows

    def recent_rows(self):
        try:
            results = self.client.repo.results()
            rules = verdict.settings(self.client.repo.read("config.json", {}))
        except Exception:  # noqa: BLE001 (no checkout yet)
            results, rules = {}, verdict.DEFAULT
        status = self.status()
        posted = {**status, "recent": [r for r in status.get("recent", []) if not r.get("local")]}
        rows = model.recent(posted, results, self.config.machine, rules)
        if self.local.enabled():
            done = [e for e in self.local.read()["entries"] if e["status"] in ("done", "failed")]
            rows = [{"number": e["pr"], "head": e["head"], "at": e.get("at", ""), "status": e["status"], "verdict": e.get("verdict", e["status"]),
                     "draft": e.get("draft", ""), "local": True} for e in reversed(done)] + rows
        return rows

    def home(self):
        ready, why, _ = self.readiness()
        best = next((r for r in self.up_next_rows() if r["score"] > 0), None)
        allowed, allowed_why = self.allowed_now() if ready else (False, why)
        return model.header(self.status(), ready, why, self.config.automatic, allowed, allowed_why, best)

    def comment_link(self, pr):
        """The App's comment on pr: a GitHub link, or the stand-in's outbox when the results repository is local."""
        comment_id = self.comments.get("prs", {}).get(str(pr), {}).get("comment_id")
        if comment_id is None:
            return ""
        if not self.config.results_url.startswith(("https://", "git@", "ssh://")):
            return f"stand-in comment {comment_id} (outbox)"
        return f"https://github.com/{self.repository}/pull/{pr}#issuecomment-{comment_id}"

    # -- requests from the UI ------------------------------------------------------------------------------------------

    def pause(self, hours=None):
        until = "indefinitely" if hours is None else formats.iso(formats.now() + datetime.timedelta(hours=hours))
        self.client.status.update(paused_until=until)

    def resume(self):
        self.client.status.update(paused_until=None)

    def request_stop(self):
        self.client.status.update(stop_requested=True)

    def running(self):
        return self.status().get("state") == "running"

    def start_now(self):
        """Start the next test now, whatever the schedule says (still only once the machine is set up)."""
        self.client.status.update(paused_until=None, stop_requested=False)
        self.work.put(("next", None))

    def set_automatic(self, on):
        self.config.automatic = bool(on)
        self.save_config()
        self.work.put(("wake", None))

    def stop(self, quitting=False):
        """Stop the running test at once: its build or game is ended, its claim taken back, nothing is sent. Automatic
        testing goes off too, so another test doesn't start a minute later; Start or the switch turns it back on."""
        self.client.status.update(stop_requested=True)
        if self.config.automatic and not quitting:
            self.config.automatic = False
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

    def run_on_trust(self, row, scope):
        self.client.trust.grant(scope, row["author"], row["number"], row["head"])
        self.log(f"trust: {scope} for {row['author']} (#{row['number']} {row['head'][:9]})")
        self.work.put(("tester", row))

    def save_config(self):
        configfile.save(self.config)
        self.log(f"saved {self.config.path}")

    def switch_results(self, location):
        """Settings' results repository changed: the client starts afresh for the new one (Client.use)."""
        url = self.client.use(location)
        self.save_config()
        self.load(sync=False)
        state, _ = self.client.registration()
        return (f"Now using {self.client.results_repository() or url}. "
                + ("Signed in as " + self.client.tester() + "." if self.client.tester() else "Sign in again: this repository names another App.")
                + ("" if state == "approved" else " Register this machine there."))

    def check_connection(self, url):
        try:
            repo = store.ResultsRepo(clients.configs.results_location(url), self.dir / "connection-check")
            repo.sync()
            config, registry = repo.config(), repo.registry()
            last = repo.cursors().get("last_run")
            return (f"Read {config['results_repository']}: {len(repo.queue()['entries'])} queued, {len(registry['machines'])} machine(s), "
                    f"the workflow last ran {formats.parse_time(last).astimezone():%Y-%m-%d %H:%M}." if last else "the workflow has not run yet.")
        except Exception as error:  # noqa: BLE001
            return f"Could not read it: {error}"

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

    def schedule_allows(self):
        """The schedule alone (hours, power, fullscreen), for local tests, which need no registered machine."""
        ready = self.client.ready
        try:
            self.client.ready = lambda: (True, "")
            return self.client.allowed_now()
        finally:
            self.client.ready = ready

    def run_local(self):
        """The next head on the local tests list, if there is one. Returns what was done, or None."""
        if not self.local.enabled():
            return None
        queued = self.local.queued()
        if not queued or self.local.held():
            return None
        result = self.local.run(queued[0], self.client)
        return f"tested #{queued[0]['pr']} (a local test)" if result else f"stopped #{queued[0]['pr']}"

    def refresh_local(self, force=False):
        """The local tests list from GitHub every 15 minutes (read only, with the tester's sign-in)."""
        if not self.local.enabled() or not self.client.tester():
            return
        now = formats.now()
        if not force and self._local_checked and now - self._local_checked < datetime.timedelta(minutes=15):
            return
        self._local_checked = now
        try:
            self.local.refresh(self.client.flow().token())
        except Exception as error:  # noqa: BLE001
            self.log(f"could not read the local tests list: {error}")

    RELAY_STALE = datetime.timedelta(minutes=6)
    RELAY_EVERY = datetime.timedelta(minutes=5)

    def keep_relay_going(self, now=None):
        """GitHub's schedule for the relay can fail to fire at all (it did on the first real repository). While a
        maintainer's app is open, it starts the relay itself when the last run is over 6 minutes old, at most every 5
        minutes: with the maintainer's own sign-in (if the App may start workflows), else the gh command line. Returns
        how it was started, or None."""
        now = now or formats.now()
        if not self.client.maintainer():
            return None
        last = self.client.repo.cursors().get("last_run")
        if last and now - formats.parse_time(last) < self.RELAY_STALE:
            return None
        if getattr(self, "_dispatched", None) and now - self._dispatched < self.RELAY_EVERY:
            return None
        self._dispatched = now
        repository = self.results_repository()
        try:
            from .. import gh
            gh.GitHubRepo(repository, token=self.client.flow().token()).dispatch("relay.yml")
            how = "the App sign-in"
        except Exception:  # noqa: BLE001 (the App may not have Actions: write; gh is the fallback)
            done = subprocess.run(["gh", "workflow", "run", "relay.yml", "-R", repository], capture_output=True, text=True)
            if done.returncode != 0:
                self.log(f"could not start the relay: {done.stderr.strip()[:200]}")
                return None
            how = "gh"
        self.log(f"started the relay workflow ({how}): its last run was {last or 'never'}")
        return how

    # -- the worker thread ---------------------------------------------------------------------------------------------

    def start(self):
        self.thread = threading.Thread(target=self.worker, daemon=True)
        self.thread.start()

    def run_best(self):
        """Start (the Start button): the best test for this machine now, schedule or not: the queue's, then local tests."""
        ready, why = self.client.ready()
        if not ready and not (self.local.enabled() and self.client.onboarded()):
            return why
        best = self.client.next_job() if ready else None
        if best is None:
            return self.run_local() or "nothing to do"
        entry = best.entry
        self.client.run(entry["pr"], entry["head"], "queue", entry.get("title", ""), entry.get("author", ""))
        return f"ran {entry['job']}"

    def worker(self):
        self.load(sync=True)
        while not self.quitting:
            try:
                kind, row = self.work.get(timeout=30)
            except queues.Empty:
                kind, row = None, None
            if self.quitting or kind == "quit":
                break
            try:
                if kind == "tester":
                    self.client.run(row["number"], row["head"], "tester", row["title"], row["author"])
                elif kind == "listing":
                    self.refresh_listing(force=True)
                elif kind == "next":
                    self.log(self.run_best())
                elif self.config.automatic:
                    done = self.client.run_next()
                    if not done.startswith("ran ") and self.schedule_allows()[0]:  # nothing queued for this machine: local tests
                        done = self.run_local() or done
                    self.log(done)
                if kind != "listing" and not self.quitting:
                    self.refresh_listing()
                    self.refresh_local(force=kind == "local")
            except Exception as error:  # noqa: BLE001
                if not self.quitting:
                    self.client.status.update(state="error", line=f"Error: {clients.clean(error, 200)}")
                self.log(f"error: {error}")
            if not self.quitting:
                self.load(sync=True)
                try:
                    self.keep_relay_going()
                except Exception as error:  # noqa: BLE001 (a convenience; never stops the worker)
                    self.log(f"relay check: {error}")


def grab(widget, path):
    QApplication.processEvents()
    widget.grab().save(str(path))
    return Path(path)


def screenshots(engine, out, prefix=""):
    """The window's tabs, the trust dialog and the tray's menu with its four dots, rendered offscreen into out/."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QPainter, QPixmap
    from PySide6.QtWidgets import QWidget

    from .tray import COLOURS, Tray, dot
    from .trust_dialog import TrustDialog
    from .window import MainWindow

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    window = MainWindow(engine)
    window.refresh()
    window.show()
    saved = []
    for index, (tab, name) in enumerate(window.pages):
        window.show_page(tab)
        saved.append(grab(window, out / f"{prefix}{name.lower().replace(' ', '-')}.png"))
    if engine.client.maintainer():
        window.open_maintainer()
        saved.append(grab(window.maintainer_window, out / f"{prefix}maintainer.png"))
        window.maintainer_window.close()
    rows = engine.waiting() or engine.sections()[model.SECTIONS[2]]
    if rows:
        row = rows[0]
        dialog = TrustDialog(row["number"], row["title"], row["author"], window)
        dialog.show()
        saved.append(grab(dialog, out / f"{prefix}trust-dialog.png"))
        dialog.close()
    tray = Tray(engine, lambda: None, lambda: None)
    tray.refresh()
    tray.menu.popup(QPoint(0, 0))
    QApplication.processEvents()
    menu = tray.menu.grab()
    tray.menu.hide()
    strip = QPixmap(max(menu.width(), 4 * 120) + 40, menu.height() + 110)
    strip.fill(QWidget().palette().window().color())
    painter = QPainter(strip)
    painter.drawPixmap(20, 20, menu)
    for i, state in enumerate(COLOURS):
        painter.drawPixmap(20 + i * 120, menu.height() + 40, dot(state, 32))
        painter.drawText(58 + i * 120, menu.height() + 62, state)
    painter.end()
    strip.save(str(out / f"{prefix}tray.png"))
    saved.append(out / f"{prefix}tray.png")
    window.close()
    return saved


def new_config(path, results, github, state_dir=None):
    """A starting config for the walkthrough to fill: the results repository (or none yet: the walkthrough asks), the
    stand-in or GitHub, the state directory (the user's data folder unless given)."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    data = {"state_dir": str(state_dir or configs.user_dirs()[1]),
            "results": {"url": configs.results_location(results) if results else "", "github": github},
            "schedule": dict(configs.SCHEDULE), "sandbox": {"mode": "bwrap"}}
    Path(path).write_text("# anyps5-title-runs: written by the title-runs window. config.example.toml explains every key.\n\n" + configfile.dumps(data))


def main(argv=None):
    import os
    import signal
    from . import theme
    parser = argparse.ArgumentParser(prog="title-runs ui")
    parser.add_argument("--config", type=Path, default=configs.DEFAULT_CONFIG)
    parser.add_argument("--listing", type=Path)
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--dumps", default="", help="the walkthrough's dumps folder to start from")
    parser.add_argument("--results", default="", help="a new config: the results repository, OWNER/NAME or a URL")
    parser.add_argument("--github", default="github", help='a new config: "github", or "standin:<github.json>" for the local stand-in')
    parser.add_argument("--state", type=Path, help="a new config: the state directory")
    parser.add_argument("--screenshots", type=Path)
    parser.add_argument("--no-sync", action="store_true", help="--screenshots: read the results checkout as it is (a client may be using it)")
    args = parser.parse_args(argv)
    if sys.platform.startswith("linux") and os.environ.get("DISPLAY") and not os.environ.get("QT_QPA_PLATFORM") and not args.screenshots:
        # An X11 program on Wayland desktops too (XWayland), and the game an X11 window: then the game shows inside the app.
        os.environ["QT_QPA_PLATFORM"] = "xcb"
        os.environ["TITLE_RUNS_GAME_DISPLAY"] = "x11"
    if not args.config.exists():
        new_config(args.config, args.results, args.github, args.state)
    config = configs.load(args.config)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("AnyPS5 title runs")
    app.setQuitOnLastWindowClosed(False)
    theme.apply(app, config.text_size)
    engine = Engine(config, args.listing, args.auto)
    if args.screenshots:
        engine.load(sync=not args.no_sync)
        for path in screenshots(engine, args.screenshots):
            print(path)
        return 0
    if not engine.client.onboarded():
        from .walkthrough import Walkthrough
        if engine.config.results_url:
            engine.client.repo.sync()
        if Walkthrough(engine, args.dumps).exec() != Walkthrough.Accepted:
            return 1  # nothing runs before the walkthrough
    from PySide6.QtWidgets import QSystemTrayIcon
    from .tray import Tray
    from .window import MainWindow
    window = MainWindow(engine)
    tray = None
    if config.tray and QSystemTrayIcon.isSystemTrayAvailable():
        tray = Tray(engine, lambda: (window.refresh(), window.show(), window.raise_(), window.activateWindow()), app.quit)
        tray.show()
        tray.refresh()
    app.aboutToQuit.connect(engine.shutdown)  # quitting ends the running test: nothing is left running after the app
    # Ctrl+C in the terminal quits like the window's close: Qt's event loop does not hand Python the signal by itself.
    signal.signal(signal.SIGINT, lambda *_: QTimer.singleShot(0, window.close))
    wake = QTimer()
    wake.timeout.connect(lambda: None)
    wake.start(250)
    engine.start()
    timer = QTimer()
    timer.timeout.connect(lambda: (tray.refresh() if tray else None, window.isVisible() and window.refresh()))
    timer.start(2000)
    window.refresh()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
