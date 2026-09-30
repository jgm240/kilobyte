#!/usr/bin/env python3
"""Generate Kilobyte's pixel fonts: tiny console fonts for block video.

The video player draws with libcaca, which picks for every character cell a
foreground colour, a background colour and a character from the ramp
" .:;t%SX@8" whose "ink" mixes the two. In these fonts each ramp character is
an ordered-dither pattern with exactly that much ink, and the Unicode block
elements (U+2580-U+259F) are drawn geometrically. Loaded with setfont at
1x2, 2x4 or 4x8 pixels per cell, the text console becomes a grid of coloured
dots.

Output: rootfs/usr/share/kilobyte/fonts/kb-pixels-WxH.psf (PSF2 with a
Unicode table). Run after editing:  python3 tools/make-fonts.py
"""
import gzip
import os
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "rootfs", "usr", "share", "kilobyte", "fonts")
SIZES = [(1, 2), (2, 4), (4, 8)]

# libcaca's ASCII ramp, from empty to full.
RAMP = " .:;t%SX@8"

# 8x8 Bayer matrix: the order in which a cell's pixels light up.
BAYER8 = [
    [0, 32, 8, 40, 2, 34, 10, 42],
    [48, 16, 56, 24, 50, 18, 58, 26],
    [12, 44, 4, 36, 14, 46, 6, 38],
    [60, 28, 52, 20, 62, 30, 54, 22],
    [3, 35, 11, 43, 1, 33, 9, 41],
    [51, 19, 59, 27, 49, 17, 57, 25],
    [15, 47, 7, 39, 13, 45, 5, 37],
    [63, 31, 55, 23, 61, 29, 53, 21],
]


def vga_coverage():
    """Ink coverage (0..1) of each ASCII character in the VGA font, if the
    reference font is at hand; otherwise a rough guess."""
    path = os.path.join(HERE, "data", "FullGreek-VGA16.psf.gz")
    cov = {}
    try:
        data = gzip.open(path).read()
        magic, ver, hdr, flags, n, size, h, w = struct.unpack("<8I", data[:32])
        assert magic == 0x864AB572
        glyphs = data[hdr : hdr + n * size]
        table = data[hdr + n * size :]
        # Map code points to glyph indexes from the Unicode table.
        idx, i = 0, 0
        cp_to_glyph = {}
        while idx < n and i < len(table):
            j = table.index(b"\xff", i)
            entry = table[i:j]
            for ch in entry.split(b"\xfe")[0].decode("utf-8", "ignore"):
                cp_to_glyph[ord(ch)] = idx
            idx, i = idx + 1, j + 1
        for c in range(0x20, 0x7F):
            g = cp_to_glyph.get(c)
            if g is None:
                continue
            bits = glyphs[g * size : (g + 1) * size]
            cov[chr(c)] = sum(bin(b).count("1") for b in bits) / (w * h)
    except (OSError, AssertionError, ValueError):
        pass
    if not cov:
        cov = {chr(c): 0.3 for c in range(0x21, 0x7F)}
        cov[" "] = 0.0
    top = max(cov.values()) or 1
    return {c: v / top for c, v in cov.items()}


def dither(w, h, level):
    """A w x h cell with `level` (0..1) of its pixels lit, spread evenly."""
    order = sorted(((BAYER8[y % 8][x % 8], y, x) for y in range(h) for x in range(w)))
    lit = round(level * w * h)
    cell = [[0] * w for _ in range(h)]
    for _, y, x in order[:lit]:
        cell[y][x] = 1
    return cell


