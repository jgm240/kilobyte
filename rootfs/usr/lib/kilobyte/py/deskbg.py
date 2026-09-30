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
    """Network, battery, update notice, volume and USB sticks, asked from
    lib.sh every now and then without ever making the desktop wait."""

    def __init__(self, every=15):
        self.every = every
        self.network = self.battery = self.volume = ""
        self.update = False
        self.usb = None                    # names of the sticks plugged in (None: not known yet)
        self.proc = None
        self.next = 0
        self.tiles_next = 0
        self.fresh = False                 # True once after every answer

    def ask_soon(self):
        self.next = 0

    def poll(self):
        now = time.time()
        if self.proc and self.proc.poll() is not None:
            try:
                out = self.proc.stdout.read().decode("utf-8", "replace").split("\n")
            except OSError:
                out = []
            self.proc = None
            out += [""] * 5
            self.network, self.battery = out[0].strip(), out[1].strip()
            self.update = out[2].strip() == "update"
            self.volume = out[3].strip()
            self.usb = [u for u in out[4].strip().split(";") if u]
            self.fresh = True
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


# --- programs and the icons on the desktop ---------------------------------------

DESKTOP = os.path.expanduser("~/Desktop")
DEFAULT_ICONS = ["Files", "Editor", "Web", "Terminal", "Settings", "Trash"]
CATEGORIES = [("main", "Programs"), ("internet", "Internet"), ("media", "Media"),
              ("accessories", "Accessories"), ("games", "Games"), ("more", "More programs")]


def apps():
    """The programs, as the Program Manager lists them (kilobyte --list-apps):
    [{"id", "cat", "name", "help", "icon", "size"}]."""
    try:
        out = subprocess.run(["/usr/bin/kilobyte", "--list-apps"], capture_output=True, timeout=10,
                             stdin=subprocess.DEVNULL).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return []
    result = []
    for line in out.split("\n"):
        f = line.split("|")
        if len(f) >= 6:
            result.append({"id": f[0], "cat": f[1], "name": f[2], "help": f[3], "icon": (f[4] + "  ")[:2], "size": f[5]})
    return result


def desktop_apps():
    """The programs that have an icon on the desktop (Settings > Desktop)."""
    try:
        with open(os.path.join(CONF, "desktop-apps"), encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except OSError:
        return list(DEFAULT_ICONS)


# What a file's icon looks like: (two characters, background colour).
FILE_KINDS = (
    (("txt", "md", "log", "conf", "ini", "sh", "py", "c", "h", "html", "css", "js", "json", "xml"), "≡ ", 7),
    (("docx", "odt", "rtf", "doc"), "Ed", 7),
    (("xlsx", "ods", "csv", "tsv", "sc", "xls"), "##", 7),
    (("png", "jpg", "jpeg", "gif", "bmp", "webp", "tif", "tiff", "svg", "ans"), "▒▓", 5),
    (("mp3", "ogg", "oga", "flac", "wav", "m4a", "opus", "aac", "wma", "m3u"), "♫ ", 2),
    (("mp4", "mkv", "avi", "mov", "webm", "mpg", "mpeg", "flv", "wmv", "m4v"), "Tv", 1),
    (("exe", "msi", "bat", "com"), "W ", 4),
    (("zip", "tar", "gz", "xz", "bz2", "7z", "rar", "deb", "tgz"), "[]", 3),
    (("pdf", "ps", "epub"), "¶ ", 1),
    (("ica",), "Cx", 4),
)


def file_icon(path):
    if os.path.isdir(path):
        return "▓▓", 3
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    for exts, glyph, bg in FILE_KINDS:
        if ext in exts:
            return glyph, bg
    return "· ", 7


def icons(app_list):
    """What is on the desktop: program shortcuts, then the files and folders
    in ~/Desktop. [{"kind": "app"|"file", "id"|"path", "label", "glyph", "bg"}]"""
    by_id = {}
    for a in app_list:
        by_id.setdefault(a["id"], a)
    out = []
    for i in desktop_apps():
        a = by_id.get(i)
        if a:
            out.append({"kind": "app", "id": i, "label": a["name"], "glyph": a["icon"], "bg": 6})
    try:
        names = sorted(os.listdir(DESKTOP), key=lambda n: (not os.path.isdir(os.path.join(DESKTOP, n)), n.lower()))
    except OSError:
        names = []
    for n in names:
        if n.startswith("."):
            continue
        path = os.path.join(DESKTOP, n)
        glyph, bg = file_icon(path)
        out.append({"kind": "file", "path": path, "label": n, "glyph": glyph, "bg": bg})
    return out


def desktop_stamp():
    """Changes whenever the desktop's icons may have changed."""
    stamps = []
    for path in (DESKTOP, os.path.join(CONF, "desktop-apps")):
        try:
            stamps.append(os.stat(path).st_mtime)
        except OSError:
            stamps.append(0)
    return tuple(stamps)
