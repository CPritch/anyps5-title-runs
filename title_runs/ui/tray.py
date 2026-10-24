"""The tray icon and menu (DESIGN.md, "The tray"): a dot, grey idle, green running, amber waiting for you, red error;
the status lines, the testing switch (Off, On schedule, Now), Open…, Quit. A desktop notification
when a PR starts waiting for the tester or a job fails."""

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QActionGroup, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

COLOURS = {"idle": "#9e9e9e", "running": "#2e9d4f", "waiting": "#e0a100", "error": "#d32f2f"}


def dot(state, size=64):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QColor("#ffffff"))
    painter.setBrush(QColor(COLOURS[state]))
    margin = size // 8
    painter.drawEllipse(margin, margin, size - 2 * margin, size - 2 * margin)
    painter.end()
    return pixmap


class Tray(QObject):
    def __init__(self, engine, open_window, quit_app):
        super().__init__()
        self.engine = engine
        self.icons = {}
        for state in COLOURS:
            icon = QIcon()
            for mode in (QIcon.Normal, QIcon.Disabled):  # the menu's status lines are disabled entries; keep their colour
                icon.addPixmap(dot(state), mode)
            self.icons[state] = icon
        self.icon = QSystemTrayIcon(self.icons["idle"])
        self.icon.setToolTip("AnyPS5 title runs")
        self.menu = QMenu()
        header = self.menu.addAction(self.icons["idle"], "AnyPS5 title runs")
        header.setEnabled(False)
        self.header = header
        self.menu.addSeparator()
        self.lines = [self.menu.addAction("") for _ in range(4)]
        for action in self.lines:
            action.setEnabled(False)
        self.menu.addSeparator()
        from .model import TESTING
        group = QActionGroup(self.menu)
        self.modes = {}
        for mode in ("off", "schedule", "now"):
            action = self.menu.addAction(f"Testing: {TESTING[mode][0]}", lambda m=mode: engine.set_testing(m))
            action.setCheckable(True)
            group.addAction(action)
            self.modes[mode] = action
        self.menu.addSeparator()
        self.menu.addAction("Open…", open_window)
        self.menu.addAction("Quit", quit_app)
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(lambda reason: open_window() if reason == QSystemTrayIcon.Trigger else None)
        self.last = None

    def refresh(self):
        state, lines, waiting = self.engine.tray_view()
        self.icon.setIcon(self.icons[state])
        self.header.setIcon(self.icons[state])
        self.icon.setToolTip("AnyPS5 title runs\n" + "\n".join(lines))
        for action, text in zip(self.lines, lines + [""] * len(self.lines)):
            action.setText(text)
            action.setVisible(bool(text))
        self.modes[self.engine.config.testing].setChecked(True)
        if self.last is not None and QSystemTrayIcon.supportsMessages():
            if state == "error" and self.last[0] != "error":
                self.icon.showMessage("AnyPS5 title runs", lines[0], QSystemTrayIcon.Critical)
            elif len(waiting) > self.last[1]:
                self.icon.showMessage("AnyPS5 title runs", f"{len(waiting)} pull request{'s mention' if len(waiting) > 1 else ' mentions'} your games", QSystemTrayIcon.Information)
        self.last = (state, len(waiting))

    def show(self):
        self.icon.show()
