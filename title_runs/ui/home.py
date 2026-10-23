"""The main screen: what this machine is doing in one line, the testing switch (Off, On schedule, Now) and Stop, the
test's progress and the game itself while it runs, the tests coming up and the results. Data from app.Engine through
ui/model.py, in a tester's words."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from ..formats import utc_text as utc
from . import model, theme
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
        self.on_link = None  # links go here instead of the browser when set

    def set_rows(self, rows):
        if rows == self.rows:  # unchanged: no rebuild, so no flicker on the two-second refresh
            return
        self.rows = list(rows)
        self.clear()
        for html in rows:
            item = QListWidgetItem()
            label = rich(html)
            if self.on_link is not None:
                label.setOpenExternalLinks(False)
                label.linkActivated.connect(self.on_link)
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
        self.stop = theme.mark(QPushButton("Stop this test"), danger="true")
        self.stop.setToolTip("Ends the test now and switches testing to Off")
        self.stop.clicked.connect(self.stop_clicked)
        buttons.addWidget(self.stop)
        self.fix = theme.mark(QPushButton("Finish setting up"), primary="true")
        self.fix.clicked.connect(lambda: self.engine.window.fix_readiness())
        buttons.addWidget(self.fix)
        row.addLayout(buttons)
        box.addLayout(row)
        switch = QHBoxLayout()
        switch.setSpacing(0)
        switch.addWidget(theme.mark(QLabel("Testing"), role="heading"))
        switch.addSpacing(14)
        self.testing = QButtonGroup(self)
        self.testing.setExclusive(True)
        self.modes = {}
        for mode, end in (("off", "left"), ("schedule", "middle"), ("now", "right")):
            button = theme.mark(QPushButton(model.TESTING[mode][0]), segment=end)
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, m=mode: self.testing_clicked(m))
            self.testing.addButton(button)
            switch.addWidget(button)
            self.modes[mode] = button
        switch.addSpacing(14)
        self.testing_note = rich("", role="muted")
        switch.addWidget(self.testing_note, 1)
        box.addLayout(switch)
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
        self.recent.on_link = self.link_clicked
        box.addWidget(self.recent)
        lists.addWidget(done, 1)
        layout.addLayout(lists, 2)
        self.state = None
        self.idle_detectable = None

    def advanced(self):
        return self.engine.config.view == "advanced"

    def stop_clicked(self):
        self.engine.stop()
        self.headline.setText("Stopping")
        self.detail.setText("Ending the test. Nothing is sent, and testing is now Off.")

    def testing_clicked(self, mode):
        if mode != self.engine.config.testing:
            self.engine.set_testing(mode)
        self.refresh()

    def testing_words(self):
        mode = self.engine.config.testing
        if mode == "schedule":
            if self.idle_detectable is None:  # asked once: it asks the desktop
                from .. import platform_info
                self.idle_detectable = platform_info.idle_detection()[0]
            return "Tests start by themselves " + model.schedule_words(self.engine.config.schedule, self.idle_detectable) + "."
        return model.TESTING[mode][1]

    def refresh(self):
        state = self.engine.home()
        self.headline.setText(state["headline"])
        self.detail.setText(state["detail"])
        notice = self.engine.local_notice()
        self.notice.setText(notice)
        self.notice.setVisible(bool(notice))
        running = state["kind"] == "running"
        self.stop.setVisible(running)
        self.fix.setVisible(state["kind"] == "setup" and bool(self.engine.readiness()[2]))
        self.modes[self.engine.config.testing].setChecked(True)
        self.testing_note.setText(self.testing_words())
        recording = running and state["step"] < 0
        self.progress.setVisible(running and not recording)
        if running and not recording:
            self.progress.setValue(state["step"] + 1)
            self.progress.setFormat(f"Step {state['step'] + 1} of {len(model.STEPS)}: {model.STEPS[state['step']]}")
        self.game_card.setVisible(running or self.advanced())
        if running and (recording or state["step"] >= 3):
            self.game.watch()
        elif self.state == "running" and not running:
            self.game.unwatch()
        self.state = state["kind"]
        self.fill_upcoming()
        self.fill_recent()

    def link_clicked(self, href):
        if href.startswith("report:"):
            self.engine.window.open_report(int(href.split(":", 1)[1]))
        elif href.startswith("https://"):
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl(href))

    def fill_upcoming(self):
        rows = self.engine.up_next_rows()
        if not rows:
            self.upcoming.set_rows(["Nothing waiting. Add a pull request on the Local tests page."])
            return
        muted = theme.COLOURS["muted"]
        out = []
        for row in rows:
            extra = f"<br><small style='color:{muted}'>head {row['head'][:9]}, added {utc(row['added'])}</small>" if self.advanced() else ""
            who = f"by {row['author']} · " if row["author"] else ""
            out.append(f"<b>#{row['number']}</b> {row['title']}<br><span style='color:{muted}'>{who}</span><b>{row['why']}</b>{extra}")
        self.upcoming.set_rows(out)

    def fill_recent(self):
        rows = self.engine.recent_rows()
        if not rows:
            self.recent.set_rows(["No results yet. Each result stays on this computer, with a report you can post yourself."])
            return
        out = []
        for row in rows:
            report = row.get("report", "")
            state = "<b style='color:#a36a00'>Stale</b>" if report.startswith("Stale") else report
            where = f" · {state} · <a href='report:{row['number']}'>Report</a>"
            out.append(f"<b>#{row['number']}</b> {row['verdict']}<br><small style='color:{theme.COLOURS['muted']}'>{utc(row['at'])}{where}</small>")
        self.recent.set_rows(out)
