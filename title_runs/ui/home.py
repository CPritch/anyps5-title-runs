"""The main screen: what this machine is doing in one line, Start and Stop, automatic testing on or off, the test's
progress and the game itself while it runs, the tests coming up and the results sent. Data from app.Engine through
ui/model.py; the words are a tester's, not the workflow's."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from ..relay.render import utc
from . import model, theme, words
from .gameview import GameView


def card():
    frame = theme.mark(QFrame(), card="true")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(10)
    return frame, layout


class RowList(QListWidget):
    """Rows of rich text that wrap to the list's width, also when it is resized."""

    def __init__(self):
        super().__init__()
        self.setSelectionMode(QListWidget.NoSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.rows = None

    def set_rows(self, rows):
        if rows == self.rows:  # unchanged: no rebuild, so no flicker on the two-second refresh
            return
        self.rows = list(rows)
        self.clear()
        for html in rows:
            item = QListWidgetItem()
            label = rich(html)
            label.setContentsMargins(8, 6, 8, 6)
            self.addItem(item)
            self.setItemWidget(item, label)
        self.fit()

    def fit(self):
        width = max(120, self.viewport().width() - 4)
        for i in range(self.count()):
            item = self.item(i)
            label = self.itemWidget(item)
            if label is None:  # a row being added: a scrollbar appearing resizes the list before its label is set
                continue
            item.setSizeHint(QSize(width, label.heightForWidth(width) + 4))

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self.fit()


def rich(html, role=None):
    label = QLabel(html)
    label.setTextFormat(Qt.RichText)
    label.setWordWrap(True)
    label.setOpenExternalLinks(True)
    if role:
        theme.mark(label, role=role)
    return label


class HomePage(QWidget):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        top, box = card()
        row = QHBoxLayout()
        words = QVBoxLayout()
        self.headline = theme.mark(QLabel(""), role="title")
        self.headline.setWordWrap(True)
        words.addWidget(self.headline)
        self.detail = rich("", role="muted")
        words.addWidget(self.detail)
        self.notice = rich("")
        self.notice.setStyleSheet("QLabel { background: #fff4d6; color: #5c4400; border: 1px solid #e0a100; border-radius: 8px; padding: 8px 12px; }")
        self.notice.hide()
        words.addWidget(self.notice)
        row.addLayout(words, 1)
        buttons = QVBoxLayout()
        self.start = theme.mark(QPushButton("Start"), primary="true")
        self.start.clicked.connect(self.start_clicked)
        buttons.addWidget(self.start)
        self.stop = theme.mark(QPushButton("Stop"), danger="true")
        self.stop.clicked.connect(self.stop_clicked)
        buttons.addWidget(self.stop)
        self.fix = theme.mark(QPushButton("Finish setting up"), primary="true")
        self.fix.clicked.connect(lambda: self.engine.window.fix_readiness())
        buttons.addWidget(self.fix)
        row.addLayout(buttons)
        box.addLayout(row)
        self.automatic = QCheckBox("Test automatically when the computer is free")
        self.automatic.setToolTip("Tests start by themselves while this app is open, within the times set in Settings, When to test")
        self.automatic.toggled.connect(self.automatic_toggled)
        box.addWidget(self.automatic)
        self.progress = QProgressBar()
        self.progress.setRange(0, len(model.STEPS))
        self.progress.setTextVisible(True)
        box.addWidget(self.progress)
        layout.addWidget(top)

        self.game_card, game = card()
        game.addWidget(theme.mark(QLabel("The test, running here in the sandbox"), role="heading"))
        self.game = GameView(lambda: list(self.engine.names.values()) + [d.get("name", "") for d in self.engine.dumps.values()], engine.log,
                             title_ids=lambda: list(self.engine.names))
        game.addWidget(self.game, 1)
        game.addWidget(rich("Stop ends it at once. Nothing you click here reaches the game.", role="muted"))
        layout.addWidget(self.game_card, 3)

        lists = QHBoxLayout()
        lists.setSpacing(16)
        upcoming, box = card()
        box.addWidget(theme.mark(QLabel("Up next"), role="heading"))
        self.upcoming = RowList()
        box.addWidget(self.upcoming)
        lists.addWidget(upcoming, 1)
        done, box = card()
        box.addWidget(theme.mark(QLabel("Results"), role="heading"))
        self.recent = RowList()
        box.addWidget(self.recent)
        lists.addWidget(done, 1)
        layout.addLayout(lists, 2)
        self.state = None

    def advanced(self):
        return self.engine.config.view == "advanced"

    def start_clicked(self):
        self.engine.start_now()
        self.headline.setText("Starting the next test")
        self.detail.setText("Getting the change…")

    def stop_clicked(self):
        self.engine.stop()
        self.headline.setText("Stopping")
        self.detail.setText("Ending the test and taking back its claim. Nothing is sent.")

    def automatic_toggled(self, on):
        if on != self.engine.config.automatic:
            self.engine.set_automatic(on)

    def refresh(self):
        state = self.engine.home()
        self.headline.setText(state["headline"])
        self.detail.setText(state["detail"])
        notes = [n for n in (self.engine.local_notice(), self.engine.stale_text(), self.engine.ignored_mine()) if n]
        self.notice.setText("<br>".join(notes))
        self.notice.setVisible(bool(notes))
        running = state["kind"] == "running"
        self.stop.setVisible(running)
        self.fix.setVisible(state["kind"] == "setup" and bool(self.engine.readiness()[2]))
        self.start.setVisible(not running and state["kind"] != "setup")
        self.start.setEnabled(state["kind"] in ("off", "waiting", "ready", "error") and bool(self.engine.up_next_rows()) and
                              any(r["score"] > 0 for r in self.engine.up_next_rows()))
        self.start.setText("Start now" if state["kind"] == "waiting" else "Start")
        self.automatic.blockSignals(True)
        self.automatic.setChecked(self.engine.config.automatic)
        self.automatic.blockSignals(False)
        self.progress.setVisible(running)
        if running:
            self.progress.setValue(state["step"] + 1)
            self.progress.setFormat(f"Step {state['step'] + 1} of {len(model.STEPS)}: {model.STEPS[state['step']]}")
        self.game_card.setVisible(running or self.advanced())
        if running and state["step"] >= 3:
            self.game.watch()
        elif self.state == "running" and not running:
            self.game.unwatch()
        self.state = state["kind"]
        self.fill_upcoming()
        self.fill_recent()

    def fill_upcoming(self):
        rows = self.engine.up_next_rows()
        if not rows:
            self.upcoming.set_rows([f"Nothing queued. When {words.team()} asks for a test, it shows up here."])
            return
        muted = theme.COLOURS["muted"]
        out = []
        for row in rows:
            extra = (f"<br><small style='color:{muted}'>" + "; ".join(row["reasons"]) + "</small>") if self.advanced() else ""
            who = f"by {row['author']} · " if row["author"] else ""
            out.append(f"<b>#{row['number']}</b> {row['title']}<br><span style='color:{muted}'>{who}</span><b>{row['why']}</b>{extra}")
        self.upcoming.set_rows(out)

    def fill_recent(self):
        rows = self.engine.recent_rows()
        if not rows:
            self.recent.set_rows(["No results yet. A queued test sends its result to the change on GitHub; a local test's stays on this computer."])
            return
        out = []
        for row in rows:
            if row.get("local"):
                draft = row.get("draft", "")
                where = (f" · kept on this computer · <a href='file://{draft}'>the draft comment</a>" if draft else " · kept on this computer")
            else:
                link = self.engine.comment_link(row["number"])
                where = f" · <a href='{link}'>see it on GitHub</a>" if link.startswith("https://") else ""
            out.append(f"<b>#{row['number']}</b> {row['verdict']}<br><small style='color:{theme.COLOURS['muted']}'>{utc(row['at'])}{where}</small>")
        self.recent.set_rows(out)
