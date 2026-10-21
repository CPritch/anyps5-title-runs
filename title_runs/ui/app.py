"""The client's application: the engine (client.Client on a worker thread), the tray and the window.

  title-runs ui [--config FILE] [--listing FILE] [--auto]       the tray and the window; the walkthrough on first open
  title-runs ui --config NEW --results URL [--github standin:FILE] [--dumps DIR]   a new config, then the walkthrough
  title-runs ui --screenshots DIR [--config FILE] [--listing FILE] [--no-sync]   render the window's screens to DIR (offscreen)

--listing: the PR listing the Pull requests tab shows (default: the state directory's cache/pull-requests.json, which
`title-runs poll` keeps). --auto: run the queue's jobs when the schedule allows (otherwise only on request).
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
from . import model


class Engine(QObject):
    def __init__(self, config, listing=None, auto=False):
        super().__init__()
        self.config = config
        self.dir = Path(config.state_dir) / "client"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.client = clients.Client(config, log=lambda text: None)
        self.listing_path = Path(listing) if listing else Path(config.state_dir) / "cache" / "pull-requests.json"
        self.auto = auto
        self.window = None
        self.ranked, self.queue, self.repository = [], {"entries": []}, config.repo
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
        return (f"<b>The results repository's workflow last ran {hours:.0f} h ago.</b> GitHub may have delayed or dropped its scheduled runs, "
                f"or disabled the schedule after 60 days without activity; a maintainer turns it back on in the repository's Actions tab.")

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

    def listing(self):
        if not self.listing_path.exists():
            return []
        return poller.Listing(self.listing_path).open()

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
                         "check": "full timing (route)" if title.route else "boot check", "seeds": f"{len(title.seed)} file(s)" if title.seed else "none",
                         "seed_paths": [str(p) for p in title.seed], "path": str(title.dump)})
        return rows

    def allowed_now(self):
        return self.client.allowed_now()

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

    def run_on_trust(self, row, scope):
        self.client.trust.grant(scope, row["author"], row["number"], row["head"])
        self.log(f"trust: {scope} for {row['author']} (#{row['number']} {row['head'][:9]})")
        self.work.put(("tester", row))

    def save_config(self):
        configfile.save(self.config)
        self.log(f"saved {self.config.path}")

    def check_connection(self, url):
        try:
            repo = store.ResultsRepo(url, self.dir / "connection-check")
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
        parts = ["network blocked" if net.returncode != 0 else "NETWORK REACHABLE", "home not visible" if home.returncode != 0 else "HOME VISIBLE",
                 "GPU visible to runs" if gpu.stdout.strip() else "no GPU device in the run sandbox"]
        ok = net.returncode != 0 and home.returncode != 0
        return ("Self-test passed: " if ok else "Self-test FAILED: ") + ", ".join(parts) + "."

    # -- the worker thread ---------------------------------------------------------------------------------------------

    def start(self):
        threading.Thread(target=self.worker, daemon=True).start()

    def worker(self):
        self.load(sync=True)
        while True:
            try:
                kind, row = self.work.get(timeout=60)
            except queues.Empty:
                kind, row = None, None
            try:
                if kind == "tester":
                    self.client.run(row["number"], row["head"], "tester", row["title"], row["author"])
                elif self.auto:
                    self.log(self.client.run_next())
            except Exception as error:  # noqa: BLE001
                self.client.status.update(state="error", line=f"Error: {clients.clean(error, 200)}")
                self.log(f"error: {error}")
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
        window.tabs.setCurrentWidget(tab)
        tab.refresh()
        saved.append(grab(window, out / f"{prefix}{name.lower().replace(' ', '-')}.png"))
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
    """A starting config for the walkthrough to fill: the results repository, the stand-in or GitHub, the state directory."""
    data = {"state_dir": str(state_dir or ROOT / "state"), "results": {"url": results, "github": github},
            "schedule": dict(configs.SCHEDULE), "sandbox": {"mode": "bwrap"}}
    Path(path).write_text("# anyps5-title-runs: written by the title-runs window. config.example.toml explains every key.\n\n" + configfile.dumps(data))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="title-runs ui")
    parser.add_argument("--config", type=Path, default=ROOT / "config.toml")
    parser.add_argument("--listing", type=Path)
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--dumps", default="", help="the walkthrough's dumps folder to start from")
    parser.add_argument("--results", default="", help="a new config: the results repository's URL")
    parser.add_argument("--github", default="github", help='a new config: "github", or "standin:<github.json>" for the local stand-in')
    parser.add_argument("--state", type=Path, help="a new config: the state directory")
    parser.add_argument("--screenshots", type=Path)
    parser.add_argument("--no-sync", action="store_true", help="--screenshots: read the results checkout as it is (a client may be using it)")
    args = parser.parse_args(argv)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("AnyPS5 title runs")
    app.setQuitOnLastWindowClosed(False)
    if not args.config.exists():
        if not args.results:
            raise SystemExit(f"{args.config} does not exist: pass --results URL to start a new one")
        new_config(args.config, args.results, args.github, args.state)
    engine = Engine(configs.load(args.config), args.listing, args.auto)
    if args.screenshots:
        engine.load(sync=not args.no_sync)
        for path in screenshots(engine, args.screenshots):
            print(path)
        return 0
    if not engine.client.onboarded():
        from .walkthrough import Walkthrough
        engine.client.repo.sync()
        if Walkthrough(engine, args.dumps).exec() != Walkthrough.Accepted:
            return 1  # nothing runs before the walkthrough
    from .tray import Tray
    from .window import MainWindow
    window = MainWindow(engine)
    tray = Tray(engine, lambda: (window.refresh(), window.show(), window.raise_(), window.activateWindow()), app.quit)
    tray.show()
    engine.start()
    timer = QTimer()
    timer.timeout.connect(lambda: (tray.refresh(), window.isVisible() and window.refresh()))
    timer.start(3000)
    tray.refresh()
    if not tray.icon.isSystemTrayAvailable():
        window.refresh()
        window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
