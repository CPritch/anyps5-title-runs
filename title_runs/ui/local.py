"""The Local tests page and the report window: pull requests the tester picks, tested on this computer against the
project's main (with any fixes carried on both sides), each result with a report the tester may post themselves.
Nothing here posts anything: the report window gives the pull request's link, the text to copy, and Mark as posted.
Data from app.Engine (local_rows, local_results and the local_* actions)."""

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QTableWidget, QVBoxLayout, QWidget)

from ..relay.render import utc
from . import theme
from .home import card, rich


def amber(text=""):
    label = rich(text)
    label.setStyleSheet("QLabel { background: #fff4d6; color: #5c4400; border: 1px solid #e0a100; border-radius: 8px; padding: 8px 12px; }")
    label.setVisible(bool(text))
    return label


def numbers(text):
    return [int(x) for x in text.replace("#", " ").replace(",", " ").split() if x.isdigit()]


def result_words(row):
    """The Result column: what the newest entry says, and against what."""
    entry, muted = row["entry"], theme.COLOURS["muted"]
    if entry["status"] == "queued":
        return "Waiting to be tested" + (" again" if entry.get("again") else "")
    if entry["status"] == "skipped":
        return f"Not tested: {entry.get('reason', '')}"
    base = f"main {entry.get('main', '?')[:9]}" + "".join(f" + #{f['pr']}" for f in entry.get("fixes", []))
    return (f"{entry.get('verdict', entry['status'])}<br><small style='color:{muted}'>{utc(entry.get('at', ''))} · "
            f"{entry['head'][:9]} against {base}</small>")


def report_words(row):
    report = row.get("report", "")
    if report.startswith("Stale: "):
        return f"<b style='color:#a36a00'>Stale</b><br><small>{report[len('Stale: '):]}</small>"
    if report == "Posted":
        return f"Posted<br><small style='color:{theme.COLOURS['muted']}'>{utc(row['entry']['posted']['at'])}</small>"
    return report or "—"


class LocalTestsPage(QWidget):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        config = engine.config
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        top, box = card()
        heading = QHBoxLayout()
        heading.addWidget(theme.mark(QLabel("Local tests"), role="title"), 1)
        self.toggle = QPushButton("What to test…")
        self.toggle.setCheckable(True)
        self.toggle.toggled.connect(lambda on: self.settings.setVisible(on))
        heading.addWidget(self.toggle, 0, Qt.AlignTop)
        box.addLayout(heading)
        box.addWidget(rich("Pull requests you pick, tested on this computer against the project's main. Nothing is posted: each result "
                           "has a report you can post yourself.", role="muted"))
        self.notice = amber()
        box.addWidget(self.notice)
        add = QHBoxLayout()
        self.add_text = QLineEdit()
        self.add_text.setPlaceholderText("A pull request number, or its link")
        self.add_text.returnPressed.connect(self.add)
        add.addWidget(self.add_text, 1)
        button = theme.mark(QPushButton("Add"), primary="true")
        button.clicked.connect(self.add)
        add.addWidget(button)
        box.addLayout(add)
        self.add_note = rich("", role="muted")
        self.add_note.hide()
        box.addWidget(self.add_note)
        base = QHBoxLayout()
        self.base = rich("")
        base.addWidget(self.base, 1)
        latest = QPushButton("Use the latest main")
        latest.setToolTip("The next local test is measured against main as it is then")
        latest.clicked.connect(lambda: (engine.local_unpin(), self.refresh()))
        base.addWidget(latest)
        box.addLayout(base)
        layout.addWidget(top)

        listed, box = card()
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Pull request", "Result", "Report", ""])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setWordWrap(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        box.addWidget(self.table)
        layout.addWidget(listed, 1)

        settings = QGroupBox("What to test")
        form = QFormLayout(settings)
        self.repository = QLineEdit(config.local_repository)
        self.repository.setPlaceholderText("the project on GitHub, OWNER/NAME")
        form.addRow("Project", self.repository)
        self.people = QLineEdit(", ".join(config.local_people))
        self.people.setPlaceholderText("GitHub names (optional)")
        form.addRow("People", self.people)
        form.addRow(rich("Their open pull requests are tested too.", role="muted"))
        self.fixes = QLineEdit(", ".join(str(n) for n in config.local_fixes))
        self.fixes.setPlaceholderText("pull request numbers (optional)")
        form.addRow("Fixes on both sides", self.fixes)
        form.addRow(rich("Merged onto main for both sides, for when main can't run your games without them. One main already has "
                         "is left out by itself.", role="muted"))
        save = QPushButton("Save")
        save.clicked.connect(self.save)
        form.addRow(save)
        layout.addWidget(settings)
        self.settings = settings
        self.toggle.setChecked(not config.local_repository)
        settings.setVisible(not config.local_repository)
        self.shown = None

    def add(self):
        self.add_note.setText(self.engine.local_add(self.add_text.text()))
        self.add_note.show()
        if self.add_note.text().startswith("Added"):
            self.add_text.clear()
        self.refresh()

    def save(self):
        self.engine.local_save(self.repository.text().strip(), [a for a in self.people.text().replace(",", " ").split() if a],
                               numbers(self.fixes.text()))
        self.refresh()

    def refresh(self):
        held = self.engine.local_notice()
        self.notice.setText(held)
        self.notice.setVisible(bool(held))
        self.base.setText(f"Measured against {self.engine.local_base()}.")
        rows = self.engine.local_rows()
        shown = [(r["pr"], r["entry"].get("head"), r["entry"]["status"], r.get("report"), r["entry"].get("at")) for r in rows]
        if shown == self.shown:  # unchanged: no rebuild on the two-second refresh
            return
        self.shown = shown
        self.table.setRowCount(len(rows))
        muted = theme.COLOURS["muted"]
        for i, row in enumerate(rows):
            title = (f"<b>#{row['pr']}</b> {row['title']}<br><small style='color:{muted}'>{row['author']}"
                     + (" · removed from the list" if row.get("removed") else "") + "</small>")
            for column, html in enumerate((title, result_words(row), report_words(row))):
                label = rich(html)
                label.setContentsMargins(6, 4, 6, 4)
                self.table.setCellWidget(i, column, label)
            buttons = QWidget()
            line = QHBoxLayout(buttons)
            line.setContentsMargins(4, 2, 4, 2)
            has_result = row["entry"]["status"] in ("done", "failed") or bool(row["earlier"])
            for text, action, enabled in (("Report", lambda _=False, n=row["pr"]: self.engine.window.open_report(n), has_result),
                                          ("Test again", lambda _=False, n=row["pr"]: (self.engine.local_again(n), self.refresh()),
                                           row["entry"]["status"] in ("done", "failed", "skipped")),
                                          ("Remove", lambda _=False, n=row["pr"]: (self.engine.local_remove(n), self.refresh()), not row.get("removed"))):
                button = QPushButton(text)
                button.setEnabled(enabled)
                button.clicked.connect(action)
                line.addWidget(button)
            self.table.setCellWidget(i, 3, buttons)
        self.table.resizeRowsToContents()


