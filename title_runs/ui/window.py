"""The tester's window: a sidebar with Home (ui/home.py), Local tests (ui/local.py), All pull requests (the advanced view
only) and Settings, the simple or advanced view, and the maintainers' window (ui/maintainer.py) for maintainers. Data
comes from the engine (app.Engine) through ui/model.py; nothing here is platform-specific."""

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QListWidget, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QStackedWidget,
                               QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import platform_info, verdict
from ..config import results_location as clients_location
from ..relay import overview
from ..relay.render import utc
from . import model, theme, words
from .home import HomePage
from .local import LocalTestsPage, ReportDialog
from .trust_dialog import TrustDialog


def tree(columns, widths=()):
    widget = QTreeWidget()
    widget.setHeaderLabels(columns)
    widget.setRootIsDecorated(False)
    widget.setUniformRowHeights(True)
    for i, width in enumerate(widths):
        widget.setColumnWidth(i, width)
    return widget


def bold(text):
    label = QLabel(text)
    font = label.font()
    font.setBold(True)
    label.setFont(font)
    return label


def fit(widget, stretch):
    """Columns sized to their contents, one stretched to the width: buttons in the last column stay in view."""
    header = widget.header()
    header.setStretchLastSection(False)
    for column in range(widget.columnCount()):
        header.setSectionResizeMode(column, QHeaderView.Stretch if column == stretch else QHeaderView.ResizeToContents)


def banner():
    """An amber strip for what keeps the client from working (not ready, the workflow not running); hidden when empty."""
    label = QLabel("")
    label.setWordWrap(True)
    label.setTextFormat(Qt.RichText)
    label.setStyleSheet("QLabel { background: #fff4d6; color: #5c4400; border: 1px solid #e0a100; border-radius: 4px; padding: 6px 10px; }")
    label.hide()
    return label


def show(label, text):
    label.setText(text)
    label.setVisible(bool(text))


def when(stamp):
    return utc(stamp) if stamp else "never"


def title_of(name):
    """overview.coverage's class key is "<class>, <title ID>"."""
    return name.rsplit(", ", 1)[-1]


class PullRequestsTab(QWidget):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.note = bold("")
        top.addWidget(self.note)
        refresh = QPushButton("Refresh")
        refresh.setToolTip("List the pull requests again now (otherwise every 15 minutes)")
        refresh.clicked.connect(lambda: engine.work.put(("listing", None)))
        top.addWidget(refresh)
        top.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("search…")
        self.search.setMaximumWidth(260)
        self.search.textChanged.connect(self.refresh)
        top.addWidget(self.search)
        layout.addLayout(top)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["PR", "Title", "Priority", "Titles", "Status", ""])
        for i, width in enumerate((110, 430, 70, 160, 150)):
            self.tree.setColumnWidth(i, width)
        self.tree.itemDoubleClicked.connect(self.double_clicked)
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
                item = QTreeWidgetItem([f"#{row['number']}", row["title"], row["priority"], row["titles"], row["badge"], ""])
                item.setData(0, Qt.UserRole, row)
                item.setToolTip(1, f"{row['title']}\nby {row['author']}, head {row['head'][:9]}")
                if row["badge"].startswith("⚠"):
                    item.setForeground(4, Qt.darkYellow)
                elif row["badge"].startswith("✓"):
                    item.setForeground(4, Qt.darkGreen)
                top.addChild(item)
                if row["run"] and name != model.SECTIONS[3]:
                    button = QPushButton("Run…")
                    button.clicked.connect(lambda _=False, r=row: self.engine.window.run_unchecked(r))
                    self.tree.setItemWidget(item, 5, button)
            top.setExpanded(self.expanded.get(name, False))

    def double_clicked(self, item, _column):
        row = item.data(0, Qt.UserRole)
        if isinstance(row, dict) and row.get("run"):
            self.engine.window.run_unchecked(row)


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
        note = QLabel("" if detectable else "This computer can't tell when you're away from it, so the hours below decide.")
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
        self.now.setText("A test may start now." if allowed else f"Not now: a test may start {model.waiting_for(why)}.")

    def save(self):
        self.engine.config.schedule.update(idle_only=self.idle.isChecked(), idle_minutes=self.idle_minutes.value(), mains_only=self.mains.isChecked(),
                                           pause_fullscreen=self.fullscreen.isChecked(), hours=[self.first.value(), self.last.value()],
                                           pause_for=[p.strip() for p in self.pause_for.text().split(",") if p.strip()],
                                           max_disk_gb=self.disk.value(), max_job_hours=self.job_hours.value())
        self.engine.save_config()
        self.refresh()


