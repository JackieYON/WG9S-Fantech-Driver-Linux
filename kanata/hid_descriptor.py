def report_layout(data):
    state = {'size': 0, 'count': 0, 'id': 0}
    stack, bits = ([], {})
    offset = 0
    while offset < len(data):
        prefix = data[offset]
        offset += 1
        if prefix == 254:
            if offset + 2 > len(data):
                raise ValueError('Truncated HID long item')
            length = data[offset]
            offset += 2 + length
            if offset > len(data):
                raise ValueError('Truncated HID long payload')
            continue
        length = (0, 1, 2, 4)[prefix & 3]
        if offset + length > len(data):
            raise ValueError('Truncated HID item')
        value = int.from_bytes(data[offset:offset + length], 'little')
        offset += length
        kind, tag = (prefix >> 2 & 3, prefix >> 4)
        if kind == 1:
            if tag in (7, 8, 9):
                state[{7: 'size', 8: 'id', 9: 'count'}[tag]] = value
            elif tag == 10:
                stack.append(state.copy())
            elif tag == 11:
                if not stack:
                    raise ValueError('HID global stack underflow')
                state = stack.pop()
        elif kind == 0 and tag in (8, 9, 11):
            key = ({8: 'input', 9: 'output', 11: 'feature'}[tag], state['id'])
            bits[key] = bits.get(key, 0) + state['size'] * state['count']
    return [dict(type=kind, report_id=rid, payload_bits=size,
                 payload_bytes=(size + 7) // 8,
                 numbered_report_bytes=(size + 7) // 8 + bool(rid))
            for (kind, rid), size in sorted(bits.items())]

