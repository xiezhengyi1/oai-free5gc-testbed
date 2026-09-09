"""Count actual GTP-U TCP/8080 paths in a Linux cooked-v2 tcpdump capture."""

import argparse
import collections
import json
import socket
import struct
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("pcap", type=Path)
args = parser.parse_args()
counts = collections.Counter()
with args.pcap.open("rb") as capture:
    header = capture.read(24)
    assert header[:4] == b"\xd4\xc3\xb2\xa1", "requires little-endian microsecond pcap"
    assert struct.unpack_from("<I", header, 20)[0] == 276, "requires Linux cooked v2"
    while record := capture.read(16):
        _, _, size, _ = struct.unpack("<IIII", record)
        packet = capture.read(size)
        assert len(packet) == size, "truncated capture"
        if packet[:2] != b"\x08\x00":
            continue
        outer = packet[20:]
        if outer[9] != 17:
            continue
        udp = outer[(outer[0] & 15) * 4 :]
        source_port, destination_port = struct.unpack_from("!HH", udp)
        if 2152 not in (source_port, destination_port):
            continue
        gtp = udp[8:]
        if gtp[1] != 255:
            continue
        offset = 8
        if gtp[0] & 7:
            extension = gtp[11]
            offset = 12
            while extension:
                length = gtp[offset] * 4
                assert length > 0, "invalid GTP extension length"
                extension = gtp[offset + length - 1]
                offset += length
        inner = gtp[offset:]
        if inner[0] >> 4 != 4 or inner[9] != 6:
            continue
        tcp = inner[(inner[0] & 15) * 4 :]
        ports = struct.unpack_from("!HH", tcp)
        if 8080 not in ports:
            continue
        key = (
            socket.inet_ntoa(outer[12:16]),
            socket.inet_ntoa(outer[16:20]),
            f"0x{struct.unpack_from('!I', gtp, 4)[0]:08x}",
            socket.inet_ntoa(inner[12:16]),
            socket.inet_ntoa(inner[16:20]),
        )
        counts[key] += 1
print(
    json.dumps(
        {
            "capture": str(args.pcap),
            "note": "any-interface capture can duplicate packets; counts are not throughput",
            "tcp_8080_gtpu_paths": [
                {
                    "outer_src": key[0],
                    "outer_dst": key[1],
                    "teid": key[2],
                    "inner_src": key[3],
                    "inner_dst": key[4],
                    "captured_packets": value,
                }
                for key, value in sorted(counts.items())
            ],
        },
        indent=2,
    )
)