def rect(w, h, x0, y0, x1, y1):
    """Lit rectangle given in fractions of the cell."""
    cell = [[0] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            cx, cy = (x + 0.5) / w, (y + 0.5) / h
            if x0 <= cx < x1 and y0 <= cy < y1:
                cell[y][x] = 1
    return cell


def union(*cells):
    return [[max(p) for p in zip(*rows)] for rows in zip(*cells)]


def blocks(w, h):
    """U+2580..U+259F drawn to the cell size."""
    q = {  # quadrants
        "ul": rect(w, h, 0, 0, 0.5, 0.5), "ur": rect(w, h, 0.5, 0, 1, 0.5),
        "ll": rect(w, h, 0, 0.5, 0.5, 1), "lr": rect(w, h, 0.5, 0.5, 1, 1),
    }
    g = {0x2580: rect(w, h, 0, 0, 1, 0.5)}
    for i in range(1, 9):  # lower eighths ▁..█
        g[0x2580 + i] = rect(w, h, 0, 1 - i / 8, 1, 1)
    for i in range(1, 8):  # left eighths ▉..▏
        g[0x2590 - i] = rect(w, h, 0, 0, i / 8, 1)
    g[0x2590] = rect(w, h, 0.5, 0, 1, 1)
    g[0x2591], g[0x2592], g[0x2593] = dither(w, h, 0.25), dither(w, h, 0.5), dither(w, h, 0.75)
    g[0x2594] = rect(w, h, 0, 0, 1, 1 / 8)
    g[0x2595] = rect(w, h, 7 / 8, 0, 1, 1)
    combos = {
        0x2596: ["ll"], 0x2597: ["lr"], 0x2598: ["ul"], 0x2599: ["ul", "ll", "lr"],
        0x259A: ["ul", "lr"], 0x259B: ["ul", "ur", "ll"], 0x259C: ["ul", "ur", "lr"],
        0x259D: ["ur"], 0x259E: ["ur", "ll"], 0x259F: ["ur", "ll", "lr"],
    }
    for cp, parts in combos.items():
        g[cp] = union(*(q[p] for p in parts))
    return g


def build(w, h, coverage):
    glyphs = []  # (bitmap, [code points])
    glyphs.append((dither(w, h, 0.5), [0xFFFD]))  # anything unknown: grey
    # ASCII sits at its own numbers: the console clears the screen with glyph
    # 32 whatever the Unicode table says, and that glyph must be empty.
    while len(glyphs) < 0x20:
        glyphs.append(([[0] * w for _ in range(h)], []))
    for c in range(0x20, 0x7F):
        ch = chr(c)
        if ch in RAMP:
            level = RAMP.index(ch) / (len(RAMP) - 1)
        else:
            level = coverage.get(ch, 0.3)
        glyphs.append((dither(w, h, level), [c]))
    for cp, cell in sorted(blocks(w, h).items()):
        extra = [0x25A0] if cp == 0x2588 else []  # ■ looks like a full cell
        glyphs.append((cell, [cp] + extra))
    while len(glyphs) < 256:  # the console wants 256 or 512 glyphs
        glyphs.append(([[0] * w for _ in range(h)], []))

    row_bytes = (w + 7) // 8
    size = row_bytes * h
    out = bytearray(struct.pack("<8I", 0x864AB572, 0, 32, 1, len(glyphs), size, h, w))
    for cell, _ in glyphs:
        for row in cell:
            v = 0
            for x, bit in enumerate(row):
                v |= bit << (row_bytes * 8 - 1 - x)
            out += v.to_bytes(row_bytes, "big")
    for _, cps in glyphs:
        out += "".join(chr(c) for c in cps).encode("utf-8") + b"\xff"
    return bytes(out)


def main():
    os.makedirs(OUT, exist_ok=True)
    coverage = vga_coverage()
    for w, h in SIZES:
        path = os.path.join(OUT, f"kb-pixels-{w}x{h}.psf")
        with open(path, "wb") as f:
            f.write(build(w, h, coverage))
        print("wrote", os.path.relpath(path))
    # Show the ramp at 4x8 as a check.
    for level_char in RAMP:
        cell = dither(4, 8, RAMP.index(level_char) / (len(RAMP) - 1))
        print(repr(level_char), " ".join("".join("#" if b else "." for b in row) for row in cell))


if __name__ == "__main__":
    main()
