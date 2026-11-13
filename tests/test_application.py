import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

from kanata.application import DeviceService
from kanata.demo import settings
from kanata.reports import ProtocolError


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.factory = MagicMock()
        self.session_patch = patch('kanata.application.Session')
        self.session = self.session_patch.start().return_value
        self.addCleanup(self.session_patch.stop)
        self.session.identify.return_value = {'cid': 13, 'mid': 7}
        self.session.read_settings.return_value = settings()
        self.service = DeviceService(self.factory)

    def test_optional_battery_failure_keeps_valid_configuration(self):
        self.session.battery.side_effect = ProtocolError('Unsupported reply')
        trace = []
        result = self.service.read('/dev/hidraw-test', trace)
        self.assertEqual(result.settings, settings())
        self.assertIsNone(result.battery)
        self.factory.assert_called_once_with('/dev/hidraw-test', trace)
        self.factory.return_value.__exit__.assert_called_once()

    def test_configuration_failure_propagates_and_closes_transport(self):
        self.session.read_settings.side_effect = ProtocolError('Bad checksum')
        with self.assertRaisesRegex(ProtocolError, 'Bad checksum'):
            self.service.read('/dev/hidraw-test', [])
        self.session.battery.assert_not_called()
        self.factory.return_value.__exit__.assert_called_once()

    def test_apply_receives_a_snapshot_not_live_widgets(self):
        baseline = settings()
        draft = (500, 1, [None] * 5, [None] * 6)
        self.session.apply.return_value = (baseline, 1)
        result = self.service.apply('/dev/hidraw-test', [], baseline, draft, None)
        self.session.apply.assert_called_once_with(baseline, *draft)
        self.assertIn('1 records', result.message)
        self.factory.return_value.__exit__.assert_called_once()

    def test_cli_import_does_not_load_qt(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "import kanata.__main__, sys; "
             "assert not any(m.startswith('PySide6') for m in sys.modules)"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
