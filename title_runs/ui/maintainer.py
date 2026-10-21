"""The maintainers' window, apart from the tester's: the queue with what has reported and what is still wanted, approvals a
push expired, every registered machine and when it last reported, registrations to approve, and queueing a pull
request by its number. Everything here acts through the signed-in maintainer's own GitHub sign-in."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import verdict
from ..relay import overview
from . import theme
from .window import banner, fit, show, title_of, tree, when


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


class MaintainerWindow(QMainWindow):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.setWindowTitle("AnyPS5 title runs: maintainer tools")
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(20, 16, 20, 16)
        queue = QGroupBox("Queue a pull request")
        row = QHBoxLayout(queue)
        row.addWidget(QLabel("Pull request #"))
        self.number = QLineEdit()
        self.number.setPlaceholderText("its number")
        self.number.setMaximumWidth(160)
        row.addWidget(self.number)
        add = theme.mark(QPushButton("Queue its current head"), primary="true")
        add.clicked.connect(self.queue_pr)
        row.addWidget(add)
        self.queued = theme.mark(QLabel("Adds the title-test label to it as you, which is the same as adding it on GitHub."), role="muted")
        self.queued.setWordWrap(True)
        row.addWidget(self.queued, 1)
        layout.addWidget(queue)
        self.overview = OverviewTab(engine)
        layout.addWidget(self.overview, 1)
        self.setCentralWidget(body)
        self.resize(1300, 900)

    def refresh(self):
        self.overview.refresh()

    def queue_pr(self):
        text = self.number.text().strip().lstrip("#")
        if not text.isdigit():
            self.queued.setText("Type the pull request's number.")
            return
        message = self.engine.queue_pr(int(text))
        self.queued.setText(message)
