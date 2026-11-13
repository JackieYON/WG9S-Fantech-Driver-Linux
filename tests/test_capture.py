import json
import unittest
from pathlib import Path
from kanata.protocol import Settings
from kanata.reports import validate
from kanata.device import Session

CAPTURE = Path(__file__).parent / 'fixtures/wg9s-read.json'


class CaptureTests(unittest.TestCase):
    def test_reports_and_configuration_match(self):
        capture = json.loads(CAPTURE.read_text())
        assembled = bytearray(192)
        for entry in capture['transactions']:
            report = validate(bytes.fromhex(entry['hex']))
            if entry['direction'] == 'in' and report[1] == 8:
                address = int.from_bytes(report[3:5], 'big')
                assembled[address:address + report[5]] = report[6:6 + report[5]]
        self.assertEqual(assembled.hex(), capture['settings']['raw_hex'])
        current = Settings.parse(bytes(assembled))
        self.assertEqual(current.rate, 1000)
        self.assertEqual(current.active, 2)
        self.assertEqual(current.dpi, ((400, 400), (800, 800), (1200, 1200), (2400, 2400), (3200, 3200)))
        self.assertEqual(current.buttons[3], (5, 0, 0))
        self.assertEqual(current.buttons[5], (6, 5, 1))
        plan = current.plan(500, 2, [None] * 5, [None] * 6)
        self.assertEqual([address for address, _ in plan], [0])

    def test_captured_read_transactions_replay(self):
        capture = json.loads(CAPTURE.read_text())
        entries = iter(capture['transactions'])
        class Replay:
            def exchange(self, request):
                expected = bytes.fromhex(next(entries)['hex'])

                if request[1] == 1:
                    self_test.assertEqual(request[:6], expected[:6])
                else:
                    self_test.assertEqual(request, expected)
                return bytes.fromhex(next(entries)['hex'])
        self_test = self
        session = Session(Replay())
        self.assertEqual(session.identify(), capture['identity'])
        self.assertEqual(session.read_settings().raw.hex(), capture['settings']['raw_hex'])
        self.assertIsNone(next(entries, None))
