"""The desktop of Kilobyte Windows: the wallpaper, the weather and news tiles
on it, and the status shown at the right of the menu bar.

The wallpaper is set in Settings > Wallpaper and kept in
~/.config/kilobyte/wallpaper as KEY=VALUE lines:

    style=pattern | text | picture
    pattern=classic            one of PATTERNS
    text=Kilobyte              any characters, repeated over the desktop
    picture=/path/to/picture   anything ffmpeg can read
    fg=lightgrey  bg=blue      two of COLOURS (not used by pictures)

Everything here is plain data (rows of (character, foreground, background)
cells), so it can be tried without a console; desk.py draws it.
"""
import os
import subprocess
import time

from kbui import BLACK, BLUE, LIGHTGREY, FULL, LOWER, UPPER, RGB

CONF = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "kilobyte")
LIB = "/usr/lib/kilobyte"

COLOURS = ["black", "red", "green", "brown", "blue", "magenta", "cyan", "lightgrey",
           "darkgrey", "lightred", "lightgreen", "yellow", "lightblue", "lightmagenta", "lightcyan", "white"]

# name: (what Settings calls it, the tile that is repeated: rows of characters)
PATTERNS = {
    "classic":  ("Classic (light dots)", ["░"]),
    "solid":    ("Plain colour", [" "]),
    "medium":   ("Medium dots", ["▒"]),
    "dense":    ("Dense dots", ["▓"]),
    "checker":  ("Checkerboard", ["██  ", "  ██"]),
    "stripes":  ("Stripes", ["▀"]),
    "columns":  ("Columns", ["▌"]),
    "diagonal": ("Diagonal lines", ["/   ", "   /", "  / ", " /  "]),
    "bricks":   ("Bricks", ["___|", "_|__"]),
    "grid":     ("Grid", ["┼───", "│   "]),
    "weave":    ("Weave", ["═╬", " ║"]),
    "waves":    ("Waves", ["≈"]),
    "diamonds": ("Diamonds", ["♦   ", "  ♦ "]),
    "cards":    ("Card suits", ["♠   ♥   ", "  ♦   ♣ "]),
    "stars":    ("Starry sky", None),
}


def read_conf(path=None):
    conf = {"style": "pattern", "pattern": "classic", "text": "Kilobyte ", "picture": "",
            "fg": "lightgrey", "bg": "blue"}
    try:
        with open(path or os.path.join(CONF, "wallpaper"), encoding="utf-8", errors="replace") as f:
            for line in f:
                key, sep, value = line.rstrip("\n").partition("=")
                if sep and key in conf:
                    conf[key] = value
    except OSError:
        pass
    return conf


def colour(name, default):
    return COLOURS.index(name) if name in COLOURS else default


def wallpaper(conf, w, h):
    """The desktop as h rows of w cells, each (character, fg, bg)."""
    fg, bg = colour(conf["fg"], LIGHTGREY), colour(conf["bg"], BLUE) & 7
    style = conf["style"]
    if style == "picture" and conf["picture"]:
        try:
            return picture(conf["picture"], w, h)
        except (OSError, subprocess.SubprocessError, ValueError):
            pass                                   # unreadable: the pattern instead
    if style == "text" and conf["text"]:
        text = conf["text"]
        return [[(text[(x + y * 3) % len(text)], fg, bg) for x in range(w)] for y in range(h)]
    tile = PATTERNS.get(conf["pattern"], PATTERNS["classic"])[1]
    if tile is None:                               # stars: the same sky every time
        rows = []
        for y in range(h):
            row = []
            for x in range(w):
                n = (x * 73856093 ^ y * 19349663) % 211
                row.append(("*" if n == 0 else "·" if n < 4 else " ", fg, bg))
            rows.append(row)
        return rows
    return [[(tile[y % len(tile)][x % len(tile[y % len(tile)])], fg, bg) for x in range(w)] for y in range(h)]


