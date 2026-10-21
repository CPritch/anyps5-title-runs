"""The window: Queue, Pull requests, Schedule, Titles, Settings (DESIGN.md, "The window"). Data comes from the engine
(app.Engine) through ui/model.py; nothing here is platform-specific."""

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (QCheckBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QMainWindow, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import model
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


class QueueTab(QWidget):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        layout = QVBoxLayout(self)
        running = QGroupBox("Running")
        row = QHBoxLayout(running)
        self.running = bold("Nothing is running.")
        self.running.setWordWrap(True)
        row.addWidget(self.running, 1)
        self.stop = QPushButton("Stop")
        self.stop.clicked.connect(engine.request_stop)
        row.addWidget(self.stop)
        layout.addWidget(running)
        nxt = QGroupBox("Up next (hover for the score's reasons)")
        box = QVBoxLayout(nxt)
        self.up_next = tree(["PR", "Title", "Head", "Priority", "Titles", "Score"], (70, 420, 90, 70, 110))
        box.addWidget(self.up_next)
        layout.addWidget(nxt, 2)
        waiting = QGroupBox("Waiting for you (not queued by a maintainer)")
        box = QVBoxLayout(waiting)
        self.waiting = tree(["PR", "Title", "Author", "Why", ""], (70, 420, 120, 160))
        box.addWidget(self.waiting)
        layout.addWidget(waiting, 1)
        recent = QGroupBox("Recently posted")
        box = QVBoxLayout(recent)
        self.recent = tree(["PR", "Head", "Status", "When", "Comment"], (70, 100, 90, 170))
        self.recent.itemDoubleClicked.connect(lambda item, _: (item.data(4, Qt.UserRole) or "").startswith("https://")
                                              and QDesktopServices.openUrl(QUrl(item.data(4, Qt.UserRole))))
        box.addWidget(self.recent)
        layout.addWidget(recent, 1)

    def refresh(self):
        view = self.engine.queue_view()
        running = view["running"]
        if running:
            trust = "" if running["trust"] == "queue" else " (on your trust)"
            titles = ", ".join(self.engine.names.values())
            self.running.setText(f"#{running['number']} {running['head'][:9]}{trust} · {titles} · {running['progress'] or 'starting'}")
        else:
            last = self.engine.status().get("line", "")
            self.running.setText("Nothing is running." + (f" Last: {last}." if last and last != "Idle" else ""))
        self.stop.setEnabled(bool(running))
        self.up_next.clear()
        for row in view["up_next"]:
            item = QTreeWidgetItem([f"#{row['number']}", row["title"], row["head"][:9], row["priority"], row["titles"], f"{row['score']:.2f}"])
            tip = "\n".join(row["reasons"])
            if row["unapproved"]:
                tip += "\n" + "\n".join(f"{sha[:9]} pushed after approval: not checked" for sha in row["unapproved"])
            for column in range(6):
                item.setToolTip(column, tip)
            if row["score"] <= 0:
                for column in range(6):
                    item.setForeground(column, Qt.gray)
            self.up_next.addTopLevelItem(item)
        self.waiting.clear()
        for row in self.engine.waiting():
            item = QTreeWidgetItem([f"#{row['number']}", row["title"], row["author"], row["titles"], ""])
            self.waiting.addTopLevelItem(item)
            button = QPushButton("Run…")
            button.clicked.connect(lambda _=False, r=row: self.engine.window.run_unchecked(r))
            self.waiting.setItemWidget(item, 4, button)
        self.recent.clear()
        for row in view["recent"]:
            link = self.engine.comment_link(row["pr"])
            item = QTreeWidgetItem([f"#{row['pr']}", row["head"][:9], row["status"], row["at"].replace("T", " ").replace("Z", " UTC"), link])
            item.setData(4, Qt.UserRole, link)
            self.recent.addTopLevelItem(item)


class PullRequestsTab(QWidget):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(bold("Pull requests"))
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
        when = QGroupBox("When work may run")
        form = QFormLayout(when)
        self.idle = QCheckBox("Only when the computer is idle")
        self.idle.setChecked(rules["idle_only"])
        self.idle_minutes = QSpinBox()
        self.idle_minutes.setRange(1, 240)
        self.idle_minutes.setValue(rules["idle_minutes"])
        self.idle_minutes.setSuffix(" min without input")
        form.addRow(self.idle, self.idle_minutes)
        self.mains = QCheckBox("Only on mains power")
        self.mains.setChecked(rules["mains_only"])
        form.addRow(self.mains)
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
        self.disk.setSuffix(" GB for builds and caches")
        form.addRow("Disk", self.disk)
        self.job_hours = QSpinBox()
        self.job_hours.setRange(1, 24)
        self.job_hours.setValue(rules["max_job_hours"])
        self.job_hours.setSuffix(" h")
        form.addRow("Longest job", self.job_hours)
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
        self.now.setText("Work may start now." if allowed else f"Not now: {why}.")

    def save(self):
        self.engine.config.schedule.update(idle_only=self.idle.isChecked(), idle_minutes=self.idle_minutes.value(), mains_only=self.mains.isChecked(),
                                           hours=[self.first.value(), self.last.value()],
                                           pause_for=[p.strip() for p in self.pause_for.text().split(",") if p.strip()],
                                           max_disk_gb=self.disk.value(), max_job_hours=self.job_hours.value())
        self.engine.save_config()
        self.refresh()


class TitlesTab(QWidget):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Titles found in your dumps. A title with a route gets the full timed A/B; the others get #7264's boot check "
                                "(outcome only)."))
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["On", "Title ID", "Name", "Version", "Check", "Seed saves", "Dump"])
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
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
            for column, key in enumerate(("title_id", "name", "version", "check", "seeds", "path"), start=1):
                item = QTableWidgetItem(row[key])
                if key == "seeds":
                    item.setToolTip("\n".join(row["seed_paths"]))
                self.table.setItem(i, column, item)
        self.table.resizeColumnsToContents()


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
        self.tester = QLineEdit(config.tester)
        form.addRow("Tester (GitHub account)", self.tester)
        info = engine.client.info
        form.addRow("GPU, driver, OS", QLabel(f"{info['gpu']}, {info.get('driver', '')}, {info['os']}"))
        layout.addWidget(machine)
        results = QGroupBox("Results repository")
        form = QFormLayout(results)
        self.url = QLineEdit(config.results_url)
        form.addRow("Repository", self.url)
        self.token_env = QLineEdit(config.results_token_env)
        form.addRow("Token (environment variable)", self.token_env)
        check = QHBoxLayout()
        self.check_label = QLabel("")
        check.addWidget(self.check_label, 1)
        button = QPushButton("Check connection")
        button.clicked.connect(self.check_connection)
        check.addWidget(button)
        form.addRow(check)
        layout.addWidget(results)
        sandbox = QGroupBox("Sandbox")
        form = QFormLayout(sandbox)
        self.sandbox_label = QLabel(f"{config.sandbox} (bubblewrap): builds and runs, network off after the fetch" if config.sandbox == "bwrap"
                                    else "OFF: builds and runs are not sandboxed; every report says so")
        test = QHBoxLayout()
        test.addWidget(self.sandbox_label, 1)
        button = QPushButton("Self-test")
        button.clicked.connect(self.self_test)
        test.addWidget(button)
        form.addRow(test)
        layout.addWidget(sandbox)
        posted = QGroupBox("What is posted")
        form = QFormLayout(posted)
        form.addRow(QLabel("Timings, summary lines and outcome classes. Never game files."))
        self.screenshots = QCheckBox("Also a screenshot of the scene")
        self.screenshots.setChecked(config.screenshots)
        form.addRow(self.screenshots)
        layout.addWidget(posted)
        trusted = QGroupBox("Trusted authors (from the trust dialog)")
        box = QHBoxLayout(trusted)
        self.trusted = QListWidget()
        box.addWidget(self.trusted, 1)
        revoke = QPushButton("Revoke")
        revoke.clicked.connect(self.revoke)
        box.addWidget(revoke, 0, Qt.AlignTop)
        layout.addWidget(trusted)
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

    def refresh(self):
        self.trusted.clear()
        for entry in self.engine.client.trust.entries:
            self.trusted.addItem(self.engine.client.trust.describe(entry))
        self.log.setPlainText(self.engine.log_tail())

    def check_connection(self):
        self.check_label.setText(self.engine.check_connection(self.url.text(), self.token_env.text()))

    def self_test(self):
        self.sandbox_label.setText(self.engine.sandbox_self_test())

    def revoke(self):
        row = self.trusted.currentRow()
        if row >= 0:
            self.engine.client.trust.revoke(row)
            self.refresh()

    def save(self):
        config = self.engine.config
        config.machine, config.tester, config.results_url, config.results_token_env = (self.machine.text().strip(), self.tester.text().strip(),
                                                                                         self.url.text().strip(), self.token_env.text().strip())
        config.screenshots = self.screenshots.isChecked()
        self.engine.save_config()


class MainWindow(QMainWindow):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        engine.window = self
        self.setWindowTitle("AnyPS5 title runs")
        self.tabs = QTabWidget()
        self.queue, self.prs, self.schedule, self.titles, self.settings = (QueueTab(engine), PullRequestsTab(engine), ScheduleTab(engine),
                                                                            TitlesTab(engine), SettingsTab(engine))
        for widget, name in ((self.queue, "Queue"), (self.prs, "Pull requests"), (self.schedule, "Schedule"), (self.titles, "Titles"),
                             (self.settings, "Settings")):
            self.tabs.addTab(widget, name)
        self.setCentralWidget(self.tabs)
        self.resize(1120, 720)

    def refresh(self):
        for tab in (self.queue, self.prs, self.schedule, self.titles, self.settings):
            tab.refresh()

    def run_unchecked(self, row):
        """Run… on a PR no maintainer queued: the trust dialog, then the job on the tester's trust."""
        dialog = TrustDialog(row["number"], row["title"], row["author"], self)
        if dialog.exec() == TrustDialog.Accepted and dialog.scope:
            self.engine.run_on_trust(row, dialog.scope)
