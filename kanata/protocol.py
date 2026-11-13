import json
from dataclasses import dataclass, field
from pathlib import Path

from .reports import ProtocolError, record, checked_record
from .macros import MacroBinding, MACRO_SIZE, macro_address

DPI_TABLE = {int(k): v for k, v in json.loads((Path(__file__).parent / 'data/sensor3311.json').read_text()).items()}
RATE_CODES = {125: 8, 250: 4, 500: 2, 1000: 1}
BUTTONS = {'Left click': (1, 1, 0), 'Right click': (1, 2, 0),
           'Middle click': (1, 4, 0), 'Back': (1, 8, 0), 'Forward': (1, 16, 0),
           'Cycle DPI': (2, 1, 0), 'DPI up': (2, 2, 0), 'DPI down': (2, 3, 0),
           'Disabled': (0, 0, 0)}
CONFIG_SIZE = 192


def encode_dpi(value):
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError('DPI must be an integer')
    extended = value > 10000
    if not 50 <= value <= 12000 or value % (100 if extended else 50):
        raise ValueError('DPI must be 50-10000 in steps of 50, or 10100-12000 in steps of 100')
    code = DPI_TABLE[value // 2 if extended else value]
    return bytes((code, code, 34 if extended else 0))


def decode_dpi(value):
    reverse = {v: k for k, v in DPI_TABLE.items()}
    x, y, extension = value
    if extension not in (0, 34) or x not in reverse or y not in reverse:
        raise ProtocolError('Unknown WG9S DPI encoding')
    result = (reverse[x] * (2 if extension else 1), reverse[y] * (2 if extension else 1))
    if any((v > 12000 for v in result)):
        raise ProtocolError('DPI exceeds the WG9S range')
    return result


@dataclass(frozen=True)
class Settings:
    raw: bytes
    rate: int
    stages: int
    active: int
    dpi: tuple
    buttons: tuple
    macro_slots: dict = field(default_factory=dict)

    @classmethod
    def parse(cls, raw):
        if len(raw) != CONFIG_SIZE:
            raise ProtocolError('Incomplete configuration snapshot')
        rate, = checked_record(raw, 0, 1)
        stages, = checked_record(raw, 2, 1)
        active, = checked_record(raw, 4, 1)
        reverse = {v: k for k, v in RATE_CODES.items()}
        if rate not in reverse or not 1 <= stages <= 5 or (not 0 <= active < stages):
            raise ProtocolError('Unsupported rate, stage count or active stage')
        dpi = tuple((decode_dpi(checked_record(raw, 12 + i * 4, 3)) for i in range(stages)))
        buttons = tuple((tuple(checked_record(raw, 96 + i * 4, 3)) for i in range(6)))
        return cls(bytes(raw), reverse[rate], stages, active, dpi, buttons)

    def as_dict(self):
        return {'polling_hz': self.rate, 'stage_count': self.stages, 'active_stage': self.active + 1,
                'dpi_xy': self.dpi, 'buttons': self.buttons, 'raw_hex': self.raw.hex(),
                'macro_slots': {str(k): v.hex() for k, v in self.macro_slots.items()}}

    def plan(self, rate, active, dpi, buttons):





        if (
            rate not in RATE_CODES
            or not 0 <= active < self.stages
            or len(dpi) != self.stages
            or len(buttons) != len(self.buttons)
        ):
            raise ValueError('Invalid settings shape')

        candidates = [
            (0, record(bytes((RATE_CODES[rate],)))),
            (4, record(bytes((active,)))),
        ]
        for index, value in enumerate(dpi):

            if value is not None:
                candidates.append((12 + index * 4, record(encode_dpi(value))))

        resulting_buttons = list(self.buttons)
        macro_writes = []
        changed_macro_slots = set()
        for index, binding in enumerate(buttons):
            if binding is None:
                continue
            if isinstance(binding, MacroBinding):
                writes = self._plan_macro(index, binding)
                if writes:
                    changed_macro_slots.add(index)
                macro_writes.extend(writes)
                assignment = (6, index, binding.repeats)
            elif binding in BUTTONS:
                assignment = BUTTONS[binding]
            else:
                raise ValueError('Unsupported button assignment')
            resulting_buttons[index] = assignment
            candidates.append((96 + index * 4, record(bytes(assignment))))

        if (1, 1, 0) not in resulting_buttons:
            raise ValueError('Keep at least one button assigned to Left click')

        for slot in changed_macro_slots:
            shared = any(
                index != slot and assignment[:2] == (6, slot)
                for index, assignment in enumerate(resulting_buttons)
            )
            if shared:
                raise ValueError(
                    "This macro slot is shared with another button; "
                    "reassign that button before replacing its contents"
                )

        changed = [
            (address, value)
            for address, value in candidates
            if self.raw[address:address + len(value)] != value
        ]
        return macro_writes + changed

    def _plan_macro(self, index, binding):
        binding.validate()
        if index not in self.macro_slots:
            raise ValueError('Read macro storage from the mouse before assigning macros')
        previous = self.macro_slots[index]
        if len(previous) != MACRO_SIZE:
            raise ValueError('Incomplete macro baseline')

        encoded = binding.macro.encode()
        if previous[:len(encoded)] == encoded:
            return []
        return [
            (macro_address(index) + offset, encoded[offset:offset + 10])
            for offset in range(0, len(encoded), 10)
        ]
