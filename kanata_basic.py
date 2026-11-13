import argparse

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QMainWindow, QPushButton, QSpinBox,
    QVBoxLayout, QWidget,
)

from kanata.application import DeviceService, DeviceState
from kanata.device import discover
from kanata.macro_editor import MacroEditor
from kanata.macros import Macro, MacroBinding
from kanata.protocol import BUTTONS, RATE_CODES
from kanata.reports import ProtocolError

BUTTON_NAMES = (
    "Left click", "Right click", "Middle click",
    "Back button", "Forward button", "DPI button",
)


class DeviceJob(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, action):
        super().__init__()
        self.action = action

    def run(self):
        try:
            self.completed.emit(self.action())
        except Exception as error:

            self.failed.emit(str(error))


class BasicWindow(QMainWindow):
    def __init__(self, demo=False, service=None):
        super().__init__()
        self.demo = demo
        self.service = service or DeviceService()
        self.state = None
        self.job = None
        self.populating = False
        self.trace = []
        self.macro_drafts = {}
        self.setWindowTitle("Kanata WG9S - Basic")
        self.resize(630, 650)

        self.panel = QWidget()
        self.setCentralWidget(self.panel)
        layout = QVBoxLayout(self.panel)

        connection = QHBoxLayout()
        self.devices = QComboBox()
        self.devices.currentIndexChanged.connect(self.device_changed)
        connection.addWidget(self.devices, 1)
        scan = QPushButton("Rescan")
        scan.clicked.connect(self.scan)
        connection.addWidget(scan)
        self.read_button = QPushButton("Read mouse")
        self.read_button.clicked.connect(self.read_mouse)
        connection.addWidget(self.read_button)
        layout.addLayout(connection)

        form = QFormLayout()
        self.rate = QComboBox()
        for hz in sorted(RATE_CODES):
            self.rate.addItem(f"{hz} Hz", hz)
        self.rate.currentIndexChanged.connect(self.update_controls)
        form.addRow("Polling rate", self.rate)
        self.active = QComboBox()
        self.active.currentIndexChanged.connect(self.update_controls)
        form.addRow("Active DPI stage", self.active)
        layout.addLayout(form)

        dpi_group = QGroupBox("DPI stages")
        dpi_layout = QGridLayout(dpi_group)
        self.dpi = []
        for index in range(5):
            dpi_layout.addWidget(QLabel(f"Stage {index + 1}"), 0, index)
            value = QSpinBox()
            value.setRange(50, 12000)
            value.setSingleStep(50)
            value.valueChanged.connect(self.update_controls)
            self.dpi.append(value)
            dpi_layout.addWidget(value, 1, index)
        layout.addWidget(dpi_group)

        button_group = QGroupBox("Button assignments")
        button_layout = QGridLayout(button_group)
        self.assignments = []
        self.macro_buttons = []
        for index, name in enumerate(BUTTON_NAMES):
            button_layout.addWidget(QLabel(name), index, 0)
            options = QComboBox()
            options.currentIndexChanged.connect(self.update_controls)
            self.assignments.append(options)
            button_layout.addWidget(options, index, 1)
            edit = QPushButton("Edit macro…")
            edit.clicked.connect(lambda checked=False, i=index: self.edit_macro(i))
            self.macro_buttons.append(edit)
            button_layout.addWidget(edit, index, 2)
        layout.addWidget(button_group)

        self.apply_button = QPushButton("Apply changes")
        self.apply_button.clicked.connect(self.apply_changes)
        layout.addWidget(self.apply_button)
        self.status = QLabel("Read the mouse to load its settings.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch()
        self.scan()
        if demo:
            from kanata.demo import settings
            self.set_state(DeviceState(settings(include_macros=True), {"cid": 13, "mid": 7}))
            self.status.setText("Demo: sample settings. Device writes are disabled.")

    def device_changed(self):
        self.state = None
        self.macro_drafts.clear()
        self.update_controls()

    def scan(self):
        self.devices.clear()
        for device in discover():
            if device["usable"]:
                self.devices.addItem(device["node"], device["node"])
        if not self.devices.count():
            self.devices.addItem("No matching mouse found", None)
        self.device_changed()

    def update_controls(self, *_):
        if self.populating:
            return
        loaded = self.state is not None
        for control in [self.rate, self.active] + self.assignments + self.macro_buttons:
            control.setEnabled(loaded)
        for index, control in enumerate(self.dpi):
            control.setEnabled(loaded and index < self.state.settings.stages)
        self.read_button.setEnabled(bool(self.devices.currentData()) and not self.demo)
        self.apply_button.setEnabled(False)
        if loaded:
            try:
                count = len(self.state.settings.plan(*self.draft()))
                self.apply_button.setEnabled(count > 0 and not self.demo and self.job is None)
                self.apply_button.setText(f"Apply changes ({count} records)" if count else "No changes")
            except ValueError as error:
                self.apply_button.setText("Apply changes")
                self.status.setText(str(error))

    def draft(self):
        settings = self.state.settings
        dpi = [
            control.value() if control.value() != settings.dpi[i][0] else None
            for i, control in enumerate(self.dpi[:settings.stages])
        ]
        buttons = []
        for index, control in enumerate(self.assignments):
            value = control.currentData()
            if value == "macro":
                if index not in self.macro_drafts:
                    raise ValueError(f"Use Edit macro for {BUTTON_NAMES[index]} first.")
                value = self.macro_drafts[index]
            buttons.append(value)
        return self.rate.currentData(), self.active.currentData(), dpi, buttons

    def set_state(self, state):
        self.populating = True
        self.state = state
        self.macro_drafts.clear()
        settings = state.settings
        self.rate.setCurrentIndex(self.rate.findData(settings.rate))
        self.active.clear()
        for index in range(settings.stages):
            self.active.addItem(f"Stage {index + 1}", index)
            x, y = settings.dpi[index]
            self.dpi[index].setValue(x)
            self.dpi[index].setToolTip(f"Current X/Y: {x}/{y}. Unchanged stages are preserved.")
        self.active.setCurrentIndex(settings.active)
        for control, binding in zip(self.assignments, settings.buttons):
            control.clear()
            for name in BUTTONS:
                control.addItem(name, name)
            control.addItem("Custom macro", "macro")
            name = next((name for name, value in BUTTONS.items() if value == binding), None)
            if name is None:
                kind = "macro" if binding[0] == 6 else "action"
                control.addItem(f"Existing {kind} (preserve)", None)
            control.setCurrentIndex(control.findData(name))
        self.status.setText(state.message or "Settings loaded. Edit values, then Apply changes.")
        self.populating = False
        self.update_controls()

    def start_job(self, action):
        self.trace = []
        self.panel.setEnabled(False)
        self.status.setText("Communicating with mouse…")
        self.job = DeviceJob(action)
        self.job.completed.connect(self.set_state)
        self.job.failed.connect(self.failed)
        self.job.finished.connect(self.job_finished)
        self.job.start()

    def job_finished(self):
        self.job.deleteLater()
        self.job = None
        self.panel.setEnabled(True)
        self.update_controls()

    def failed(self, message):
        self.state = None
        self.macro_drafts.clear()
        self.status.setText(message + " Read the mouse again before editing.")

    def read_mouse(self):
        node = self.devices.currentData()
        if self.demo or not node or self.job is not None:
            return
        self.state = None
        self.start_job(lambda: self.service.read(node, self.trace))

    def apply_changes(self):
        if self.demo or self.state is None or self.job is not None:
            return
        try:
            draft = self.draft()
            self.state.settings.plan(*draft)
        except ValueError as error:
            self.status.setText(str(error))
            return
        state = self.state
        self.start_job(lambda: self.service.apply(
            state.node, self.trace, state.settings, draft, state.battery
        ))

    def edit_macro(self, index):
        if self.state is None or self.job is not None:
            return
        binding = self.macro_drafts.get(index)
        problem = None
        if binding is None and self.state.settings.buttons[index][0] == 6:
            _, slot, repeats = self.state.settings.buttons[index]
            try:
                binding = MacroBinding(Macro.decode(self.state.settings.macro_slots[slot]), repeats)
            except (KeyError, ProtocolError) as error:
                problem = str(error)
        editor = MacroEditor(self, binding, BUTTON_NAMES[index])
        if problem:
            editor.error.setText("Cannot decode the old macro: " + problem)
        if editor.exec() == MacroEditor.DialogCode.Accepted:
            self.macro_drafts[index] = editor.binding
            self.assignments[index].setCurrentIndex(self.assignments[index].findData("macro"))
        editor.deleteLater()
        self.update_controls()

    def closeEvent(self, event):
        if self.job is not None:
            self.status.setText("Wait for the device operation to finish before closing.")
            event.ignore()
        else:
            event.accept()


def main():
    parser = argparse.ArgumentParser(description="WG9S mouse configuration")
    parser.add_argument("--demo", action="store_true", help="Use sample settings; no device writes")
    args = parser.parse_args()
    app = QApplication([])
    window = BasicWindow(demo=args.demo)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
