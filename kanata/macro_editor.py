import json
import time
from PySide6.QtCore import Qt, QEvent, Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QSpinBox, QPushButton, QTableWidget, QHeaderView, QAbstractItemView,
    QFileDialog, QFrame, QDialogButtonBox)
from .macros import KEYS, Macro, MacroStep, MacroBinding, MAX_EVENTS


QT_KEYS = {ord(c): KEYS[c] for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'}
for name, qtname in {'Enter':'Return', 'Escape':'Escape', 'Backspace':'Backspace', 'Tab':'Tab',
                    'Space':'Space', 'Insert':'Insert', 'Delete':'Delete', 'Home':'Home',
                    'End':'End', 'Page Up':'PageUp', 'Page Down':'PageDown', 'Up':'Up',
                    'Down':'Down', 'Left':'Left', 'Right':'Right', 'Caps Lock':'CapsLock'}.items():
    QT_KEYS[int(getattr(Qt.Key, 'Key_' + qtname))] = KEYS[name]
for i in range(1, 13):
    QT_KEYS[int(getattr(Qt.Key, f'Key_F{i}'))] = KEYS[f'F{i}']
for char in "-=[]\\;'`,./":
    QT_KEYS[ord(char)] = KEYS[char]
for name, qtname in [('Left Ctrl', 'Control'), ('Left Shift', 'Shift'), ('Left Alt', 'Alt'), ('Left Super', 'Meta')]:
    QT_KEYS[int(getattr(Qt.Key, 'Key_' + qtname))] = KEYS[name]


class Recorder(QFrame):
    finished = Signal(object)
    progress = Signal(str)

    def __init__(self):
        self.recording = False
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        box = QVBoxLayout(self)
        self.caption = QLabel('Recording is local to this panel. System shortcuts may be intercepted by your desktop.')
        self.caption.setWordWrap(True)
        box.addWidget(self.caption)
        self.setStyleSheet('Recorder { border: 1px dashed #557466; border-radius: 8px; padding: 10px; }')
        self.recording = False
        self.steps = []
        self.held = {}
        self.last = None

    def start(self):
        self.recording = True
        self.steps = []
        self.held = {}
        self.last = None
        self.caption.setText('Recording… type your sequence here, then click Stop. Recording also stops when this panel loses focus.')
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def stop(self):
        if not self.recording:
            return
        for key in tuple(self.held):
            self.append_event(1, self.held.pop(key))
        self.recording = False
        self.caption.setText('Recording stopped. Review the events below before using the macro.')
        self.finished.emit(tuple(self.steps))

    def append_event(self, state, key):
        now = time.monotonic()
        if self.steps:
            old = self.steps[-1]
            self.steps[-1] = MacroStep(old.state, old.kind, old.value, min(65535, max(0, round((now - self.last) * 1000))))
        self.steps.append(MacroStep(state, *key, 0))
        self.last = now
        self.progress.emit(f'{len(self.steps)} events recorded')

    def event(self, event):
        if self.recording and event.type() == QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        if self.recording and event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            event.accept()
            if event.isAutoRepeat():
                return True
            key = int(event.key())
            usage = QT_KEYS.get(key)
            if usage is None:
                self.progress.emit('That key is not supported by the recorder; add supported events using the editor.')
                return True
            if event.type() == QEvent.Type.KeyPress and key not in self.held:
                if len(self.steps) + len(self.held) + 2 > MAX_EVENTS:
                    self.stop()
                    return True
                self.held[key] = usage
                self.append_event(0, usage)
            elif event.type() == QEvent.Type.KeyRelease and key in self.held:
                self.append_event(1, self.held.pop(key))
            return True
        return super().event(event)

    def focusOutEvent(self, event):
        self.stop()
        super().focusOutEvent(event)


class MacroEditor(QDialog):
    def __init__(self, parent=None, binding=None, button_name='button'):
        super().__init__(parent)
        self.setWindowTitle(f'Macro • {button_name}')
        self.resize(800, 720)
        self.binding = None
        box = QVBoxLayout(self)
        box.setContentsMargins(24, 24, 24, 24)
        box.setSpacing(14)
        title = QLabel(f'Macro for {button_name}')
        title.setObjectName('title')
        box.addWidget(title)
        desc = QLabel('Build a sequence, review its timing, then stage it for Apply. Nothing is sent from this editor.')
        desc.setWordWrap(True)
        box.addWidget(desc)
        row = QHBoxLayout()
        row.addWidget(QLabel('Name'))
        self.name = QLineEdit('My macro')
        self.name.setMaxLength(29)
        row.addWidget(self.name, 1)
        box.addLayout(row)
        repeat = QHBoxLayout()
        repeat.addWidget(QLabel('Playback'))
        self.playback = QComboBox()
        for text, code in [('Repeat count', 0), ('While button is held', 254), ('Toggle with this button', 253), ('Until any key is pressed', 255)]:
            self.playback.addItem(text, code)
        repeat.addWidget(self.playback, 1)
        self.repeats = QSpinBox()
        self.repeats.setRange(1, 252)
        self.repeats.setSuffix(' times')
        repeat.addWidget(self.repeats)
        box.addLayout(repeat)
        self.playback.currentIndexChanged.connect(lambda: self.repeats.setEnabled(self.playback.currentData() == 0))
        toolbar = QHBoxLayout()
        self.key = QComboBox()
        self.key.setMaxVisibleItems(12)
        self.key.setStyleSheet("QComboBox { combobox-popup: 0; }")
        for name in KEYS:
            self.key.addItem(name, KEYS[name])
        toolbar.addWidget(self.key, 1)
        self.delay = QSpinBox()
        self.delay.setRange(0, 65535)
        self.delay.setValue(50)
        self.delay.setSuffix(' ms')
        toolbar.addWidget(self.delay)
        add = QPushButton('Add press + release')
        add.clicked.connect(self.add_press)
        toolbar.addWidget(add)
        box.addLayout(toolbar)
        recording = QHBoxLayout()
        self.record_button = QPushButton('Record keys')
        self.record_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.record_button.clicked.connect(self.toggle_recording)
        recording.addWidget(self.record_button)
        self.count = QLabel('0 / 70 events')
        recording.addWidget(self.count, 1)
        box.addLayout(recording)
        self.recorder = Recorder()
        self.recorder.finished.connect(self.recorded)
        self.recorder.progress.connect(self.count.setText)
        box.addWidget(self.recorder)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['Action', 'Key / mouse button', 'Delay after (ms)'])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setDefaultSectionSize(46)
        self.table.setMinimumHeight(220)
        box.addWidget(self.table, 1)
        actions = QHBoxLayout()
        for text, callback in [('Move up', lambda: self.move(-1)), ('Move down', lambda: self.move(1)), ('Remove event', self.remove_event), ('Clear', self.clear_events), ('Import…', self.import_macro), ('Export…', self.export_macro)]:
            button = QPushButton(text)
            button.clicked.connect(callback)
            actions.addWidget(button)
        box.addLayout(actions)
        self.error = QLabel('Names use 1-29 ASCII characters. Maximum 70 events; delays are milliseconds after each event.')
        self.error.setWordWrap(True)
        box.addWidget(self.error)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        use = controls.addButton('Use macro on this button', QDialogButtonBox.ButtonRole.AcceptRole)
        use.clicked.connect(self.save)
        controls.rejected.connect(self.reject)
        box.addWidget(controls)
        if binding:
            self.load(binding)

    def append_step(self, step):
        if self.table.rowCount() >= MAX_EVENTS:
            raise ValueError('A macro can contain at most 70 events')
        row = self.table.rowCount()
        self.table.insertRow(row)
        action = QComboBox()
        for text, state in [('Press', 0), ('Release', 1), ('No transition', 2)]:
            action.addItem(text, state)
        action.setCurrentIndex(action.findData(step.state))
        self.table.setCellWidget(row, 0, action)
        key = QComboBox()
        key.setMaxVisibleItems(12)
        key.setStyleSheet("QComboBox { combobox-popup: 0; }")
        for name, value in KEYS.items():
            key.addItem(name, value)
        index = next((i for i in range(key.count())
                      if tuple(key.itemData(i)) == (step.kind, step.value)), -1)
        if index < 0:
            key.addItem(f'Existing type {step.kind} · 0x{step.value:04x}', (step.kind, step.value))
            index = key.count() - 1
        key.setCurrentIndex(index)
        self.table.setCellWidget(row, 1, key)
        delay = QSpinBox()
        delay.setRange(0, 65535)
        delay.setValue(step.delay_ms)
        self.table.setCellWidget(row, 2, delay)
        self.count.setText(f'{self.table.rowCount()} / 70 events')

    def steps(self):
        return tuple(MacroStep(self.table.cellWidget(i,0).currentData(),
                               *self.table.cellWidget(i,1).currentData(), self.table.cellWidget(i,2).value())
                     for i in range(self.table.rowCount()))

    def value(self):
        if self.recorder.recording:
            raise ValueError('Stop recording before using or exporting the macro')
        repeats = self.playback.currentData() or self.repeats.value()
        result = MacroBinding(Macro(self.name.text(), self.steps()), repeats)
        result.validate()
        return result

    def load(self, binding):
        self.name.setText(binding.macro.name)
        self.playback.setCurrentIndex(self.playback.findData(binding.repeats if binding.repeats >= 253 else 0))
        if binding.repeats < 253:
            self.repeats.setValue(binding.repeats)
        self.table.setRowCount(0)
        for step in binding.macro.steps:
            self.append_step(step)

    def add_press(self):
        if self.recorder.recording:
            return
        if self.table.rowCount() > 68:
            self.error.setText('Not enough room for another complete press.')
            return
        for state in (0, 1):
            self.append_step(MacroStep(state, *self.key.currentData(), self.delay.value()))

    def toggle_recording(self):
        if self.recorder.recording:
            self.recorder.stop()
        else:
            if self.table.rowCount():
                self.error.setText('Clear the current events before starting a new recording.')
                return
            self.record_button.setText('Stop recording')
            self.recorder.start()

    def recorded(self, steps):
        self.record_button.setText('Record keys')
        for step in steps:
            self.append_step(step)

    def remove_event(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
        self.count.setText(f'{self.table.rowCount()} / 70 events')

    def clear_events(self):
        if self.recorder.recording:
            self.recorder.stop()
        self.table.setRowCount(0)
        self.count.setText('0 / 70 events')

    def move(self, direction):
        row = self.table.currentRow()
        target = row + direction
        if row < 0 or not 0 <= target < self.table.rowCount():
            return
        steps = list(self.steps())
        steps[row], steps[target] = (steps[target], steps[row])
        self.table.setRowCount(0)
        for step in steps:
            self.append_step(step)
        self.table.selectRow(target)

    def save(self):
        try:
            self.binding = self.value()
        except ValueError as error:
            self.error.setText(str(error))
            return
        self.accept()

    def import_macro(self):
        if self.recorder.recording:
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Import Kanata macro', '', 'JSON (*.json)')
        if not path:
            return
        try:
            from pathlib import Path
            source = Path(path)
            if source.stat().st_size > 65536:
                raise ValueError('Macro file exceeds 64 KB')
            self.load(MacroBinding.from_dict(json.loads(source.read_text())))
        except (OSError, ValueError) as error:
            self.error.setText(str(error))

    def export_macro(self):
        try:
            binding = self.value()
        except ValueError as error:
            self.error.setText(str(error))
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export Kanata macro', 'macro.json', 'JSON (*.json)')
        if not path:
            return
        try:
            from pathlib import Path
            Path(path).write_text(json.dumps(binding.as_dict(), indent=2) + '\n')
        except OSError as error:
            self.error.setText(str(error))

    def reject(self):
        self.recorder.stop()
        super().reject()
