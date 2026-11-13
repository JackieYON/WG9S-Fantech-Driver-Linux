import fcntl
import os
import secrets
import select
import stat
import struct
import time
from pathlib import Path
from dataclasses import replace
from .macros import FLASH_SIZE, MACRO_SIZE, MacroBinding, macro_address
from .protocol import CONFIG_SIZE, Settings
from .reports import ProtocolError, packet, validate
from .hid_descriptor import report_layout


def discover(root=Path('/sys/class/hidraw')):
    found = []
    for node in sorted(root.glob('hidraw*')):
        device = node / 'device'
        try:
            fields = dict((line.split('=', 1) for line in (device / 'uevent').read_text().splitlines() if '=' in line))
            parts = fields.get('HID_ID', '').split(':')
            if len(parts) != 3 or int(parts[1], 16) != 13652 or int(parts[2], 16) not in (62720, 62721):
                continue
            descriptor = (device / 'report_descriptor').read_bytes()
            reports = report_layout(descriptor)
            usable = all(any(r['type'] == kind and r['report_id'] == 8 and r['payload_bytes'] == 16
                             for r in reports) for kind in ('input', 'output'))
            found.append({'node': '/dev/' + node.name, 'identity': fields, 'usable': usable,
                          'descriptor_hex': descriptor.hex(), 'reports': reports})
        except (OSError, ValueError) as error:
            found.append({'node': '/dev/' + node.name, 'usable': False, 'error': str(error)})
    return found


class Hidraw:
    def __init__(self, path, trace=None):
        self.path = path
        self.fd = None
        self.trace = trace if trace is not None else []

    def __enter__(self):
        candidates = {d['node'] for d in discover() if d['usable']}
        if self.path not in candidates:
            raise ProtocolError('Select a matching WG9S vendor HID interface')
        self.fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK | os.O_NOFOLLOW)
        try:
            if not stat.S_ISCHR(os.fstat(self.fd).st_mode):
                raise ProtocolError('Expected a hidraw character device')
            info = bytearray(8)
            fcntl.ioctl(self.fd, 2148026371, info, True)
            bus, vendor, product = struct.unpack('=IHH', info)
            if bus != 3 or vendor != 13652 or product not in (62720, 62721):
                raise ProtocolError('Opened device identity changed during discovery')
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            os.close(self.fd)
            self.fd = None
            raise
        return self

    def __exit__(self, *_):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def exchange(self, request):
        validate(request)

        for _ in range(64):
            try:
                if not os.read(self.fd, 64):
                    raise OSError('Mouse disconnected')
            except BlockingIOError:
                break
        self.trace.append({'direction': 'out', 'hex': request.hex()})
        if os.write(self.fd, request) != len(request):
            raise OSError('Short HID write')
        deadline = time.monotonic() + 0.5
        while (remaining := (deadline - time.monotonic())) > 0:
            if not select.select([self.fd], [], [], remaining)[0]:
                break
            try:
                response = os.read(self.fd, 64)
            except BlockingIOError:
                continue
            if not response:
                raise OSError('Mouse disconnected')
            if response[0] != 8:
                continue
            self.trace.append({'direction': 'in', 'hex': response.hex()})
            try:
                validate(response)
            except ProtocolError:
                continue
            if response[1] != request[1]:
                continue
            if request[1] == 8 and response[3:6] != request[3:6]:
                continue

            if request[1] == 7 and response != request:
                raise ProtocolError('Configuration write acknowledgement differs; re-read before retrying')
            return response
        raise ProtocolError(f'No valid response to command 0x{request[1]:02x}; wake the mouse and retry')


class Session:
    def __init__(self, transport):
        self.transport = transport
        self.identity = None

    def identify(self):
        self.identity = None

        response = self.transport.exchange(packet(1, payload=secrets.token_bytes(4), length=8))
        cid, mid, device_type = response[10:13]
        if (cid, mid) != (13, 7):
            raise ProtocolError(f'Device identity is not WG9S (CID={cid}, MID={mid}); configuration stopped')
        self.identity = {'cid': cid, 'mid': mid, 'device_type': device_type}
        return self.identity

    def read_bytes(self, address, length):
        if self.identity is None:
            raise ProtocolError('Identify the device first')
        if not 0 <= address < FLASH_SIZE or not 1 <= length <= FLASH_SIZE - address:
            raise ValueError('Read outside the configuration region')
        data = bytearray()
        while len(data) < length:
            count = min(10, length - len(data))
            response = self.transport.exchange(packet(8, address + len(data), length=count))
            data.extend(response[6:6 + count])
        return bytes(data)

    def read_settings(self, include_macros=False):
        settings = Settings.parse(self.read_bytes(0, CONFIG_SIZE))
        if include_macros:


            slots = set(range(6)) | {b[1] for b in settings.buttons if b[0] == 6}
            snapshots = {slot: self.read_bytes(macro_address(slot), MACRO_SIZE) for slot in sorted(slots)}
            settings = replace(settings, macro_slots=snapshots)
        return settings

    def battery(self):
        if self.identity is None:
            raise ProtocolError('Identify the device first')
        response = self.transport.exchange(packet(4))
        level, charging = response[6:8]
        if not 0 <= level <= 100 or charging not in (0, 1):
            raise ProtocolError('Unrecognized battery response')
        return {'percent': level, 'charging': bool(charging),
                'voltage_mv': int.from_bytes(response[8:10], 'big')}

    def apply(self, baseline, rate, active, dpi, buttons):

        plan = baseline.plan(rate, active, dpi, buttons)
        live = self.read_settings()
        if live.raw != baseline.raw:
            raise ProtocolError('Mouse settings changed since loading. Reload before applying.')
        for i, binding in enumerate(buttons):
            if isinstance(binding, MacroBinding):
                if self.read_bytes(macro_address(i), MACRO_SIZE) != baseline.macro_slots[i]:
                    raise ProtocolError('Mouse macro changed since loading. Reload before applying.')
        applied = 0
        try:
            for address, value in plan:
                self.transport.exchange(packet(7, address, value))
                if self.read_bytes(address, len(value)) != value:
                    raise ProtocolError(f'Readback mismatch at 0x{address:02x}')
                applied += 1
            return (self.read_settings(include_macros=bool(baseline.macro_slots)), applied)
        except (OSError, ProtocolError) as error:
            raise ProtocolError(f'Apply stopped after {applied}/{len(plan)} verified records. '
                                f'Some settings may have changed; reload the device. {error}') from error
