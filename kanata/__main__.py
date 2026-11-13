import argparse
import json
import sys

from .device import Hidraw, Session, discover
from .reports import ProtocolError


def main():
    parser = argparse.ArgumentParser(description="WG9S mouse configuration")
    parser.add_argument('--demo', action='store_true', help='Preview sample settings; no device writes')
    parser.add_argument('--inspect', action='store_true', help='Print sysfs metadata without opening HID devices')
    parser.add_argument('--read', action='store_true', help='Read device configuration and print JSON')
    parser.add_argument('--read-macros', action='store_true', help='Include macro slots with --read')
    parser.add_argument('--device', help='hidraw node to read; otherwise require one matching interface')
    args = parser.parse_args()
    if args.inspect:
        print(json.dumps(discover(), indent=2))
        return 0
    if args.read:
        trace = []
        try:
            nodes = [d['node'] for d in discover() if d['usable']]
            node = args.device or (nodes[0] if len(nodes) == 1 else None)
            if not node:
                raise ProtocolError('Specify --device when zero or multiple interfaces are detected')
            with Hidraw(node, trace) as transport:
                session = Session(transport)
                identity = session.identify()
                settings = session.read_settings(include_macros=args.read_macros)
                print(json.dumps({'identity': identity, 'settings': settings.as_dict(), 'transactions': trace}, indent=2))
            return 0
        except (OSError, ProtocolError) as error:
            print(json.dumps({'error': str(error), 'transactions': trace}, indent=2), file=sys.stderr)
            return 1
    from kanata_basic import main as run_basic
    return run_basic()


if __name__ == '__main__':
    sys.exit(main())
