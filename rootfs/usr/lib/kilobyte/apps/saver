#!/usr/bin/python3
"""Kilobyte screen saver: starfield, bouncing lines or flying floppies,
drawn in coloured half blocks. On the text console it switches to Kilobyte's
2x4 pixel font for a fine picture. Any key or mouse movement ends it.

    saver [starfield|lines|floppies|random]
"""
import curses
import math
import os
import random
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, "/usr/lib/kilobyte/py")
import kbui  # noqa: E402
from kbui import BLACK, BLUE, DARKGREY, LIGHTGREY, WHITE, YELLOW  # noqa: E402

MODES = ["starfield", "lines", "floppies"]


def starfield(cv):
    stars = [[random.uniform(-1, 1), random.uniform(-1, 1), random.uniform(0.05, 1)] for _ in range(260)]
    lit = []
    while True:
        for x, y in lit:
            cv.set(x, y, BLACK)
        lit = []
        for s in stars:
            s[2] -= 0.012
            if s[2] <= 0.02:
                s[:] = [random.uniform(-1, 1), random.uniform(-1, 1), 1.0]
            sx = int(cv.w / 2 + s[0] / s[2] * cv.w / 2)
            sy = int(cv.h / 2 + s[1] / s[2] * cv.h / 2)
            colour = WHITE if s[2] < 0.3 else LIGHTGREY if s[2] < 0.65 else DARKGREY
            cv.set(sx, sy, colour)
            lit.append((sx, sy))
            if s[2] < 0.15:          # close stars are bigger
                for dx, dy in ((1, 0), (0, 1), (1, 1)):
                    cv.set(sx + dx, sy + dy, colour)
                    lit.append((sx + dx, sy + dy))
        yield


def lines(cv):
    def shape():
        return [[random.uniform(0, cv.w), random.uniform(0, cv.h),
                 random.choice((-1, 1)) * random.uniform(0.6, 1.6),
                 random.choice((-1, 1)) * random.uniform(0.4, 1.2)] for _ in range(4)]

    shapes = [shape(), shape()]
    colours = [kbui.LIGHTMAGENTA, kbui.LIGHTCYAN]
    trails = [[], []]
    tick = 0
    while True:
        tick += 1
        for i, pts in enumerate(shapes):
            for p in pts:
                p[0] += p[2]
                p[1] += p[3]
                if not 0 <= p[0] < cv.w:
                    p[2] = -p[2]
                if not 0 <= p[1] < cv.h:
                    p[3] = -p[3]
            poly = [(int(p[0]), int(p[1])) for p in pts]
            trails[i].append(poly)
            if len(trails[i]) > 7:        # rub out the oldest copy
                old = trails[i].pop(0)
                for a, b in zip(old, old[1:] + old[:1]):
                    cv.line(*a, *b, BLACK)
            if tick % 200 == 0:
                colours[i] = random.choice([c for c in range(9, 16) if c != colours[i]])
            for poly_ in trails[i]:
                for a, b in zip(poly_, poly_[1:] + poly_[:1]):
                    cv.line(*a, *b, colours[i])
        yield


FLOPPY = [  # 3.5" floppy disk, 12 x 12 pixels. B body, S shutter, L label
    "BBBBBBBBBBB.",
    "BBSSSSSSBBBB",
    "BBSSBSSSBBBB",
    "BBSSBSSSBBBB",
    "BBSSSSSSBBBB",
    "BBBBBBBBBBBB",
    "BLLLLLLLLLLB",
    "BLLLLLLLLLLB",
    "BLLLLLLLLLLB",
    "BLLLLLLLLLLB",
    "BLLLLLLLLLLB",
    "BBBBBBBBBBBB",
]
FLOPPY_COLOURS = {"B": BLUE, "S": LIGHTGREY, "L": WHITE}
WINGS = [["W.........W", ".W.......W."], ["...........", "WW.......WW"]]


def floppies(cv):
    fl = [[random.uniform(0, cv.w), random.uniform(-cv.h, cv.h), random.uniform(0.5, 1.0)] for _ in range(9)]
    drawn = []
    tick = 0
    while True:
        tick += 1
        for x, y in drawn:
            cv.set(x, y, BLACK)
        drawn = []
        for f in sorted(fl, key=lambda f: f[2]):
            f[0] -= 1.2 * f[2]
            f[1] += 0.6 * f[2]
            if f[0] < -14 or f[1] > cv.h + 2:
                f[:] = [random.uniform(cv.w * 0.3, cv.w + 20), random.uniform(-30, -12), random.uniform(0.5, 1.0)]
            ox, oy = int(f[0]), int(f[1])
            wing = WINGS[(tick // 6 + int(f[2] * 10)) % 2]
            for dy, row in enumerate(wing):
                for dx, ch in enumerate(row):
                    if ch == "W":
                        cv.set(ox + dx, oy - 2 + dy, YELLOW)
                        drawn.append((ox + dx, oy - 2 + dy))
            for dy, row in enumerate(FLOPPY):
                for dx, ch in enumerate(row):
                    if ch in FLOPPY_COLOURS:
                        cv.set(ox + dx, oy + dy, FLOPPY_COLOURS[ch])
                        drawn.append((ox + dx, oy + dy))
        yield


def on_console():
    try:
        return os.environ.get("TERM") == "linux" and os.ttyname(0).startswith("/dev/tty")
    except OSError:
        return False


def main(scr, mode):
    scr.scr.nodelay(True)
    scr.fill()
    cv = kbui.Canvas(scr)
    frames = {"starfield": starfield, "lines": lines, "floppies": floppies}[mode](cv)
    started = time.time()
    while True:
        next(frames)
        cv.flush()
        scr.scr.refresh()
        time.sleep(0.04)
        key = scr.scr.getch()
        # A key, a click or a moved mouse ends it (after a short grace time).
        if key != -1 and time.time() - started > 0.5:
            return


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "random"
    if mode not in MODES:
        mode = random.choice(MODES)
    saved = None
    if on_console():
        saved = tempfile.mktemp(prefix="kb-font.")
        if subprocess.run(["setfont", "-O", saved], capture_output=True).returncode == 0:
            for size in ("2x4", "4x8"):
                if subprocess.run(["setfont", f"{kbui.KB_SHARE}/fonts/kb-pixels-{size}.psf"],
                                  capture_output=True).returncode == 0:
                    break
        else:
            saved = None
    try:
        kbui.run(lambda s: main(s, mode))
    finally:
        if saved:
            subprocess.run(["setfont", saved], capture_output=True)
            os.unlink(saved)
