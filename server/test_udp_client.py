#!/usr/bin/env python3
"""Send AXF1 thumbnail datagram(s) to udp_image_server.py."""

import argparse
import socket
import struct
import zlib

HEADER_FMT = "<IBBIBHHBHH"
MAGIC = 0x41584631
COMPANION_MSG_DETECT_IMAGE = 1
COMPANION_MSG_DETECT_IMAGE_CHUNK = 2


def build_frame(
    frame_id: int,
    score_mille: int,
    width: int,
    height: int,
    image: bytes,
    *,
    msg_type: int = COMPANION_MSG_DETECT_IMAGE,
    chunk_index: int = 0,
    chunk_total: int = 0,
) -> bytes:
    header = struct.pack(
        HEADER_FMT,
        MAGIC,
        1,
        msg_type,
        frame_id,
        chunk_index if msg_type == COMPANION_MSG_DETECT_IMAGE_CHUNK else 1,
        score_mille,
        len(image),
        chunk_total if msg_type == COMPANION_MSG_DETECT_IMAGE_CHUNK else 0,
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
    parser.add_argument("--score", type=int, default=850)
    parser.add_argument("--width", type=int, default=64)
    parser.add_argument("--height", type=int, default=64)
    parser.add_argument("--chunked", action="store_true", help="4x1024 B chunks (64x64)")
    parser.add_argument(
        "--garbage",
        action="store_true",
        help="send junk instead of a valid frame",
    )
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    if args.garbage:
        payload = b"not-a-frame"
    elif args.chunked:
        full = bytes((i * 3) & 0xFF for i in range(args.width * args.height))
        chunk_size = len(full) // 4
        for i in range(4):
            chunk = full[i * chunk_size : (i + 1) * chunk_size]
            payload = build_frame(
                args.frame_id,
                args.score,
                args.width,
                args.height,
                chunk,
                msg_type=COMPANION_MSG_DETECT_IMAGE_CHUNK,
                chunk_index=i,
                chunk_total=4,
            )
            sock.sendto(payload, (args.host, args.port))
            print(f"sent chunk {i + 1}/4 ({len(payload)} B)")
        return
    else:
        w, h = args.width, args.height
        image = bytes((i * 17) & 0xFF for i in range(w * h))
        payload = build_frame(args.frame_id, args.score, w, h, image)

    sock.sendto(payload, (args.host, args.port))
    print(f"sent {len(payload)} bytes to {args.host}:{args.port}")


if __name__ == "__main__":
    main()
