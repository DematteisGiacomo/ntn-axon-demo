#!/usr/bin/env python3
# Copyright (c) 2026 Nordic Semiconductor ASA
# SPDX-License-Identifier: LicenseRef-Nordic-5-Clause
"""UDP server for AXF1 person-detect thumbnails from Iridium NTN demo."""

from __future__ import annotations

import argparse
import struct
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

COMPANION_MAGIC = 0x41584631
COMPANION_HEADER_SIZE = 20
COMPANION_CRC_SIZE = 4
COMPANION_WIRE_MAX = 2048
COMPANION_MAX_IMAGE = COMPANION_WIRE_MAX - COMPANION_HEADER_SIZE - COMPANION_CRC_SIZE
COMPANION_MSG_DETECT_IMAGE = 1
COMPANION_MSG_DETECT_IMAGE_CHUNK = 2
COMPANION_FMT_RAW_LUMA = 0
COMPANION_FMT_JPEG = 1

HEADER_FMT = "<IBBIBHHBHH"
HEADER_SIZE = struct.calcsize(HEADER_FMT)

REASM_TIMEOUT_SEC = 120


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

    if magic != COMPANION_MAGIC or version != 1:
        return None
    if msg_type not in (COMPANION_MSG_DETECT_IMAGE, COMPANION_MSG_DETECT_IMAGE_CHUNK):
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
        "image_len": image_len,
        "image_fmt": image_fmt,
        "thumb_w": thumb_w,
        "thumb_h": thumb_h,
        "msg_type": msg_type,
        "image": image,
    }


@dataclass
class Reassembly:
    frame_id: int
    chunk_total: int
    thumb_w: int
    thumb_h: int
    score_mille: int
    chunks: dict[int, bytes] = field(default_factory=dict)
    updated: float = field(default_factory=time.time)


def reasm_key(src: tuple[str, int], frame_id: int) -> tuple[str, int, int]:
    return (src[0], src[1], frame_id)


def try_finish_reassembly(
    pending: dict[tuple[str, int, int], Reassembly],
    out_dir: Path,
    src: tuple[str, int],
) -> Path | None:
    now = time.time()
    for key in list(pending.keys()):
        if now - pending[key].updated > REASM_TIMEOUT_SEC:
            job = pending[key]
            missing = [i + 1 for i in range(job.chunk_total) if i not in job.chunks]
            print(
                f"Reassembly timeout frame={job.frame_id} from {key[0]}:{key[1]} "
                f"missing chunk(s) {missing} (had {len(job.chunks)}/{job.chunk_total})",
                flush=True,
            )
            del pending[key]

    for key, job in list(pending.items()):
        if key[0] != src[0] or key[1] != src[1]:
            continue
        if len(job.chunks) != job.chunk_total:
            continue

        image = b"".join(job.chunks[i] for i in range(job.chunk_total))
        pkt = {
            "frame_id": job.frame_id,
            "detect_count": job.chunk_total,
            "top_score_mille": job.score_mille,
            "image_fmt": COMPANION_FMT_RAW_LUMA,
            "thumb_w": job.thumb_w,
            "thumb_h": job.thumb_h,
            "image": image,
        }
        del pending[key]
        return save_capture(out_dir, pkt, src, chunked=True)

    return None


def handle_chunk(
    pkt: dict,
    src: tuple[str, int],
    pending: dict[tuple[str, int, int], Reassembly],
    out_dir: Path,
) -> Path | None:
    idx = pkt["detect_count"]
    total = pkt["image_fmt"]
    key = reasm_key(src, pkt["frame_id"])

    if total < 2 or idx >= total:
        return None

    job = pending.get(key)
    if job is None or job.frame_id != pkt["frame_id"]:
        job = Reassembly(
            frame_id=pkt["frame_id"],
            chunk_total=total,
            thumb_w=pkt["thumb_w"],
            thumb_h=pkt["thumb_h"],
            score_mille=pkt["top_score_mille"],
        )
        pending[key] = job

    job.updated = time.time()
    job.chunks[idx] = pkt["image"]
    return try_finish_reassembly(pending, out_dir, src)


def save_capture(
    out_dir: Path, pkt: dict, src: tuple[str, int], *, chunked: bool = False
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    base = f"{ts}_frame{pkt['frame_id']}_score{pkt['top_score_mille']}"

    if pkt["image_fmt"] == COMPANION_FMT_JPEG and pkt["image"][:2] == b"\xff\xd8":
        path = out_dir / f"{base}.jpg"
        path.write_bytes(pkt["image"])
    elif pkt["image_fmt"] == COMPANION_FMT_RAW_LUMA:
        suffix = "_chunked" if chunked else ""
        path = out_dir / f"{base}{suffix}_{pkt['thumb_w']}x{pkt['thumb_h']}.raw"
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
        f"size={len(pkt['image'])}\n"
        f"chunked={chunked}\n",
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

    pending: dict[tuple[str, int, int], Reassembly] = {}

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))
    print(f"Listening UDP {args.host}:{args.port} -> {args.out.resolve()}", flush=True)

    while True:
        data, addr = sock.recvfrom(2048)
        pkt = parse_packet(data)
        if pkt is None:
            hint = ""
            if len(data) >= 6 and int.from_bytes(data[:4], "little") == COMPANION_MAGIC:
                hint = f" magic=AXF1 type={data[5]}"
            print(f"Invalid packet {len(data)} B from {addr}{hint}", flush=True)
            continue

        if pkt["msg_type"] == COMPANION_MSG_DETECT_IMAGE_CHUNK:
            path = handle_chunk(pkt, addr, pending, args.out)
            if path is None:
                idx = pkt["detect_count"]
                total = pkt["image_fmt"]
                key = reasm_key(addr, pkt["frame_id"])
                job = pending.get(key)
                have = sorted(job.chunks.keys()) if job else [idx]
                print(
                    f"Chunk {idx + 1}/{total} frame={pkt['frame_id']} "
                    f"({pkt['image_len']} B) from {addr[0]} "
                    f"(have {len(have)}/{total}: {[i + 1 for i in have]})",
                    flush=True,
                )
                continue
        else:
            path = save_capture(args.out, pkt, addr)

        raw_size = path.stat().st_size
        print(
            f"Saved {path.name} frame={pkt['frame_id']} "
            f"score={pkt.get('top_score_mille', 0)/1000:.3f} "
            f"{pkt.get('thumb_w', '?')}x{pkt.get('thumb_h', '?')} ({raw_size} B raw)",
            flush=True,
        )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
