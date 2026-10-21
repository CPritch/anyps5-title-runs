"""The first-run walkthrough (DESIGN.md, "First run: the walkthrough"): what the tool does and what leaves the machine,
the sandbox and what it does not protect against, when it may run (idle where the machine can tell, otherwise hours;
mains power; fullscreen programs), the dumps, signing in through the App, registering the machine. Nothing runs before
the tester has been through it: Finish writes the config and marks the walkthrough done (client.finish_onboarding)."""

import socket
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QSpinBox,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWizard, QWizardPage)

from .. import ROOT, configfile, platform_info, verdict
from ..config import Title


def text(html):
    label = QLabel(html)
    label.setWordWrap(True)
    label.setTextFormat(Qt.RichText)
    label.setOpenExternalLinks(True)
    return label


class WhatPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("What AnyPS5 title runs does")
        self.setSubTitle("A few pages before anything runs. Nothing is built or run until you finish and a maintainer approves this machine.")
        layout = QVBoxLayout(self)
        layout.addWidget(text(
            "AnyPS5's maintainers queue pull requests they want tested on real games. When this computer is free, the client takes one, builds "
            "the change and the AnyPS5 it changes, runs both on <b>your own dumps</b>, and reports the timings on the pull request. Developers get "
            "results from hardware and games they do not have; you decide when your machine works."))
        leaves = QGroupBox("What leaves this computer")
        box = QVBoxLayout(leaves)
        box.addWidget(text(
            "<ul><li>Your GitHub account name and this machine's name, GPU, driver and OS: public, in the registration issue.</li>"
            "<li>Timings, the summary lines AnyPS5 prints (build, GPU, driver, OS, CPU core count, memory, switches) and outcome classes "
            "(rendering, crashed, …): public, on the pull request.</li>"
            "<li>A screenshot of the test scene, only if you turn it on in Settings.</li></ul>"
            "<b>Never game files, save data or anything of your dumps.</b>"))
        layout.addWidget(leaves)
        layout.addStretch(1)


class SandboxPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("The sandbox")
        self.setSubTitle("The code being tested is a stranger's change to an emulator. It runs in a sandbox, which has limits.")
        layout = QVBoxLayout(self)
        layout.addWidget(text(
            "Builds and runs happen in <b>bubblewrap</b>: no network once the source is fetched, your home directory hidden, the dumps "
            "read-only, the system read-only. Only the build and game folders of the job are writable. A maintainer has looked at every "
            "change the queue runs, and approval names one commit: a push after it is not run."))
        limits = QGroupBox("What the sandbox does NOT protect against")
        box = QVBoxLayout(limits)
        box.addWidget(text(
            "<ul><li>A malicious driver or kernel exploit through the GPU: the game needs the GPU's device files.</li>"
            "<li>The display server: the game draws on your screen and can read what your desktop lets any window read.</li>"
            "<li>Running out of disk, memory or CPU: limits are set in the Schedule tab, not by the sandbox.</li>"
            "<li>Anything you run with the sandbox turned off, or a pull request you choose to run outside the queue.</li></ul>"))
        layout.addWidget(limits)
        self.read = QCheckBox("I have read what the sandbox does not protect against")
        self.read.toggled.connect(self.completeChanged)
        layout.addWidget(self.read)
        layout.addStretch(1)

    def isComplete(self):  # noqa: N802
        return self.read.isChecked()


