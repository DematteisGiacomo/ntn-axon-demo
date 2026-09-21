#!/usr/bin/env python3
# Copyright (c) 2026 Nordic Semiconductor ASA
# SPDX-License-Identifier: LicenseRef-Nordic-5-Clause
"""Convert AXF1 luma .raw captures from udp_image_server to PNG (and optional preview)."""

from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Install Pillow: pip install pillow", file=sys.stderr)
    raise

DIM_RE = re.compile(r"_(\d+)x(\d+)\.raw$", re.IGNORECASE)


def dimensions_for_raw(path: Path, data: bytes) -> tuple[int, int]:
    m = DIM_RE.search(path.name)
    if m:
        w, h = int(m.group(1)), int(m.group(2))
        if w * h != len(data):
            print(
                f"warning: {path.name} says {w}x{h} ({w * h} B) but file is {len(data)} B",
                file=sys.stderr,
            )
        return w, h

    n = len(data)
    side = int(math.isqrt(n))
    if side * side == n:
        print(f"warning: guessing {side}x{side} from {n} bytes (no _WxH in name)", file=sys.stderr)
        return side, side

    raise SystemExit(
        f"Cannot infer size for {path} ({n} bytes). "
        "Expected filename like *_16x16.raw or pass --width/--height."
    )


def load_meta_txt(raw_path: Path) -> str | None:
    stem = raw_path.name
    if stem.endswith(".raw"):
        stem = stem[: -len(".raw")]
    meta = raw_path.with_name(stem + ".txt")
    if meta.is_file():
        return meta.read_text(encoding="utf-8")
    return None


def raw_to_png(
    raw_path: Path,
    png_path: Path,
    *,
    width: int | None,
    height: int | None,
    scale: int,
) -> None:
    data = raw_path.read_bytes()
    if width is not None and height is not None:
        w, h = width, height
        if w * h != len(data):
            raise SystemExit(f"{raw_path}: expected {w * h} bytes, got {len(data)}")
    else:
        w, h = dimensions_for_raw(raw_path, data)

    im = Image.frombytes("L", (w, h), data)
    if scale > 1:
        im = im.resize((w * scale, h * scale), Image.NEAREST)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    im.save(png_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "raw",
        nargs="*",
        type=Path,
        help=".raw file(s); omit with --latest to use newest in --dir",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=Path("captures"),
        help="Capture directory for --latest (default: captures)",
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Convert the most recent *_*.raw in --dir",
    )
    parser.add_argument("--width", type=int, default=None, help="Override width (with --height)")
    parser.add_argument("--height", type=int, default=None, help="Override height (with --width)")
    parser.add_argument(
        "--scale",
        type=int,
        default=16,
        help="Nearest-neighbor upscale factor for viewing (default: 16)",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Open a preview window (needs display)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="PNG path (default: same name as .raw with .png; --latest only)",
    )
    args = parser.parse_args()

    if args.width is not None or args.height is not None:
        if args.width is None or args.height is None:
            parser.error("--width and --height must be used together")

    paths = list(args.raw)
    if args.latest:
        if paths:
            parser.error("Do not pass raw files with --latest")
        candidates = sorted(args.dir.glob("*_*x*.raw"), key=lambda p: p.stat().st_mtime)
        if not candidates:
            print(f"No *_WxH.raw files in {args.dir.resolve()}", file=sys.stderr)
            return 1
        paths = [candidates[-1]]

    if not paths:
        parser.error("Pass .raw file(s) or use --latest")

    for raw_path in paths:
        if not raw_path.is_file():
            print(f"Not found: {raw_path}", file=sys.stderr)
            return 1

        if args.out is not None and len(paths) > 1:
            parser.error("--out only allowed with a single input file or --latest")

        png_path = args.out if args.out is not None else raw_path.with_suffix(".png")

        raw_to_png(
            raw_path,
            png_path,
            width=args.width,
            height=args.height,
            scale=max(1, args.scale),
        )
        print(f"Wrote {png_path.resolve()}")

        meta = load_meta_txt(raw_path)
        if meta:
            print(meta.rstrip())

        if args.show:
            Image.open(png_path).show(title=raw_path.name)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
