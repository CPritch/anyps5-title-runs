"""The window: Queue, Overview, Pull requests, Schedule, Titles, Settings (DESIGN.md, "The window"). Data comes from the
engine (app.Engine) through ui/model.py and relay/overview.py; nothing here is platform-specific."""

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (QCheckBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import platform_info, verdict
from ..config import results_location as clients_location
from ..relay import overview
from ..relay.render import utc
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


class QueueTab(QWidget):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.not_ready = banner()
        top.addWidget(self.not_ready, 1)
        self.fix = QPushButton("")
        self.fix.clicked.connect(lambda: engine.window.fix_readiness())
        self.fix.hide()
        top.addWidget(self.fix, 0, Qt.AlignTop)
        layout.addLayout(top)
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
        ready, why, fix = self.engine.readiness()
        stale = self.engine.stale_text()
        unused = self.engine.ignored_mine()
        show(self.not_ready, "<br>".join(x for x in ((f"<b>This machine takes no jobs yet</b>: {why}." if not ready else ""), stale, unused) if x))
        self.fix.setText(fix)
        self.fix.setVisible(bool(fix))
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


class OverviewTab(QWidget):
    """What the maintainers see in the results repository's Overview issue, live from the checkout: the queue with each
    approved head's coverage and combined verdicts and what is still wanted, approvals that need a maintainer, the
    registered machines and when each last reported, and the pending registrations (approve or decline, for maintainers)."""

    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.sent = {}
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        top.addWidget(self.summary, 1)
        self.open_issue = QPushButton("Open the Overview issue")
        self.open_issue.clicked.connect(lambda: self.engine.open_url(self.engine.issue_url(self.engine.overview_issue())))
        top.addWidget(self.open_issue)
        layout.addLayout(top)
        self.stale = banner()
        layout.addWidget(self.stale)
        self.ignored = QLabel("")
        self.ignored.setWordWrap(True)
        self.ignored.setStyleSheet("QLabel { color: palette(mid); }")
        layout.addWidget(self.ignored)
        queue = QGroupBox("Queue: approved heads, what has reported and what is still wanted")
        box = QVBoxLayout(queue)
        self.queue = QTreeWidget()
        self.queue.setHeaderLabels(["PR", "Approved head", "Approved by", "Reported", "Still wanted", "Job"])
        for i, width in enumerate((250, 100, 170, 230, 250)):
            self.queue.setColumnWidth(i, width)
        self.queue.itemDoubleClicked.connect(lambda item, _: self.engine.open_url(item.data(0, Qt.UserRole) or ""))
        box.addWidget(self.queue)
        layout.addWidget(queue, 3)
        attention = QGroupBox("Approvals that need a maintainer")
        box = QVBoxLayout(attention)
        self.attention = tree(["PR", "What happened", "Head", "By", "When"])
        fit(self.attention, stretch=1)
        box.addWidget(self.attention)
        layout.addWidget(attention, 1)
        row = QHBoxLayout()
        machines = QGroupBox("Registered machines")
        box = QVBoxLayout(machines)
        self.machines = tree(["Tester / machine", "Class", "Titles", "Approved by", "Last report"])
        fit(self.machines, stretch=1)
        box.addWidget(self.machines)
        row.addWidget(machines, 3)
        pending = QGroupBox("Pending registrations")
        box = QVBoxLayout(pending)
        self.pending = tree(["Issue", "Tester / machine", "Class", ""])
        fit(self.pending, stretch=2)
        box.addWidget(self.pending)
        self.pending_note = QLabel("")
        self.pending_note.setWordWrap(True)
        box.addWidget(self.pending_note)
        row.addWidget(pending, 2)
        layout.addLayout(row, 2)

    def refresh(self):
        data, maintainer = self.engine.overview(), self.engine.client.maintainer()
        login = self.engine.client.tester()
        repository = self.engine.repository
        self.summary.setText(f"<b>{repository}</b> · results in {self.engine.results_repository()} · the workflow last ran {when(data['last_run'])}"
                             f" · {'you are a maintainer' if maintainer else ('signed in as ' + login) if login else 'not signed in'}")
        self.summary.setTextFormat(Qt.RichText)
        self.open_issue.setEnabled(bool(self.engine.overview_issue()))
        show(self.stale, self.engine.stale_text())
        ignored = overview.ignored_text(data.get("ignored"))
        show(self.ignored, f"Ignored without a reply: {ignored}." if ignored else "")
        self.queue.clear()
        for item in data["entries"]:
            e, c = item["entry"], item["coverage"]
            reported = f"{c['reported']} machine{'s' if c['reported'] != 1 else ''}" + (f", {', '.join(c['titles'])}" if c["titles"] else "")
            if item["claims"]:
                reported += f"; running on {', '.join(item['claims'])}"
            top = QTreeWidgetItem([f"#{e['pr']} {e.get('title', '')}", e["head"][:9], f"@{e['approval']['by']} ({e['approval']['via']})", reported,
                                   c["wanted"], f"#{item['issue']}" if item["issue"] else "-"])
            top.setToolTip(0, f"#{e['pr']} {e.get('title', '')}\nby {e.get('author', '?')}")
            top.setData(0, Qt.UserRole, self.engine.pull_url(e["pr"]))
            if c["wanted"] != "nothing":
                top.setForeground(4, Qt.darkYellow)
            self.queue.addTopLevelItem(top)
            for name, combined in c["classes"].items():
                child = QTreeWidgetItem([f"{title_of(name)}: {combined['text']}"])
                child.setToolTip(0, f"{name}: {combined['text']}")
                colour = {"faster": Qt.darkGreen, "slower": Qt.darkRed, "mixed": Qt.darkYellow}.get(combined["verdict"])
                if colour is not None:
                    child.setForeground(0, colour)
                top.addChild(child)
                child.setFirstColumnSpanned(True)
            for head in e.get("unapproved", []):
                child = QTreeWidgetItem([f"{head['sha'][:9]} is the PR's head but not the approved commit: not checked"])
                child.setForeground(0, Qt.darkYellow)
                top.addChild(child)
                child.setFirstColumnSpanned(True)
            top.setExpanded(True)
        if not data["entries"]:
            empty = QTreeWidgetItem(["Nothing is queued. A maintainer queues a PR by adding the label "
                                     f"{self.engine.label()} to it on GitHub."])
            empty.setForeground(0, Qt.gray)
            self.queue.addTopLevelItem(empty)
            empty.setFirstColumnSpanned(True)
        self.attention.clear()
        rows = [(x["at"], [f"#{x['pr']}", f"approval expired: {x['by'][:9]} was pushed after it; the App removed {self.engine.label()}",
                           x["head"][:9], f"@{x['pusher']}" if x.get("pusher") else "?", when(x["at"])]) for x in data["expired"]]
        rows += [(x["labelled"], [f"#{x['pr']}", f"label refused: the head {x['head'][:9]} was pushed after the label ({x.get('source', '')})",
                                  x["head"][:9], f"@{x['by']}", when(x["labelled"])]) for x in data["refused"]]
        for _, columns in sorted(rows, reverse=True):
            item = QTreeWidgetItem(columns)
            item.setToolTip(1, columns[1])
            self.attention.addTopLevelItem(item)
        if not rows:
            item = QTreeWidgetItem(["", "None."])
            item.setForeground(1, Qt.gray)
            self.attention.addTopLevelItem(item)
        self.machines.clear()
        for m in data["machines"]:
            item = QTreeWidgetItem([m["key"], verdict.class_of(m["class"]), ", ".join(m.get("titles", [])) or "-", f"@{m.get('approved_by', '?')}",
                                    when(m.get("last_report"))])
            if m["tester"] == login and m["machine"] == self.engine.config.machine:
                font = QFont(item.font(0))
                font.setBold(True)
                item.setFont(0, font)
            self.machines.addTopLevelItem(item)
        self.pending.clear()
        for p in data["pending"]:
            item = QTreeWidgetItem([f"#{p['issue']}", p["key"], verdict.class_of(p["class"]), ""])
            self.pending.addTopLevelItem(item)
            sent = self.sent.get(p["issue"])
            if sent:
                item.setText(3, f"{sent}: next workflow run")
                item.setForeground(3, Qt.darkGreen)
                continue
            buttons = QWidget()
            row = QHBoxLayout(buttons)
            row.setContentsMargins(0, 0, 0, 0)
            for word, label in (("Approve", "approved"), ("Decline", "declined")):
                button = QPushButton(word)
                button.setEnabled(maintainer)
                button.setToolTip(f"Adds the label {label} to issue #{p['issue']} as you" if maintainer else "Only a maintainer can approve machines")
                button.clicked.connect(lambda _=False, issue=p["issue"], lab=label, w=word: self.decide(issue, lab, w))
                row.addWidget(button)
            self.pending.setItemWidget(item, 3, buttons)
        self.pending_note.setText("None." if not data["pending"] else
                                  "Approve adds the label approved to the registration issue (as you); the workflow records it on its next run."
                                  if maintainer else "A maintainer approves each new machine by adding the label approved to its issue.")

    def decide(self, issue, label, word):
        message = self.engine.decide_registration(issue, label)
        if message:
            QMessageBox.warning(self, "AnyPS5 title runs", message)
            return
        self.sent[issue] = "approved" if label == "approved" else "declined"
        self.refresh()


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
        when = QGroupBox("When work may run")
        form = QFormLayout(when)
        detectable, how = platform_info.idle_detection()
        self.idle = QCheckBox("Only when the computer is idle")
        self.idle.setChecked(rules["idle_only"] and detectable)
        self.idle_minutes = QSpinBox()
        self.idle_minutes.setRange(1, 240)
        self.idle_minutes.setValue(rules["idle_minutes"])
        self.idle_minutes.setSuffix(" min without input")
        form.addRow(self.idle, self.idle_minutes)
        note = QLabel(f"{how}." if detectable else f"Not available here: {how}. The hours below decide when work may run.")
        note.setWordWrap(True)
        form.addRow(note)
        if not detectable:
            self.idle.setEnabled(False)
            self.idle_minutes.setEnabled(False)
        self.mains = QCheckBox("Only on mains power")
        self.mains.setChecked(rules["mains_only"])
        form.addRow(self.mains)
        full_ok, full_how = platform_info.fullscreen_detection()
        self.fullscreen = QCheckBox("Pause while a fullscreen program runs")
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
        form.addRow("GPU, driver, OS", QLabel(f"{info['gpu']}, {info.get('driver', '')}, {info['os']} (class {verdict.class_of(engine.client.machine_class)})"))
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
        self.url.setPlaceholderText("The testing link the AnyPS5 team gave you (https://github.com/…)")
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
        login = self.engine.client.tester()
        self.account.setText(f"signed in as {login} through the App" if login else "not signed in")
        self.sign.setText("Sign out" if login else "Sign in…")
        state, record = self.engine.client.registration()
        record = record or {}
        issue = record.get("issue")
        link = f" (<a href='{self.engine.issue_url(issue)}'>#{issue}</a>)" if issue else ""
        self.registration.setText({"approved": f"approved by @{record.get('approved_by', '?')}{link}",
                                   "pending": f"waiting for a maintainer{link}", "declined": f"declined{link}",
                                   "not registered": "not registered: this machine takes no jobs"}[state])
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


class MainWindow(QMainWindow):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        engine.window = self
        self.setWindowTitle("AnyPS5 title runs")
        self.tabs = QTabWidget()
        self.queue, self.overview, self.prs, self.schedule, self.titles, self.settings = (
            QueueTab(engine), OverviewTab(engine), PullRequestsTab(engine), ScheduleTab(engine), TitlesTab(engine), SettingsTab(engine))
        self.pages = ((self.queue, "Queue"), (self.overview, "Overview"), (self.prs, "Pull requests"), (self.schedule, "Schedule"),
                      (self.titles, "Titles"), (self.settings, "Settings"))
        for widget, name in self.pages:
            self.tabs.addTab(widget, name)
        self.setCentralWidget(self.tabs)
        self.resize(1180, 760)

    def refresh(self):
        for tab, _ in self.pages:
            tab.refresh()

    def walkthrough(self, start="what"):
        from .walkthrough import Walkthrough
        folder = next((str(t.dump.parent) for t in self.engine.config.titles.values()), "")
        Walkthrough(self.engine, folder, self, start).exec()
        self.refresh()

    def fix_readiness(self):
        """The Queue tab's button next to "takes no jobs yet": the walkthrough, sign-in or registration."""
        _, _, fix = self.engine.readiness()
        if fix == "Register this machine":
            self.tabs.setCurrentWidget(self.settings)
            self.settings.register_machine()
        else:
            self.walkthrough({"Finish the walkthrough": "what", "Sign in…": "sign-in"}.get(fix, "what"))

    def run_unchecked(self, row):
        """Run… on a PR no maintainer queued: the trust dialog, then the job on the tester's trust."""
        ready, why, _ = self.engine.readiness()
        if not ready:
            QMessageBox.information(self, "AnyPS5 title runs", f"This machine takes no jobs yet: {why}.")
            return
        dialog = TrustDialog(row["number"], row["title"], row["author"], self)
        if dialog.exec() == TrustDialog.Accepted and dialog.scope:
            self.engine.run_on_trust(row, dialog.scope)