class WhenPage(QWizardPage):
    def __init__(self, schedule):
        super().__init__()
        self.setTitle("When it may run")
        self.setSubTitle("It should get out of the way when you use the computer.")
        layout = QVBoxLayout(self)
        self.idle_ok, idle_how = platform_info.idle_detection()
        self.full_ok, full_how = platform_info.fullscreen_detection()
        idle = QGroupBox("Idle")
        form = QFormLayout(idle)
        self.idle = QCheckBox("Only when the computer has been idle for")
        self.minutes = QSpinBox()
        self.minutes.setRange(1, 240)
        self.minutes.setValue(schedule["idle_minutes"])
        self.minutes.setSuffix(" min")
        if self.idle_ok:
            form.addRow(text(f"This computer can tell when it is idle: {idle_how}."))
            self.idle.setChecked(True)
        else:
            form.addRow(text(f"<b>This computer cannot tell when it is idle</b>: {idle_how}. Set the hours it may work instead "
                             f"(on Hyprland, running hypridle or swayidle with an idle hint makes idle work)."))
            self.idle.setChecked(False)
            self.idle.setEnabled(False)
            self.minutes.setEnabled(False)
        form.addRow(self.idle, self.minutes)
        layout.addWidget(idle)
        hours = QGroupBox("Hours")
        form = QFormLayout(hours)
        row = QHBoxLayout()
        self.first, self.last = QSpinBox(), QSpinBox()
        first, last = schedule["hours"]
        if not self.idle_ok and [first, last] == [0, 24]:
            first, last = 1, 7  # nights, unless the tester picks other hours
        for box, value in ((self.first, first), (self.last, last)):
            box.setRange(0, 24)
            box.setValue(value)
            box.setSuffix(":00")
            box.valueChanged.connect(self.completeChanged)
        row.addWidget(QLabel("from"))
        row.addWidget(self.first)
        row.addWidget(QLabel("to"))
        row.addWidget(self.last)
        row.addStretch(1)
        form.addRow("Work only", row)
        layout.addWidget(hours)
        other = QGroupBox("Power and other programs")
        form = QFormLayout(other)
        self.mains = QCheckBox("Only on mains power")
        self.mains.setChecked(schedule["mains_only"])
        form.addRow(self.mains)
        self.fullscreen = QCheckBox("Pause while a fullscreen program runs")
        self.fullscreen.setChecked(schedule.get("pause_fullscreen", True) and self.full_ok)
        self.fullscreen.setEnabled(self.full_ok)
        form.addRow(self.fullscreen, text(full_how + "." if self.full_ok else f"Not available here: {full_how}."))
        self.games = QLineEdit(", ".join(schedule["pause_for"]))
        form.addRow("Pause while these run", self.games)
        layout.addWidget(other)
        layout.addStretch(1)

    def isComplete(self):  # noqa: N802
        return self.idle_ok or self.first.value() < self.last.value()


class DumpsPage(QWizardPage):
    def __init__(self, folder="", repo_dir=""):
        super().__init__()
        self.setTitle("Your dumps")
        self.setSubTitle("Pick the folder with your extracted packages (eboot.bin and sce_sys/param.json). They stay where they are, read-only.")
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.folder = QLineEdit(folder)
        row.addWidget(self.folder, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.browse)
        row.addWidget(browse)
        scan = QPushButton("Find titles")
        scan.clicked.connect(self.scan)
        row.addWidget(scan)
        layout.addLayout(row)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Title ID", "Name", "Version", "Check", "Folder"])
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)
        layout.addWidget(text("<i>Full timing</i>: a route drives the game to a scene and times main against the change. "
                              "<i>Boot check</i>: the game is started and its outcome classed (rendering, crashed, …)."))
        source = QGroupBox("AnyPS5's source")
        form = QFormLayout(source)
        self.repo_dir = QLineEdit(str(repo_dir))
        self.repo_dir.textChanged.connect(self.check_clone)
        form.addRow("Your AnyPS5 clone, with its submodules", self.repo_dir)
        self.clone_state = QLabel("")
        form.addRow(self.clone_state)
        layout.addWidget(source)
        self.found = []
        self.check_clone()
        if folder:
            self.scan()

    def browse(self):
        chosen = QFileDialog.getExistingDirectory(self, "Folder with your dumps", self.folder.text() or str(Path.home()))
        if chosen:
            self.folder.setText(chosen)
            self.scan()

    def scan(self):
        self.found = platform_info.find_dumps(self.folder.text())
        self.table.setRowCount(len(self.found))
        for i, dump in enumerate(self.found):
            route = (ROOT / "routes" / f"{dump['title_id']}.json").exists()
            dump["route"] = str(ROOT / "routes" / f"{dump['title_id']}.json") if route else ""
            for column, value in enumerate((dump["title_id"], dump["name"], dump["version"], "full timing (route)" if route else "boot check", dump["path"])):
                self.table.setItem(i, column, QTableWidgetItem(value))
        self.table.resizeColumnsToContents()
        self.completeChanged.emit()

    def check_clone(self):
        path = Path(self.repo_dir.text()).expanduser()
        self.clone_ok = (path / ".git").exists() and (path / "CMakeLists.txt").exists()
        self.clone_state.setText("Builds take main and the change from here, in worktrees of their own; your checkout is not touched."
                                 if self.clone_ok else "Not an AnyPS5 clone. Clone it with git clone --recursive first.")
        self.completeChanged.emit()

    def isComplete(self):  # noqa: N802
        return bool(self.found) and self.clone_ok


