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
from . import model


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
        return (f"<b>The test list hasn't updated for {hours:.0f} hours</b>, so new tests may show up late. The AnyPS5 team can restart it.")

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
        return (f"<b>Your last report wasn't accepted</b> ({utc_text(last['at'])}){detail}. If it happens again, tell the AnyPS5 team.")

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
            return "Only the AnyPS5 team can queue tests."
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
        return model.up_next(self.ranked, self.status())

    def recent_rows(self):
        try:
            results = self.client.repo.results()
            rules = verdict.settings(self.client.repo.read("config.json", {}))
        except Exception:  # noqa: BLE001 (no checkout yet)
            results, rules = {}, verdict.DEFAULT
        return model.recent(self.status(), results, self.config.machine, rules)

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

    # -- the worker thread ---------------------------------------------------------------------------------------------

    def start(self):
        self.thread = threading.Thread(target=self.worker, daemon=True)
        self.thread.start()

    def run_best(self):
        """Start (the Start button): the best test for this machine now, schedule or not."""
        ready, why = self.client.ready()
        if not ready:
            return why
        best = self.client.next_job()
        if best is None:
            self.client.status.update(state="idle", line="Idle: nothing in the queue for this machine")
            return "nothing to do"
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
                    self.log(self.client.run_next())
                if kind != "listing" and not self.quitting:
                    self.refresh_listing()
            except Exception as error:  # noqa: BLE001
                if not self.quitting:
                    self.client.status.update(state="error", line=f"Error: {clients.clean(error, 200)}")
                self.log(f"error: {error}")
            if not self.quitting:
                self.load(sync=True)


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
        # An X11 program on Wayland desktops too (XWayland): the game's window, an X11 window, can then be shown inside the app.
        os.environ["QT_QPA_PLATFORM"] = "xcb"
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
