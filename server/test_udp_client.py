#!/usr/bin/env python3
"""Send one AXF1 thumbnail datagram to udp_image_server.py."""

import argparse
import socket
import struct
import zlib

# Matches packed struct companion_header in common/companion_proto.h (20 bytes).
HEADER_FMT = "<IBBIBHHBHH"
MAGIC = 0x41584631  # "AXF1"


def build_frame(frame_id: int, score_mille: int, width: int, height: int) -> bytes:
    image = bytes((i * 17) & 0xFF for i in range(width * height))
    header = struct.pack(
        HEADER_FMT,
        MAGIC,
        1,              # version
        1,              # msg_type: detect image
        frame_id,
        1,              # detect_count
        score_mille,
        len(image),
        0,              # raw luma
        width,
        height,
    )
    crc = zlib.crc32(header + image) & 0xFFFFFFFF
    return header + image + struct.pack("<I", crc)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4567)
    parser.add_argument("--frame-id", type=int, default=1)
    parser.add_argument("--score", type=int, default=850, help="score times 1000")
    parser.add_argument("--width", type=int, default=8)
    parser.add_argument("--height", type=int, default=8)
    parser.add_argument(
        "--garbage",
        action="store_true",
        help="send junk instead of a valid frame (server should print Invalid packet)",
    )
    args = parser.parse_args()

    payload = b"not-a-frame" if args.garbage else build_frame(
        args.frame_id, args.score, args.width, args.height
    )

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(payload, (args.host, args.port))
    print(f"sent {len(payload)} bytes to {args.host}:{args.port}")


if __name__ == "__main__":
    main()