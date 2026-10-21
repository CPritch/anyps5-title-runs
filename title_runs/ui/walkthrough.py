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

from .. import ROOT, auth, configfile, platform_info, verdict
from ..config import Title
from . import words


def text(html):
    label = QLabel(html)
    label.setWordWrap(True)
    label.setTextFormat(Qt.RichText)
    label.setOpenExternalLinks(True)
    return label


class WhatPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("What this does")
        self.setSubTitle(f"A few steps before anything runs. Nothing runs until you finish and {words.team()} approves this machine.")
        layout = QVBoxLayout(self)
        layout.addWidget(text(
            f"{words.Team()} picks changes to AnyPS5 to try on real games. When your computer is free, this app takes one, builds "
            "AnyPS5 with and without the change, plays a short part of <b>your own copy</b> of a game with each, and posts how fast each ran "
            "on the change's page on GitHub. The people working on AnyPS5 get results from computers and games they don't have, and you "
            "choose when yours helps."))
        leaves = QGroupBox("What leaves this computer")
        box = QVBoxLayout(leaves)
        box.addWidget(text(
            "<ul><li>Your GitHub name, and your machine's name, graphics card, driver and system. They're public, so the team can tell "
            "machines apart.</li>"
            "<li>How fast each run was, and whether the game started and showed a picture. That's public too, on the change.</li>"
            "<li>A screenshot of the test scene, only if you turn that on in Settings.</li></ul>"
            "<b>Never your game files, your saves, or anything else on this computer.</b>"))
        layout.addWidget(leaves)
        layout.addStretch(1)


class SandboxPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Keeping your computer safe")
        self.setSubTitle("The changes come from people you don't know, so they run in a sandbox. A sandbox has limits.")
        layout = QVBoxLayout(self)
        layout.addWidget(text(
            "Building and playing happen in a sandbox. Once the change is downloaded it has no internet, it can't see your files, and your "
            f"games are read-only to it. It can only write to the test's own folders. {words.Team()} looks at every change before "
            "it's queued, and anything pushed to a change after that isn't run."))
        limits = QGroupBox("What the sandbox can't protect against")
        box = QVBoxLayout(limits)
        box.addWidget(text(
            "<ul><li>A change that attacks your graphics driver or the system itself. The game needs the graphics card, so the sandbox lets it "
            "reach it.</li>"
            "<li>Your screen. The game shows on it, like any program.</li>"
            "<li>Filling your disk or keeping the computer busy. Settings has limits for that.</li>"
            "<li>Anything you run with the sandbox turned off, or a change you choose to run that the team hasn't checked.</li></ul>"))
        layout.addWidget(limits)
        self.read = QCheckBox("I've read what the sandbox can't protect against")
        self.read.toggled.connect(self.completeChanged)
        layout.addWidget(self.read)
        layout.addStretch(1)

    def isComplete(self):  # noqa: N802
        return self.read.isChecked()


class WhenPage(QWizardPage):
    def __init__(self, schedule):
        super().__init__()
        self.setTitle("When to test")
        self.setSubTitle("It should keep out of your way.")
        layout = QVBoxLayout(self)
        self.idle_ok, idle_how = platform_info.idle_detection()
        self.full_ok, full_how = platform_info.fullscreen_detection()
        idle = QGroupBox("When you're away")
        form = QFormLayout(idle)
        self.idle = QCheckBox("Only when the computer has been left alone for")
        self.minutes = QSpinBox()
        self.minutes.setRange(1, 240)
        self.minutes.setValue(schedule["idle_minutes"])
        self.minutes.setSuffix(" min")
        if self.idle_ok:
            form.addRow(text("This computer can tell when you're away from it."))
            self.idle.setChecked(True)
        else:
            away = text("<b>This computer can't tell when you're away from it</b>, so choose the hours it may test instead.")
            away.setToolTip(f"{idle_how}. On Hyprland, an idle daemon such as hypridle or swayidle makes this work.")
            form.addRow(away)
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
        form.addRow("Test only", row)
        layout.addWidget(hours)
        other = QGroupBox("Power and other programs")
        form = QFormLayout(other)
        self.mains = QCheckBox("Only when plugged in")
        self.mains.setChecked(schedule["mains_only"])
        form.addRow(self.mains)
        self.fullscreen = QCheckBox("Pause while a game or video is fullscreen")
        self.fullscreen.setChecked(schedule.get("pause_fullscreen", True) and self.full_ok)
        self.fullscreen.setEnabled(self.full_ok)
        self.fullscreen.setToolTip(full_how)
        form.addRow(self.fullscreen, text("" if self.full_ok else "This computer can't tell when something is fullscreen."))
        self.games = QLineEdit(", ".join(schedule["pause_for"]))
        self.games.setPlaceholderText("program names, separated by commas")
        form.addRow("Also pause while these run", self.games)
        layout.addWidget(other)
        layout.addStretch(1)

    def isComplete(self):  # noqa: N802
        return self.idle_ok or self.first.value() < self.last.value()


