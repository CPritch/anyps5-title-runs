"""The tester's window: a sidebar with Home (ui/home.py), Local tests (ui/local.py), Games (ui/games.py), All pull requests
(the advanced view only) and Settings, and the simple or advanced view. Data comes from the engine (app.Engine) through ui/model.py;
nothing here is platform-specific."""

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QStackedWidget,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import platform_info, sandbox, verdict
from . import model, theme
from .games import GamesPage
from .home import HomePage
from .local import LocalTestsPage, ReportDialog


def bold(text):
    label = QLabel(text)
    font = label.font()
    font.setBold(True)
    label.setFont(font)
    return label


class PullRequestsTab(QWidget):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.note = bold("")
        top.addWidget(self.note)
        refresh = QPushButton("Refresh")
        refresh.setToolTip("Get the project's open pull requests from GitHub. Each 100 uses one of the 60 requests an hour GitHub "
                           "allows without a sign-in, so this page only updates when you press Refresh.")
        refresh.clicked.connect(lambda: engine.work.put(("listing", None)))
        top.addWidget(refresh)
        self.added = theme.mark(QLabel(""), role="muted")
        top.addWidget(self.added)
        top.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("search…")
        self.search.setMaximumWidth(260)
        self.search.textChanged.connect(self.refresh)
        top.addWidget(self.search)
        layout.addLayout(top)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["PR", "Title", "Titles", "", ""])
        for i, width in enumerate((110, 500, 160, 130)):
            self.tree.setColumnWidth(i, width)
        layout.addWidget(self.tree)
        self.expanded = {model.SECTIONS[0]: True, model.SECTIONS[1]: True, model.SECTIONS[2]: False, model.SECTIONS[3]: False}

    def refresh(self, *_):
        self.note.setText(self.engine.listing_note())
        sections = self.engine.sections(self.search.text())
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            self.expanded[item.data(0, Qt.UserRole)] = item.isExpanded()
        self.tree.clear()
        for name in model.SECTIONS:
            rows = sections[name]
            top = QTreeWidgetItem([f"{name} ({len(rows)})"])
            top.setData(0, Qt.UserRole, name)
            font = QFont(top.font(0))
            font.setBold(True)
            top.setFont(0, font)
            self.tree.addTopLevelItem(top)
            top.setFirstColumnSpanned(True)
            for row in rows[:400]:
                item = QTreeWidgetItem([f"#{row['number']}", row["title"], row["titles"], row["badge"], ""])
                item.setData(0, Qt.UserRole, row)
                item.setToolTip(1, f"{row['title']}\nby {row['author']}, latest commit {row['head'][:9]}")
                if row["badge"]:
                    item.setForeground(3, Qt.darkGreen)
                top.addChild(item)
                if row["add"]:
                    button = QPushButton("Add")
                    button.setToolTip("Add it to your local tests. Each new commit its author pushes is tested on this computer.")
                    button.clicked.connect(lambda _=False, r=row: self.add(r))
                    self.tree.setItemWidget(item, 4, button)
            top.setExpanded(self.expanded.get(name, False))

    def add(self, row):
        self.added.setText(self.engine.local_add(str(row["number"])))
        self.refresh()


