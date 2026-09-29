#!/usr/bin/python3
"""Kilobyte Paint: pictures made of coloured half blocks.

Every character cell holds two square pixels. Draw with the mouse or the
keyboard; pictures are saved as PNG (one pixel per pixel) and can be
exported as ANSI art for BBSes.

    paint [FILE]
"""
import copy
import curses
import os
import sys

sys.path.insert(0, "/usr/lib/kilobyte/py")
import kbui  # noqa: E402
from kbui import BLACK, BLUE, CYAN, DARKGREY, LIGHTGREY, WHITE, YELLOW  # noqa: E402

TOOLS = [  # key, name
    ("p", "Pencil"), ("l", "Line"), ("b", "Box"), ("x", "Filled box"),
    ("c", "Ellipse"), ("o", "Filled ellipse"), ("f", "Fill"), ("e", "Eraser"), ("k", "Pick colour"),
]
TWO_POINT = {"l", "b", "x", "c", "o"}
HELP = ("Arrows move  Space draw  , . colour  P L B X C O F E K tools  "
        "U undo  S save  ^O open  I import  A ANSI  N new  Q quit")


class Paint:
    def __init__(self, s, path):
        self.s = s
        H, W = s.size()
        self.cv = kbui.Canvas(s, 1, 2, W - 2, H - 4)
        self.cv.clear(WHITE)
        self.fg, self.bg = BLACK, WHITE
        self.tool = "p"
        self.cx, self.cy = self.cv.w // 2, self.cv.h // 2
        self.anchor = None
        self.undo = []
        self.path = path
        self.modified = False
        self.blink = False
        self.message = "Welcome to Paint.  " + HELP
        if path and os.path.exists(path):
            self.load(path)

    # --- editing --------------------------------------------------------
    def remember(self):
        self.undo.append(copy.deepcopy(self.cv.px))
        del self.undo[:-50]
        self.modified = True

    def restore(self):
        if self.undo:
            self.cv.px = self.undo.pop()
            self.cv.dirty = {(x, y) for y in range(self.cv.rows) for x in range(self.cv.cols)}

    def shape(self, x0, y0, x1, y1, colour):
        t, cv = self.tool, self.cv
        if t == "l":
            cv.line(x0, y0, x1, y1, colour)
        elif t in ("b", "x"):
            cv.rect(x0, y0, x1, y1, colour, filled=(t == "x"))
        elif t in ("c", "o"):
            cv.ellipse(x0, y0, x1, y1, colour, filled=(t == "o"))

    def apply(self, x, y, colour=None):
        colour = self.fg if colour is None else colour
        t = self.tool
        if t == "k":
            self.fg = self.cv.get(x, y)
            return
        if t in TWO_POINT:
            if self.anchor is None:
                self.anchor = (x, y)
                self.message = "Now move to the other end and press Space (Esc cancels)."
                return
            self.remember()
            self.shape(*self.anchor, x, y, colour)
            self.anchor = None
            self.message = HELP
            return
        self.remember()
        if t == "f":
            self.cv.flood(x, y, colour)
        elif t == "e":
            self.cv.set(x, y, self.bg)
        else:
            self.cv.set(x, y, colour)

    # --- files ----------------------------------------------------------
    def ask(self, prompt, default=""):
        H, W = self.s.size()
        self.s.put(H - 1, 0, (prompt + " ").ljust(W), BLACK, CYAN)
        curses.echo()
        curses.curs_set(1)
        self.s.scr.move(H - 1, len(prompt) + 1)
        try:
            text = self.s.scr.getstr(H - 1, len(prompt) + 1, 200).decode("utf-8", "replace").strip()
        except curses.error:
            text = ""
        finally:
            curses.noecho()
            curses.curs_set(0)
        return text or default

    def ask_path(self, prompt, ext):
        folder = os.path.expanduser("~/Pictures")
        os.makedirs(folder, exist_ok=True)
        default = self.path or os.path.join(folder, "picture" + ext)
        name = self.ask(f"{prompt} [{default}]:", default)
        name = os.path.expanduser(name)
        if not os.path.isabs(name):
            name = os.path.join(folder, name)
        return name

    def load(self, path, fit=False):
        try:
            rows = kbui.load_picture(path, self.cv.w, self.cv.h)
        except Exception as e:  # noqa: BLE001 - show any failure to the user
            self.message = f"Could not open {path}: {e}"
            return
        self.remember()
        for y, row in enumerate(rows):
            for x, c in enumerate(row):
                self.cv.set(x, y, c)
        if not fit:
            self.path = path
        self.modified = fit
        self.message = f"Opened {os.path.basename(path)}"

    def save(self):
        path = self.ask_path("Save as PNG", ".png")
        if not path.lower().endswith(".png"):
            path += ".png"
        kbui.save_png(path, self.cv.px)
        self.path, self.modified = path, False
        self.message = f"Saved {path}"

    def export_ansi(self):
        path = self.ask_path("Export ANSI art", ".ans")
        if not path.lower().endswith(".ans"):
            path = os.path.splitext(path)[0] + ".ans"
        out = bytearray()
        ansi = [0, 4, 2, 6, 1, 5, 3, 7]         # console order -> ANSI order
        for cy in range(self.cv.rows):
            for cx in range(self.cv.cols):
                ch, fg, bg = self.cv.cell(cx, cy)
                code = {" ": 0x20, kbui.UPPER: 0xDF, kbui.LOWER: 0xDC, kbui.FULL: 0xDB}[ch]
                bold = "1;" if fg >= 8 else "0;"
                out += f"\x1b[{bold}{30 + ansi[fg & 7]};{40 + ansi[bg & 7]}m".encode() + bytes([code])
            out += b"\x1b[0m\r\n"
        with open(path, "wb") as f:
            f.write(bytes(out))
        self.message = f"Exported {path}"

    # --- screen ---------------------------------------------------------
    def draw(self):
        s, cv = self.s, self.cv
        H, W = s.size()
        name = os.path.basename(self.path) if self.path else "untitled"
        s.put(0, 0, f" Kilobyte Paint - {name}{' *' if self.modified else ''}".ljust(W), BLACK, LIGHTGREY)
        # Palette and tools on the second line.
        x = 1
        for c in range(16):
            mark = "▼" if c == self.fg else ("▲" if c == self.bg else " ")
            s.put(1, x, mark, YELLOW, BLUE)
            s.put(1, x + 1, "██", c, BLUE)
            x += 3
        tools = "  ".join(f"{k.upper()}:{n}" if k != self.tool else f"[{n}]" for k, n in TOOLS)
        s.put(1, x, (" " + tools).ljust(W - x)[: W - x], WHITE, BLUE)
        # Preview a shape between the anchor and the cursor.
        saved = None
        if self.anchor and self.tool in TWO_POINT:
            saved = copy.deepcopy(cv.px)
            self.shape(*self.anchor, self.cx, self.cy, self.fg)
        cv.flush()
        # The cursor pixel blinks; the other half of its cell stays as it is.
        cell_y = self.cy // 2
        top, bottom = cv.px[2 * cell_y][self.cx], cv.px[2 * cell_y + 1][self.cx]
        mark = YELLOW if self.fg != YELLOW else LIGHTGREY
        if self.blink:
            if self.cy % 2 == 0:
                s.put(cv.y0 + cell_y, cv.x0 + self.cx, kbui.UPPER, mark, bottom & 7)
            else:
                s.put(cv.y0 + cell_y, cv.x0 + self.cx, kbui.LOWER, mark, top & 7)
        else:
            cv.dirty.add((self.cx, cell_y))
        if saved is not None:
            cv.px = saved
            cv.dirty = {(x, y) for y in range(cv.rows) for x in range(cv.cols)}
        s.put(H - 1, 0, f" {self.cx},{self.cy}  {self.message}".ljust(W)[:W], BLACK, CYAN)

    def run(self):
        s = self.s
        s.fill(LIGHTGREY, BLUE)
        self.cv.flush(everything=True)
        s.scr.timeout(450)
        drawing = False
        while True:
            self.blink = not self.blink
            self.draw()
            s.scr.refresh()
            k = s.scr.getch()
            if k == -1:
                continue
            self.blink = True
            ch = chr(k).lower() if 0 < k < 256 else ""
            if k == curses.KEY_LEFT:
                self.cx = max(0, self.cx - 1)
            elif k == curses.KEY_RIGHT:
                self.cx = min(self.cv.w - 1, self.cx + 1)
            elif k == curses.KEY_UP:
                self.cy = max(0, self.cy - 1)
            elif k == curses.KEY_DOWN:
                self.cy = min(self.cv.h - 1, self.cy + 1)
            elif k in (ord(" "), 10, 13):
                self.apply(self.cx, self.cy)
            elif k == 27:
                self.anchor, self.message = None, HELP
            elif ch == ",":
                self.fg = (self.fg - 1) % 16
            elif ch == ".":
                self.fg = (self.fg + 1) % 16
            elif ch in dict(TOOLS):
                self.tool, self.anchor = ch, None
                self.message = f"{dict(TOOLS)[ch]}.  " + HELP
            elif ch == "u":
                self.restore()
            elif ch == "s":
                self.save()
            elif ch == "a":
                self.export_ansi()
            elif k == 15:                                  # Ctrl-O
                self.load(self.ask_path("Open picture", ".png"))
            elif ch == "i":
                self.load(self.ask_path("Import any picture (fitted to the page)", ".jpg"), fit=True)
            elif ch == "n":
                self.remember()
                self.cv.clear(WHITE)
                self.path = None
            elif ch == "q":
                if self.modified and self.ask("Picture not saved. Quit anyway? (y/n)", "n").lower() != "y":
                    continue
                return
            elif k == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, b = curses.getmouse()
                except curses.error:
                    continue
                if my == 1 and 1 <= mx < 49:          # palette
                    c = (mx - 1) // 3
                    if b & (curses.BUTTON3_PRESSED | curses.BUTTON3_CLICKED):
                        self.bg = c
                    else:
                        self.fg = c
                    continue
                x, y = mx - self.cv.x0, my - self.cv.y0
                if not (0 <= x < self.cv.w and 0 <= y < self.cv.rows):
                    continue
                self.cx, self.cy = x, y * 2 + (self.cy % 2)
                right = b & (curses.BUTTON3_PRESSED | curses.BUTTON3_CLICKED)
                colour = self.bg if right else self.fg
                if b & (curses.BUTTON1_PRESSED | curses.BUTTON3_PRESSED):
                    drawing = True
                    self.apply(self.cx, self.cy, colour)
                elif b & (curses.BUTTON1_RELEASED | curses.BUTTON3_RELEASED):
                    if drawing and self.tool in TWO_POINT and self.anchor:
                        self.apply(self.cx, self.cy, colour)
                    drawing = False
                elif b & (curses.BUTTON1_CLICKED | curses.BUTTON3_CLICKED):
                    self.apply(self.cx, self.cy, colour)
                elif drawing and self.tool in ("p", "e"):
                    self.cv.set(self.cx, self.cy, self.bg if self.tool == "e" else colour)


if __name__ == "__main__":
    kbui.run(lambda s: Paint(s, sys.argv[1] if len(sys.argv) > 1 else None).run())
