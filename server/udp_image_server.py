#!/usr/bin/env python3
# Copyright (c) 2026 Nordic Semiconductor ASA
# SPDX-License-Identifier: LicenseRef-Nordic-5-Clause
"""UDP server for AXF1 person-detect thumbnails from Iridium NTN demo."""

from __future__ import annotations

import argparse
import struct
import sys
import time
from pathlib import Path

COMPANION_MAGIC = 0x41584631
COMPANION_HEADER_SIZE = 20
COMPANION_CRC_SIZE = 4
COMPANION_WIRE_MAX = 2048
COMPANION_MAX_IMAGE = COMPANION_WIRE_MAX - COMPANION_HEADER_SIZE - COMPANION_CRC_SIZE
COMPANION_FMT_RAW_LUMA = 0
COMPANION_FMT_JPEG = 1

HEADER_FMT = "<IBBIBHHBHH"
HEADER_SIZE = struct.calcsize(HEADER_FMT)


def crc32_ieee(data: bytes) -> int:
    import zlib

    return zlib.crc32(data) & 0xFFFFFFFF


def parse_packet(data: bytes) -> dict | None:
    if len(data) < HEADER_SIZE + COMPANION_CRC_SIZE:
        return None

    (
        magic,
        version,
        msg_type,
        frame_id,
        detect_count,
        top_score_mille,
        image_len,
        image_fmt,
        thumb_w,
        thumb_h,
    ) = struct.unpack_from(HEADER_FMT, data, 0)

    if magic != COMPANION_MAGIC or version != 1 or msg_type != 1:
        return None

    total = HEADER_SIZE + image_len + COMPANION_CRC_SIZE
    if len(data) != total or image_len > COMPANION_MAX_IMAGE:
        return None

    body = data[: HEADER_SIZE + image_len]
    expect_crc = crc32_ieee(body)
    got_crc = struct.unpack_from("<I", data, HEADER_SIZE + image_len)[0]
    if expect_crc != got_crc:
        return None

    image = data[HEADER_SIZE : HEADER_SIZE + image_len]
    return {
        "frame_id": frame_id,
        "detect_count": detect_count,
        "top_score_mille": top_score_mille,
        "image_fmt": image_fmt,
        "thumb_w": thumb_w,
        "thumb_h": thumb_h,
        "image": image,
    }


def save_capture(out_dir: Path, pkt: dict, src: tuple[str, int]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    base = f"{ts}_frame{pkt['frame_id']}_score{pkt['top_score_mille']}"

    if pkt["image_fmt"] == COMPANION_FMT_JPEG and pkt["image"][:2] == b"\xff\xd8":
        path = out_dir / f"{base}.jpg"
        path.write_bytes(pkt["image"])
    elif pkt["image_fmt"] == COMPANION_FMT_RAW_LUMA:
        path = out_dir / f"{base}_{pkt['thumb_w']}x{pkt['thumb_h']}.raw"
        path.write_bytes(pkt["image"])
    else:
        path = out_dir / f"{base}.bin"
        path.write_bytes(pkt["image"])

    meta = out_dir / f"{base}.txt"
    meta.write_text(
        f"from={src[0]}:{src[1]}\n"
        f"frame_id={pkt['frame_id']}\n"
        f"detect_count={pkt['detect_count']}\n"
        f"score_mille={pkt['top_score_mille']}\n"
        f"fmt={pkt['image_fmt']}\n"
        f"size={len(pkt['image'])}\n",
        encoding="utf-8",
    )
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=4567)
    parser.add_argument("--out", type=Path, default=Path("captures"))
    args = parser.parse_args()

    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))
    print(f"Listening UDP {args.host}:{args.port} -> {args.out.resolve()}", flush=True)

    while True:
        data, addr = sock.recvfrom(2048)
        pkt = parse_packet(data)
        if pkt is None:
            print(f"Invalid packet {len(data)} B from {addr}", flush=True)
            continue
        path = save_capture(args.out, pkt, addr)
        print(
            f"Saved {path.name} frame={pkt['frame_id']} score={pkt['top_score_mille']/1000:.3f}",
            flush=True,
        )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
