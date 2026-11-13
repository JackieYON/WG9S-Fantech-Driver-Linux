import json
import unittest
from dataclasses import replace
from unittest.mock import patch
from kanata.macros import (Macro, MacroStep, MacroBinding, MACRO_SIZE, FLASH_SIZE,
                           macro_address, KEYS)
from kanata.reports import ProtocolError, record, packet, validate
from kanata.device import Session
from kanata.demo import settings


def example():
    return Macro('Test', (MacroStep(0, 1, 4, 50), MacroStep(1, 1, 4, 0)))


class MacroPeer:
    def __init__(self):
        self.raw = bytearray([255]) * FLASH_SIZE
        self.raw[:192] = settings().raw
        self.writes = []
        self.fail_at = None
    def exchange(self, request):
        validate(request)
        command, address, length = (request[1], int.from_bytes(request[3:5], 'big'), request[5])
        if command == 8:
            return packet(8, address, bytes(self.raw[address:address + length]))
        if command == 7:
            if len(self.writes) == self.fail_at:
                raise OSError('Disconnected')
            self.writes.append((address, request[6:6 + length]))
            self.raw[address:address + length] = request[6:6 + length]
            return request
        raise AssertionError(command)


class MacroTests(unittest.TestCase):
    def session(self):
        peer = MacroPeer()
        session = Session(peer)
        session.identity = {'cid': 13, 'mid': 7}
        return (peer, session)

    def test_instruction_derived_event_vector(self):
        self.assertEqual(MacroStep(0, 1, 4, 50).encode(), bytes.fromhex('8104000032'))
        self.assertEqual(MacroStep(1, 1, 4, 0).encode(), bytes.fromhex('4104000000'))
        encoded = example().encode()
        self.assertEqual(len(encoded), 43)
        self.assertEqual(encoded[31:].hex(), '028104000032410400000057')

    def test_roundtrip_maximum_and_types(self):
        for kind in range(6):
            for state in range(3):
                step = MacroStep(state, kind, 43981, 65535)
                self.assertEqual(MacroStep.decode(step.encode()), step)
        macro = Macro('Maximum', tuple((MacroStep(state, 1, 4, 65535) for _ in range(35) for state in (0, 1))))
        encoded = macro.encode()
        self.assertEqual(len(encoded), 383)
        self.assertEqual(Macro.decode(encoded.ljust(MACRO_SIZE, b'\xff')), macro)
        self.assertEqual(macro_address(15) + MACRO_SIZE, FLASH_SIZE)

    def test_name_excluded_from_checksum(self):
        raw = bytearray(example().encode().ljust(MACRO_SIZE, b'\xff'))
        raw[1] = ord('B')
        self.assertEqual(Macro.decode(raw).name, 'Best')
        raw[34] ^= 1
        with self.assertRaises(ProtocolError):
            Macro.decode(raw)

    def test_invalid_macros_rejected(self):
        for macro in (Macro('',example().steps),Macro('x'*30,example().steps),Macro('名字',example().steps),
                      Macro('One',(MacroStep(0,1,4),)),
                      Macro('Held',(MacroStep(0,1,4),MacroStep(0,1,5))),
                      Macro('Released',(MacroStep(1,1,4),MacroStep(1,1,4))),
                      Macro('Too long',example().steps*36),
                      Macro('Delay',(MacroStep(0,1,4,65536),MacroStep(1,1,4)))):
            with self.assertRaises(ValueError):
                macro.encode()
        for raw in (bytes([255]) * MACRO_SIZE, b'', bytes(MACRO_SIZE)):
            with self.assertRaises(ProtocolError):
                Macro.decode(raw)
        for slot in (-1, 16, True):
            with self.assertRaises(ValueError):
                macro_address(slot)

    def test_import_export_modes_and_validation(self):
        for repeats in (1, 252, 253, 254, 255):
            binding = MacroBinding(example(), repeats)
            self.assertEqual(MacroBinding.from_dict(json.loads(json.dumps(binding.as_dict()))), binding)
        for data in ({}, {'format': 'other'}, {'format': 'kanata-macro-v1', 'steps': [{}] * 71}):
            with self.assertRaises(ValueError):
                MacroBinding.from_dict(data)
        malformed = MacroBinding(example()).as_dict()
        malformed['steps'][0]['state'] = '0'
        with self.assertRaises(ValueError):
            MacroBinding.from_dict(malformed)

    def test_requires_storage_snapshot_and_primary_click(self):
        base = settings()
        buttons = [None] * 6
        buttons[3] = MacroBinding(example())
        with self.assertRaisesRegex(ValueError, 'Read macro storage'):
            base.plan(1000, 1, [None] * 5, buttons)
        base = settings(include_macros=True)
        buttons[0] = buttons[3]
        with self.assertRaisesRegex(ValueError, 'Left click'):
            base.plan(1000, 1, [None] * 5, buttons)

    def test_apply_writes_macro_before_button_and_preserves_other_slots(self):
        peer, session = self.session()
        base = session.read_settings(include_macros=True)
        before = bytes(peer.raw)
        buttons = [None] * 6
        buttons[3] = MacroBinding(example(), 2)
        result, count = session.apply(base, 1000, 1, [None] * 5, buttons)
        self.assertEqual(result.buttons[3], (6, 3, 2))
        self.assertEqual(count, 6)
        self.assertEqual(peer.writes[-1][0], 108)
        slot = macro_address(3)
        self.assertEqual(Macro.decode(result.macro_slots[3]), example())
        self.assertEqual(peer.raw[slot + 43:], before[slot + 43:])
        self.assertEqual(peer.raw[192:slot], before[192:slot])
        self.assertEqual(peer.raw[112:192], before[112:192])

    def test_stale_macro_prevents_all_writes(self):
        peer, session = self.session()
        base = session.read_settings(include_macros=True)
        peer.raw[macro_address(3)] ^= 1
        buttons = [None] * 6
        buttons[3] = MacroBinding(example())
        with self.assertRaisesRegex(ProtocolError, 'macro changed since'):
            session.apply(base, 500, 1, [None] * 5, buttons)
        self.assertEqual(peer.writes, [])

    def test_failed_macro_write_does_not_enable_assignment(self):
        peer, session = self.session()
        base = session.read_settings(include_macros=True)
        peer.fail_at = 2
        buttons = [None] * 6
        buttons[3] = MacroBinding(example())
        with self.assertRaisesRegex(ProtocolError, '2/6 verified'):
            session.apply(base, 1000, 1, [None] * 5, buttons)
        self.assertEqual(bytes(peer.raw[108:112]), base.raw[108:112])

    def test_shared_slot_cannot_change_an_unrelated_button(self):
        peer, session = self.session()
        peer.raw[112:116] = record(bytes((6, 3, 1)))
        baseline = session.read_settings(include_macros=True)
        buttons = [None] * 6
        buttons[3] = MacroBinding(example())
        with self.assertRaisesRegex(ValueError, 'shared with another button'):
            session.apply(baseline, 1000, 1, [None] * 5, buttons)
        self.assertEqual(peer.writes, [])

    def test_unchanged_macro_does_not_rewrite(self):
        peer, session = self.session()
        encoded = example().encode()
        offset = macro_address(3)
        peer.raw[offset:offset + len(encoded)] = encoded
        peer.raw[108:112] = record(bytes((6, 3, 1)))
        base = session.read_settings(include_macros=True)
        buttons = [None] * 6
        buttons[3] = MacroBinding(example())
        self.assertEqual(base.plan(1000, 1, [None] * 5, buttons), [])


if __name__ == '__main__':
    unittest.main()
