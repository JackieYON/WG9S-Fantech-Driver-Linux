import argparse
import hashlib
import json
from pathlib import Path


import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kanata.hid_descriptor import report_layout


def collect(output, vendor, product):
    output.mkdir(parents=True, exist_ok=True)
    devices = []
    for node in sorted(Path('/sys/class/hidraw').glob('hidraw*')):
        device = node / 'device'
        fields = dict(line.split("=", 1) for line in
                      (device / "uevent").read_text().splitlines() if "=" in line)
        parts = fields.get('HID_ID', '').split(':')
        if len(parts) != 3 or (int(parts[1], 16), int(parts[2], 16)) != (vendor, product):
            continue
        descriptor = (device / 'report_descriptor').read_bytes()
        filename = node.name + '-report-descriptor.bin'
        (output / filename).write_bytes(descriptor)
        devices.append(dict(node="/dev/" + node.name, sysfs=str(device.resolve()),
                            identity=fields, descriptor=filename,
                            sha256=hashlib.sha256(descriptor).hexdigest(),
                            reports=report_layout(descriptor)))
    result = dict(vendor=f"{vendor:04x}", product=f"{product:04x}",
                  model_confirmed=False, devices=devices)
    (output / 'device.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return bool(devices)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="WG9S mouse configuration")
    parser.add_argument('--output', type=Path, default=Path('evidence/receiver'))
    parser.add_argument('--vendor', type=lambda s: int(s, 16), default=13652)
    parser.add_argument('--product', type=lambda s: int(s, 16), default=62720)
    args = parser.parse_args()
    if not collect(args.output, args.vendor, args.product):
        parser.exit(1, 'No matching HID interfaces found.\n')
