#!/usr/bin/python3
"""Mines: clear the field without stepping on a mine.

Arrows move, Space or Enter uncovers, F puts a flag, N new game,
1/2/3 choose the size, Q quits. The mouse works too: left click uncovers,
right click flags. Uncovering a number whose flags are all placed clears
its neighbours.
"""
import random
import sys
import time

sys.path.insert(0, "/usr/lib/kilobyte/py")
import kbui  # noqa: E402
from kbui import BLACK, BLUE, DARKGREY, GREEN, LIGHTGREY, RED, WHITE, YELLOW  # noqa: E402
import curses  # noqa: E402

SIZES = {"1": (9, 9, 10), "2": (16, 16, 40), "3": (30, 16, 99)}
NUMBER_COLOURS = [None, kbui.LIGHTBLUE, GREEN, kbui.LIGHTRED, BLUE, RED, kbui.CYAN, BLACK, DARKGREY]


class Game:
    def __init__(self, w, h, mines):
        self.w, self.h, self.mines = w, h, mines
        self.mine = [[False] * w for _ in range(h)]
        self.open = [[False] * w for _ in range(h)]
        self.flag = [[False] * w for _ in range(h)]
        self.placed = False
        self.over = self.won = False
        self.start = None
        self.end = None
        self.cx, self.cy = w // 2, h // 2

    def neighbours(self, x, y):
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if (dx or dy) and 0 <= x + dx < self.w and 0 <= y + dy < self.h:
                    yield x + dx, y + dy

    def count(self, x, y):
        return sum(self.mine[ny][nx] for nx, ny in self.neighbours(x, y))

    def place(self, sx, sy):
        # The first cell and its neighbours are always safe.
        safe = {(sx, sy), *self.neighbours(sx, sy)}
        cells = [(x, y) for y in range(self.h) for x in range(self.w) if (x, y) not in safe]
        for x, y in random.sample(cells, self.mines):
            self.mine[y][x] = True
        self.placed = True
        self.start = time.time()

    def uncover(self, x, y):
        if self.over or self.flag[y][x]:
            return
        if not self.placed:
            self.place(x, y)
        if self.open[y][x]:
            # Chord: a number with all its flags placed opens its neighbours.
            if self.count(x, y) == sum(self.flag[ny][nx] for nx, ny in self.neighbours(x, y)):
                for nx, ny in self.neighbours(x, y):
                    if not self.open[ny][nx] and not self.flag[ny][nx]:
                        self.uncover(nx, ny)
            return
        stack = [(x, y)]
        while stack:
            x, y = stack.pop()
            if self.open[y][x] or self.flag[y][x]:
                continue
            self.open[y][x] = True
            if self.mine[y][x]:
                self.over, self.end = True, time.time()
                return
            if self.count(x, y) == 0:
                stack += [n for n in self.neighbours(x, y) if not self.open[n[1]][n[0]]]
        closed = sum(not self.open[y][x] for y in range(self.h) for x in range(self.w))
        if closed == self.mines:
            self.over = self.won = True
            self.end = time.time()

    def toggle_flag(self, x, y):
        if not self.over and not self.open[y][x]:
            self.flag[y][x] = not self.flag[y][x]

    def seconds(self):
        if not self.start:
            return 0
        return int((self.end or time.time()) - self.start)


def draw(s, g):
    s.fill(LIGHTGREY, BLUE)
    H, W = s.size()
    bw, bh = g.w * 2 + 2, g.h + 2
    ox, oy = (W - bw) // 2, max(3, (H - bh) // 2)
    flags = sum(map(sum, g.flag))
    face = "☺" if not g.over else ("☻" if g.won else "×")
    iw = max(bw, 32)                       # the counter bar needs room
    ix = ox - (iw - bw) // 2
    s.box(oy - 3, ix, 3, iw, BLACK, LIGHTGREY)
    s.put(oy - 2, ix + 2, f"Mines {g.mines - flags:3d}", RED, LIGHTGREY)
    s.put(oy - 2, ix + iw // 2 - 1, f"[{face}]", BLACK, LIGHTGREY)
    s.put(oy - 2, ix + iw - 11, f"Time {g.seconds():3d}", RED, LIGHTGREY)
    s.box(oy, ox, bh, bw, WHITE, LIGHTGREY, double=True)
    for y in range(g.h):
        for x in range(g.w):
            cur = (x, y) == (g.cx, g.cy)
            if g.open[y][x]:
                if g.mine[y][x]:
                    text, fg, bg = "* ", BLACK, RED
                else:
                    n = g.count(x, y)
                    text, fg, bg = (f"{n} " if n else "· "), (NUMBER_COLOURS[n] if n else DARKGREY), LIGHTGREY
            elif g.over and g.mine[y][x]:
                text, fg, bg = ("¶ " if g.flag[y][x] else "* "), BLACK, DARKGREY
            elif g.flag[y][x]:
                text, fg, bg = "¶ ", RED, DARKGREY
            else:
                text, fg, bg = "▒▒", LIGHTGREY, DARKGREY
            if cur and not g.over:
                fg, bg = YELLOW, BLUE
            s.put(oy + 1 + y, ox + 1 + x * 2, text, fg, bg)
    if g.over:
        msg = " Cleared! N plays again " if g.won else " Boom. N plays again "
        s.put(oy + bh, ox + (bw - len(msg)) // 2, msg, WHITE, GREEN if g.won else RED)
    s.put(H - 1, 0, " Arrows move  Space uncover  F flag  N new  1/2/3 size  Q quit ".ljust(W), BLACK, kbui.CYAN)
    return ox + 1, oy + 1


def main(s):
    size = "1"
    g = Game(*SIZES[size])
    s.scr.timeout(500)          # redraw the clock twice a second
    while True:
        bx, by = draw(s, g)
        s.scr.refresh()
        k = s.scr.getch()
        if k in (ord("q"), ord("Q"), 27):
            return
        if k in (ord("n"), ord("N")):
            g = Game(*SIZES[size])
        elif k in (ord("1"), ord("2"), ord("3")):
            size = chr(k)
            g = Game(*SIZES[size])
        elif k == curses.KEY_LEFT:
            g.cx = (g.cx - 1) % g.w
        elif k == curses.KEY_RIGHT:
            g.cx = (g.cx + 1) % g.w
        elif k == curses.KEY_UP:
            g.cy = (g.cy - 1) % g.h
        elif k == curses.KEY_DOWN:
            g.cy = (g.cy + 1) % g.h
        elif k in (ord(" "), 10, 13):
            g.uncover(g.cx, g.cy)
        elif k in (ord("f"), ord("F")):
            g.toggle_flag(g.cx, g.cy)
        elif k == curses.KEY_MOUSE:
            try:
                _, mx, my, _, b = curses.getmouse()
            except curses.error:
                continue
            x, y = (mx - bx) // 2, my - by
            if 0 <= x < g.w and 0 <= y < g.h:
                g.cx, g.cy = x, y
                if b & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED):
                    g.uncover(x, y)
                elif b & (curses.BUTTON3_CLICKED | curses.BUTTON3_PRESSED):
                    g.toggle_flag(x, y)


if __name__ == "__main__":
    kbui.run(main)