class TitlesTab(QWidget):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Your games. A game with a full test is played and timed in its scenario; the others get a start-up check."))
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["On", "Game ID", "Name", "Version", "Test", "Scenario", "Saves copied in", "Folder"])
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

    def refresh(self):
        rows = self.engine.titles()
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            on = QTableWidgetItem()
            on.setFlags(on.flags() | Qt.ItemIsUserCheckable)
            on.setCheckState(Qt.Checked if row["on"] else Qt.Unchecked)
            self.table.setItem(i, 0, on)
            for column, key in zip((1, 2, 3, 4, 6, 7), ("title_id", "name", "version", "check", "seeds", "path")):
                item = QTableWidgetItem(row[key])
                if key == "seeds":
                    item.setToolTip("\n".join(row["seed_paths"]))
                self.table.setItem(i, column, item)
            self.table.setCellWidget(i, 5, self.scenario_box(row))
        self.table.resizeColumnsToContents()

    def scenario_box(self, row):
        """The title's scenarios: which run its tests are timed in, each with what is on screen and its save, if any."""
        if not row["scenarios"]:
            return QLabel("—")
        box = QComboBox()
        for choice in row["scenarios"]:
            box.addItem(choice["name"], choice["id"])
            box.setItemData(box.count() - 1, "\n\n".join(t for t in (choice["scene"], choice.get("save", "")) if t), Qt.ToolTipRole)
        box.setCurrentIndex(max(0, box.findData(row["scenario"])))
        box.currentIndexChanged.connect(lambda _, b=box, t=row["title_id"]: self.engine.set_scenario(t, b.currentData()))
        return box


