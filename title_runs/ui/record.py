"""Record a scenario (Settings, Your games): the game, the scenario to start from, a name, what happens, how long, and the
controller found. Record hands it to the engine's worker (Engine.record_scenario, recording.py) and Home shows it
running; Stop there ends it with nothing saved."""

from PySide6.QtWidgets import QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout

from .. import recording
from . import theme


class RecordDialog(QDialog):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("Record a scenario")
        self.setMinimumWidth(640)
        layout = QVBoxLayout(self)
        intro = QLabel("The game starts on the main build and goes to the starting scene on its own. Then you take over. The "
                       "first second is ignored, and after that everything you do on the controller is recorded until time runs "
                       "out. Tests in the new scenario replay it from the same scene. Pressing Stop on Home ends the recording "
                       "without saving it.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        self.game = QComboBox()
        for row in engine.titles():
            self.game.addItem(f"{row['name']} ({row['title_id']})", row["title_id"])
        self.game.currentIndexChanged.connect(self.fill_starts)
        form.addRow("Game", self.game)
        self.start = QComboBox()
        form.addRow("Start from", self.start)
        self.name = QLineEdit()
        self.name.setPlaceholderText("e.g. Out of the house")
        form.addRow("Name", self.name)
        self.scene = QLineEdit()
        self.scene.setMaxLength(120)
        self.scene.setPlaceholderText("what happens, for reports, e.g. Franklin walks out of his house to the road")
        form.addRow("What happens", self.scene)
        self.seconds = QSpinBox()
        self.seconds.setRange(recording.MIN_SECONDS, recording.MAX_SECONDS)
        self.seconds.setValue(recording.DEFAULT_SECONDS)
        self.seconds.setSuffix(" s")
        self.seconds.setToolTip("Timing starts about 30 s after the scene appears and lasts up to 60 s, so record at least 100 s")
        form.addRow("Length", self.seconds)
        controller = engine.controller()
        self.controller = QLabel(controller["name"] if controller else "No controller found. Connect one, then open this again.")
        form.addRow("Controller", self.controller)
        layout.addLayout(form)
        self.note = theme.mark(QLabel(""), role="muted")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.record = theme.mark(QPushButton("Record"), primary="true")
        self.record.setEnabled(controller is not None)
        self.record.clicked.connect(self.start_recording)
        buttons.addWidget(self.record)
        layout.addLayout(buttons)
        self.fill_starts()

    def fill_starts(self, *_):
        """The scenarios a recording can start from: those with scene colours and no recorded play of their own."""
        self.start.clear()
        row = next((r for r in self.engine.titles() if r["title_id"] == self.game.currentData()), None)
        for choice in (row or {}).get("scenarios", []):
            if choice.get("startable"):
                self.start.addItem(choice["name"], choice["id"])

    def request(self):
        """The recording asked for, as Engine.record_scenario takes it; raises RecordError for anything missing."""
        title_id, start = self.game.currentData(), self.start.currentData()
        name, scene = self.name.text().strip(), self.scene.text().strip()
        taken = {choice["id"] for row in self.engine.titles() if row["title_id"] == title_id for choice in row["scenarios"]}
        scenario_id = recording.new_id(name, taken)
        recording.check(self.engine.config, title_id, start, scenario_id, name, scene, self.seconds.value())
        return {"title_id": title_id, "from_id": start, "scenario_id": scenario_id, "name": name, "scene": scene, "seconds": self.seconds.value()}

    def start_recording(self):
        try:
            request = self.request()
        except recording.RecordError as error:
            self.note.setText(str(error))
            return
        self.engine.work.put(("record", request))
        self.accept()
