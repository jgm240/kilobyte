#!/usr/bin/env python3
"""Build Kilobyte's console fonts: the IBM VGA font with every DOS graphics
character AND the Western European letters.

Debian's console-setup ships the VGA font in character sets that each lack
something: FullGreek has all the blocks, lines and symbols but misses letters
such as å ì ò Ø; Lat15 has those letters but no half blocks. FullGreek has
121 unused glyph slots, so the letters from Lat15 are copied into them (or,
where a glyph looks exactly like one FullGreek already has, only its Unicode
code point is added).

Input:  tools/data/{FullGreek,Lat15}-VGA16.psf.gz and -VGA32x16.psf.gz, from
        Debian's console-setup-linux package (GPL-2+).
Output: rootfs/usr/share/consolefonts/Kilobyte-VGA16.psf.gz, -VGA32x16.psf.gz
Run:    python3 tools/make-console-font.py
"""
import gzip
import os
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "..", "rootfs", "usr", "share", "consolefonts")


def read_psf(path):
    d = gzip.open(path).read()
    if d[:2] == b"\x36\x04":                      # PSF1
        mode, h = d[2], d[3]
        n = 512 if mode & 1 else 256
        w, size, pos = 8, h, 4
        glyphs = [d[pos + i * size: pos + (i + 1) * size] for i in range(n)]
        table, i, maps = d[pos + n * size:], 0, []
        for _ in range(n):
            cps = []
            while True:
                v = struct.unpack("<H", table[i:i + 2])[0]
                i += 2
                if v == 0xFFFF:
                    break
                if v != 0xFFFE:
                    cps.append(v)
            maps.append(cps)
        return w, h, glyphs, maps
    _, _, hdr, _, n, size, h, w = struct.unpack("<8I", d[:32])
    glyphs = [d[hdr + i * size: hdr + (i + 1) * size] for i in range(n)]
    table, i, maps = d[hdr + n * size:], 0, []
    for _ in range(n):
        j = table.index(b"\xff", i)
        entry = table[i:j].split(b"\xfe")[0]
        maps.append([ord(c) for c in entry.decode("utf-8", "ignore")])
        i = j + 1
    return w, h, glyphs, maps


def write_psf2(path, w, h, glyphs, maps):
    size = ((w + 7) // 8) * h
    out = bytearray(struct.pack("<8I", 0x864AB572, 0, 32, 1, len(glyphs), size, h, w))
    for g in glyphs:
        out += g
    for cps in maps:
        out += "".join(chr(c) for c in cps).encode("utf-8") + b"\xff"
    # A fixed time stamp keeps rebuilt files identical.
    with open(path, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as f:
        f.write(bytes(out))


def merge(size_name):
    w, h, glyphs, maps = read_psf(os.path.join(DATA, f"FullGreek-{size_name}.psf.gz"))
    lw, lh, lglyphs, lmaps = read_psf(os.path.join(DATA, f"Lat15-{size_name}.psf.gz"))
    assert (w, h) == (lw, lh), "fonts differ in size"
    have = {c for m in maps for c in m}
    by_bitmap = {g: i for i, g in enumerate(glyphs) if maps[i]}
    free = [i for i, m in enumerate(maps) if not m]
    added = shared = 0
    for g, cps in zip(lglyphs, lmaps):
        new = [c for c in cps if c not in have]
        if not new:
            continue
        if g in by_bitmap:                         # same picture: just map it
            maps[by_bitmap[g]] += new
            shared += len(new)
        elif free:
            slot = free.pop(0)
            glyphs[slot], maps[slot] = g, new
            by_bitmap[g] = slot
            added += 1
        else:
            print("  out of room for", "".join(chr(c) for c in new))
            continue
        have.update(new)
    path = os.path.join(OUT, f"Kilobyte-{size_name}.psf.gz")
    write_psf2(path, w, h, glyphs, maps)
    print(f"wrote {os.path.relpath(path)}: {added} glyphs added, {shared} characters shared, {len(free)} slots left")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    merge("VGA16")
    merge("VGA32x16")