class SettingsTab(QWidget):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        config = engine.config
        layout = QVBoxLayout(self)
        machine = QGroupBox("You and this machine")
        form = QFormLayout(machine)
        account = QHBoxLayout()
        self.account = QLabel("")
        account.addWidget(self.account, 1)
        self.sign = QPushButton("")
        self.sign.clicked.connect(self.sign_in_or_out)
        account.addWidget(self.sign)
        form.addRow("GitHub account", account)
        self.machine = QLineEdit(config.machine)
        form.addRow("Machine name", self.machine)
        info = engine.client.info
        hardware = QLabel(f"{info['gpu']}, {info.get('driver', '')}, {info['os']}")
        hardware.setWordWrap(True)
        hardware.setToolTip(f"Results are compared with machines of the same kind: {verdict.class_of(engine.client.machine_class)}")
        form.addRow("Graphics card, driver, system", hardware)
        registration = QHBoxLayout()
        self.registration = QLabel("")
        self.registration.setTextFormat(Qt.RichText)
        self.registration.setOpenExternalLinks(True)
        registration.addWidget(self.registration, 1)
        self.register = QPushButton("Register this machine")
        self.register.clicked.connect(self.register_machine)
        registration.addWidget(self.register)
        again = QPushButton("Run the walkthrough again")
        again.clicked.connect(lambda: engine.window.walkthrough())
        registration.addWidget(again)
        form.addRow("Registration", registration)
        layout.addWidget(machine)
        results = QGroupBox("Testing")
        form = QFormLayout(results)
        self.url = QLineEdit(config.results_url)
        self.url.setPlaceholderText("The testing link you were given (https://github.com/…)")
        self.url.setToolTip("Saving another link switches to that testing: its tests, a new registration for this machine, "
                            "and a new sign-in if it needs one.")
        form.addRow("Testing link", self.url)
        check = QHBoxLayout()
        self.check_label = QLabel("")
        self.check_label.setWordWrap(True)
        check.addWidget(self.check_label, 1)
        button = QPushButton("Check")
        button.clicked.connect(self.check_connection)
        check.addWidget(button)
        form.addRow(check)
        layout.addWidget(results)
        sandbox = QGroupBox("Sandbox")
        form = QFormLayout(sandbox)
        self.sandbox_label = QLabel("On: tests build and play in a sandbox, with no internet once the change is downloaded" if config.sandbox == "bwrap"
                                    else "Off: tests run without the sandbox, and every result says so")
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
        form.addRow(QLabel("How fast each run was, and whether the game showed a picture. Never your game files."))
        self.screenshots = QCheckBox("Also a screenshot of the test scene")
        self.screenshots.setChecked(config.screenshots)
        form.addRow(self.screenshots)
        layout.addWidget(posted)
        trusted = QGroupBox("People you chose to trust")
        box = QHBoxLayout(trusted)
        self.trusted = QListWidget()
        box.addWidget(self.trusted, 1)
        revoke = QPushButton("Revoke")
        revoke.clicked.connect(self.revoke)
        box.addWidget(revoke, 0, Qt.AlignTop)
        layout.addWidget(trusted)
        self.trusted_group = trusted
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
        login = self.engine.client.tester()
        self.account.setText(f"Signed in as {login}" if login else "not signed in")
        self.sign.setText("Sign out" if login else "Sign in…")
        state, record = self.engine.client.registration()
        record = record or {}
        issue = record.get("issue")
        link = f" (<a href='{self.engine.issue_url(issue)}'>#{issue}</a>)" if issue else ""
        self.registration.setText({"approved": f"Approved by {record.get('approved_by', '?')}{link}",
                                   "pending": f"Waiting for {words.team()} to approve it{link}", "declined": f"Turned down by {words.team()}{link}",
                                   "not registered": "Not registered yet, so this machine doesn't run tests"}[state])
        self.register.setVisible(state == "not registered")
        self.register.setEnabled(bool(login))
        self.trusted.clear()
        for entry in self.engine.client.trust.entries:
            self.trusted.addItem(self.engine.client.trust.describe(entry))
        self.log.setPlainText(self.engine.log_tail())

    def check_connection(self):
        self.check_label.setText(self.engine.check_connection(self.url.text()))

    def sign_in_or_out(self):
        if self.engine.client.tester():
            self.engine.client.flow().sign_out()
            self.refresh()
        else:
            self.engine.window.walkthrough("sign-in")

    def register_machine(self):
        self.engine.config.machine = self.machine.text().strip() or self.engine.config.machine
        try:
            self.engine.client.register()
        except Exception as error:  # noqa: BLE001
            QMessageBox.warning(self, "AnyPS5 title runs", f"Could not register: {error}")
        self.refresh()

    def self_test(self):
        self.sandbox_label.setText(self.engine.sandbox_self_test())

    def revoke(self):
        row = self.trusted.currentRow()
        if row >= 0:
            self.engine.client.trust.revoke(row)
            self.refresh()

    def save(self):
        config = self.engine.config
        config.machine = self.machine.text().strip()
        location = self.url.text().strip()
        if location and clients_location(location) != config.results_url:
            try:
                self.check_label.setText(self.engine.switch_results(location))
            except Exception as error:  # noqa: BLE001
                self.check_label.setText(f"Could not switch: {error}")
            self.url.setText(self.engine.config.results_url)
        config.screenshots = self.screenshots.isChecked()
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
        self.advanced = QCheckBox("Advanced view: every pull request, the scheduling details, logs")
        self.advanced.setChecked(config.view == "advanced")
        form.addRow(self.advanced)
        self.tray = QCheckBox("Keep testing in the background when the window is closed (in the system tray)")
        self.tray.setChecked(config.tray)
        from PySide6.QtWidgets import QSystemTrayIcon
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.setEnabled(False)
            self.tray.setChecked(False)
            self.tray.setToolTip("This desktop has no system tray, so closing the window always quits")
        form.addRow(self.tray)
        form.addRow(theme.mark(QLabel("Otherwise closing the window quits the app, and a running test stops with it."), role="muted"))
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
        self.engine.save_config()
        if changed_size:
            theme.apply(QApplication.instance(), size)
        self.engine.window.apply_view()