class DumpsPage(QWizardPage):
    def __init__(self, folder="", repo_dir=""):
        super().__init__()
        self.setTitle("Your games")
        self.setSubTitle("Choose the folder your games are in. They stay where they are and aren't changed.")
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.folder = QLineEdit(folder)
        row.addWidget(self.folder, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.browse)
        row.addWidget(browse)
        scan = QPushButton("Find games")
        scan.clicked.connect(self.scan)
        row.addWidget(scan)
        layout.addLayout(row)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Game ID", "Name", "Version", "Test", "Folder"])
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.result = text("Press Find games to look through your home folder, or choose a folder first.")
        layout.addWidget(self.result)
        layout.addWidget(self.table)
        layout.addWidget(text("<i>Full test</i>: the app plays a set part of the game and times it. "
                              "<i>Start-up check</i>: the app only checks the game starts and shows a picture."))
        source = QGroupBox("AnyPS5's source code")
        form = QFormLayout(source)
        self.repo_dir = QLineEdit(str(repo_dir))
        self.repo_dir.textChanged.connect(self.check_clone)
        form.addRow("Its folder", self.repo_dir)
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
        where = platform_info.search_folder(self.folder.text())
        skip = [self.wizard().engine.config.state_dir] if self.wizard() else []
        self.found = platform_info.find_dumps(where, depth=3 if self.folder.text().strip() else 4, skip=skip)
        shown = str(where).replace(str(Path.home()), "~", 1)
        if self.found:
            names = ", ".join(sorted({d["name"] for d in self.found}))
            self.result.setText(f"Found {len(self.found)} game{'s' if len(self.found) != 1 else ''} in {shown}: {names}.")
        elif not where.is_dir():
            self.result.setText(f"There is no folder {shown}. Choose the folder your games are in with Browse.")
        else:
            self.result.setText(f"No games found in {shown}. A game's folder has eboot.bin and a sce_sys folder in it: "
                                f"choose the folder that holds your game folders, or a game's own folder.")
        self.table.setRowCount(len(self.found))
        for i, dump in enumerate(self.found):
            route = (ROOT / "routes" / f"{dump['title_id']}.json").exists()
            dump["route"] = str(ROOT / "routes" / f"{dump['title_id']}.json") if route else ""
            for column, value in enumerate((dump["title_id"], dump["name"], dump["version"], "Full test" if route else "Start-up check", dump["path"])):
                self.table.setItem(i, column, QTableWidgetItem(value))
        self.table.resizeColumnsToContents()
        self.completeChanged.emit()

    def check_clone(self):
        path = Path(self.repo_dir.text()).expanduser()
        self.clone_ok = (path / ".git").exists() and (path / "CMakeLists.txt").exists()
        self.clone_state.setText("Found. Each test works on its own copies, so this folder isn't changed." if self.clone_ok else
                                 "That folder isn't AnyPS5's source code. (Developers: git clone --recursive the AnyPS5 repository.)")
        self.completeChanged.emit()

    def isComplete(self):  # noqa: N802
        return bool(self.found) and self.clone_ok


