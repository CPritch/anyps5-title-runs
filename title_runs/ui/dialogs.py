"""Dialogs sized from the window they come from. A tiling desktop such as Hyprland opens a dialog at the size it asks
for, and Qt's own ask small: a folder picker 640 x 440 with its side panel cut off, a question 400 x 130."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QPushButton, QSplitter, QVBoxLayout

from . import theme


def fit(dialog, parent, width, height=None):
    """Resize dialog to a share of its parent's window (at least as big as it asks to be)."""
    window = parent.window() if parent is not None else None
    if window is None or window.width() < 200:
        return
    hint = dialog.sizeHint()
    dialog.resize(max(hint.width(), round(window.width() * width)),
                  max(hint.height(), round(window.height() * height)) if height else hint.height())


def ask(parent, text, action, danger=False):
    """A question with Cancel and an action button (red when it deletes): True when the action is chosen."""
    dialog = QDialog(parent)
    dialog.setWindowTitle("AnyPS5 title runs")
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(24, 20, 24, 20)
    layout.setSpacing(16)
    label = QLabel(text)
    label.setWordWrap(True)
    layout.addWidget(label)
    buttons = QHBoxLayout()
    buttons.addStretch(1)
    cancel = QPushButton("Cancel")
    cancel.clicked.connect(dialog.reject)
    buttons.addWidget(cancel)
    chosen = theme.mark(QPushButton(action), **({"danger": "true"} if danger else {"primary": "true"}))
    chosen.clicked.connect(dialog.accept)
    chosen.setDefault(True)
    buttons.addWidget(chosen)
    layout.addLayout(buttons)
    fit(dialog, parent, 0.45)
    return dialog.exec() == QDialog.Accepted


def folder(parent, title, start=None):
    """A folder chosen in a folder picker the size of most of the window, or "" when none is."""
    dialog = QFileDialog(parent, title, str(start or Path.home()))
    dialog.setFileMode(QFileDialog.Directory)
    dialog.setOption(QFileDialog.ShowDirsOnly, True)
    dialog.setOption(QFileDialog.DontUseNativeDialog, True)
    fit(dialog, parent, 0.8, 0.75)
    splitter = dialog.findChild(QSplitter)
    if splitter is not None:  # the side panel of places, wide enough for their names
        splitter.setSizes([dialog.width() // 4, dialog.width() * 3 // 4])
    dialog.setWindowModality(Qt.WindowModal)
    return dialog.selectedFiles()[0] if dialog.exec() == QDialog.Accepted and dialog.selectedFiles() else ""
