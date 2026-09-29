"""Kilobyte's toolkit for real-time text programs (games, paint, screen
savers): colours, a half-block pixel canvas and small drawing helpers.

Everything is drawn with coloured characters. The Linux console has 16
foreground but only 8 background colours (bright colours are the "bold"
versions), so colour pairs are made of an 8-colour background and a
foreground that may be bright.
"""
import curses
import locale
import os
import subprocess
import sys

locale.setlocale(locale.LC_ALL, "")

# The 16 text colours, in console order.
BLACK, RED, GREEN, BROWN, BLUE, MAGENTA, CYAN, LIGHTGREY = range(8)
DARKGREY, LIGHTRED, LIGHTGREEN, YELLOW, LIGHTBLUE, LIGHTMAGENTA, LIGHTCYAN, WHITE = range(8, 16)

# Approximate RGB of the console colours, for converting pictures.
RGB = [
    (0, 0, 0), (170, 0, 0), (0, 170, 0), (170, 85, 0), (0, 0, 170), (170, 0, 170), (0, 170, 170), (170, 170, 170),
    (85, 85, 85), (255, 85, 85), (85, 255, 85), (255, 255, 85), (85, 85, 255), (255, 85, 255), (85, 255, 255), (255, 255, 255),
]

UPPER, LOWER, FULL = "▀", "▄", "█"
KB_SHARE = "/usr/share/kilobyte"


