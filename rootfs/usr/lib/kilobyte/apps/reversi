#!/usr/bin/python3
"""Reversi: you play black against the computer.

Arrows move, Space or Enter places a stone, H shows where you can play,
N new game, 1/2/3 computer strength, Q quits. Clicking a square works too.
Stones you enclose in a line between two of yours turn to your colour.
"""
import random
import sys

sys.path.insert(0, "/usr/lib/kilobyte/py")
import kbui  # noqa: E402
from kbui import BLACK, BLUE, GREEN, LIGHTGREEN, LIGHTGREY, WHITE, YELLOW  # noqa: E402
import curses  # noqa: E402

N = 8
EMPTY, DARK, LIGHT = 0, 1, 2
DIRS = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
# Corners are gold, the squares next to them are dangerous.
WEIGHTS = [
    [100, -20, 10, 5, 5, 10, -20, 100],
    [-20, -50, -2, -2, -2, -2, -50, -20],
    [10, -2, 1, 1, 1, 1, -2, 10],
    [5, -2, 1, 0, 0, 1, -2, 5],
    [5, -2, 1, 0, 0, 1, -2, 5],
    [10, -2, 1, 1, 1, 1, -2, 10],
    [-20, -50, -2, -2, -2, -2, -50, -20],
    [100, -20, 10, 5, 5, 10, -20, 100],
]


def new_board():
    b = [[EMPTY] * N for _ in range(N)]
    b[3][3] = b[4][4] = LIGHT
    b[3][4] = b[4][3] = DARK
    return b


def flips(b, x, y, who):
    if b[y][x] != EMPTY:
        return []
    other = LIGHT if who == DARK else DARK
    out = []
    for dx, dy in DIRS:
        run, cx, cy = [], x + dx, y + dy
        while 0 <= cx < N and 0 <= cy < N and b[cy][cx] == other:
            run.append((cx, cy))
            cx, cy = cx + dx, cy + dy
        if run and 0 <= cx < N and 0 <= cy < N and b[cy][cx] == who:
            out += run
    return out


def moves(b, who):
    return {(x, y): f for y in range(N) for x in range(N) if (f := flips(b, x, y, who))}


def play(b, x, y, who):
    for fx, fy in flips(b, x, y, who):
        b[fy][fx] = who
    b[y][x] = who


def score(b, who):
    return sum(row.count(who) for row in b)


def evaluate(b):
    """Position value for the computer (light)."""
    v = 0
    for y in range(N):
        for x in range(N):
            if b[y][x] == LIGHT:
                v += WEIGHTS[y][x]
            elif b[y][x] == DARK:
                v -= WEIGHTS[y][x]
    return v + 3 * (len(moves(b, LIGHT)) - len(moves(b, DARK)))


def search(b, depth, who, alpha, beta):
    ms = moves(b, who)
    other = LIGHT if who == DARK else DARK
    if depth == 0 or (not ms and not moves(b, other)):
        return evaluate(b), None
    if not ms:
        return search(b, depth - 1, other, alpha, beta)[0], None
    best = None
    for (x, y) in sorted(ms, key=lambda m: -WEIGHTS[m[1]][m[0]]):
        nb = [row[:] for row in b]
        play(nb, x, y, who)
        v, _ = search(nb, depth - 1, other, alpha, beta)
        if who == LIGHT:
            if best is None or v > alpha:
                alpha, best = max(alpha, v), (x, y)
        else:
            if best is None or v < beta:
                beta, best = min(beta, v), (x, y)
        if alpha >= beta:
            break
    return (alpha if who == LIGHT else beta), best


def computer_move(b, level):
    ms = moves(b, LIGHT)
    if not ms:
        return None
    if level == 1:
        return max(ms, key=lambda m: len(ms[m]) + random.random())
    return search(b, 2 if level == 2 else 4, LIGHT, -10**9, 10**9)[1] or random.choice(list(ms))


