from .protocol import CONFIG_SIZE, Settings, encode_dpi
from .reports import record


def settings(include_macros=False):
    raw = bytearray(CONFIG_SIZE)
    for address, data in [(0, b'\x01'), (2, b'\x05'), (4, b'\x01')]:
        raw[address:address + 2] = record(data)
    for i, value in enumerate((400, 800, 1200, 2400, 3200)):
        raw[12 + i * 4:16 + i * 4] = record(encode_dpi(value))
    for i, value in enumerate(((1, 1, 0), (1, 2, 0), (1, 4, 0), (1, 8, 0), (1, 16, 0), (2, 1, 0))):
        raw[96 + i * 4:100 + i * 4] = record(bytes(value))
    if not include_macros:
        return Settings.parse(bytes(raw))
    from dataclasses import replace
    from .macros import Macro, MacroStep, MACRO_SIZE
    slots = {i: bytes([255]) * MACRO_SIZE for i in range(6)}
    macro = Macro('Example macro', (MacroStep(0, 1, 4, 50), MacroStep(1, 1, 4, 0)))
    encoded = macro.encode()
    slots[5] = encoded.ljust(MACRO_SIZE, b'\xff')
    return replace(Settings.parse(bytes(raw)), macro_slots=slots)
