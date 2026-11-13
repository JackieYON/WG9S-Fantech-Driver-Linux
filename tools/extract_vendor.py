import hashlib
import lzma
from pathlib import Path

DIGEST = 'fe868bc22604b7b32b584ef3907d4906659d0bd95146112861daf50cf59089c5'


def decode_executable(raw):
    data = bytearray(raw)
    i = 0
    while i + 4 < len(data):
        if data[i] not in (232, 233) or i % 65536 > 65531:
            i += 1
            continue
        if data[i + 4] in (0, 255):
            relative = int.from_bytes(data[i + 1:i + 4], 'little') - (i + 5) & 16777215
            data[i + 1:i + 4] = relative.to_bytes(3, 'little')
            if relative & 8388608:
                data[i + 4] ^= 255
        i += 5
    return bytes(data)


def main():
    root = Path(__file__).resolve().parents[1]
    source = root / 'vendor/Kanata_S_Wireless_WG9S_Software_V1.0.0.42_24081600.exe'
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != DIGEST:
        raise SystemExit('Installer digest differs; offsets must be re-established.')
    assert data[790016:790020] == b'zlb\x1a'
    prop = data[790020]
    filters = [{'id': lzma.FILTER_LZMA1, 'dict_size': int.from_bytes(data[790021:790025], 'little'),
                'lc': prop % 9, 'lp': prop // 9 % 5, 'pb': prop // 45}]
    decoder = lzma.LZMADecompressor(lzma.FORMAT_RAW, filters=filters)
    stream = decoder.decompress(data[790025:], max_length=16 * 1024 * 1024)
    if not decoder.eof or len(stream) != 9843402:
        raise SystemExit('Unexpected payload size or incomplete stream.')

    output = root / 'vendor/extracted'
    output.mkdir(exist_ok=True)
    target = output / 'MouseDriver.exe'
    target.write_bytes(decode_executable(stream[:5318144]))
    print(target)


if __name__ == '__main__':
    main()