class SignInPage(QWizardPage):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.setTitle("Sign in with GitHub")
        self.setSubTitle("The app posts results as you. It can only post on the testing pages you joined, nothing else on your account.")
        layout = QVBoxLayout(self)
        self.where = QGroupBox("Join the testing")
        row = QHBoxLayout(self.where)
        self.location = QLineEdit(engine.config.results_url)
        self.location.setPlaceholderText("Paste the testing link you were given (https://github.com/…)")
        row.addWidget(self.location, 1)
        use = QPushButton("Join")
        use.clicked.connect(self.use)
        row.addWidget(use)
        layout.addWidget(self.where)
        self.where.setVisible(not engine.config.results_url)
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

    def use(self):
        try:
            self.engine.client.use(self.location.text())
            self.engine.save_config()
        except Exception as error:  # noqa: BLE001 (shown on the page)
            self.state.setText(f"That link didn't work. Check it's the testing link you were given. ({str(error)[:120]})")
            return
        self.show_state()

    def show_state(self):
        login = self.engine.client.tester()
        has_repo = bool(self.engine.config.results_url) and bool((self.engine.client.repo.read("config.json", {}).get("app") or {}).get("client_id"))
        self.start_button.setEnabled(has_repo)
        if not has_repo:
            self.state.setText("First paste the testing link you were given, and press Join.")
            self.completeChanged.emit()
            return
        if login:
            self.state.setText(f"Signed in as <b>{login}</b>. You stay signed in; Settings can sign you out.")
            self.code.setText("✓")
            for button in (self.start_button, self.copy, self.open):
                button.hide()
        elif self.device:
            self.state.setText(f"Open <a href='{self.device['verification_uri']}'>{self.device['verification_uri']}</a> and type this code. "
                               f"This page carries on by itself once you have.")
        else:
            self.state.setText("Press Sign in with GitHub to get a code to type on GitHub, in any browser.")
        self.completeChanged.emit()

    def start(self):
        self.device = self.engine.client.flow().start()
        self.code.setText(self.device["user_code"])
        self.copy.setEnabled(True)
        self.open.setEnabled(True)
        self.timer.start(auth.DeviceFlow.interval(self.device) * 1000)
        self.start_button.setText("New code")
        self.show_state()

    def poll(self):
        try:
            if self.engine.client.flow().poll(self.device):
                self.timer.stop()
                self.device = None
            else:
                self.timer.setInterval(auth.DeviceFlow.interval(self.device) * 1000)  # GitHub's slow_down lengthens it
        except Exception as error:  # noqa: BLE001
            self.timer.stop()
            self.state.setText(f"Sign-in didn't work: {error}")
        self.show_state()

    def isComplete(self):  # noqa: N802
        return bool(self.engine.client.tester())


class RegisterPage(QWizardPage):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.setTitle("Register this machine")
        self.setSubTitle(f"{words.Team()} approves each new machine. Until then it doesn't run tests.")
        info = engine.client.info
        form = QFormLayout(self)
        self.machine = QLineEdit(engine.config.machine or socket.gethostname().split(".")[0].lower()[:32])
        form.addRow("Machine name", self.machine)
        form.addRow("Graphics card", QLabel(info["gpu"]))
        form.addRow("Driver", QLabel(info.get("driver") or "unknown"))
        form.addRow("System", QLabel(info["os"]))
        form.addRow(text("Results are compared with machines like this one: the same graphics card, driver and system."))
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
            self.state.setText(f"<b>Approved</b> by {record.get('approved_by', '?')}: this machine runs tests.")
        elif state == "pending":
            self.state.setText(f"<b>Waiting for {words.team()}</b> to approve it. You can finish now: it starts testing once approved.")
        elif state == "declined":
            self.state.setText(f"{words.Team()} turned this machine down.")
        else:
            self.state.setText(f"Registering shares this machine's name, graphics card, driver and system with {words.team()}, in public.")
        self.completeChanged.emit()

    def register(self):
        self.engine.config.machine = self.machine.text().strip()
        try:
            self.engine.client.register()
        except Exception as error:  # noqa: BLE001
            self.state.setText(f"Couldn't register: {error}")
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
        how = (f"when the computer has been left alone for {when.minutes.value()} minutes" if when.idle.isChecked()
               else f"from {when.first.value():02d}:00 to {when.last.value():02d}:00")
        how += (", only when plugged in" if when.mains.isChecked() else "") + (", pausing while something is fullscreen" if when.fullscreen.isChecked() else "")
        state, record = self.engine.client.registration()
        titles = ", ".join(f"{d['name']} ({d['title_id']})" for d in wizard.dumps.found)
        machine = {"approved": ("✓", "approved, so it runs tests"),
                   "pending": ("…", f"waiting for {words.team()} to approve it. It starts testing once approved"),
                   "declined": ("✗", f"turned down by {words.team()}, so it doesn't run tests"),
                   "not registered": ("…", f"not registered yet. It doesn't run tests until you register it (Settings) and {words.team()} approves it")}[state]
        rows = [("✓", "You've read what leaves this computer and what the sandbox can't protect against."), ("✓", f"It tests {how}."),
                ("✓", f"Games: {titles}."), ("✓", f"Signed in as <b>{self.engine.client.tester()}</b>."),
                (machine[0], f"This machine, <b>{wizard.register_page.machine.text().strip()}</b>: {machine[1]}.")]
        self.summary.setText("<table cellspacing='6'>" + "".join(f"<tr><td><b>{mark}</b></td><td>{line}</td></tr>" for mark, line in rows) + "</table>"
                             "<p>Finish opens the app. You can change all of this later in Settings, and go through these steps again from there.</p>")


class Walkthrough(QWizard):
    PAGES = ("what", "sandbox", "when", "dumps", "sign-in", "register", "done")

    def __init__(self, engine, folder="", parent=None, start="what"):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("AnyPS5 title runs: getting started")
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
