#!/usr/bin/python3
"""Picture viewer: a picture drawn with coloured half blocks, as large as
the window (or screen) allows, in the 16 console colours with dithering.

    view.py PICTURE

Keys: ← → the other pictures in the same folder, D dithering on and off,
q, Esc or Enter closes."""
import curses
import os
import subprocess
import sys

sys.path.insert(0, "/usr/lib/kilobyte/py")
import kbui  # noqa: E402
import deskbg  # noqa: E402
from kbui import BLACK, LIGHTGREY, WHITE  # noqa: E402

PICTURES = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff")


def load(path, w, h, dither):
    """The picture fitted into w x h cells (not stretched): rows of cells."""
    ph = h * 2
    raw = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", path, "-vf",
         f"scale={w}:{ph}:force_original_aspect_ratio=decrease:flags=area,"
         f"pad={w}:{ph}:(ow-iw)/2:(oh-ih)/2:black",
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True, timeout=60).stdout
    if len(raw) < w * ph * 3:
        raise ValueError("no picture")
    if dither:
        colours = deskbg.dither(raw, w, ph)
    else:
        colours = [[deskbg.nearest(*raw[(y * w + x) * 3:(y * w + x) * 3 + 3]) for x in range(w)] for y in range(ph)]
    return deskbg.half_blocks(colours)


def main(s, path):
    folder = os.path.dirname(os.path.abspath(path))
    try:
        files = sorted(f for f in os.listdir(folder) if f.lower().endswith(PICTURES))
    except OSError:
        files = []
    name = os.path.basename(path)
    if name not in files:
        files.append(name)
    i = files.index(name)
    dither = True
    shown = None
    s.scr.keypad(True)
    while True:
        h, w = s.size()
        key = (files[i], w, h, dither)
        if key != shown:
            shown = key
            s.fill(LIGHTGREY, BLACK)
            s.put(h - 1, 0, " Loading ... ".ljust(w - 1), BLACK, LIGHTGREY)
            s.scr.refresh()
            try:
                rows = load(os.path.join(folder, files[i]), w, h - 1, dither)
                for y, row in enumerate(rows):
                    x = 0
                    while x < len(row):                # runs of one colour in one go
                        ch, fg, bg = row[x]
                        end = x + 1
                        while end < len(row) and row[end][1:] == (fg, bg):
                            end += 1
                        s.put(y, x, "".join(c[0] for c in row[x:end]), fg, bg)
                        x = end
            except (OSError, subprocess.SubprocessError, ValueError):
                s.fill(LIGHTGREY, BLACK)
                s.put(h // 2, 2, "This picture cannot be shown.", WHITE, BLACK)
            bar = " %s   (%d of %d)   ← → other pictures   D dithering %s   q closes" % (
                files[i], i + 1, len(files), "off" if dither else "on")
            s.put(h - 1, 0, bar[:w - 1].ljust(w - 1), BLACK, LIGHTGREY)
            s.scr.refresh()
        k = s.scr.getch()
        if k in (ord("q"), ord("Q"), 27, 10, 13, 3):
            return
        if k in (curses.KEY_RIGHT, ord(" "), ord("n"), curses.KEY_NPAGE):
            i = (i + 1) % len(files)
        elif k in (curses.KEY_LEFT, ord("p"), curses.KEY_PPAGE, curses.KEY_BACKSPACE):
            i = (i - 1) % len(files)
        elif k in (ord("d"), ord("D")):
            dither = not dither


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: view.py PICTURE")
    kbui.run(lambda s: main(s, sys.argv[1]), mouse=False)