class ScheduleTab(QWidget):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        rules = engine.config.schedule
        layout = QVBoxLayout(self)
        when = QGroupBox("When to test")
        form = QFormLayout(when)
        detectable, how = platform_info.idle_detection()
        self.idle = QCheckBox("Only when the computer has been left alone for")
        self.idle.setChecked(rules["idle_only"] and detectable)
        self.idle_minutes = QSpinBox()
        self.idle_minutes.setRange(1, 240)
        self.idle_minutes.setValue(rules["idle_minutes"])
        self.idle_minutes.setSuffix(" minutes")
        form.addRow(self.idle, self.idle_minutes)
        note = QLabel("" if detectable else "This computer can't tell when you're away from it, so tests run in the hours below.")
        note.setToolTip(how)
        note.setWordWrap(True)
        form.addRow(note)
        if not detectable:
            self.idle.setEnabled(False)
            self.idle_minutes.setEnabled(False)
        self.mains = QCheckBox("Only when plugged in")
        self.mains.setChecked(rules["mains_only"])
        form.addRow(self.mains)
        full_ok, full_how = platform_info.fullscreen_detection()
        self.fullscreen = QCheckBox("Pause while a game or video is fullscreen")
        self.fullscreen.setChecked(rules.get("pause_fullscreen", True) and full_ok)
        self.fullscreen.setEnabled(full_ok)
        self.fullscreen.setToolTip(full_how)
        form.addRow(self.fullscreen)
        hours = QHBoxLayout()
        self.first, self.last = QSpinBox(), QSpinBox()
        for box, value in ((self.first, rules["hours"][0]), (self.last, rules["hours"][1])):
            box.setRange(0, 24)
            box.setValue(value)
            box.setSuffix(":00")
        hours.addWidget(QLabel("from"))
        hours.addWidget(self.first)
        hours.addWidget(QLabel("to"))
        hours.addWidget(self.last)
        hours.addStretch(1)
        form.addRow("Hours", hours)
        self.pause_for = QLineEdit(", ".join(rules["pause_for"]))
        form.addRow("Pause while these run", self.pause_for)
        layout.addWidget(when)
        limits = QGroupBox("Limits")
        form = QFormLayout(limits)
        self.disk = QSpinBox()
        self.disk.setRange(10, 2000)
        self.disk.setValue(rules["max_disk_gb"])
        self.disk.setSuffix(" GB")
        form.addRow("Disk space for tests", self.disk)
        self.job_hours = QSpinBox()
        self.job_hours.setRange(1, 24)
        self.job_hours.setValue(rules["max_job_hours"])
        self.job_hours.setSuffix(" h")
        form.addRow("Longest test", self.job_hours)
        layout.addWidget(limits)
        now = QHBoxLayout()
        self.now = QLabel()
        now.addWidget(self.now, 1)
        save = QPushButton("Save")
        save.clicked.connect(self.save)
        now.addWidget(save)
        layout.addLayout(now)
        layout.addStretch(1)

    def refresh(self):
        allowed, why = self.engine.allowed_now()
        self.now.setText("A test can start now." if allowed else f"Not now. The next test starts {model.waiting_for(why)}.")

    def save(self):
        self.engine.config.schedule.update(idle_only=self.idle.isChecked(), idle_minutes=self.idle_minutes.value(), mains_only=self.mains.isChecked(),
                                           pause_fullscreen=self.fullscreen.isChecked(), hours=[self.first.value(), self.last.value()],
                                           pause_for=[p.strip() for p in self.pause_for.text().split(",") if p.strip()],
                                           max_disk_gb=self.disk.value(), max_job_hours=self.job_hours.value())
        self.engine.save_config()
        self.refresh()