def nearest(r, g, b):
    best, dist = 0, 1 << 30
    for i, (cr, cg, cb) in enumerate(RGB):
        d = (cr - r) ** 2 * 3 + (cg - g) ** 2 * 4 + (cb - b) ** 2 * 2
        if d < dist:
            best, dist = i, d
    return best


def dither(raw, w, h):
    """RGB bytes -> h rows of w console colours, with Floyd-Steinberg error
    diffusion: 16 colours go a long way for photos that way."""
    px = [[[raw[(y * w + x) * 3 + c] for c in range(3)] for x in range(w)] for y in range(h)]
    out = []
    for y in range(h):
        row = []
        for x in range(w):
            r, g, b = (max(0, min(255, v)) for v in px[y][x])
            i = nearest(r, g, b)
            row.append(i)
            err = (r - RGB[i][0], g - RGB[i][1], b - RGB[i][2])
            for dx, dy, part in ((1, 0, 7), (-1, 1, 3), (0, 1, 5), (1, 1, 1)):
                if 0 <= x + dx < w and y + dy < h:
                    p = px[y + dy][x + dx]
                    for c in range(3):
                        p[c] += err[c] * part / 16
        out.append(row)
    return out


def half_blocks(colours):
    """Rows of pixel colours (two per character row) -> rows of cells."""
    rows = []
    for y in range(0, len(colours) - 1, 2):
        row = []
        for top, bottom in zip(colours[y], colours[y + 1]):
            if top == bottom:
                row.append((" ", LIGHTGREY, top) if top < 8 else (FULL, top, BLACK))
            elif top >= 8 and bottom >= 8:          # the background has 8 colours only
                row.append((UPPER, top, bottom & 7))
            elif bottom >= 8:
                row.append((LOWER, bottom, top))
            else:
                row.append((UPPER, top, bottom))
        rows.append(row)
    return rows


def picture(path, w, h):
    """A picture filling w x h cells (cropped, not stretched), in half blocks."""
    ph = h * 2
    raw = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", path,
         "-vf", f"scale={w}:{ph}:force_original_aspect_ratio=increase:flags=area,crop={w}:{ph}",
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True, timeout=30).stdout
    if len(raw) < w * ph * 3:
        raise ValueError("no picture")
    return half_blocks(dither(raw, w, ph))


# --- weather and news ------------------------------------------------------

def tiles():
    """[(title, [lines])] as saved by kb-tiles, empty when switched off."""
    if os.path.exists(os.path.join(CONF, "tiles-off")):
        return []
    out = []
    for name, title in (("weather", "Weather"), ("news", "News")):
        try:
            with open(os.path.join(CONF, "tiles", name), encoding="utf-8", errors="replace") as f:
                lines = [line.rstrip("\n") for line in f]
        except OSError:
            continue
        while lines and not lines[-1].strip():
            lines.pop()
        if lines:
            out.append((title, lines))
    return out


# --- status for the menu bar -------------------------------------------------

class Status:
    """Network, battery and update notice, asked from lib.sh every now and
    then without ever making the desktop wait for the answer."""

    def __init__(self, every=15):
        self.every = every
        self.network = self.battery = ""
        self.update = False
        self.proc = None
        self.next = 0
        self.tiles_next = 0

    def poll(self):
        now = time.time()
        if self.proc and self.proc.poll() is not None:
            try:
                out = self.proc.stdout.read().decode("utf-8", "replace").split("\n")
            except OSError:
                out = []
            self.proc = None
            out += [""] * 3
            self.network, self.battery, self.update = out[0].strip(), out[1].strip(), out[2].strip() == "update"
        if not self.proc and now >= self.next:
            self.next = now + self.every
            try:
                self.proc = subprocess.Popen(
                    ["bash", "-c", ". %s/lib.sh; kb_status" % LIB], stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            except OSError:
                self.proc = None
        if now >= self.tiles_next:                  # kb-tiles limits itself (30 minutes)
            self.tiles_next = now + 600
            try:
                subprocess.Popen([LIB + "/kb-tiles", "refresh"], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                pass
