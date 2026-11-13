class ProtocolError(Exception):
    pass


def checksum(data):
    return 85 - sum(data) & 255


def packet(command, address=0, payload=b'', length=None):
    if command not in (1, 4, 7, 8):
        raise ValueError('Command is outside the implemented configuration subset')
    if not 0 <= address < 65536 or len(payload) > 10:
        raise ValueError('Invalid report address or payload length')
    length = len(payload) if length is None else length
    if not 0 <= length <= 10 or len(payload) > length:
        raise ValueError('Invalid report length')
    report = bytes((8, command, 0, address >> 8, address & 255, length)) + payload.ljust(10, b'\x00')
    return report + bytes((checksum(report),))


def validate(report):
    if len(report) != 17 or report[0] != 8 or checksum(report[:16]) != report[16]:
        raise ProtocolError('Invalid vendor report length, ID or checksum')
    return report


def record(payload):
    return bytes(payload) + bytes((checksum(payload),))


def checked_record(data, address, size):
    value = data[address:address + size]
    if len(value) != size or address + size >= len(data) or checksum(value) != data[address + size]:
        raise ProtocolError(f'Configuration record checksum failed at 0x{address:02x}')
    return value