class SignInPage(QWizardPage):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.setTitle("Sign in with GitHub")
        self.setSubTitle("The client reports as you, through the maintainers' App. It can comment and open issues in the results repository; "
                         "nothing else of your account.")
        layout = QVBoxLayout(self)
        self.state = text("")
        layout.addWidget(self.state)
        self.code = QLabel("")
        font = self.code.font()
        font.setPointSize(font.pointSize() * 2)
        font.setBold(True)
        self.code.setFont(font)
        self.code.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.code, 0, Qt.AlignHCenter)
        row = QHBoxLayout()
        row.addStretch(1)
        self.start_button = QPushButton("Sign in with GitHub")
        self.start_button.clicked.connect(self.start)
        row.addWidget(self.start_button)
        self.copy = QPushButton("Copy the code")
        self.copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.code.text()))
        self.copy.setEnabled(False)
        row.addWidget(self.copy)
        self.open = QPushButton("Open github.com/login/device")
        self.open.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.device["verification_uri"])))
        self.open.setEnabled(False)
        row.addWidget(self.open)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        self.device = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.show_state()

    def show_state(self):
        login = self.engine.client.tester()
        if login:
            self.state.setText(f"Signed in as <b>{login}</b>. The sign-in lasts 8 hours and renews itself for 6 months; Settings signs out.")
            self.code.setText("✓")
            for button in (self.start_button, self.copy, self.open):
                button.hide()
        elif self.device:
            self.state.setText(f"Open <a href='{self.device['verification_uri']}'>{self.device['verification_uri']}</a> and enter this code. "
                               f"The page waits until you have.")
        else:
            self.state.setText("Press Sign in: the client shows a code to enter on GitHub's device page, in any browser.")
        self.completeChanged.emit()

    def start(self):
        self.device = self.engine.client.flow().start()
        self.code.setText(self.device["user_code"])
        self.copy.setEnabled(True)
        self.open.setEnabled(True)
        self.timer.start(int(self.device.get("interval", 5)) * 1000)
        self.start_button.setText("New code")
        self.show_state()

    def poll(self):
        try:
            if self.engine.client.flow().poll(self.device):
                self.timer.stop()
                self.device = None
        except Exception as error:  # noqa: BLE001
            self.timer.stop()
            self.state.setText(f"Sign-in failed: {error}")
        self.show_state()

    def isComplete(self):  # noqa: N802
        return bool(self.engine.client.tester())


class RegisterPage(QWizardPage):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.setTitle("Register this machine")
        self.setSubTitle("A maintainer approves new machines. Until then this machine takes no jobs.")
        info = engine.client.info
        form = QFormLayout(self)
        self.machine = QLineEdit(engine.config.machine or socket.gethostname().split(".")[0].lower()[:32])
        form.addRow("Machine name", self.machine)
        form.addRow("GPU", QLabel(info["gpu"]))
        form.addRow("Driver", QLabel(info.get("driver") or "unknown"))
        form.addRow("OS", QLabel(info["os"]))
        form.addRow("Class", QLabel(verdict.class_of(engine.client.machine_class)))
        form.addRow(text("Machines of one class (GPU model, driver branch, OS) are compared with each other; the results of different "
                         "classes are kept apart."))
        row = QHBoxLayout()
        self.state = text("")
        row.addWidget(self.state, 1)
        self.button = QPushButton("Register this machine")
        self.button.clicked.connect(self.register)
        row.addWidget(self.button)
        form.addRow(row)
        self.refresh()

    def refresh(self):
        state, record = self.engine.client.registration()
        self.button.setEnabled(state == "not registered" and bool(self.engine.client.tester()))
        if state == "approved":
            self.state.setText(f"<b>Approved</b> by @{record.get('approved_by', '?')}: this machine takes jobs.")
        elif state == "pending":
            self.state.setText(f"Registration issue #{record.get('issue', '?')} is open: <b>waiting for a maintainer</b>. You can finish now; "
                               f"the client takes jobs once it is approved.")
        elif state == "declined":
            self.state.setText("A maintainer declined this machine.")
        else:
            self.state.setText("Opens an issue in the results repository with this machine's name, GPU, driver, OS and titles.")
        self.completeChanged.emit()

    def register(self):
        self.engine.config.machine = self.machine.text().strip()
        try:
            self.engine.client.register()
        except Exception as error:  # noqa: BLE001
            self.state.setText(f"Could not register: {error}")
            return
        self.refresh()

    def isComplete(self):  # noqa: N802
        return True  # registering can wait; the client takes no jobs until a maintainer has approved the machine