def draw(s, b, cx, cy, hints, msg, level):
    s.fill(LIGHTGREY, kbui.BLUE)
    H, W = s.size()
    cw, ch = (6, 3) if H >= 30 else (5, 2)     # smaller squares on 80x25
    bw, bh = N * cw + 2, N * ch + 2
    ox, oy = (W - bw) // 2, max(1, (H - bh - 2) // 2)
    s.box(oy, ox, bh, bw, LIGHTGREEN, GREEN, double=True)
    legal = moves(b, DARK) if hints else {}
    for y in range(N):
        for x in range(N):
            px, py = ox + 1 + x * cw, oy + 1 + y * ch
            bg = GREEN
            cur = (x, y) == (cx, cy)
            for i in range(ch):
                s.put(py + i, px, " " * cw, LIGHTGREY, BLUE if cur else bg)
            stone = b[y][x]
            sy, sx = py + (ch - 2) // 2, px + (cw - 4) // 2
            if stone:
                colour = BLACK if stone == DARK else WHITE
                s.put(sy, sx, "▄██▄", colour, BLUE if cur else bg)
                s.put(sy + 1, sx, "▀██▀", colour, BLUE if cur else bg)
            elif (x, y) in legal:
                s.put(py + ch // 2, sx + 1, "··", YELLOW, BLUE if cur else bg)
    dark, light = score(b, DARK), score(b, LIGHT)
    s.put(oy - 1 if oy > 0 else 0, ox, f" You (black) {dark:2d}   Computer (white) {light:2d}   Strength {level} ", WHITE, kbui.BLUE)
    if msg:
        s.put(oy + bh, ox + (bw - len(msg)) // 2, msg, BLACK, YELLOW)
    s.put(H - 1, 0, " Arrows move  Space play  H hints  N new game  1/2/3 strength  Q quit ".ljust(W), BLACK, kbui.CYAN)
    return ox + 1, oy + 1, cw, ch


def main(s):
    b, cx, cy, hints, level, msg = new_board(), 2, 3, True, 2, " Your move "
    while True:
        bx, by, cw, ch = draw(s, b, cx, cy, hints, msg, level)
        s.scr.refresh()
        k = s.scr.getch()
        target = None
        if k in (ord("q"), ord("Q"), 27):
            return
        if k in (ord("n"), ord("N")):
            b, msg = new_board(), " Your move "
        elif k in (ord("h"), ord("H")):
            hints = not hints
        elif k in (ord("1"), ord("2"), ord("3")):
            level = k - ord("0")
        elif k == curses.KEY_LEFT:
            cx = (cx - 1) % N
        elif k == curses.KEY_RIGHT:
            cx = (cx + 1) % N
        elif k == curses.KEY_UP:
            cy = (cy - 1) % N
        elif k == curses.KEY_DOWN:
            cy = (cy + 1) % N
        elif k in (ord(" "), 10, 13):
            target = (cx, cy)
        elif k == curses.KEY_MOUSE:
            try:
                _, mx, my, _, _ = curses.getmouse()
            except curses.error:
                continue
            x, y = (mx - bx) // cw, (my - by) // ch
            if 0 <= x < N and 0 <= y < N:
                cx, cy, target = x, y, (x, y)
        if not target:
            continue
        if not moves(b, DARK):
            msg = " You cannot move - the computer plays "
        elif target not in moves(b, DARK):
            curses.beep()
            continue
        else:
            play(b, *target, DARK)
        # The computer answers, and keeps playing while you cannot move.
        while True:
            draw(s, b, cx, cy, hints, " Computer is thinking... ", level)
            s.scr.refresh()
            m = computer_move(b, level)
            if m:
                play(b, *m, LIGHT)
            if moves(b, DARK) or (not moves(b, DARK) and not moves(b, LIGHT)):
                break
            if not m:
                break
        if not moves(b, DARK) and not moves(b, LIGHT):
            d, l = score(b, DARK), score(b, LIGHT)
            msg = f" You win {d}:{l}! " if d > l else f" The computer wins {l}:{d} " if l > d else " A draw! "
            msg += " N plays again "
        else:
            msg = " Your move "


if __name__ == "__main__":
    kbui.run(main)
