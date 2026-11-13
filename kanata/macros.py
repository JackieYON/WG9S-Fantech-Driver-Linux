from dataclasses import dataclass
from .reports import ProtocolError, checksum

MACRO_BASE = 768
MACRO_SIZE = 384
MACRO_SLOTS = 16
FLASH_SIZE = MACRO_BASE + MACRO_SIZE * MACRO_SLOTS
MAX_EVENTS = 70


KEYS = {chr(65 + i): (1, 4 + i) for i in range(26)}
KEYS.update({str((i + 1) % 10): (1, 30 + i) for i in range(10)})
KEYS.update({name: (1, code) for name, code in {
    'Enter': 40, 'Escape': 41, 'Backspace': 42, 'Tab': 43, 'Space': 44,
    '-': 45, '=': 46, '[': 47, ']': 48, '\\': 49, ';': 51, "'": 52,
    '`': 53, ',': 54, '.': 55, '/': 56, 'Caps Lock': 57,
    'Insert': 73, 'Home': 74, 'Page Up': 75, 'Delete': 76, 'End': 77,
    'Page Down': 78, 'Right': 79, 'Left': 80, 'Down': 81, 'Up': 82,
}.items()})
KEYS.update({f'F{i + 1}': (1, 58 + i) for i in range(12)})
KEYS.update({name: (0, 1 << i) for i, name in enumerate(
    ('Left Ctrl', 'Left Shift', 'Left Alt', 'Left Super',
     'Right Ctrl', 'Right Shift', 'Right Alt', 'Right Super'))})
KEYS.update({name: (4, 1 << i) for i, name in enumerate(
    ('Mouse left', 'Mouse right', 'Mouse middle', 'Mouse back', 'Mouse forward'))})


def macro_address(slot):
    if type(slot) is not int or not 0 <= slot < MACRO_SLOTS:
        raise ValueError('Macro slot must be 0-15')
    return MACRO_BASE + slot * MACRO_SIZE


@dataclass(frozen=True)
class MacroStep:
    state: int
    kind: int
    value: int
    delay_ms: int = 0

    def validate(self):
        if any((type(v) is not int for v in (self.state, self.kind, self.value, self.delay_ms))):
            raise ValueError('Macro event fields must be integers')
        if self.state not in (0, 1, 2) or self.kind not in range(6):
            raise ValueError('Unknown macro event action or device type')
        if not 0 <= self.value <= 65535 or not 0 <= self.delay_ms <= 65535:
            raise ValueError('Macro key values and delays must fit in 16 bits')

    def encode(self):
        self.validate()
        flags = (128, 64, 0)[self.state]
        return bytes((flags | self.kind, self.value & 255, self.value >> 8)) + self.delay_ms.to_bytes(2, 'big')

    @classmethod
    def decode(cls, raw):
        if len(raw) != 5:
            raise ProtocolError('A macro event must contain five bytes')
        flags = raw[0] & 192
        if flags not in (0, 64, 128) or raw[0] & 48:
            raise ProtocolError('Unknown macro event flags')
        item = cls({0: 2, 0x40: 1, 0x80: 0}[flags], raw[0] & 15,
                   int.from_bytes(raw[1:3], 'little'), int.from_bytes(raw[3:5], 'big'))
        try:
            item.validate()
        except ValueError as error:
            raise ProtocolError(str(error)) from error
        return item


@dataclass(frozen=True)
class Macro:
    name: str
    steps: tuple

    def validate(self):
        try:
            name = self.name.encode('ascii')
        except (AttributeError, UnicodeEncodeError) as error:
            raise ValueError('Use an ASCII macro name (1-29 characters)') from error
        if not 1 <= len(name) <= 29 or any((c < 32 or c > 126 for c in name)):
            raise ValueError('Use an ASCII macro name (1-29 printable characters)')
        if not 2 <= len(self.steps) <= MAX_EVENTS:
            raise ValueError('A macro needs 2-70 events (up to 35 complete presses)')
        held = set()
        for step in self.steps:
            if not isinstance(step, MacroStep):
                raise ValueError('Invalid macro event')
            step.validate()
            if step.kind not in (0, 1, 4):
                continue
            key = (step.kind, step.value)
            if step.state == 0:
                if key in held:
                    raise ValueError('A key is pressed twice without being released')
                held.add(key)
            elif step.state == 1:
                if key not in held:
                    raise ValueError('A key is released before it is pressed')
                held.remove(key)
        if held:
            raise ValueError('Release every pressed key before the macro ends')

    def encode(self):
        self.validate()
        header = bytes((len(self.name),)) + self.name.encode('ascii').ljust(30, b'\xff')
        events = bytes((len(self.steps),)) + b''.join((step.encode() for step in self.steps))

        return header + events + bytes((checksum(events),))

    @classmethod
    def decode(cls, raw):
        if len(raw) != MACRO_SIZE:
            raise ProtocolError('Incomplete macro slot')
        name_size, count = (raw[0], raw[31])
        if not 0 <= name_size <= 30 or not 2 <= count <= MAX_EVENTS:
            raise ProtocolError('Macro slot is empty or has invalid name/event counts')
        end = 32 + 5 * count
        if checksum(raw[31:end]) != raw[end]:
            raise ProtocolError('Macro checksum does not match')


        name = raw[1:1 + name_size].decode('ascii', errors='replace') or 'Mouse macro'
        return cls(name, tuple((MacroStep.decode(raw[i:i + 5]) for i in range(32, end, 5))))


@dataclass(frozen=True)
class MacroBinding:
    macro: Macro
    repeats: int = 1

    def validate(self):
        self.macro.validate()
        if type(self.repeats) is not int or not 1 <= self.repeats <= 255:
            raise ValueError('Repeat count must be 1-252, or a supported repeat mode')

    def as_dict(self):
        return {'format': 'kanata-macro-v1', 'name': self.macro.name, 'repeats': self.repeats,
                'steps': [{'state': s.state, 'kind': s.kind, 'value': s.value, 'delay_ms': s.delay_ms}
                          for s in self.macro.steps]}

    @classmethod
    def from_dict(cls, data):
        try:
            if data['format'] != 'kanata-macro-v1':
                raise ValueError('Unsupported macro file format')
            steps = data['steps']
            if not isinstance(steps, list) or len(steps) > MAX_EVENTS:
                raise ValueError('Too many macro events')
            binding = cls(Macro(data['name'], tuple((MacroStep(**step) for step in steps))), data['repeats'])
            binding.validate()
            return binding
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError('Invalid macro file structure') from error