class SettingsPage(QScrollArea):
    """One page of sections: you and this machine, when to test, your games, the app, the sandbox and logs."""

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
        self.account, self.schedule, self.titles, self.app = SettingsTab(engine), ScheduleTab(engine), TitlesTab(engine), AppTab(engine)
        for title, widget in (("", self.account), ("When to test", self.schedule), ("Your games", self.titles), ("This app", self.app)):
            if title:
                layout.addWidget(theme.mark(QLabel(title), role="heading"))
            layout.addWidget(widget)
        layout.addStretch(1)
        self.setWidget(inner)

    def refresh(self):
        advanced = self.engine.config.view == "advanced"
        self.account.trusted_group.setVisible(advanced)  # the simple view keeps to what a tester sets
        self.account.logs_group.setVisible(advanced)
        for part in (self.account, self.schedule, self.titles, self.app):
            part.refresh()


class MainWindow(QMainWindow):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        engine.window = self
        self.setWindowTitle("AnyPS5 title runs")
        self.home, self.local, self.prs, self.settings = HomePage(engine), LocalTestsPage(engine), PullRequestsTab(engine), SettingsPage(engine)
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
        for key, name, page in (("home", "Home", self.home), ("local", "Local tests", self.local), ("prs", "All pull requests", self.prs),
                                ("settings", "Settings", self.settings)):
            button = theme.mark(QPushButton(name), nav="true")
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, p=page: self.show_page(p))
            self.group.addButton(button)
            nav.addWidget(button)
            self.stack.addWidget(page)
            self.buttons[key] = button
        nav.addStretch(1)
        self.maintain = QPushButton("Maintainer tools")
        self.maintain.setToolTip("Queue tests, approve machines and see every machine's results (for the people running this testing)")
        self.maintain.clicked.connect(self.open_maintainer)
        nav.addWidget(self.maintain)
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
        self.maintainer_window = None
        self.buttons["home"].setChecked(True)
        self.apply_view()
        self.resize(1280, 860)

    @property
    def pages(self):
        return ((self.home, "Home"), (self.local, "Local tests"), (self.prs, "All pull requests"), (self.settings, "Settings"))

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
        self.maintain.setVisible(self.engine.client.maintainer())
        current = self.stack.currentWidget()
        current.refresh()
        if self.maintainer_window is not None and self.maintainer_window.isVisible():
            self.maintainer_window.refresh()

    def open_maintainer(self):
        from .maintainer import MaintainerWindow
        if self.maintainer_window is None:
            self.maintainer_window = MaintainerWindow(self.engine)
        self.maintainer_window.refresh()
        self.maintainer_window.show()
        self.maintainer_window.raise_()

    def walkthrough(self, start="what"):
        from .walkthrough import Walkthrough
        folder = next((str(t.dump.parent) for t in self.engine.config.titles.values()), "")
        Walkthrough(self.engine, folder, self, start).exec()
        self.refresh()

    def fix_readiness(self):
        """Home's Finish setting up: the walkthrough, sign-in or registration."""
        _, _, fix = self.engine.readiness()
        if fix == "Register this machine":
            self.buttons["settings"].setChecked(True)
            self.show_page(self.settings)
            self.settings.account.register_machine()
        else:
            self.walkthrough({"Finish the walkthrough": "what", "Sign in…": "sign-in"}.get(fix, "what"))

    def open_report(self, number):
        """A local test's report: the PR's link first, the text to copy, Mark as posted. Nothing is posted from here."""
        ReportDialog(self.engine, number, self).exec()
        self.refresh()

    def run_unchecked(self, row):
        """Run… on a PR no maintainer queued: the trust dialog, then the job on the tester's trust."""
        ready, why, _ = self.engine.readiness()
        if not ready:
            QMessageBox.information(self, "AnyPS5 title runs", f"This machine can't test yet: {model.setup_text(why)}")
            return
        dialog = TrustDialog(row["number"], row["title"], row["author"], self)
        if dialog.exec() == TrustDialog.Accepted and dialog.scope:
            self.engine.run_on_trust(row, dialog.scope)

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
