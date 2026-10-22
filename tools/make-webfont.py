#!/usr/bin/env python3
"""Turn Kilobyte's console font into a web font for the website: every pixel
of the 8x16 bitmap becomes a square, so the site shows exactly the letters,
lines and blocks of Kilobyte's screen. At font-size 16px (or 32px, 48px...)
the pixels land on whole screen pixels.

Input:  rootfs/usr/share/consolefonts/Kilobyte-VGA16.psf.gz (PSF 1 or 2,
        with its Unicode table)
Output: site/fonts/kilobyte-vga16.woff2 and .ttf
Run:    python3 tools/make-webfont.py   (needs fontTools and brotli)

The font keeps the licence of the console font: GPL 2 or later (Debian's
console-setup fonts, see tools/data/README).
"""
import gzip
import os
import struct

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "rootfs", "usr", "share", "consolefonts", "Kilobyte-VGA16.psf.gz")
OUT = os.path.join(HERE, "..", "site", "fonts")
PX = 64                 # font units per pixel: 16 rows = 1024 units per em
BASELINE = 12           # rows above the baseline (VGA: 12 up, 4 down)


def read_psf(path):
    data = gzip.open(path).read()
    if data[:2] == b"\x36\x04":                               # PSF 1
        mode, height = data[2], data[3]
        count, width, size, start = (512 if mode & 1 else 256), 8, height, 4
        glyphs = [data[start + i * size:start + (i + 1) * size] for i in range(count)]
        table, pos, uni = {}, start + count * size, {}
        if mode & 2:
            for g in range(count):
                while True:
                    (u,) = struct.unpack_from("<H", data, pos)
                    pos += 2
                    if u == 0xFFFF:
                        break
                    if u == 0xFFFE:                           # a sequence: skip to the end
                        while struct.unpack_from("<H", data, pos)[0] != 0xFFFF:
                            pos += 2
                        continue
                    uni.setdefault(u, g)
        return glyphs, width, height, uni
    magic, version, hsize, flags, count, size, height, width = struct.unpack_from("<8I", data)
    assert magic == 0x864AB572, "not a PSF font"
    glyphs = [data[hsize + i * size:hsize + (i + 1) * size] for i in range(count)]
    uni, pos = {}, hsize + count * size
    if flags & 1:
        for g in range(count):
            end = data.index(b"\xff", pos)
            entry = data[pos:end]
            pos = end + 1
            single = entry.split(b"\xfe")[0]                 # sequences after 0xFE are skipped
            for ch in single.decode("utf-8", "replace"):
                uni.setdefault(ord(ch), g)
    return glyphs, width, height, uni


def outline(bitmap, width, height):
    """The glyph as rectangles: each row's runs of set pixels."""
    pen = TTGlyphPen(None)
    row_bytes = (width + 7) // 8
    for y in range(height):
        row = bitmap[y * row_bytes:(y + 1) * row_bytes]
        bits = [(row[x // 8] >> (7 - x % 8)) & 1 for x in range(width)]
        x = 0
        while x < width:
            if not bits[x]:
                x += 1
                continue
            x0 = x
            while x < width and bits[x]:
                x += 1
            top, bottom = (BASELINE - y) * PX, (BASELINE - y - 1) * PX
            pen.moveTo((x0 * PX, bottom))                     # clockwise: an outer contour
            pen.lineTo((x0 * PX, top))
            pen.lineTo((x * PX, top))
            pen.lineTo((x * PX, bottom))
            pen.closePath()
    return pen.glyph()


def main():
    glyphs, width, height, uni = read_psf(SRC)
    names, cmap, outlines, metrics = [".notdef"], {}, {}, {}
    empty = TTGlyphPen(None).glyph()
    outlines[".notdef"] = empty
    metrics[".notdef"] = (width * PX, 0)
    for code, g in sorted(uni.items()):
        if code < 0x20 or 0xD800 <= code <= 0xDFFF:
            continue
        name = "g%04d" % g
        if name not in outlines:
            names.append(name)
            outlines[name] = outline(glyphs[g], width, height)
            metrics[name] = (width * PX, 0)
        cmap[code] = name
    fb = FontBuilder(height * PX, isTTF=True)
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(outlines)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=BASELINE * PX, descent=-(height - BASELINE) * PX)
    fb.setupNameTable({"familyName": "Kilobyte VGA", "styleName": "Regular",
                       "fullName": "Kilobyte VGA", "psName": "KilobyteVGA-Regular",
                       "uniqueFontIdentifier": "Kilobyte VGA Regular",
                       "copyright": "Debian console-setup authors; Kilobyte contributors. GNU GPL 2 or later.",
                       "licenseDescription": "GNU General Public License, version 2 or later"})
    fb.setupOS2(sTypoAscender=BASELINE * PX, sTypoDescender=-(height - BASELINE) * PX, sTypoLineGap=0,
                usWinAscent=BASELINE * PX, usWinDescent=(height - BASELINE) * PX,
                xAvgCharWidth=width * PX)
    fb.font["OS/2"].panose.bProportion = 9                    # monospaced
    fb.setupPost(isFixedPitch=1)
    os.makedirs(OUT, exist_ok=True)
    ttf = os.path.join(OUT, "kilobyte-vga16.ttf")
    fb.save(ttf)
    fb.font.flavor = "woff2"
    fb.save(os.path.join(OUT, "kilobyte-vga16.woff2"))
    print("%d characters, %d glyphs -> %s" % (len(cmap), len(names), OUT))


if __name__ == "__main__":
    main()