class SettingsTab(QWidget):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        config = engine.config
        layout = QVBoxLayout(self)
        machine = QGroupBox("This machine")
        form = QFormLayout(machine)
        self.machine = QLineEdit(config.machine)
        form.addRow("Machine name", self.machine)
        info = engine.client.info
        hardware = QLabel(f"{info['gpu']}, {info.get('driver', '')}, {info['os']}")
        hardware.setWordWrap(True)
        hardware.setToolTip(f"Results are compared with other machines like this one ({verdict.class_of(engine.client.machine_class)})")
        form.addRow("Graphics card, driver, system", hardware)
        again = QPushButton("Run the walkthrough again")
        again.clicked.connect(lambda: engine.window.walkthrough())
        form.addRow("First-run steps", again)
        layout.addWidget(machine)
        sandbox = QGroupBox("Sandbox")
        form = QFormLayout(sandbox)
        self.sandbox_label = QLabel("On. Tests build and play in a sandbox, cut off from the internet once the change is downloaded." if config.sandbox == "bwrap"
                                    else "Off. Tests run without the sandbox, and every result says so.")
        self.sandbox_label.setWordWrap(True)
        test = QHBoxLayout()
        test.addWidget(self.sandbox_label, 1)
        button = QPushButton("Check the sandbox")
        button.clicked.connect(self.self_test)
        test.addWidget(button)
        form.addRow(test)
        layout.addWidget(sandbox)
        posted = QGroupBox("What's shared")
        form = QFormLayout(posted)
        form.addRow(QLabel("Nothing is uploaded automatically. Results stay on this computer until you post a report."))
        layout.addWidget(posted)
        logs = QGroupBox("Logs")
        box = QVBoxLayout(logs)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(120)
        box.addWidget(self.log)
        row = QHBoxLayout()
        row.addStretch(1)
        open_folder = QPushButton("Open the log folder")
        open_folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(engine.log_dir()))))
        row.addWidget(open_folder)
        save = QPushButton("Save")
        save.clicked.connect(self.save)
        row.addWidget(save)
        box.addLayout(row)
        layout.addWidget(logs)
        self.logs_group = logs

    def refresh(self):
        self.log.setPlainText(self.engine.log_tail())

    def self_test(self):
        self.sandbox_label.setText(self.engine.sandbox_self_test())

    def save(self):
        self.engine.config.machine = self.machine.text().strip() or self.engine.config.machine
        self.engine.save_config()


class AppTab(QWidget):
    """How the app looks and behaves: text size, the simple or advanced view, and whether closing the window quits."""

    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        config = engine.config
        form = QFormLayout(self)
        self.size = QComboBox()
        for key, name in (("normal", "Normal"), ("large", "Large"), ("larger", "Larger")):
            self.size.addItem(name, key)
        self.size.setCurrentIndex(max(0, self.size.findData(config.text_size)))
        form.addRow("Text size", self.size)
        self.advanced = QCheckBox("Advanced view (every pull request, more detail on Home, and the logs)")
        self.advanced.setChecked(config.view == "advanced")
        form.addRow(self.advanced)
        self.inside = QCheckBox("Show the game inside this window")
        self.inside.setChecked(config.game_in_window)
        self.inside.setToolTip("The game then uses X11, which it shares with your other X11 apps. Off, it opens in its own "
                               "window on Wayland, where it can't reach other apps.")
        from .gameview import embeddable
        if not embeddable():
            self.inside.setEnabled(False)
            self.inside.setToolTip("This desktop can't show the game inside the window")
        form.addRow(self.inside)
        self.tray = QCheckBox("Keep testing in the background when the window is closed (in the system tray)")
        self.tray.setChecked(config.tray)
        from PySide6.QtWidgets import QSystemTrayIcon
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.setEnabled(False)
            self.tray.setChecked(False)
            self.tray.setToolTip("This desktop has no system tray, so closing the window always quits")
        form.addRow(self.tray)
        form.addRow(theme.mark(QLabel("If this is off, closing the window quits the app and stops any running test."), role="muted"))
        save = QPushButton("Save")
        save.clicked.connect(self.save)
        form.addRow(save)

    def refresh(self):
        pass

    def save(self):
        config = self.engine.config
        size = self.size.currentData()
        changed_size = size != config.text_size
        config.text_size, config.view, config.tray = size, "advanced" if self.advanced.isChecked() else "simple", self.tray.isChecked()
        if self.inside.isEnabled():
            config.game_in_window = self.inside.isChecked()
            sandbox.show_game_in_window(config.game_in_window)  # from the next test on
        self.engine.save_config()
        if changed_size:
            theme.apply(QApplication.instance(), size)
        self.engine.window.apply_view()


class SettingsPage(QScrollArea):
    """One page of sections: this machine, the sandbox, what's shared, when to test, the app and the logs."""

    def __init__(self, engine):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(18)
        self.engine = engine
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.account, self.schedule, self.app = SettingsTab(engine), ScheduleTab(engine), AppTab(engine)
        for title, widget in (("", self.account), ("When to test", self.schedule), ("This app", self.app)):
            if title:
                layout.addWidget(theme.mark(QLabel(title), role="heading"))
            layout.addWidget(widget)
        layout.addStretch(1)
        self.setWidget(inner)

    def refresh(self):
        advanced = self.engine.config.view == "advanced"
        self.account.logs_group.setVisible(advanced)  # the simple view keeps to what a tester sets
        for part in (self.account, self.schedule, self.app):
            part.refresh()


