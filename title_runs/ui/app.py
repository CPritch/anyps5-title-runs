"""The window's application: the tray and the window over the engine (title_runs/engine.py, its worker thread).

  title-runs ui [--config FILE] [--listing FILE] [--auto]       the tray and the window; the walkthrough on first open
  title-runs ui --config NEW --results URL [--github standin:FILE] [--dumps DIR]   a new config, then the walkthrough
  title-runs ui --screenshots DIR [--config FILE] [--listing FILE] [--no-sync]   render the window's screens to DIR (offscreen)

--listing: the PR listing the Pull requests tab shows (default: the listing of the repository the results repository
names, kept in the state directory's cache and refreshed with the tester's sign-in every 15 minutes or on request). --auto: the switch On schedule.
All git and build work happens on the engine's worker thread; the UI reads the status file and cached data.
"""

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .. import config as configs, engine as engines
from ..engine import new_config, report_state  # noqa: F401 (the window's and the tests' names for them)
from . import model


class Engine(engines.Engine):
    """The engine (title_runs/engine.py), with links opened through the desktop."""

    def open_url(self, url):
        if url.startswith("https://") and self.config.results_url.startswith(("https://", "git@", "ssh://")):
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl(url))


def grab(widget, path):
    QApplication.processEvents()
    widget.grab().save(str(path))
    return Path(path)


def screenshots(engine, out, prefix=""):
    """The window's tabs, a local test's report, the trust dialog and the tray's menu with its four dots, rendered offscreen into out/."""
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
        list(window.buttons.values())[index].setChecked(True)  # the sidebar names the page shown
        window.show_page(tab)
        saved.append(grab(window, out / f"{prefix}{name.lower().replace(' ', '-')}.png"))
    reported = next((r["pr"] for r in engine.local_rows() if r["entry"]["status"] in ("done", "failed")), None) if engine.local.enabled() else None
    if reported is not None:
        from .local import ReportDialog
        dialog = ReportDialog(engine, reported, window)
        dialog.show()
        saved.append(grab(dialog, out / f"{prefix}report.png"))
        dialog.close()
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
    timer.timeout.connect(lambda: (engine.sync_config(), tray.refresh() if tray else None, window.isVisible() and window.refresh()))
    timer.start(2000)
    window.refresh()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
