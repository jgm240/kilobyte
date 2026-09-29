#!/usr/bin/python3
"""Solitaire (Klondike).

Left/Right choose a pile, Up/Down choose how many cards to take from a
column, Space or Enter picks up and puts down, D draws from the stock,
F sends the chosen card to the foundations, A sends every card that can go,
U undoes, 3 switches between drawing one and three cards, N new game,
Q quits. Mouse: click a pile to pick up, click another to put down.
"""
import copy
import random
import sys
import time

sys.path.insert(0, "/usr/lib/kilobyte/py")
import kbui  # noqa: E402
from kbui import BLACK, BLUE, GREEN, LIGHTBLUE, LIGHTGREY, LIGHTRED, WHITE, YELLOW  # noqa: E402
import curses  # noqa: E402

SUITS = "♠♥♦♣"
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
RED_SUITS = "♥♦"
CW = 7          # card width
GAP = 2


class Card:
    def __init__(self, rank, suit):
        self.rank, self.suit, self.up = rank, suit, False

    @property
    def red(self):
        return self.suit in RED_SUITS

    def label(self):
        return f"{RANKS[self.rank]}{self.suit}"


class Game:
    def __init__(self, draw=1):
        deck = [Card(r, s) for s in SUITS for r in range(13)]
        random.shuffle(deck)
        self.tableau = []
        for i in range(7):
            col = [deck.pop() for _ in range(i + 1)]
            col[-1].up = True
            self.tableau.append(col)
        self.stock = deck
        self.waste = []
        self.found = [[] for _ in range(4)]
        self.draw = draw
        self.moves = 0
        self.start = time.time()
        self.history = []

    def snapshot(self):
        self.history.append(copy.deepcopy((self.tableau, self.stock, self.waste, self.found, self.moves)))
        del self.history[:-100]

    def undo(self):
        if self.history:
            self.tableau, self.stock, self.waste, self.found, self.moves = self.history.pop()

    def deal(self):
        self.snapshot()
        if not self.stock:
            self.stock = [c for c in reversed(self.waste)]
            for c in self.stock:
                c.up = False
            self.waste = []
        else:
            for _ in range(min(self.draw, len(self.stock))):
                c = self.stock.pop()
                c.up = True
                self.waste.append(c)
        self.moves += 1

    # piles: 0 stock, 1 waste, 2-5 foundations, 6-12 tableau
    def pile(self, p):
        if p == 1:
            return self.waste
        if 2 <= p <= 5:
            return self.found[p - 2]
        if p >= 6:
            return self.tableau[p - 6]
        return self.stock

    def fits_found(self, card, f):
        if not f:
            return card.rank == 0
        return f[-1].suit == card.suit and f[-1].rank + 1 == card.rank

    def fits_tableau(self, card, col):
        if not col:
            return card.rank == 12
        top = col[-1]
        return top.up and top.red != card.red and top.rank == card.rank + 1

    def move(self, src, n, dst):
        """Move n cards from pile src to pile dst if the rules allow it."""
        s, d = self.pile(src), self.pile(dst)
        if src == dst or n < 1 or len(s) < n or dst in (0, 1):
            return False
        cards = s[-n:]
        if not cards[0].up:
            return False
        if 2 <= dst <= 5:
            if n != 1 or not self.fits_found(cards[0], d):
                return False
        elif not self.fits_tableau(cards[0], d):
            return False
        self.snapshot()
        del s[-n:]
        d.extend(cards)
        if s and src >= 6:
            s[-1].up = True
        self.moves += 1
        return True

    def to_foundation(self, src):
        s = self.pile(src)
        if not s or not s[-1].up:
            return False
        for i in range(4):
            if self.fits_found(s[-1], self.found[i]):
                return self.move(src, 1, 2 + i)
        return False

    def auto(self):
        while any(self.to_foundation(p) for p in [1] + list(range(6, 13))):
            pass

    def won(self):
        return all(len(f) == 13 for f in self.found)


def card_lines(card, height):
    """The lines of a card: face up, face down or an empty place."""
    if card is None:
        return [("┌" + "─" * (CW - 2) + "┐", GREEN), *[("│" + " " * (CW - 2) + "│", GREEN)] * (height - 2),
                ("└" + "─" * (CW - 2) + "┘", GREEN)]
    if not card.up:
        return [("▒" * CW, BLUE)] * height
    colour = LIGHTRED if card.red else BLACK
    top = card.label().ljust(CW - 1) + " "
    rows = [(" " + top[: CW - 1], colour)]
    rows += [(" " * CW, colour)] * (height - 2)
    rows += [(" " * (CW - 1 - len(card.label())) + card.label() + " ", colour)]
    return rows[:height]


