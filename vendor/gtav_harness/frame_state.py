#!/usr/bin/env python3
"""Classify a frame dumped by APS5_DUMP_FRAMES, or compare two frames.

Usage:
  frame_state.py classify <frame.bmp>      prints: <state> mean=.. grey=.. dark=.. sat=..
  frame_state.py differ <a.bmp> <b.bmp>    exit 0 when the frames differ, 1 when they match

States, from frames of GTA V's start-up screens (thresholds measured on the desktop):
  black        loading screen, mean brightness below 3
  title        mostly black with a colourless logo (dark >= 0.8, sat < 2)
  calibration  the flat grey Display Calibration screen (grey >= 0.6)
  colour       landing page, tabs, settings, gameplay (sat >= 10)
  other        anything else

Frames are uncompressed 32-bit BMPs (BITMAPINFOHEADER, top-down or bottom-up); this reads
them without third-party modules and samples a 96x54 grid.
"""
import struct
import sys

GRID_W, GRID_H = 96, 54


def sample(path):
    data = open(path, "rb").read()
    if data[:2] != b"BM":
        raise SystemExit(f"{path}: not a BMP")
    offset = struct.unpack_from("<I", data, 10)[0]
    width, height, _, bpp = struct.unpack_from("<iiHH", data, 18)
    if bpp != 32:
        raise SystemExit(f"{path}: {bpp} bits per pixel, expected 32")
    rows = abs(height)
    stride = width * 4
    out = []
    for gy in range(GRID_H):
        y = gy * rows // GRID_H
        row = y if height < 0 else rows - 1 - y
        base = offset + row * stride
        for gx in range(GRID_W):
            x = gx * width // GRID_W
            b, g, r = data[base + x * 4], data[base + x * 4 + 1], data[base + x * 4 + 2]
            out.append((r, g, b))
    return out


def stats(px):
    n = len(px)
    mean = sum(r + g + b for r, g, b in px) / (3 * n)
    grey = sum(1 for r, g, b in px if abs(r - g) < 6 and abs(g - b) < 6 and 55 < r < 95) / n
    dark = sum(1 for r, g, b in px if r + g + b < 30) / n
    sat = sum(max(p) - min(p) for p in px) / n
    return mean, grey, dark, sat


def classify(px):
    mean, grey, dark, sat = stats(px)
    if mean < 3:
        state = "black"
    elif grey >= 0.6:
        state = "calibration"
    elif dark >= 0.8 and sat < 2:
        state = "title"
    elif sat >= 10:
        state = "colour"
    else:
        state = "other"
    return state, mean, grey, dark, sat


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "classify":
        state, mean, grey, dark, sat = classify(sample(sys.argv[2]))
        print(f"{state} mean={mean:.1f} grey={grey:.2f} dark={dark:.2f} sat={sat:.1f}")
    elif len(sys.argv) == 4 and sys.argv[1] == "differ":
        a, b = sample(sys.argv[2]), sample(sys.argv[3])
        changed = sum(1 for p, q in zip(a, b) if sum(abs(x - y) for x, y in zip(p, q)) > 24)
        sys.exit(0 if changed / len(a) > 0.02 else 1)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
