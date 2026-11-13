import unittest
from unittest.mock import patch
from kanata.device import Hidraw
from kanata.reports import packet, ProtocolError


class TransportTests(unittest.TestCase):
    def transport(self):
        transport = Hidraw('/dev/hidraw-test')
        transport.fd = 123
        return transport

    def test_filters_unrelated_and_corrupt_responses(self):
        request = packet(8, 16, length=2)
        response = packet(8, 16, b'\x01T')
        unrelated = packet(8, 32, b'\x01T')
        with patch('kanata.device.os.read', side_effect=[BlockingIOError(), unrelated, b'\x08'*17, response]), \
             patch('kanata.device.os.write', return_value=17), patch('kanata.device.select.select', return_value=([123], [], [])):
            self.assertEqual(self.transport().exchange(request), response)

    def test_timeout(self):
        with patch('kanata.device.os.read', side_effect=BlockingIOError()), \
             patch('kanata.device.os.write', return_value=17), patch('kanata.device.select.select', return_value=([], [], [])):
            with self.assertRaisesRegex(ProtocolError, 'No valid response'):
                self.transport().exchange(packet(4))

    def test_write_acknowledgement_must_match(self):
        with patch('kanata.device.os.read', side_effect=[BlockingIOError(), packet(7, 0, b'\x01\x54')]), \
             patch('kanata.device.os.write', return_value=17), patch('kanata.device.select.select', return_value=([123], [], [])):
            with self.assertRaisesRegex(ProtocolError, 'acknowledgement differs'):
                self.transport().exchange(packet(7, 0, b'\x02S'))

    def test_short_write(self):
        with patch('kanata.device.os.read', side_effect=BlockingIOError()), patch('kanata.device.os.write', return_value=3):
            with self.assertRaisesRegex(OSError, 'Short HID write'):
                self.transport().exchange(packet(4))


if __name__ == '__main__':
    unittest.main()