def draw(s, g, cursor, depth, held):
    s.fill(LIGHTGREY, GREEN)
    H, W = s.size()
    x0 = max(0, (W - 7 * (CW + GAP)) // 2)
    full = 4 if H >= 30 else 3
    cells = {}

    def px(i):
        return x0 + i * (CW + GAP)

    def paint(y, x, card, height, hl=False):
        for i, (text, fg) in enumerate(card_lines(card, height)):
            bg = LIGHTGREY if card is not None and card.up else (BLUE if card is not None else GREEN)
            if card is not None and not card.up:
                fg, bg = LIGHTBLUE, BLUE
            if card is None:
                fg, bg = LIGHTGREY, GREEN
            if hl:
                bg = BLUE if card is None or card.up else bg
                fg = YELLOW if card is None or not card.up else WHITE
            s.put(y + i, x, text, fg, bg)

    # Top row: stock, waste, foundations.
    top = 1
    paint(top, px(0), g.stock[-1] if g.stock else None, full, cursor == 0)
    cells[0] = (top, px(0))
    shown = g.waste[-g.draw:] if g.waste else []
    for i, c in enumerate(shown):
        paint(top, px(1) + i * 2, c, full, cursor == 1 and i == len(shown) - 1)
    if not shown:
        paint(top, px(1), None, full, cursor == 1)
    cells[1] = (top, px(1))
    for i in range(4):
        f = g.found[i]
        paint(top, px(3 + i), f[-1] if f else None, full, cursor == 2 + i)
        if not f:
            s.put(top + 1, px(3 + i) + 3, SUITS[i], LIGHTGREY, GREEN)
        cells[2 + i] = (top, px(3 + i))

    # Tableau: covered cards show one line, the last card is full.
    ty = top + full + 1
    for i, col in enumerate(g.tableau):
        p = 6 + i
        cells[p] = (ty, px(i))
        if not col:
            paint(ty, px(i), None, full, cursor == p)
            continue
        for j, c in enumerate(col):
            last = j == len(col) - 1
            hl = cursor == p and j >= len(col) - depth
            paint(ty + j, px(i), c, full if last else 1, hl)

    held_text = f"Holding {held[1]} card(s) - choose where to put them" if held else ""
    elapsed = int(time.time() - g.start)
    s.put(0, x0, f"Moves {g.moves}   Time {elapsed // 60}:{elapsed % 60:02d}   Draw {g.draw}   {held_text}"[: W - x0],
          WHITE, GREEN)
    if g.won():
        msg = " You won! Press N for a new game "
        s.put(H // 2, (W - len(msg)) // 2, msg, BLACK, YELLOW)
    s.put(H - 1, 0, " ←→ pile  ↑↓ cards  Space take/put  D draw  F to foundation  A all  U undo  N new  Q quit".ljust(W)[:W],
          BLACK, kbui.CYAN)
    return cells, ty


def main(s):
    g = Game()
    cursor, depth, held = 6, 1, None
    s.scr.timeout(1000)
    while True:
        cells, ty = draw(s, g, cursor, depth, held)
        s.scr.refresh()
        k = s.scr.getch()
        pile = g.pile(cursor)
        if k in (ord("q"), ord("Q")):
            return
        if k == 27:
            held = None
        elif k in (ord("n"), ord("N")):
            g, held, depth = Game(g.draw), None, 1
        elif k == ord("3"):
            g.draw = 3 if g.draw == 1 else 1
        elif k in (ord("u"), ord("U")):
            g.undo()
            held = None
        elif k in (ord("d"), ord("D")):
            g.deal()
        elif k in (ord("a"), ord("A")):
            g.auto()
        elif k in (ord("f"), ord("F")):
            g.to_foundation(cursor)
        elif k == curses.KEY_LEFT:
            cursor = (cursor - 1) % 13
            depth = 1
        elif k == curses.KEY_RIGHT:
            cursor = (cursor + 1) % 13
            depth = 1
        elif k == curses.KEY_UP:
            face_up = sum(c.up for c in pile)
            if cursor >= 6 and depth < face_up:
                depth += 1
            else:
                cursor = {6: 0, 7: 1, 8: 1, 9: 2, 10: 3, 11: 4, 12: 5}.get(cursor, cursor)
        elif k == curses.KEY_DOWN:
            if cursor >= 6 and depth > 1:
                depth -= 1
            elif cursor < 6:
                cursor = {0: 6, 1: 7, 2: 9, 3: 10, 4: 11, 5: 12}[cursor]
        elif k in (ord(" "), 10, 13) or k == curses.KEY_MOUSE:
            if k == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, _ = curses.getmouse()
                except curses.error:
                    continue
                hit = None
                for p, (y, x) in cells.items():
                    if x <= mx < x + CW + (4 if p == 1 else 0) and (y <= my < y + 4 if p < 6 else my >= y):
                        hit = p
                if hit is None:
                    continue
                cursor = hit
                if cursor >= 6:
                    col = g.pile(cursor)
                    # How many cards from the clicked one down to the end.
                    idx = min(my - ty, len(col) - 1)
                    depth = max(1, len(col) - idx) if col and col[idx].up else 1
            if cursor == 0:
                g.deal()
                held = None
            elif held:
                if not g.move(held[0], held[1], cursor):
                    curses.beep()
                held = None
            elif pile and pile[-1].up:
                held = (cursor, depth if cursor >= 6 else 1)
            depth = 1 if not held else depth


if __name__ == "__main__":
    kbui.run(main)
