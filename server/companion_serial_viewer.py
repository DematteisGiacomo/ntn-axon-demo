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

from udp_image_server import (
    COMPANION_FMT_RAW_LUMA,
    COMPANION_MSG_DETECT_IMAGE_CHUNK,
    parse_packet,
    save_capture,
)

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore


HEX_LINE_RE = re.compile(r"^COMPANION_HEX([0-9a-fA-F]+)\s*$")
TRIGGERS = (
    b"Companion image pending",
    b"Companion image received",
    b"Companion reassembly complete",
)


def parse_dump_text(text: str) -> list[bytes]:
    """Split `att_companion dump` output into wire frames, one per COMPANION_WIRE line."""
    wires: list[bytes] = []
    hex_parts: list[str] | None = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("COMPANION_WIRE"):
            if hex_parts:
                wires.append(bytes.fromhex("".join(hex_parts)))
            hex_parts = []
            continue
        m = HEX_LINE_RE.match(line)
        if m and hex_parts is not None:
            hex_parts.append(m.group(1))
    if hex_parts:
        wires.append(bytes.fromhex("".join(hex_parts)))
    return wires


def assemble(wires: list[bytes]) -> dict | None:
    """Decode wire frames and join chunked payloads into one thumbnail packet."""
    pkts = []
    for wire in wires:
        pkt = parse_packet(wire)
        if pkt is None:
            print(f"Invalid AXF1 wire ({len(wire)} B)", file=sys.stderr)
            return None
        pkts.append(pkt)
    if not pkts:
        return None
    if pkts[0]["msg_type"] != COMPANION_MSG_DETECT_IMAGE_CHUNK:
        return pkts[0]

    total = pkts[0]["image_fmt"]
    by_index = {p["detect_count"]: p["image"] for p in pkts}
    if sorted(by_index) != list(range(total)):
        print(f"Missing chunks: have {sorted(by_index)} of {total}", file=sys.stderr)
        return None
    pkt = dict(pkts[0])
    pkt["image"] = b"".join(by_index[i] for i in range(total))
    pkt["image_len"] = len(pkt["image"])
    pkt["image_fmt"] = COMPANION_FMT_RAW_LUMA
    pkt["detect_count"] = total
    return pkt


def fetch_dump(ser, timeout_s: float = 5.0) -> dict | None:
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
    wires = parse_dump_text(text)
    if not wires:
        print(text, file=sys.stderr)
        return None

    return assemble(wires)


def show_luma(pkt: dict, out_dir: Path | None) -> None:
    w, h = pkt["thumb_w"], pkt["thumb_h"]
    img_bytes = pkt["image"]
    print(
        f"frame={pkt['frame_id']} score={pkt['top_score_mille']/1000:.3f} "
        f"thumb={w}x{h} bytes={len(img_bytes)}"
    )

    if out_dir is not None:
        path = save_capture(out_dir, pkt, ("serial", 0), chunked=pkt["detect_count"] > 1)
        print(f"Saved {path}")

    if Image is None:
        print("Install Pillow to pop up a window: pip install pillow", file=sys.stderr)
        return

    im = Image.frombytes("L", (w, h), img_bytes)
    im = im.resize((w * 16, h * 16), Image.NEAREST)
    im.show(title=f"frame {pkt['frame_id']}")


def watch_loop(ser, out_dir: Path | None) -> None:
    print("Watching logs; auto-dump on each received companion frame (Ctrl+C to quit)",
          flush=True)
    tail = b""

    while True:
        data = ser.read(ser.in_waiting or 1)
        if not data:
            time.sleep(0.05)
            continue
        sys.stdout.buffer.write(data)
        sys.stdout.flush()
        tail = (tail + data)[-512:]
        if any(t in tail for t in TRIGGERS):
            time.sleep(0.1)
            pkt = fetch_dump(ser)
            tail = b""
            if pkt is None:
                print("\n--- dump failed ---\n", flush=True)
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

    try:
        import serial
    except ImportError:
        print("Install pyserial: pip install pyserial", file=sys.stderr)
        raise

    with serial.Serial(args.port, args.baud, timeout=0.1) as ser:
        if args.watch:
            watch_loop(ser, args.out)
            return 0

        pkt = fetch_dump(ser)
        if pkt is None:
            return 1
        show_luma(pkt, args.out)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