class Screen:
    """curses set up for 16 colours; attr(fg, bg) gives the attribute."""

    def __init__(self, stdscr):
        self.scr = stdscr
        curses.curs_set(0)
        curses.start_color()
        try:
            curses.use_default_colors()
        except curses.error:
            pass
        self.pairs = {}
        # Colours beyond 8 come from the bold attribute on 8-colour terminals.
        self.native16 = curses.COLORS >= 16 and os.environ.get("TERM") != "linux"
        stdscr.keypad(True)
        curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        curses.mouseinterval(0)

    def attr(self, fg, bg=BLACK):
        bg &= 7                                    # backgrounds: 8 colours only
        if self.native16:
            key = (fg, bg)
            bold = 0
        else:
            key = (fg & 7, bg)
            bold = curses.A_BOLD if fg >= 8 else 0
        if key not in self.pairs:
            n = len(self.pairs) + 1
            if n >= curses.COLOR_PAIRS:
                return bold
            curses.init_pair(n, key[0], key[1])
            self.pairs[key] = n
        return curses.color_pair(self.pairs[key]) | bold

    def size(self):
        return self.scr.getmaxyx()

    def put(self, y, x, text, fg=LIGHTGREY, bg=BLACK):
        h, w = self.scr.getmaxyx()
        if y < 0 or y >= h or x >= w:
            return
        if x < 0:
            text, x = text[-x:], 0
        text = text[: w - x]
        try:
            self.scr.addstr(y, x, text, self.attr(fg, bg))
        except curses.error:
            pass  # writing the very last cell of the screen raises

    def box(self, y, x, h, w, fg=LIGHTGREY, bg=BLACK, double=False, title=""):
        tl, tr, bl, br, hz, vt = ("╔", "╗", "╚", "╝", "═", "║") if double else ("┌", "┐", "└", "┘", "─", "│")
        self.put(y, x, tl + hz * (w - 2) + tr, fg, bg)
        for i in range(1, h - 1):
            self.put(y + i, x, vt, fg, bg)
            self.put(y + i, x + 1, " " * (w - 2), fg, bg)
            self.put(y + i, x + w - 1, vt, fg, bg)
        self.put(y + h - 1, x, bl + hz * (w - 2) + br, fg, bg)
        if title:
            self.put(y, x + (w - len(title) - 2) // 2, f" {title} ", fg, bg)

    def fill(self, fg=LIGHTGREY, bg=BLACK, ch=" "):
        h, w = self.scr.getmaxyx()
        for y in range(h):
            self.put(y, 0, ch * w, fg, bg)


class Canvas:
    """Pixels made of half blocks: every character cell shows two pixels,
    the upper one and the lower one, each in any of the 16 colours."""

    def __init__(self, screen, x0=0, y0=0, cols=None, rows=None):
        h, w = screen.size()
        self.s = screen
        self.x0, self.y0 = x0, y0
        self.cols = cols if cols is not None else w - x0
        self.rows = rows if rows is not None else h - y0
        self.w, self.h = self.cols, self.rows * 2
        self.px = [[BLACK] * self.w for _ in range(self.h)]
        self.dirty = set()

    def get(self, x, y):
        if 0 <= x < self.w and 0 <= y < self.h:
            return self.px[y][x]
        return None

    def set(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h and self.px[y][x] != c:
            self.px[y][x] = c
            self.dirty.add((x, y // 2))

    def clear(self, c=BLACK):
        for y in range(self.h):
            for x in range(self.w):
                self.set(x, y, c)

    def cell(self, cx, cy):
        top, bottom = self.px[2 * cy][cx], self.px[2 * cy + 1][cx]
        if top == bottom:
            if top < 8:
                return " ", LIGHTGREY, top
            return FULL, top, BLACK
        # The bright colour must be the foreground; the background has 8.
        if top >= 8 and bottom >= 8:
            return UPPER, top, bottom & 7
        if bottom >= 8:
            return LOWER, bottom, top
        return UPPER, top, bottom

    def flush(self, everything=False):
        cells = [(x, y) for y in range(self.rows) for x in range(self.cols)] if everything else self.dirty
        for cx, cy in cells:
            ch, fg, bg = self.cell(cx, cy)
            self.s.put(self.y0 + cy, self.x0 + cx, ch, fg, bg)
        self.dirty = set()

    def line(self, x0, y0, x1, y1, c):
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        while True:
            self.set(x0, y0, c)
            if x0 == x1 and y0 == y1:
                return
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def rect(self, x0, y0, x1, y1, c, filled=False):
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                if filled or x in (x0, x1) or y in (y0, y1):
                    self.set(x, y, c)

    def ellipse(self, x0, y0, x1, y1, c, filled=False):
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        rx, ry = (x1 - x0) / 2 + 0.5, (y1 - y0) / 2 + 0.5

        def inside(x, y):
            return ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0

        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                if not inside(x, y):
                    continue
                # Outline: inside, with at least one neighbour outside.
                edge = not all(inside(x + dx, y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
                if filled or edge:
                    self.set(x, y, c)

    def flood(self, x, y, c):
        old = self.get(x, y)
        if old is None or old == c:
            return
        stack = [(x, y)]
        while stack:
            x, y = stack.pop()
            if self.get(x, y) != old:
                continue
            self.set(x, y, c)
            stack += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]


def nearest(rgb):
    """The console colour closest to an (r, g, b) colour."""
    r, g, b = rgb
    return min(range(16), key=lambda i: (RGB[i][0] - r) ** 2 * 3 + (RGB[i][1] - g) ** 2 * 4 + (RGB[i][2] - b) ** 2 * 2)


def load_picture(path, w, h):
    """Any picture ffmpeg understands, scaled to w x h, as rows of colours."""
    raw = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", path, "-vf", f"scale={w}:{h}:flags=area",
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True).stdout
    rows = []
    for y in range(h):
        row = []
        for x in range(w):
            i = (y * w + x) * 3
            row.append(nearest(tuple(raw[i:i + 3])) if i + 3 <= len(raw) else BLACK)
        rows.append(row)
    return rows


def save_png(path, rows):
    """Write rows of console colours as a PNG (no extra libraries)."""
    import struct
    import zlib
    h, w = len(rows), len(rows[0])
    raw = b"".join(b"\x00" + bytes(v for c in row for v in RGB[c]) for row in rows)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(raw, 9)))
        f.write(chunk(b"IEND", b""))


def play_sound(name):
    """Play one of Kilobyte's sounds unless sounds are switched off."""
    conf = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "kilobyte")
    if os.path.exists(os.path.join(conf, "sounds-off")):
        return
    path = os.path.join(KB_SHARE, "sounds", name)
    if os.path.exists(path):
        subprocess.Popen(["aplay", "-q", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run(main):
    """Start a curses program; Ctrl-C ends it quietly."""
    os.environ.setdefault("ESCDELAY", "25")
    try:
        curses.wrapper(lambda stdscr: main(Screen(stdscr)))
    except KeyboardInterrupt:
        pass
    sys.exit(0)