class DonePage(QWizardPage):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.setTitle("Done")
        self.setSubTitle("Nothing has run yet.")
        layout = QVBoxLayout(self)
        self.summary = text("")
        layout.addWidget(self.summary)
        layout.addStretch(1)

    def initializePage(self):  # noqa: N802
        wizard = self.wizard()
        when = wizard.when
        how = (f"when idle for {when.minutes.value()} min" if when.idle.isChecked() else f"from {when.first.value():02d}:00 to {when.last.value():02d}:00")
        how += (", on mains power" if when.mains.isChecked() else "") + (", pausing for fullscreen programs" if when.fullscreen.isChecked() else "")
        state, record = self.engine.client.registration()
        titles = ", ".join(f"{d['name']} ({d['title_id']})" for d in wizard.dumps.found)
        machine = {"approved": ("✓", "approved: it takes jobs now"),
                   "pending": ("…", f"registration #{(record or {}).get('issue', '?')} is waiting for a maintainer: it takes jobs once approved"),
                   "declined": ("✗", "declined by a maintainer: it takes no jobs"),
                   "not registered": ("…", "not registered: it takes no jobs until you register it (Settings) and a maintainer approves it")}[state]
        rows = [("✓", "You have read what leaves this computer and what the sandbox does not protect against."), ("✓", f"It works {how}."),
                ("✓", f"Titles: {titles}."), ("✓", f"Signed in as <b>{self.engine.client.tester()}</b>."),
                (machine[0], f"This machine, <b>{wizard.register_page.machine.text().strip()}</b>: {machine[1]}.")]
        self.summary.setText("<table cellspacing='6'>" + "".join(f"<tr><td><b>{mark}</b></td><td>{line}</td></tr>" for mark, line in rows) + "</table>"
                             "<p>Finish puts the client in the tray. Everything here can be changed later in Schedule, Titles and Settings, "
                             "and the walkthrough runs again from Settings.</p>")


class Walkthrough(QWizard):
    PAGES = ("what", "sandbox", "when", "dumps", "sign-in", "register", "done")

    def __init__(self, engine, folder="", parent=None, start="what"):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("AnyPS5 title runs: first run")
        self.setWizardStyle(QWizard.ModernStyle)
        self.what, self.sandbox, self.when = WhatPage(), SandboxPage(), WhenPage(engine.config.schedule)
        self.dumps = DumpsPage(folder, engine.config.repo_dir)
        self.sign_in, self.register_page, self.done_page = SignInPage(engine), RegisterPage(engine), DonePage(engine)
        for page in (self.what, self.sandbox, self.when, self.dumps, self.sign_in, self.register_page, self.done_page):
            self.addPage(page)
        pages = self.pageIds()
        for number, page_id in enumerate(pages, start=1):
            page = self.page(page_id)
            page.setTitle(f"{number} of {len(pages)} · {page.title()}")
        self.setStartId(self.PAGES.index(start))
        self.resize(920, 620)

    def accept(self):
        config, when = self.engine.config, self.when
        config.schedule.update(idle_only=when.idle.isChecked(), idle_minutes=when.minutes.value(), hours=[when.first.value(), when.last.value()],
                               mains_only=when.mains.isChecked(), pause_fullscreen=when.fullscreen.isChecked(),
                               pause_for=[p.strip() for p in when.games.text().split(",") if p.strip()])
        for dump in self.dumps.found:
            if dump["title_id"] not in config.titles:
                config.titles[dump["title_id"]] = Title(dump["title_id"], Path(dump["path"]), Path(dump["route"]) if dump.get("route") else None)
        config.repo_dir = Path(self.dumps.repo_dir.text()).expanduser()
        config.machine = self.register_page.machine.text().strip() or config.machine
        config.tester = self.engine.client.tester() or config.tester
        configfile.save(config)
        self.engine.client.finish_onboarding({"sandbox_read": True, "idle": "idle" if when.idle.isChecked() else "hours",
                                              "idle_detectable": when.idle_ok, "titles": sorted(config.titles)})
        super().accept()
