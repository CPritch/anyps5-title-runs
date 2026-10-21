"""The trust dialog (DESIGN.md, "Trust and safety"): blocking, not dismissible by Enter. "Run anyway" is enabled only
with a scope chosen, "I understand the risk" ticked and the author's name typed exactly."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton,
                               QVBoxLayout)

SCOPES = ("head", "pr", "author")


class TrustDialog(QDialog):
    def __init__(self, number, title, author, parent=None):
        super().__init__(parent)
        self.author = author
        self.scope = None
        self.setWindowTitle("Run code nobody has checked?")
        self.setModal(True)
        self.setMinimumWidth(620)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        heading = QLabel("<b>Run code nobody has checked?</b>")
        heading.setTextFormat(Qt.RichText)
        layout.addWidget(heading)
        short = title if len(title) <= 60 else title[:59] + "…"
        for text in (f'PR #{number} "{short}" by {author} has not been queued by an AnyPS5 maintainer. Nobody has checked this code '
                     f"for safety.",
                     "If you continue, it will be built and run on this computer, with access to your GPU, inside a sandbox. The sandbox "
                     "does <b>NOT</b> protect you from a malicious driver or kernel exploit.",
                     'Results will be posted marked "run on the tester\'s trust".'):
            label = QLabel(text)
            label.setWordWrap(True)
            label.setTextFormat(Qt.RichText)
            layout.addWidget(label)
        self.group = QButtonGroup(self)
        for i, text in enumerate(("Run this PR's current head only", f"Trust {author} for this PR", f"Trust {author} for 30 days")):
            button = QRadioButton(text)
            self.group.addButton(button, i)
            layout.addWidget(button)
        confirm = QHBoxLayout()
        self.understood = QCheckBox("I understand the risk")
        confirm.addWidget(self.understood)
        confirm.addStretch(1)
        confirm.addWidget(QLabel(f'Type "{author}" to confirm:'))
        self.typed = QLineEdit()
        self.typed.setMinimumWidth(160)
        confirm.addWidget(self.typed)
        layout.addLayout(confirm)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel = QPushButton("Cancel")
        self.run = QPushButton("Run anyway")
        for button in (self.cancel, self.run):
            button.setAutoDefault(False)
            button.setDefault(False)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.cancel.clicked.connect(self.reject)
        self.run.clicked.connect(self.accept_if_ready)
        self.group.idClicked.connect(self.update_run)
        self.understood.toggled.connect(self.update_run)
        self.typed.textChanged.connect(self.update_run)
        self.update_run()

    def ready(self):
        return self.group.checkedId() >= 0 and self.understood.isChecked() and self.typed.text() == self.author

    def update_run(self, *_):
        self.run.setEnabled(self.ready())

    def accept_if_ready(self):
        if self.ready():
            self.scope = SCOPES[self.group.checkedId()]
            self.accept()

    def keyPressEvent(self, event):  # noqa: N802 (Qt's name)
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.accept()  # swallowed: Enter neither runs nor cancels
            return
        super().keyPressEvent(event)
