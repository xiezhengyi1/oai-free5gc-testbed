"""Read-only gtp5g 0.9.5 generic-netlink dump; retain every returned attribute byte."""

from __future__ import annotations

import json
import socket
import struct


def attributes(data):
    result = {}
    offset = 0
    while offset < len(data):
        length, kind = struct.unpack_from("HH", data, offset)
        if length < 4 or offset + length > len(data):
            raise ValueError("malformed kernel attribute boundary")
        key = str(kind & 0x3FFF)
        value = data[offset + 4 : offset + length].hex()
        if key in result:
            previous = result[key]
            result[key] = [*previous, value] if isinstance(previous, list) else [previous, value]
        else:
            result[key] = value
        offset += (length + 3) & ~3
    return result


def attribute(kind, value):
    packet = struct.pack("HH", len(value) + 4, kind) + value
    return packet + bytes((-len(packet)) % 4)


def main():
    with socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, 16) as client:
        client.bind((0, 0))
        client.settimeout(5)
        sequence = 0

        def query(family, operation, payload, dump=False):
            nonlocal sequence
            sequence += 1
            data = struct.pack("BBH", operation, 1, 0) + payload
            flags = 1 | (0x300 if dump else 0)
            client.sendto(
                struct.pack("IHHII", len(data) + 16, family, flags, sequence, 0) + data, (0, 0)
            )
            rows = []
            while True:
                received = client.recv(1024 * 1024)
                offset = 0
                while offset < len(received):
                    length, kind, _, seq, _ = struct.unpack_from("IHHII", received, offset)
                    if length < 16 or offset + length > len(received):
                        raise ValueError("malformed netlink response")
                    message = received[offset + 16 : offset + length]
                    offset += (length + 3) & ~3
                    if seq != sequence:
                        raise RuntimeError("unexpected netlink sequence")
                    if kind == 2:
                        error = struct.unpack_from("i", message)[0]
                        if error:
                            raise OSError(-error, "gtp5g dump failed")
                        continue
                    if kind == 3:
                        return rows
                    rows.append(attributes(message[4:]))
                if not dump:
                    return rows

        family = int.from_bytes(
            bytes.fromhex(query(16, 3, attribute(2, b"gtp5g\0"))[0]["1"]), "little"
        )
        link = socket.if_nametoindex("upfgtp")
        result = {}
        # gtp5g/include/genl{,_pdr,_far,_qer,_urr}.h, deployed 0.9.5 source.
        for name, operation, seid_attribute in [
            ("pdr", 7, "11"),
            ("far", 8, "7"),
            ("qer", 9, "13"),
            ("urr", 14, "8"),
        ]:
            rows = query(family, operation, attribute(1, struct.pack("I", link)), True)
            result[name] = sorted(
                [
                    {
                        "seid": int.from_bytes(bytes.fromhex(row[seid_attribute]), "little"),
                        "id": int.from_bytes(bytes.fromhex(row["3"]), "little"),
                        "attrs": row,
                    }
                    for row in rows
                ],
                key=lambda row: (row["seid"], row["id"]),
            )
        print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
