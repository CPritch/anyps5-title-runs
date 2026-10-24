"""The Games page: the games tests run on, each with its test and the scenario it's tested in; adding a game from a
folder, removing one, recording a scenario (ui/record.py), and the recorded scenarios, which can be deleted. Data from
app.Engine (titles, add_games, remove_game, set_scenario, delete_recording)."""

from pathlib import Path

from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from . import dialogs, theme
from .home import card, rich


def table(columns, stretch):
    widget = QTableWidget(0, len(columns))
    widget.setHorizontalHeaderLabels(columns)
    widget.verticalHeader().setVisible(False)
    widget.setSelectionMode(QTableWidget.NoSelection)
    widget.setEditTriggers(QTableWidget.NoEditTriggers)
    header = widget.horizontalHeader()
    for column in range(len(columns)):
        header.setSectionResizeMode(column, QHeaderView.Stretch if column == stretch else QHeaderView.ResizeToContents)
    return widget


class GamesPage(QWidget):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        top, box = card()
        box.addWidget(theme.mark(QLabel("Games"), role="title"))
        box.addWidget(rich("The games tests run on. A game with a full test is played and timed in its scenario. Others only get "
                           "a check that they start.", role="muted"))
        buttons = QHBoxLayout()
        add = theme.mark(QPushButton("Add a game…"), primary="true")
        add.setToolTip("Choose the folder a game is in, or the folder that holds your games")
        add.clicked.connect(self.add)
        buttons.addWidget(add)
        record = QPushButton("Record a scenario…")
        record.setToolTip("Play part of a game with your controller. Tests in the new scenario replay what you did.")
        record.clicked.connect(self.record)
        buttons.addWidget(record)
        buttons.addStretch(1)
        box.addLayout(buttons)
        self.note = rich("", role="muted")
        self.note.hide()
        box.addWidget(self.note)
        self.games = table(["Game", "Version", "Test", "Scenarios", "Folder", ""], 4)
        box.addWidget(self.games)
        layout.addWidget(top, 3)

        recorded, box = card()
        box.addWidget(theme.mark(QLabel("Recorded scenarios"), role="heading"))
        self.recorded = table(["Scenario", "What happens", "Recorded", ""], 1)
        box.addWidget(self.recorded)
        self.none_recorded = rich("None yet. Record a scenario to have tests replay your own play.", role="muted")
        box.addWidget(self.none_recorded)
        layout.addWidget(recorded, 2)

    def refresh(self):
        rows = self.engine.titles()
        self.games.setRowCount(len(rows))
        mine = []
        for i, row in enumerate(rows):
            name = QTableWidgetItem(f"{row['name']} ({row['title_id']})")
            self.games.setItem(i, 0, name)
            self.games.setItem(i, 1, QTableWidgetItem(row["version"]))
            self.games.setItem(i, 2, QTableWidgetItem(row["check"]))
            self.games.setCellWidget(i, 3, self.scenarios_cell(row))
            folder = QTableWidgetItem(row["path"].replace(str(Path.home()), "~", 1))
            folder.setToolTip(row["path"])
            self.games.setItem(i, 4, folder)
            remove = QPushButton("Remove")
            remove.clicked.connect(lambda _=False, r=row: self.remove(r))
            self.games.setCellWidget(i, 5, remove)
            mine += [(row, choice) for choice in row["scenarios"] if choice["recorded"]]
        self.recorded.setRowCount(len(mine))
        for i, (row, choice) in enumerate(mine):
            self.recorded.setItem(i, 0, QTableWidgetItem(f"{choice['name']} ({row['name']})"))
            self.recorded.setItem(i, 1, QTableWidgetItem(choice["scene"]))
            self.recorded.setItem(i, 2, QTableWidgetItem(choice["recorded_at"]))
            delete = QPushButton("Delete")
            delete.clicked.connect(lambda _=False, r=row, c=choice: self.delete(r, c))
            self.recorded.setCellWidget(i, 3, delete)
        self.recorded.setVisible(bool(mine))
        self.none_recorded.setVisible(not mine)

    def scenarios_cell(self, row):
        """The scenarios each test of the game runs in, and Choose… to tick others."""
        if not row["scenarios"]:
            return QLabel("—")
        names = {choice["id"]: choice["name"] for choice in row["scenarios"]}
        cell = QWidget()
        line = QHBoxLayout(cell)
        line.setContentsMargins(4, 0, 4, 0)
        chosen = QLabel(", ".join(names[key] for key in row["chosen"]) or "—")
        chosen.setToolTip("Each test of this game runs in each of these, one after another; its report has a part for each")
        line.addWidget(chosen, 1)
        pick = QPushButton("Choose…")
        pick.clicked.connect(lambda _=False, r=row: self.choose(r))
        line.addWidget(pick)
        return cell

    def choose(self, row):
        options = [(c["id"], c["name"], "\n\n".join(t for t in (c["scene"], c.get("save", "")) if t)) for c in row["scenarios"]]
        picked = dialogs.choose(self, f"The scenarios each test of {row['name']} runs in, one after another. Each one adds about "
                                "20 minutes to a test.", options, row["chosen"])
        if picked is None:
            return
        self.engine.set_scenarios(row["title_id"], picked)
        self.say(f"{row['name']} is tested in " + (", ".join(n for k, n, _ in options if k in picked) if picked else "its default scenario") + ".")
        self.refresh()

    def say(self, text):
        self.note.setText(text)
        self.note.show()

    def add(self):
        folder = dialogs.folder(self, "The folder your game is in")
        if folder:
            self.say(self.engine.add_games(folder))
            self.refresh()

    def remove(self, row):
        if dialogs.ask(self, f"Remove {row['name']} from your games? Its folder and any recordings stay where they are.", "Remove"):
            self.engine.remove_game(row["title_id"])
            self.say(f"Removed {row['name']}.")
            self.refresh()

    def delete(self, row, choice):
        if dialogs.ask(self, f"Delete the recording {choice['name']}? This can't be undone.", "Delete", danger=True):
            self.engine.delete_recording(row["title_id"], choice["id"])
            self.say(f"Deleted {choice['name']}.")
            self.refresh()

    def record(self):
        from .record import RecordDialog
        if RecordDialog(self.engine, self).exec() == RecordDialog.Accepted:
            window = self.engine.window
            window.buttons["home"].setChecked(True)
            window.show_page(window.home)