class MainWindow(QMainWindow):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        engine.window = self
        self.setWindowTitle("AnyPS5 title runs")
        self.home, self.local, self.games = HomePage(engine), LocalTestsPage(engine), GamesPage(engine)
        self.prs, self.settings = PullRequestsTab(engine), SettingsPage(engine)
        self.stack = QStackedWidget()
        side = theme.mark(QWidget(), objectName="sidebar")
        side.setObjectName("sidebar")
        nav = QVBoxLayout(side)
        nav.setContentsMargins(12, 16, 12, 16)
        nav.setSpacing(6)
        nav.addWidget(theme.mark(QLabel("Title runs"), role="heading"))
        nav.addSpacing(8)
        self.group = QButtonGroup(self)
        self.buttons = {}
        for key, name, page in (("home", "Home", self.home), ("local", "Local tests", self.local), ("games", "Games", self.games),
                                ("prs", "All pull requests", self.prs), ("settings", "Settings", self.settings)):
            button = theme.mark(QPushButton(name), nav="true")
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, p=page: self.show_page(p))
            self.group.addButton(button)
            nav.addWidget(button)
            self.stack.addWidget(page)
            self.buttons[key] = button
        nav.addStretch(1)
        self.view = QCheckBox("Advanced view")
        self.view.toggled.connect(self.view_toggled)
        nav.addWidget(self.view)
        body = QWidget()
        row = QHBoxLayout(body)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(side)
        row.addWidget(self.stack, 1)
        self.setCentralWidget(body)
        self.buttons["home"].setChecked(True)
        self.apply_view()
        self.resize(1280, 860)

    @property
    def pages(self):
        return ((self.home, "Home"), (self.local, "Local tests"), (self.games, "Games"), (self.prs, "All pull requests"), (self.settings, "Settings"))

    def show_page(self, page):
        self.stack.setCurrentWidget(page)
        page.refresh()

    def apply_view(self):
        advanced = self.engine.config.view == "advanced"
        self.view.blockSignals(True)
        self.view.setChecked(advanced)
        self.view.blockSignals(False)
        self.buttons["prs"].setVisible(advanced)
        if not advanced and self.stack.currentWidget() is self.prs:
            self.buttons["home"].setChecked(True)
            self.show_page(self.home)
        self.home.refresh()

    def view_toggled(self, on):
        self.engine.config.view = "advanced" if on else "simple"
        self.engine.save_config()
        self.apply_view()

    def refresh(self):
        self.stack.currentWidget().refresh()

    def walkthrough(self, start="what"):
        from .walkthrough import Walkthrough
        folder = next((str(t.dump.parent) for t in self.engine.config.titles.values()), "")
        Walkthrough(self.engine, folder, self, start).exec()
        self.refresh()

    def fix_readiness(self):
        """Home's Finish setting up: the walkthrough."""
        self.walkthrough()

    def open_report(self, number):
        """A local test's report: the PR's link first, the text to copy, Mark as posted. Nothing is posted from here."""
        ReportDialog(self.engine, number, self).exec()
        self.refresh()

    def closeEvent(self, event):  # noqa: N802
        """Closing the window quits, and a running test stops with it, unless the tester chose the tray (Settings)."""
        from PySide6.QtWidgets import QSystemTrayIcon
        if self.engine.config.tray and QSystemTrayIcon.isSystemTrayAvailable() and not self.engine.quitting:
            event.ignore()
            self.hide()
            return
        if self.engine.running():
            answer = QMessageBox.question(self, "AnyPS5 title runs", "A test is running. Stop it and quit?",
                                          QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        event.accept()
        QApplication.instance().quit()
