"""The first-run setup (DESIGN.md, "First run"): find the dumps, detect GPU, driver and OS, name the machine, connect to
the results repository (it reads the queue and writes a claim), pick a schedule. Finish writes the config file."""

import os
import socket
import tempfile
from pathlib import Path

from PySide6.QtWidgets import (QCheckBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QSpinBox,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWizard, QWizardPage)

from .. import ROOT, config as configs, configfile, platform_info, store

EXAMPLE_CMAKE = ["-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release"]


class DumpsPage(QWizardPage):
    def __init__(self, folder=""):
        super().__init__()
        self.setTitle("Your dumps")
        self.setSubTitle("Pick the folder with your extracted packages (eboot.bin and sce_sys/param.json). Nothing of them leaves this computer.")
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
        self.found = []
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
            for column, text in enumerate((dump["title_id"], dump["name"], dump["version"], "full timing (route)" if route else "boot check", dump["path"])):
                self.table.setItem(i, column, QTableWidgetItem(text))
        self.table.resizeColumnsToContents()
        self.completeChanged.emit()

    def isComplete(self):  # noqa: N802
        return bool(self.found)


class MachinePage(QWizardPage):
    def __init__(self, info=None):
        super().__init__()
        self.setTitle("This machine")
        self.setSubTitle("What the reports say about it, and where the client keeps its builds and caches.")
        info = info or platform_info.machine_info()
        self.info = info
        form = QFormLayout(self)
        form.addRow("GPU", QLabel(info["gpu"]))
        form.addRow("Driver", QLabel(info.get("driver", "") or "unknown"))
        form.addRow("OS", QLabel(info["os"]))
        self.machine = QLineEdit(socket.gethostname().split(".")[0].lower()[:32])
        form.addRow("Machine name", self.machine)
        self.tester = QLineEdit()
        self.tester.setPlaceholderText("your GitHub account")
        form.addRow("Tester", self.tester)
        self.repo_dir = QLineEdit(str(Path.home() / "src" / "AnyPS5"))
        form.addRow("AnyPS5 clone", self.repo_dir)
        self.state_dir = QLineEdit(str(Path.home() / "games" / "title-runs-state"))
        form.addRow("Builds and caches", self.state_dir)
        note = QLabel("Keep the builds and caches on the same file system as the dumps: the game folders hard-link the dumps' files.")
        note.setWordWrap(True)
        form.addRow(note)


class ResultsPage(QWizardPage):
    def __init__(self, url="", machine_page=None):
        super().__init__()
        self.machine_page = machine_page
        self.setTitle("The results repository")
        self.setSubTitle("Paste the repository and the token the maintainer gave you. The client checks that it can read the queue and write a claim.")
        form = QFormLayout(self)
        self.url = QLineEdit(url)
        self.url.setPlaceholderText("https://github.com/<owner>/anyps5-title-runs-results.git")
        form.addRow("Repository", self.url)
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.Password)
        self.token.setPlaceholderText("the token (not needed for a local stand-in)")
        form.addRow("Token", self.token)
        row = QHBoxLayout()
        self.result = QLabel("")
        self.result.setWordWrap(True)
        row.addWidget(self.result, 1)
        check = QPushButton("Check")
        check.clicked.connect(self.check)
        row.addWidget(check)
        form.addRow(row)
        self.ok = False

    def check(self):
        machine = self.machine_page.machine.text().strip() if self.machine_page else "setup-check"
        tester = (self.machine_page.tester.text().strip() if self.machine_page else "") or "tester"
        env = "TITLE_RUNS_SETUP_TOKEN"
        if self.token.text():
            os.environ[env] = self.token.text()
        try:
            with tempfile.TemporaryDirectory() as work:
                repo = store.ResultsRepo(self.url.text().strip(), work, env if self.token.text() else None,
                                         author=(tester, f"{tester}@users.noreply.github.com"))
                entries = repo.can_read_and_write(machine)
            self.result.setText(f"Read the queue ({entries} entr{'y' if entries == 1 else 'ies'}) and wrote a claim for {machine}, then removed it: connected.")
            self.ok = True
        except Exception as error:  # noqa: BLE001 (shown to the tester)
            self.result.setText(f"Not connected: {error}")
            self.ok = False
        finally:
            os.environ.pop(env, None)
        self.completeChanged.emit()

    def isComplete(self):  # noqa: N802
        return self.ok


class SchedulePage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("When to run")
        self.setSubTitle("The client works when the machine is idle and gets out of the way when you use it.")
        form = QFormLayout(self)
        self.idle = QCheckBox("Only when the computer is idle")
        self.idle.setChecked(True)
        self.minutes = QSpinBox()
        self.minutes.setRange(1, 240)
        self.minutes.setValue(10)
        self.minutes.setSuffix(" min without input")
        form.addRow(self.idle, self.minutes)
        self.mains = QCheckBox("Only on mains power")
        self.mains.setChecked(True)
        form.addRow(self.mains)
        hours = QHBoxLayout()
        self.first, self.last = QSpinBox(), QSpinBox()
        for box, value in ((self.first, 0), (self.last, 24)):
            box.setRange(0, 24)
            box.setValue(value)
            box.setSuffix(":00")
        hours.addWidget(QLabel("from"))
        hours.addWidget(self.first)
        hours.addWidget(QLabel("to"))
        hours.addWidget(self.last)
        hours.addStretch(1)
        form.addRow("Hours", hours)


class SetupWizard(QWizard):
    def __init__(self, config_path, folder="", url="", info=None, parent=None):
        super().__init__(parent)
        self.config_path = Path(config_path)
        self.setWindowTitle("AnyPS5 title runs: setup")
        self.dumps, self.machine = DumpsPage(folder), MachinePage(info)
        self.results, self.schedule = ResultsPage(url, self.machine), SchedulePage()
        for page in (self.dumps, self.machine, self.results, self.schedule):
            self.addPage(page)
        self.resize(900, 560)

    def config_data(self):
        info = self.machine.info
        token_env = "TITLE_RUNS_RESULTS_TOKEN"
        titles = {d["title_id"]: {"dump": d["path"], **({"route": d["route"]} if d.get("route") else {})} for d in self.dumps.found}
        return {"state_dir": self.machine.state_dir.text(),
                "tester": {"name": self.machine.tester.text().strip(), "machine": self.machine.machine.text().strip()},
                "machine": {"gpu": info["gpu"], "driver": info.get("driver", ""), "os": info["os"]},
                "results": {"url": self.results.url.text().strip(), "token_env": token_env},
                "schedule": {**configs.SCHEDULE, "idle_only": self.schedule.idle.isChecked(), "idle_minutes": self.schedule.minutes.value(),
                             "mains_only": self.schedule.mains.isChecked(), "hours": [self.schedule.first.value(), self.schedule.last.value()]},
                "source": {"repo_dir": self.machine.repo_dir.text(), "remote": "origin", "cmake_args": EXAMPLE_CMAKE},
                "sandbox": {"mode": "bwrap"},
                "titles": titles}

    def accept(self):
        self.config_path.write_text("# anyps5-title-runs: written by the setup window.\n\n" + configfile.dumps(self.config_data()))
        configs.load(self.config_path)
        if self.results.token.text():
            token_file = Path(self.machine.state_dir.text()) / "client" / "results-token"
            token_file.parent.mkdir(parents=True, exist_ok=True)
            token_file.write_text(self.results.token.text())
            token_file.chmod(0o600)
        super().accept()
