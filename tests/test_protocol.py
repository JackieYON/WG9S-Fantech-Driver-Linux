import unittest
from kanata.demo import settings
from kanata.protocol import Settings, encode_dpi, decode_dpi, DPI_TABLE
from kanata.reports import ProtocolError, packet, validate, record, checksum
from kanata.device import Session


class FakeMouse:

    def __init__(self):
        self.raw = bytearray(settings().raw)
        self.requests = []
        self.cid = 13
        self.fail_at = None
        self.writes = 0
    def exchange(self, request):
        validate(request)
        self.requests.append(request)
        command, address, length = (request[1], int.from_bytes(request[3:5], 'big'), request[5])
        if command == 1:
            response = bytearray(request)
            response[10:13] = bytes((self.cid, 7, 5))
            response[16] = checksum(response[:16])
            return bytes(response)
        if command == 8:
            return packet(8, address, bytes(self.raw[address:address + length]))
        if command == 7:
            self.writes += 1
            if self.writes == self.fail_at:
                raise OSError('Disconnected')
            self.raw[address:address + length] = request[6:6 + length]
            return request
        raise AssertionError(command)


class ProtocolTests(unittest.TestCase):
    def test_static_read_vector(self):

        self.assertEqual(packet(8, 0, length=10).hex(), '08080000000a000000000000000000003b')

    def test_static_write_vector(self):

        self.assertEqual(packet(7, 0, record(b'\x02')).hex(), '08070000000202530000000000000000ef')

    def test_reject_invalid_packets(self):
        for raw in (b'', b'\x08' * 17, packet(4)[:-1], bytes(17)):
            with self.assertRaises(ProtocolError):
                validate(raw)
        with self.assertRaises(ValueError):
            packet(13)
        with self.assertRaises(ValueError):
            packet(8, length=11)

    def test_every_dpi_value_roundtrips(self):
        self.assertEqual(len(DPI_TABLE), 200)
        for dpi in list(range(50, 10001, 50)) + list(range(10100, 12001, 100)):
            self.assertEqual(decode_dpi(encode_dpi(dpi)), (dpi, dpi))
        for dpi in (0, 49, 51, 10050, 12050, 16000, 100.5, True):
            with self.assertRaises(ValueError):
                encode_dpi(dpi)

    def test_corrupt_config_is_rejected(self):
        raw = bytearray(settings().raw)
        raw[13] ^= 1
        with self.assertRaises(ProtocolError):
            Settings.parse(raw)
        with self.assertRaises(ProtocolError):
            Settings.parse(raw[:-1])

    def test_preserve_unchanged_and_unknown_records(self):
        current = settings()
        self.assertEqual(current.plan(1000, 1, [None] * 5, [None] * 6), [])
        plan = current.plan(500, 1, [None, 1600, None, None, None], [None] * 6)
        self.assertEqual([p[0] for p in plan], [0, 16])
        self.assertEqual(plan[1][1], record(encode_dpi(1600)))
        with self.assertRaises(ValueError):
            current.plan(1000, 1, [None] * 5, ['Disabled'] * 6)

    def test_identification_and_read(self):
        peer = FakeMouse()
        session = Session(peer)
        with self.assertRaises(ProtocolError):
            session.read_settings()
        session.identify()
        loaded = session.read_settings()
        self.assertEqual(loaded, settings())
        self.assertEqual(len(peer.requests), 21)

    def test_wrong_identity_stops_access(self):
        peer = FakeMouse()
        peer.cid = 99
        session = Session(peer)
        with self.assertRaises(ProtocolError):
            session.identify()
        self.assertEqual(len(peer.requests), 1)
        self.assertIsNone(session.identity)

    def test_apply_and_readback(self):
        peer = FakeMouse()
        session = Session(peer)
        session.identify()
        current = session.read_settings()
        result, count = session.apply(current, 500, 1, [None, 1600, None, None, None], [None] * 6)
        self.assertEqual(count, 2)
        self.assertEqual(result.rate, 500)
        self.assertEqual(result.dpi[1], (1600, 1600))
        self.assertEqual(current.raw[96:], result.raw[96:])

    def test_stale_state_no_writes(self):
        peer = FakeMouse()
        session = Session(peer)
        session.identify()
        current = session.read_settings()
        peer.raw[0:2] = record(b'\x02')
        with self.assertRaisesRegex(ProtocolError, 'changed since'):
            session.apply(current, 250, 1, [None] * 5, [None] * 6)
        self.assertEqual(peer.writes, 0)

    def test_partial_failure_reported(self):
        peer = FakeMouse()
        session = Session(peer)
        session.identify()
        current = session.read_settings()
        peer.fail_at = 2
        with self.assertRaisesRegex(ProtocolError, '1/2 verified'):
            session.apply(current, 500, 2, [None] * 5, [None] * 6)
        self.assertEqual(peer.writes, 2)

    def test_readback_mismatch_stops(self):
        class LyingPeer(FakeMouse):
            def exchange(self, request):
                if request[1] == 7:
                    self.writes += 1
                    return request
                return super().exchange(request)
        peer = LyingPeer()
        session = Session(peer)
        session.identify()
        current = session.read_settings()
        with self.assertRaisesRegex(ProtocolError, 'Readback mismatch'):
            session.apply(current, 500, 2, [None] * 5, [None] * 6)
        self.assertEqual(peer.writes, 1)


if __name__ == '__main__':
    unittest.main()