class ReportDialog(QDialog):
    """One PR's report: the link to post it on first, the text (editable), Copy, Open the pull request, Mark as posted."""

    def __init__(self, engine, number, parent=None):
        super().__init__(parent)
        self.engine, self.number = engine, number
        self.setWindowTitle(f"Report for #{number}")
        self.resize(980, 760)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        self.results = engine.local_results(number)
        link = self.results[0]["link"] if self.results else engine.local.pull_url(number)
        self.link = link
        layout.addWidget(rich(f"Post it on <a href='{link}'>{link}</a>"))
        self.pick = QComboBox()
        for result in self.results:
            entry = result["entry"]
            base = f"main {entry.get('main', '?')[:9]}" + "".join(f" + #{f['pr']}" for f in entry.get("fixes", []))
            self.pick.addItem(f"{utc(entry.get('at', ''))} · {entry['head'][:9]} against {base} · {entry.get('verdict', '')}")
        self.pick.currentIndexChanged.connect(self.show_result)
        self.pick.setVisible(len(self.results) > 1)
        layout.addWidget(self.pick)
        self.stale = amber()
        layout.addWidget(self.stale)
        self.posted_note = rich("", role="muted")
        layout.addWidget(self.posted_note)
        self.text = QPlainTextEdit()
        self.text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        layout.addWidget(self.text, 1)
        buttons = QHBoxLayout()
        self.copy = theme.mark(QPushButton("Copy report"), primary="true")
        self.copy.clicked.connect(self.copy_text)
        buttons.addWidget(self.copy)
        open_pr = QPushButton("Open the pull request")
        open_pr.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.link)))
        buttons.addWidget(open_pr)
        self.mark = QPushButton("")
        self.mark.clicked.connect(self.toggle_posted)
        buttons.addWidget(self.mark)
        buttons.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.show_result(0)

    def current(self):
        return self.results[self.pick.currentIndex()] if self.results else None

    def show_result(self, _index):
        result = self.current()
        if result is None:
            self.text.setPlainText("No result yet.")
            self.copy.setEnabled(False)
            self.mark.setEnabled(False)
            return
        self.text.setPlainText(result["text"])
        self.stale.setText(f"<b>Stale</b>: {result['stale']}. Test it again before posting." if result["stale"] else "")
        self.stale.setVisible(bool(result["stale"]))
        posted = result["entry"].get("posted")
        self.posted_note.setText(f"You marked this posted on {utc(posted['at'])}." if posted else "")
        self.posted_note.setVisible(bool(posted))
        self.mark.setText("Mark as not posted" if posted else "Mark as posted")

    def copy_text(self):
        QGuiApplication.clipboard().setText(self.text.toPlainText())
        self.copy.setText("Copied")
        QTimer.singleShot(2000, lambda: self.copy.setText("Copy report"))

    def toggle_posted(self):
        result = self.current()
        entry = result["entry"]
        self.engine.local_posted(self.number, entry["head"], not entry.get("posted"), entry.get("at"))
        index = self.pick.currentIndex()
        self.results = self.engine.local_results(self.number)
        self.show_result(index)
