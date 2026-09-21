#!/usr/bin/env python3
# Copyright (c) 2026 Nordic Semiconductor ASA
# SPDX-License-Identifier: LicenseRef-Nordic-5-Clause
"""Fetch last companion AXF1 frame from nRF9151 shell (VCOM0) and show the thumbnail."""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

from udp_image_server import parse_packet, save_capture

try:
    import serial
except ImportError:
    print("Install pyserial: pip install pyserial", file=sys.stderr)
    raise

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore


HEX_LINE_RE = re.compile(r"^COMPANION_HEX([0-9a-fA-F]+)\s*$", re.MULTILINE)


def fetch_dump(ser: serial.Serial, timeout_s: float = 5.0) -> bytes | None:
    ser.reset_input_buffer()
    ser.write(b"att_companion dump\r\n")
    ser.flush()

    deadline = time.monotonic() + timeout_s
    blob = b""
    while time.monotonic() < deadline:
        chunk = ser.read(ser.in_waiting or 1)
        if chunk:
            blob += chunk
            if b"COMPANION_END" in blob:
                break
        else:
            time.sleep(0.02)

    text = blob.decode("utf-8", errors="replace")
    hex_parts = HEX_LINE_RE.findall(text)
    if not hex_parts:
        print(text, file=sys.stderr)
        return None

    return bytes.fromhex("".join(hex_parts))


def show_luma(pkt: dict, out_dir: Path | None) -> None:
    w, h = pkt["thumb_w"], pkt["thumb_h"]
    img_bytes = pkt["image"]
    print(
        f"frame={pkt['frame_id']} score={pkt['top_score_mille']/1000:.3f} "
        f"thumb={w}x{h} bytes={len(img_bytes)}"
    )

    if out_dir is not None:
        path = save_capture(out_dir, pkt, ("serial", 0))
        print(f"Saved {path}")

    if Image is None:
        print("Install Pillow to pop up a window: pip install pillow", file=sys.stderr)
        return

    im = Image.frombytes("L", (w, h), img_bytes)
    im = im.resize((w * 16, h * 16), Image.NEAREST)
    im.show(title=f"frame {pkt['frame_id']}")


def watch_loop(ser: serial.Serial, out_dir: Path | None) -> None:
    print("Watching logs; auto-dump on 'Companion image pending' (Ctrl+C to quit)", flush=True)
    tail = b""
    trigger = b"Companion image pending"

    while True:
        data = ser.read(ser.in_waiting or 1)
        if not data:
            time.sleep(0.05)
            continue
        sys.stdout.buffer.write(data)
        sys.stdout.flush()
        tail = (tail + data)[-512:]
        if trigger in tail:
            time.sleep(0.1)
            wire = fetch_dump(ser)
            if wire is None:
                print("\n--- dump failed ---\n", flush=True)
                continue
            pkt = parse_packet(wire)
            if pkt is None:
                print("\n--- invalid AXF1 wire ---\n", flush=True)
                continue
            print("\n--- decoded thumbnail ---", flush=True)
            show_luma(pkt, out_dir)
            print("---\n", flush=True)
            tail = b""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", help="nRF9151 VCOM0 serial device, e.g. /dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Stream VCOM0 and auto-fetch on each companion frame",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Save .raw + .txt like udp_image_server",
    )
    args = parser.parse_args()

    with serial.Serial(args.port, args.baud, timeout=0.1) as ser:
        if args.watch:
            watch_loop(ser, args.out)
            return 0

        wire = fetch_dump(ser)
        if wire is None:
            return 1
        pkt = parse_packet(wire)
        if pkt is None:
            print("Invalid AXF1 packet", file=sys.stderr)
            return 1
        show_luma(pkt, args.out)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
