#!/usr/bin/python3
"""Kilobyte Windows: a desktop with movable windows, in text mode.

Every window is a terminal of its own (a pseudo terminal, emulated with
pyte) running a program. Windows have a title bar, a close box [X], minimise
[▼] and maximise [▲] boxes and a shadow; the active one has a double frame.

The desktop behind them has a wallpaper, the weather and news tiles, icons
for programs and for the files in ~/Desktop, and notes that pop up in the
corner. The menu bar at the top opens the Programs menu (■ Kilobyte, or
F12) and shows network, volume, battery and clock; the bar at the bottom
lists the windows.

Mouse: drag a title bar to move a window (an outline shows where it goes),
drag its lower right corner to resize it, double-click a title bar to
maximise, double-click an icon to open it, right-click it for more. Drag
over text to copy it (hold Shift where a program uses the mouse itself),
click the middle button or press F11 to paste. Alt+Tab goes to the next
window.

    desk [PROGRAM [ARGS...]]     first window runs PROGRAM (default: kilobyte)
"""
import ctypes
import curses
import fcntl
import json
import os
import pty
import select
import signal
import socket
import struct
import subprocess
import sys
import termios
import time

sys.path.insert(0, "/usr/lib/kilobyte/py")
import kbui  # noqa: E402
from kbui import (BLACK, BLUE, CYAN, DARKGREY, LIGHTGREY, WHITE, YELLOW,  # noqa: E402
                  RGB, nearest)

import deskbg  # noqa: E402
import pyte  # noqa: E402

NAMES = {"black": 0, "red": 1, "green": 2, "brown": 3, "yellow": 3, "blue": 4, "magenta": 5, "cyan": 6,
         "white": 7}
MIN_W, MIN_H = 20, 6


def colour(name, default):
    """pyte colour (name, 'brightred' or hex) -> console colour 0-15."""
    if name == "default":
        return default
    if name.startswith("bright") and name[6:] in NAMES:
        return NAMES[name[6:]] + 8
    if name in NAMES:
        return NAMES[name]
    if len(name) == 6:
        try:
            return nearest((int(name[0:2], 16), int(name[2:4], 16), int(name[4:6], 16)))
        except ValueError:
            pass
    return default


# --- keys: curses -> what a program on an xterm expects ---------------------
KEYS = {
    curses.KEY_UP: b"\x1b[A", curses.KEY_DOWN: b"\x1b[B", curses.KEY_RIGHT: b"\x1b[C", curses.KEY_LEFT: b"\x1b[D",
    curses.KEY_HOME: b"\x1b[H", curses.KEY_END: b"\x1b[F", curses.KEY_PPAGE: b"\x1b[5~", curses.KEY_NPAGE: b"\x1b[6~",
    curses.KEY_IC: b"\x1b[2~", curses.KEY_DC: b"\x1b[3~", curses.KEY_BACKSPACE: b"\x7f", curses.KEY_ENTER: b"\r",
    curses.KEY_BTAB: b"\x1b[Z",
    curses.KEY_F1: b"\x1bOP", curses.KEY_F2: b"\x1bOQ", curses.KEY_F3: b"\x1bOR", curses.KEY_F4: b"\x1bOS",
    curses.KEY_F5: b"\x1b[15~", curses.KEY_F6: b"\x1b[17~", curses.KEY_F7: b"\x1b[18~", curses.KEY_F8: b"\x1b[19~",
    curses.KEY_F9: b"\x1b[20~", curses.KEY_F10: b"\x1b[21~", curses.KEY_F11: b"\x1b[23~",
    curses.KEY_SLEFT: b"\x1b[1;2D", curses.KEY_SRIGHT: b"\x1b[1;2C",
}
for name, seq in (("KEY_SR", b"\x1b[1;2A"), ("KEY_SF", b"\x1b[1;2B")):
    if hasattr(curses, name):
        KEYS[getattr(curses, name)] = seq
# When a program asks for "application cursor keys" (DECCKM, as dialog and
# every curses program does), an xterm sends these as ESC O x instead.
DECCKM = 1 << 5          # pyte keeps private mode 1 like this (it has no name for it)
APP_KEYS = {
    curses.KEY_UP: b"\x1bOA", curses.KEY_DOWN: b"\x1bOB", curses.KEY_RIGHT: b"\x1bOC",
    curses.KEY_LEFT: b"\x1bOD", curses.KEY_HOME: b"\x1bOH", curses.KEY_END: b"\x1bOF",
}


# Escape sequences that reach us unparsed (split by a slow machine): the
# Linux console's and xterm's spellings, mapped to the keys above.
RAW_KEYS = {}
for _key, _seqs in (
        (curses.KEY_UP, ("[A", "OA")), (curses.KEY_DOWN, ("[B", "OB")),
        (curses.KEY_RIGHT, ("[C", "OC")), (curses.KEY_LEFT, ("[D", "OD")),
        (curses.KEY_HOME, ("[H", "OH", "[1~", "[7~")), (curses.KEY_END, ("[F", "OF", "[4~", "[8~")),
        (curses.KEY_IC, ("[2~",)), (curses.KEY_DC, ("[3~",)),
        (curses.KEY_PPAGE, ("[5~",)), (curses.KEY_NPAGE, ("[6~",)), (curses.KEY_BTAB, ("[Z",)),
        (curses.KEY_F1, ("[[A", "OP", "[11~")), (curses.KEY_F2, ("[[B", "OQ", "[12~")),
        (curses.KEY_F3, ("[[C", "OR", "[13~")), (curses.KEY_F4, ("[[D", "OS", "[14~")),
        (curses.KEY_F5, ("[[E", "[15~")), (curses.KEY_F6, ("[17~",)), (curses.KEY_F7, ("[18~",)),
        (curses.KEY_F8, ("[19~",)), (curses.KEY_F9, ("[20~",)), (curses.KEY_F10, ("[21~",)),
        (curses.KEY_F11, ("[23~",)), (curses.KEY_F12, ("[24~",))):
    for _s in _seqs:
        RAW_KEYS["\x1b" + _s] = _key


class Gpm:
    """The console mouse straight from gpm (libgpm): every movement, drag,
    press, release and wheel turn. ncurses' own gpm support reports only
    presses and releases, which is not enough to drag windows."""

    MOVE, DRAG, DOWN, UP = 1, 2, 4, 8
    B_LEFT, B_MIDDLE, B_RIGHT, B_UP, B_DOWN = 4, 2, 1, 16, 32

    class Connect(ctypes.Structure):
        _fields_ = [("eventMask", ctypes.c_ushort), ("defaultMask", ctypes.c_ushort),
                    ("minMod", ctypes.c_ushort), ("maxMod", ctypes.c_ushort),
                    ("pid", ctypes.c_int), ("vc", ctypes.c_int)]

    class Event(ctypes.Structure):
        _fields_ = [("buttons", ctypes.c_ubyte), ("modifiers", ctypes.c_ubyte), ("vc", ctypes.c_ushort),
                    ("dx", ctypes.c_short), ("dy", ctypes.c_short), ("x", ctypes.c_short), ("y", ctypes.c_short),
                    ("type", ctypes.c_int), ("clicks", ctypes.c_int), ("margin", ctypes.c_int),
                    ("wdx", ctypes.c_short), ("wdy", ctypes.c_short)]

    @classmethod
    def open(cls):
        if os.environ.get("TERM") != "linux":
            return None
        try:
            lib = ctypes.CDLL("libgpm.so.2")
        except OSError:
            return None
        conn = cls.Connect(0xFFFF, 0, 0, 0xFFFF, 0, 0)   # every event, none to gpm itself
        if lib.Gpm_Open(ctypes.byref(conn), 0) < 0:
            return None
        g = cls()
        g.lib = lib
        g.fd = ctypes.c_int.in_dll(lib, "gpm_fd").value
        return g if g.fd >= 0 else None

    def events(self):
        """Every gpm event that is waiting -> list of (x, y, kind, button, shift),
        or None when the connection to gpm is gone (gpm was restarted).
        A mouse sends events much faster than the screen is redrawn, so a run
        of movements counts as its last one; otherwise the pointer and a
        dragged window fall further and further behind the hand."""
        out = []
        for _ in range(500):
            try:
                if not select.select([self.fd], [], [], 0)[0]:
                    break
            except (OSError, ValueError):
                return None
            ev = self.Event()
            if self.lib.Gpm_GetEvent(ctypes.byref(ev)) <= 0:
                return None
            if os.environ.get("KB_DESK_DEBUG"):
                with open("/tmp/desk-mouse.log", "a") as log:
                    log.write("raw buttons=%d dx=%d dy=%d x=%d y=%d type=%d clicks=%d vc=%d\n"
                              % (ev.buttons, ev.dx, ev.dy, ev.x, ev.y, ev.type, ev.clicks, ev.vc))
            x, y = ev.x - 1, ev.y - 1
            button = (1 if ev.buttons & self.B_LEFT else 3 if ev.buttons & self.B_RIGHT
                      else 2 if ev.buttons & self.B_MIDDLE else 0)
            shift = bool(ev.modifiers & 1)
            if ev.wdy or ev.buttons & (self.B_UP | self.B_DOWN):
                e = (x, y, "wheel", 4 if (ev.wdy > 0 or ev.buttons & self.B_UP) else 5, shift)
            elif ev.type & self.DOWN:
                e = (x, y, "down", button, shift)
            elif ev.type & self.UP:
                e = (x, y, "up", button or 1, shift)
            elif ev.type & self.DRAG:
                e = (x, y, "drag", button, shift)
            else:
                e = (x, y, "move", 0, shift)
            if out and e[2] in ("move", "drag") and out[-1][2] == e[2]:
                out[-1] = e
            else:
                out.append(e)
        return out

    def close(self):
        try:
            self.lib.Gpm_Close()
        except Exception:
            pass


class TermScreen(pyte.Screen):
    """pyte's screen, with "erase display" colouring every cell. pyte only
    recolours cells that were written before, so a program that clears to
    the end of the screen in its background colour (dialog does) left the
    untouched part black."""

    def erase_in_display(self, how=0, *args, **kwargs):
        if how == 0:
            rows = range(self.cursor.y + 1, self.lines)
        elif how == 1:
            rows = range(self.cursor.y)
        else:
            rows = range(self.lines)
        self.dirty.update(rows)
        for y in rows:
            line = self.buffer[y]
            for x in range(self.columns):
                line[x] = self.cursor.attrs
        if how in (0, 1):
            self.erase_in_line(how)


class Window:
    def __init__(self, desk, argv, x, y, w, h, title="Program Manager"):
        self.desk = desk
        self.x, self.y, self.w, self.h = x, y, w, h
        self.title = title
        self.saved = None                  # position before maximising
        self.minimised = False
        self.screen = TermScreen(w - 2, h - 2)
        self.screen.set_mode(pyte.modes.LNM)
        self.stream = pyte.ByteStream(self.screen)
        self.alive = True
        pid, fd = pty.fork()
        if pid == 0:
            env = dict(os.environ, TERM="xterm", KILOBYTE_DESK="1", COLORTERM="",
                       KB_DESK_PID=str(os.getppid()), KB_DESK_SOCK=desk.sock_path or "",
                       NCURSES_NO_UTF8_ACS="1")   # real box characters, not VT100 line mode
            env.pop("KILOBYTE", None)
            env.pop("KB_APP_WINDOW", None)
            env.pop("NCURSES_GPM_TERMS", None)
            os.chdir(os.path.expanduser("~"))
            try:
                os.execvpe(argv[0], argv, env)
            finally:
                os._exit(127)
        self.pid, self.fd = pid, fd
        self.set_size()

    # the inner size is the frame minus its border
    def cols(self):
        return self.w - 2

    def rows(self):
        return self.h - 2

    def set_size(self):
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", self.rows(), self.cols(), 0, 0))

    def clamp_size(self, w, h):
        H, W = self.desk.area()
        return max(MIN_W, min(w, W)), max(MIN_H, min(h, H))

    def clamp_pos(self, x, y):
        H, W = self.desk.area()
        return max(-self.w + 8, min(x, W - 8)), max(1, min(y, H))

    def resize(self, w, h):
        w, h = self.clamp_size(w, h)
        if (w, h) == (self.w, self.h):
            return
        self.w, self.h = w, h
        self.screen.resize(self.rows(), self.cols())
        self.set_size()                    # the kernel sends the program SIGWINCH

    def move(self, x, y):
        self.x, self.y = self.clamp_pos(x, y)

    def read(self):
        try:
            data = os.read(self.fd, 65536)
        except OSError:
            data = b""
        if not data:
            self.alive = False
            return
        self.stream.feed(data)
        if self.screen.title:
            self.title = self.screen.title

    def send(self, data):
        try:
            os.write(self.fd, data)
        except OSError:
            pass

    def close(self, sig=signal.SIGHUP):
        try:
            os.killpg(os.getpgid(self.pid), sig)
        except (ProcessLookupError, PermissionError):
            pass

    def mouse_on(self):
        modes = self.screen.mode
        return any(m << 5 in modes for m in (1000, 1002, 1003))

    def contains(self, mx, my):
        return self.x <= mx < self.x + self.w and self.y <= my < self.y + self.h

    def text(self, a=None, b=None):
        """What is on the window's screen, or the part from cell a to cell b
        (column, row), as lines of text."""
        rows, cols = self.rows(), self.cols()
        if a is None:
            a, b = (0, 0), (cols - 1, rows - 1)
        if (a[1], a[0]) > (b[1], b[0]):
            a, b = b, a
        lines = []
        for y in range(max(0, a[1]), min(rows - 1, b[1]) + 1):
            x0 = a[0] if y == a[1] else 0
            x1 = b[0] if y == b[1] else cols - 1
            line = self.screen.buffer[y]
            lines.append("".join(line[x].data or " " for x in range(max(0, x0), min(cols - 1, x1) + 1)).rstrip())
        while lines and not lines[-1]:
            lines.pop()
        return "\n".join(lines)


LIB = "/usr/lib/kilobyte"
ICON_W, ICON_H = 14, 4                     # an icon on the desktop, in cells
CLIPBOARD = os.path.expanduser("~/.cache/kilobyte-clipboard")


class Desk:
    TILE_W = 64                            # a tile with its frame

    def __init__(self, s, argv):
        self.s = s
        self.first_argv = argv
        self.windows = []                  # bottom to top; the last is active
        self.drag = None                   # ("move"|"size", window, dx, dy)
        self.outline = None                # (x, y, w, h) where the dragged window will go
        self.drag_start = None             # where the pointer was when the drag began
        self.pointer = None                # where the mouse is, drawn as a block
        self.buttons = set()               # mouse buttons held down
        # The console mouse straight from gpm (ncurses' gpm is off, see main).
        self.console = os.environ.get("TERM") == "linux"
        self.gpm = Gpm.open() if self.console else None
        self.gpm_retry = time.time() + 2   # when to look for gpm again if it is not there
        self.last_click = (0, None)
        self.menus = []                    # the open menu and its submenus
        self.mode = None                   # "move" or "resize": arrow keys act on the window
        self.volume_open = False           # the volume slider under the menu bar
        self.select = None                 # text being marked: {"win", "a", "b"} in window cells
        self.clip = ""                     # what was copied
        self.notes = []                    # notes in the corner: [title, [lines], until]
        self.status = deskbg.Status()      # network, battery, volume, ... for the menu bar
        self.seen = None                   # the status the last time, to notice changes
        self.bar_items = []                # (x0, x1, action) of what can be clicked in the menu bar
        self.task_buttons = []
        self.wall = None                   # the desktop (wallpaper, tiles, icons), drawn once and kept
        self.wall_key = None
        self.wall_checked = 0
        self.apps = []                     # the programs (kilobyte --list-apps)
        self.apps_read = 0
        self.icons = []                    # [(x, y, icon)] on the screen
        self.icon_sel = None
        self.quitting = None               # set to a time when logging out
        self.last_input = time.time()
        self.idle_checked = 0
        try:
            with open(CLIPBOARD, encoding="utf-8", errors="replace") as f:
                self.clip = f.read()
        except OSError:
            pass
        # Programs in windows ask here for things (deskrun.py): the whole
        # screen for a video, a window for a program, a note in the corner.
        self.sock = None
        self.sock_path = None
        try:
            path = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "kilobyte-desk-%d.sock" % os.getpid())
            if os.path.exists(path):
                os.unlink(path)
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            old = os.umask(0o177)
            try:
                self.sock.bind(path)
            finally:
                os.umask(old)
            self.sock.listen(8)
            self.sock_path = path
        except OSError:
            self.sock = None
        s.scr.nodelay(True)
        s.scr.keypad(True)
        curses.raw()
        signal.signal(signal.SIGCHLD, lambda *a: None)
        # "Log out" in any window: close them all and leave.
        signal.signal(signal.SIGUSR1, lambda *a: self.logout())
        os.makedirs(deskbg.DESKTOP, exist_ok=True)
        self.read_apps()
        H, W = self.area()
        if W >= 140:
            # Room for a desktop: the Program Manager is a window among the
            # icons (left) and the tiles (right).
            win = self.new_window(argv)
            win.resize(76, min(H, 30))
            win.move(min(self.icon_columns() * ICON_W + 2, max(0, W - self.TILE_W - 80)), 1)
        else:
            self.new_window(argv, maximised=True)

    def area(self):
        H, W = self.s.size()
        return H - 2, W                    # rows 1..H-2 are the desktop

    # --- programs ---------------------------------------------------------
    def read_apps(self):
        apps = deskbg.apps()
        if apps:
            self.apps = apps
        self.apps_read = time.time()
        self.wall_key = None

    def app(self, ident):
        for a in self.apps:
            if a["id"] == ident:
                return a
        return None

    def launch_app(self, ident, *args):
        a = self.app(ident) or {"name": ident, "size": "M"}
        self.open_window(["/usr/bin/kilobyte", "--app", ident] + list(args), a["name"], a["size"])

    def open_file(self, path, choose=False):
        argv = [LIB + "/kb-open", "--here"] + (["--choose"] if choose else []) + [path]
        self.open_window(argv, os.path.basename(path) or path, "L")

    # --- windows --------------------------------------------------------
    def new_window(self, argv=None, maximised=False):
        H, W = self.area()
        n = len(self.windows)
        if maximised:
            x, y, w, h = 0, 1, W, H
        else:
            w, h = max(MIN_W, W * 3 // 4), max(MIN_H, H * 3 // 4)
            x, y = min(2 + 3 * n, W - w), min(1 + 2 * n, H - h + 1)
        win = Window(self, argv or ["kilobyte"], x, y, w, h)
        if maximised:
            # Where it goes when restored (or when its title bar is dragged).
            rw, rh = max(MIN_W, W * 3 // 4), max(MIN_H, H * 3 // 4)
            win.saved = (min(2 + 3 * n, W - rw), min(1 + 2 * n, H - rh + 1), rw, rh)
        self.windows.append(win)
        return win

    def open_window(self, argv, title="", size="M"):
        """A window for a program: S small, M three quarters of the desktop,
        L nearly all of it. On a small screen M and L are maximised."""
        H, W = self.area()
        n = len(self.windows) % 6
        if size == "S":
            w, h = min(W, 72), min(H, 24)
        elif W < 100:
            w, h = W, H
        elif size == "L":
            w, h = W * 7 // 8, H
        else:
            w, h = W * 3 // 4, H * 3 // 4
        x = max(0, min(4 + 3 * n, W - w))
        y = max(1, min(1 + 2 * n, H - h + 1))
        win = Window(self, argv, x, y, max(MIN_W, w), max(MIN_H, h), title or "Program")
        if (w, h) == (W, H):
            rw, rh = max(MIN_W, W * 3 // 4), max(MIN_H, H * 3 // 4)
            win.saved = (min(2 + 3 * n, W - rw), min(1 + 2 * n, H - rh + 1), rw, rh)
        self.windows.append(win)
        return win

    def active(self):
        visible = [w for w in self.windows if not w.minimised]
        return visible[-1] if visible else None

    def raise_(self, win):
        win.minimised = False
        self.windows.remove(win)
        self.windows.append(win)

    def cycle(self):
        if len(self.windows) > 1:
            win = self.windows.pop(0)
            self.windows.append(win)
            win.minimised = False

    def maximise(self, win):
        H, W = self.area()
        if win.saved:
            x, y, w, h = win.saved
            win.saved = None
        else:
            win.saved = (win.x, win.y, win.w, win.h)
            x, y, w, h = 0, 1, W, H
        win.x, win.y = x, y
        win.resize(w, h)

    def tile(self):
        vis = [w for w in self.windows if not w.minimised]
        if not vis:
            return
        H, W = self.area()
        cols = 1 if len(vis) == 1 else 2
        rows = (len(vis) + cols - 1) // cols
        for i, win in enumerate(vis):
            c, r = i % cols, i // cols
            win.saved = None
            win.x, win.y = c * W // cols, 1 + r * H // rows
            win.resize(W // cols, H // rows)

    def cascade(self):
        H, W = self.area()
        for i, win in enumerate(w for w in self.windows if not w.minimised):
            win.saved = None
            win.resize(W * 3 // 4, H * 3 // 4)
            win.move(2 + 3 * i, 1 + 2 * i)

    def logout(self):
        """Close every window, then leave (Kilobyte logs out)."""
        self.quitting = time.time()
        for w in self.windows:
            w.close()

    # --- the desktop: wallpaper, tiles, icons ------------------------------
    def icon_rows(self):
        H, W = self.area()
        return max(1, (H - 1) // ICON_H)

    def icon_columns(self):
        n = len(deskbg.icons(self.apps))
        return max(1, (n + self.icon_rows() - 1) // self.icon_rows())

    def draw_desktop(self):
        """Wallpaper, tiles and icons. They are drawn into a window of their
        own when something changed and copied from there for every picture."""
        H, W = self.s.size()
        now = time.time()
        if now - self.wall_checked > 2 or self.wall is None:
            self.wall_checked = now
            try:
                stamp = os.stat(os.path.join(deskbg.CONF, "wallpaper")).st_mtime
            except OSError:
                stamp = 0
            tiles = deskbg.tiles()
            key = (H, W, stamp, repr(tiles), deskbg.desktop_stamp(), len(self.apps))
            if key != self.wall_key:
                self.wall_key = key
                self.wall = self.render_desktop(H - 2, W, tiles)
        if self.wall is not None:
            try:
                self.wall.overwrite(self.s.scr)
            except curses.error:
                pass
        # The chosen icon: its name in other colours.
        for x, y, icon in self.icons:
            if icon is self.icon_sel:
                self.s.put(y + 2, x, self.icon_label(icon), BLACK, CYAN)

    @staticmethod
    def icon_label(icon):
        label = icon["label"]
        if len(label) > ICON_W - 1:
            label = label[:ICON_W - 2] + "~"
        return label.center(ICON_W - 1)

    def render_desktop(self, h, w, tiles):
        if h < 1 or w < 1:
            return None
        try:
            win = curses.newwin(h, w, 1, 0)
        except curses.error:
            return None

        def put(y, x, text, fg, bg):
            if 0 <= y < h and x < w:
                if x < 0:
                    text, x = text[-x:], 0
                try:
                    win.addstr(y, x, text[:w - x], self.s.attr(fg, bg))
                except curses.error:
                    pass                           # the last cell of a window

        try:
            rows = deskbg.wallpaper(deskbg.read_conf(), w, h)
        except Exception:
            self.log_error()
            rows = [[("░", LIGHTGREY, BLUE)] * w for _ in range(h)]
        for y, row in enumerate(rows[:h]):
            x = 0
            while x < len(row):                    # runs of one colour in one go
                ch, fg, bg = row[x]
                end = x + 1
                while end < len(row) and row[end][1:] == (fg, bg):
                    end += 1
                put(y, x, "".join(c[0] for c in row[x:end]), fg, bg)
                x = end
        # Weather and news, down the right-hand side.
        tw = self.TILE_W
        if w >= tw + 20:
            x, y = w - tw - 2, 1
            for title, lines in tiles:
                th = len(lines) + 2
                if y + th + 1 > h:
                    break
                for yy in range(y + 1, y + th + 1):   # shadow
                    put(yy, x + tw, "  ", DARKGREY, BLACK)
                put(y + th, x + 2, " " * tw, DARKGREY, BLACK)
                put(y, x, "┌" + "─" * (tw - 2) + "┐", BLACK, LIGHTGREY)
                put(y, x + (tw - len(title) - 2) // 2, " %s " % title, BLUE, LIGHTGREY)
                for i, line in enumerate(lines):
                    put(y + 1 + i, x, "│ " + line[:tw - 4].ljust(tw - 4) + " │", BLACK, LIGHTGREY)
                put(y + th - 1, x, "└" + "─" * (tw - 2) + "┘", BLACK, LIGHTGREY)
                y += th + 1
        # Icons: programs, then what is in ~/Desktop, in columns from the left.
        self.icons = []
        per_col = max(1, (h - 1) // ICON_H)
        for i, icon in enumerate(deskbg.icons(self.apps)):
            x, y = 1 + (i // per_col) * ICON_W, 1 + (i % per_col) * ICON_H
            if x + ICON_W > w:
                break
            fg = WHITE if icon["bg"] in (1, 4, 5) else BLACK
            put(y, x + 3, ("  " + icon["glyph"] + "  ")[:6], fg, icon["bg"])
            put(y + 1, x + 3, "      ", fg, icon["bg"])
            put(y + 2, x, self.icon_label(icon), WHITE, BLACK)
            self.icons.append((x, y + 1, icon))    # (in screen rows: the desktop starts at row 1)
        return win

    def icon_at(self, mx, my):
        for x, y, icon in self.icons:
            if x <= mx < x + ICON_W - 1 and y <= my < y + 3:
                return icon
        return None

    def open_icon(self, icon):
        if icon["kind"] == "app":
            self.launch_app(icon["id"])
        else:
            self.open_file(icon["path"])

    # --- menu bar and taskbar -------------------------------------------
    def draw_bars(self):
        """Menu bar and taskbar: drawn last, so windows never cover them."""
        H, W = self.s.size()
        st = self.status
        # Right: what the computer is doing (each part can be clicked).
        right = []
        if st.update:
            right.append(("update", "▲ Update"))
        if st.network:
            right.append(("network", st.network))
        if st.volume:
            right.append(("volume", "♪ " + (st.volume if st.volume == "mute" else st.volume + "%")))
        if st.battery:
            right.append(("battery", "Battery " + st.battery))
        right.append(("clock", time.strftime("%a %d %b  %H:%M")))
        items = [("menu", " ■ Kilobyte "), ("tile", " Tile "), ("cascade", " Cascade ")]
        hint = "  F12 menu   Alt+Tab next window   F11 paste"
        while True:
            rlen = sum(len(t) for _, t in right) + 5 * (len(right) - 1) + 1
            left = sum(len(t) + 1 for _, t in items)
            if left + rlen + 2 <= W or (len(items) <= 1 and len(right) <= 1):
                break
            if len(items) > 1:
                items.pop()                        # narrow screens: fewer buttons,
            else:
                right.pop(0)                       # then less status
        self.s.put(0, 0, " " * W, BLACK, LIGHTGREY)
        self.bar_items = []
        x = 0
        for action, text in items:
            self.s.put(0, x, text, BLACK, LIGHTGREY)
            self.bar_items.append((x, x + len(text), action))
            x += len(text)
            self.s.put(0, x, "│", DARKGREY, LIGHTGREY)
            x += 1
        self.s.put(0, 1, "■", kbui.RED, LIGHTGREY)
        if x + len(hint) + rlen + 2 <= W:
            self.s.put(0, x, hint, DARKGREY, LIGHTGREY)
        rx = max(x, W - rlen)
        for i, (action, text) in enumerate(right):
            self.s.put(0, rx, text, kbui.RED if action == "update" else BLACK, LIGHTGREY)
            self.bar_items.append((rx, rx + len(text), action))
            rx += len(text)
            if i < len(right) - 1:
                self.s.put(0, rx, "  │  ", DARKGREY, LIGHTGREY)
                rx += 5
        # The taskbar.
        x = 1
        self.task_buttons = []
        self.s.put(H - 1, 0, " " * W, BLACK, CYAN)
        act = self.active()
        for i, win in enumerate(sorted(self.windows, key=lambda w: w.pid)):
            label = f" {i + 1} {win.title[:18]} "
            fg, bg = (WHITE, BLUE) if win is act else ((DARKGREY, CYAN) if win.minimised else (BLACK, CYAN))
            self.s.put(H - 1, x, label, fg, bg)
            self.task_buttons.append((x, x + len(label), win))
            x += len(label) + 1
        if not self.windows:
            self.s.put(H - 1, 1, "No program is open.  F12 or ■ Kilobyte opens the Programs menu; "
                       "double-click an icon to start it.", BLACK, CYAN)

    def draw_window(self, win, active):
        s, x, y, w, h = self.s, win.x, win.y, win.w, win.h
        frame_fg, frame_bg = (WHITE, BLUE) if active else (LIGHTGREY, BLUE)
        tl, tr, bl, br, hz, vt = ("╔", "╗", "╚", "╝", "═", "║") if active else ("┌", "┐", "└", "┘", "─", "│")
        # Shadow first (right and below).
        for yy in range(y + 1, y + h + 1):
            s.put(yy, x + w, "  ", DARKGREY, BLACK)
        s.put(y + h, x + 2, " " * w, DARKGREY, BLACK)
        # Frame and title bar.
        s.put(y, x, tl + hz * (w - 2) + tr, frame_fg, frame_bg)
        title = f" {win.title} "[: max(0, w - 16)]
        s.put(y, x + (w - len(title)) // 2, title, YELLOW if active else LIGHTGREY, frame_bg)
        s.put(y, x + 1, "[X]", frame_fg, frame_bg)
        s.put(y, x + w - 7, "[▼][▲]" if not win.saved else "[▼][↕]", frame_fg, frame_bg)
        for yy in range(1, h - 1):
            s.put(y + yy, x, vt, frame_fg, frame_bg)
            s.put(y + yy, x + w - 1, vt, frame_fg, frame_bg)
        s.put(y + h - 1, x, bl + hz * (w - 2) + br, frame_fg, frame_bg)   # the corner resizes
        # Contents.
        buf = win.screen.buffer
        for row in range(win.rows()):
            line = buf[row]
            col = 0
            out_x = x + 1
            while col < win.cols():
                ch = line[col]
                fg = colour(ch.fg, LIGHTGREY)
                bg = colour(ch.bg, BLACK)
                if ch.bold and fg < 8:
                    fg += 8
                if ch.reverse:
                    fg, bg = bg, fg
                # Batch runs of cells with the same colours.
                text = ch.data or " "
                end = col + 1
                while end < win.cols():
                    nxt = line[end]
                    if (nxt.fg, nxt.bg, nxt.bold, nxt.reverse) != (ch.fg, ch.bg, ch.bold, ch.reverse):
                        break
                    text += nxt.data or " "
                    end += 1
                s.put(y + 1 + row, out_x, text, fg, bg & 7)
                out_x += end - col
                col = end
        # Text being marked with the mouse.
        sel = self.select
        if sel and sel["win"] is win:
            a, b = sel["a"], sel["b"]
            if (a[1], a[0]) > (b[1], b[0]):
                a, b = b, a
            for row in range(a[1], b[1] + 1):
                x0 = a[0] if row == a[1] else 0
                x1 = b[0] if row == b[1] else win.cols() - 1
                self.invert(y + 1 + row, x + 1 + x0, x1 - x0 + 1)

    def draw(self):
        self.draw_desktop()
        act = self.active()
        for win in self.windows:
            if not win.minimised:
                self.draw_window(win, win is act)
        if self.outline:
            self.draw_outline()
        self.draw_bars()
        self.draw_notes()
        if self.volume_open:
            self.draw_volume()
        if self.menus:
            self.draw_menus()
        if self.mode:
            H, W = self.s.size()
            hint = " Arrow keys %s the window.  Enter or Esc when done. " % self.mode
            self.s.put(H - 1, 0, hint.ljust(W), BLACK, YELLOW)
        # The mouse pointer: the cell under it with its colours swapped.
        if self.pointer:
            px, py = self.pointer
            self.invert(py, px, 1)
        # The cursor of the active window's program.
        if act and not act.screen.cursor.hidden and not self.menus and not self.volume_open:
            cx, cy = act.x + 1 + act.screen.cursor.x, act.y + 1 + act.screen.cursor.y
            H, W = self.s.size()
            if 0 <= cx < W and 0 <= cy < H - 1:
                try:
                    curses.curs_set(1)
                    self.s.scr.move(cy, cx)
                except curses.error:
                    pass
        else:
            curses.curs_set(0)
        self.s.scr.refresh()

    def invert(self, y, x, n):
        """Swap foreground and background of n cells, whatever their colours
        (plain reverse video would be grey on grey over a dialog)."""
        H, W = self.s.size()
        if not 0 <= y < H:
            return
        for xx in range(max(0, x), min(W, x + n)):
            try:
                attr = self.s.scr.inch(y, xx) & (curses.A_COLOR | curses.A_BOLD | curses.A_REVERSE)
                self.s.scr.chgat(y, xx, 1, attr ^ curses.A_REVERSE)
            except curses.error:
                pass

    def draw_outline(self):
        """Where the window being dragged will go: its frame in reverse video."""
        x, y, w, h = self.outline
        H, W = self.s.size()

        def mark(yy, xx, n):
            if 0 < yy < H - 1:
                self.invert(yy, xx, n)

        mark(y, x, w)
        mark(y + h - 1, x, w)
        for yy in range(y + 1, y + h - 1):
            mark(yy, x, 1)
            mark(yy, x + w - 1, 1)

    # --- notes in the corner ----------------------------------------------
    NOTE_W = 46

    def note(self, title, text="", seconds=8):
        lines = []
        for part in str(text).split("\n"):
            while len(part) > self.NOTE_W - 4:
                cut = part.rfind(" ", 0, self.NOTE_W - 4)
                cut = cut if cut > 10 else self.NOTE_W - 4
                lines.append(part[:cut])
                part = part[cut:].lstrip()
            if part:
                lines.append(part)
        self.notes.append([str(title)[:self.NOTE_W - 6], lines[:5], time.time() + seconds])
        del self.notes[:-4]                    # four at a time are plenty

    def note_boxes(self):
        """[(x, y, h, note)], newest at the bottom right."""
        H, W = self.s.size()
        boxes, y = [], H - 1
        for n in reversed(self.notes):
            h = len(n[1]) + 2
            y -= h
            if y < 2:
                break
            boxes.append((W - self.NOTE_W - 1, y, h, n))
        return boxes

    def draw_notes(self):
        now = time.time()
        self.notes = [n for n in self.notes if n[2] > now]
        w = self.NOTE_W
        for x, y, h, (title, lines, _) in self.note_boxes():
            self.s.put(y, x, "┌" + "─" * (w - 2) + "┐", BLACK, YELLOW)
            self.s.put(y, x + 2, " %s " % title, BLACK, YELLOW)
            for i, line in enumerate(lines):
                self.s.put(y + 1 + i, x, "│ " + line.ljust(w - 4) + " │", BLACK, YELLOW)
            self.s.put(y + h - 1, x, "└" + "─" * (w - 2) + "┘", BLACK, YELLOW)

    def watch_status(self):
        """Tell about what changed: network, battery, updates, USB sticks."""
        st = self.status
        if not st.fresh:
            return
        st.fresh = False
        now = {"network": st.network, "update": st.update, "usb": list(st.usb or [])}
        old, self.seen = self.seen, now
        pct = st.battery.rstrip("+%")
        low = pct.isdigit() and int(pct) <= 10 and not st.battery.endswith("+")
        if low and not getattr(self, "battery_warned", False):
            self.note("Battery low", "The battery is at %s%%. Plug in the charger or save your work." % pct, 20)
        self.battery_warned = low
        if old is None:
            return
        if now["network"] != old["network"] and now["network"]:
            self.note("Network", now["network"])
        if now["update"] and not old["update"]:
            self.note("Kilobyte Update", "A newer Kilobyte is there: Settings > Kilobyte Update.", 12)
        for name in now["usb"]:
            if name not in old["usb"]:
                self.note("USB stick", "%s was plugged in. Accessories > USB sticks opens it." % name, 12)
        for name in old["usb"]:
            if name not in now["usb"]:
                self.note("USB stick", "%s was removed." % name)

    # --- volume ------------------------------------------------------------
    def volume_box(self):
        H, W = self.s.size()
        return max(0, W - 40), 1, 38               # x, y, width

    def draw_volume(self):
        x, y, w = self.volume_box()
        v = self.status.volume
        level = int(v) if v.isdigit() else 0
        bar = w - 12
        filled = level * bar // 100
        self.s.box(y, x, 4, w, BLACK, LIGHTGREY, title="Volume")
        self.s.put(y + 1, x + 2, "█" * filled + "░" * (bar - filled), BLUE, LIGHTGREY)
        self.s.put(y + 1, x + 3 + bar, ("mute" if v == "mute" else "%3d%%" % level).rjust(5), BLACK, LIGHTGREY)
        self.s.put(y + 2, x + 2, "← → change   M mute   Esc closes".ljust(w - 4), DARKGREY, LIGHTGREY)

    def set_volume(self, what, value=None):
        v = self.status.volume
        level = int(v) if v.isdigit() else 50
        if what == "set":
            level = max(0, min(100, value))
            self.status.volume = str(level)
            cmd = "kb_volume set %d" % level
        else:                                       # mute on and off
            self.status.volume = "mute" if v != "mute" else ""
            cmd = "kb_volume mute"
        try:
            subprocess.Popen(["bash", "-c", ". %s/lib.sh; %s" % (LIB, cmd)], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
        self.status.next = time.time() + 1          # ask what it really is now

    def volume_key(self, k):
        v = self.status.volume
        level = int(v) if v.isdigit() else 0
        if k in (curses.KEY_LEFT, "-", curses.KEY_DOWN):
            self.set_volume("set", level - 5)
        elif k in (curses.KEY_RIGHT, "+", "=", curses.KEY_UP):
            self.set_volume("set", level + 5)
        elif k in ("m", "M"):
            self.set_volume("mute")
        elif k in ("\x1b", "\n", "\r", "q", "\x03", curses.KEY_ENTER, curses.KEY_F12):
            self.volume_open = False

    # --- the Programs menu ---------------------------------------------------
    # A menu is a list of (label, action, submenu); ("-", None, None) is a line.

    def main_menu(self):
        if time.time() - self.apps_read > 30:
            self.read_apps()
        items = [("Program Manager", "pm", None)]
        for cat, title in deskbg.CATEGORIES:
            sub = [(a["name"], "app:" + a["id"], None) for a in self.apps if a["cat"] == cat]
            if sub:
                items.append((title, None, sub))
        files = [(i["label"], "file:" + i["path"], None) for i in deskbg.icons(self.apps) if i["kind"] == "file"]
        if files:
            items.append(("Desktop", None, files[:30]))
        items += [
            ("-", None, None),
            ("Windows", None, [
                ("Next window        Alt+Tab", "win:next", None),
                ("Move", "win:move", None), ("Resize", "win:resize", None),
                ("Maximise / restore", "win:max", None), ("Minimise", "win:min", None),
                ("Tile all", "win:tile", None), ("Cascade all", "win:cascade", None),
                ("Close this window", "win:close", None)]),
            ("Copy and paste", None, [
                ("Copy this window's text", "copy", None),
                ("Paste                 F11", "paste", None)]),
            ("Volume", "volume", None),
            ("Settings", "app:Settings", None),
            ("Help", "app:Help", None),
            ("-", None, None),
            ("Lock the screen", "lock", None),
            ("Switch user", "app:Users", None),
            ("Log out", "logout", None),
            ("Restart", "app:Restart", None),
            ("Shut down", "app:Shutdown", None),
        ]
        return items

    def open_menu(self, items, x, y):
        self.menus = [{"items": items, "sel": self.first_item(items), "x": x, "y": y}]
        self.volume_open = False

    @staticmethod
    def first_item(items):
        for i, it in enumerate(items):
            if it[0] != "-":
                return i
        return 0

    def menu_box(self, m):
        """(x, y, w, h) of a menu, kept on the screen."""
        H, W = self.s.size()
        w = max(len(it[0]) for it in m["items"]) + 6
        h = len(m["items"]) + 2
        return max(0, min(m["x"], W - w)), max(1, min(m["y"], H - 1 - h)), w, h

    def draw_menus(self):
        for level, m in enumerate(self.menus):
            x, y, w, h = self.menu_box(m)
            self.s.box(y, x, h, w, BLACK, LIGHTGREY)
            for yy in range(y + 1, y + h + 1):         # shadow
                self.s.put(yy, x + w, "  ", DARKGREY, BLACK)
            self.s.put(y + h, x + 2, " " * w, DARKGREY, BLACK)
            for i, (label, action, sub) in enumerate(m["items"]):
                if label == "-":
                    self.s.put(y + 1 + i, x, "├" + "─" * (w - 2) + "┤", BLACK, LIGHTGREY)
                    continue
                chosen = i == m["sel"]
                fg, bg = (WHITE, BLUE) if chosen else (BLACK, LIGHTGREY)
                text = " " + label.ljust(w - 5) + ("► " if sub else "  ")
                self.s.put(y + 1 + i, x + 1, text[:w - 2], fg, bg)

    def menu_move(self, m, step):
        n = len(m["items"])
        i = m["sel"]
        for _ in range(n):
            i = (i + step) % n
            if m["items"][i][0] != "-":
                break
        m["sel"] = i

    def menu_enter(self):
        m = self.menus[-1]
        label, action, sub = m["items"][m["sel"]]
        if sub:
            x, y, w, h = self.menu_box(m)
            self.menus.append({"items": sub, "sel": self.first_item(sub), "x": x + w - 1, "y": y + m["sel"]})
        elif action:
            self.menus = []
            self.do(action)

    def menu_key(self, k):
        m = self.menus[-1]
        if k == curses.KEY_UP:
            self.menu_move(m, -1)
        elif k == curses.KEY_DOWN:
            self.menu_move(m, 1)
        elif k in (curses.KEY_RIGHT, "\n", "\r", " ", curses.KEY_ENTER):
            self.menu_enter()
        elif k == curses.KEY_LEFT:
            if len(self.menus) > 1:
                self.menus.pop()
        elif k in ("\x1b", "\x03"):
            self.menus.pop()
        elif k == curses.KEY_F12:
            self.menus = []
        elif isinstance(k, str) and k.isprintable():
            # A letter: the next entry that starts with it.
            n = len(m["items"])
            for d in range(1, n + 1):
                i = (m["sel"] + d) % n
                if m["items"][i][0].lower().startswith(k.lower()):
                    m["sel"] = i
                    break

    def menu_pointer(self, mx, my, kind):
        """The mouse while a menu is open. Returns True if it was used."""
        for level in range(len(self.menus) - 1, -1, -1):
            m = self.menus[level]
            x, y, w, h = self.menu_box(m)
            if x <= mx < x + w and y <= my < y + h:
                i = my - y - 1
                if 0 <= i < len(m["items"]) and m["items"][i][0] != "-":
                    if kind == "down" or m["sel"] != i:
                        del self.menus[level + 1:]
                        m["sel"] = i
                    if kind == "down":
                        self.menu_enter()
                return True
        if kind == "down":
            self.menus = []
        return kind == "down"

    def do(self, action):
        """What a menu entry, a button in the menu bar or an icon's menu does."""
        win = self.active()
        if action.startswith("app:"):
            self.launch_app(action[4:])
        elif action.startswith("file:"):
            self.open_file(action[5:])
        elif action.startswith("with:"):
            self.open_file(action[5:], choose=True)
        elif action.startswith("trash:"):
            self.run_quiet([LIB + "/kb-trash", "put", action[6:]])
            self.wall_key = None
        elif action.startswith("unpin:"):
            apps = [a for a in deskbg.desktop_apps() if a != action[6:]]
            try:
                os.makedirs(deskbg.CONF, exist_ok=True)
                with open(os.path.join(deskbg.CONF, "desktop-apps"), "w", encoding="utf-8") as f:
                    f.write("".join(a + "\n" for a in apps))
            except OSError:
                pass
            self.wall_key = None
        elif action == "pm":
            H, W = self.area()
            pm = self.open_window(["kilobyte"], "Program Manager", "S" if W >= 100 else "M")
            if W >= 100:
                pm.resize(76, min(H, 30))
        elif action == "menu":
            self.open_menu(self.main_menu(), 0, 1)
        elif action == "tile" or action == "win:tile":
            self.tile()
        elif action == "cascade" or action == "win:cascade":
            self.cascade()
        elif action == "win:next":
            self.cycle()
        elif action in ("win:move", "win:resize") and win:
            if win.saved:
                self.maximise(win)
            self.mode = action[4:]
        elif action == "win:max" and win:
            self.maximise(win)
        elif action == "win:min" and win:
            win.minimised = True
        elif action == "win:close" and win:
            win.close()
        elif action == "copy" and win:
            self.copy(win.text())
        elif action == "paste":
            self.paste()
        elif action == "volume":
            if self.status.volume:
                self.volume_open = True
            else:
                self.note("Volume", "No sound card was found.")
        elif action == "update":
            self.launch_app("Settings", "Update")
        elif action == "network":
            self.launch_app("Settings", "Wi-Fi")
        elif action == "battery":
            self.launch_app("Battery")
        elif action == "clock":
            self.launch_app("Month")
        elif action == "lock":
            self.lock()
        elif action == "logout":
            self.logout()

    @staticmethod
    def run_quiet(argv):
        try:
            subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=20)
        except (OSError, subprocess.SubprocessError):
            pass

    # --- copy and paste -------------------------------------------------------
    def copy(self, text):
        if not text:
            return
        self.clip = text
        try:
            os.makedirs(os.path.dirname(CLIPBOARD), exist_ok=True)
            fd = os.open(CLIPBOARD, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            pass
        n = len(text)
        self.note("Copied", "%d character%s. F11 or the middle mouse button pastes." % (n, "" if n == 1 else "s"), 4)

    def paste(self):
        win = self.active()
        if not win or not self.clip:
            return
        data = self.clip.replace("\r\n", "\n").replace("\n", "\r").encode("utf-8")
        if 2004 << 5 in win.screen.mode:            # the program knows pasted text from typed text
            data = b"\x1b[200~" + data + b"\x1b[201~"
        win.send(data)

    # --- input ----------------------------------------------------------
    def mouse(self):
        """A curses mouse event (terminal emulators) -> pointer events."""
        try:
            _, mx, my, _, b = curses.getmouse()
        except curses.error:
            return
        B = curses
        events = []
        for bit, button in ((B.BUTTON1_PRESSED, 1), (B.BUTTON2_PRESSED, 2), (B.BUTTON3_PRESSED, 3)):
            if b & bit:
                events.append(("down", button))
        for bit, button in ((B.BUTTON1_RELEASED, 1), (B.BUTTON2_RELEASED, 2), (B.BUTTON3_RELEASED, 3)):
            if b & bit:
                events.append(("up", button))
        for bit, button, times in ((B.BUTTON1_CLICKED, 1, 1), (B.BUTTON1_DOUBLE_CLICKED, 1, 2),
                                   (B.BUTTON2_CLICKED, 2, 1), (B.BUTTON3_CLICKED, 3, 1)):
            if b & bit:
                events += [("down", button), ("up", button)] * times
        for name, button in (("BUTTON4_PRESSED", 4), ("BUTTON5_PRESSED", 5)):
            if b & getattr(B, name, 0):
                events.append(("wheel", button))
        if b & B.REPORT_MOUSE_POSITION and not events:
            events.append(("drag" if self.buttons else "move", 0))
        for kind, button in events:
            self.pointer_event(mx, my, kind, button)

    def pointer_event(self, mx, my, kind, button, shift=False):
        """One mouse event: kind is down, up, move, drag or wheel; button
        1 (left), 2 (middle), 3 (right), 4/5 (wheel up/down). Coordinates
        start at 0."""
        self.pointer = (mx, my)
        self.last_input = time.time()
        if kind == "down":
            self.buttons.add(button)
        elif kind == "up":
            self.buttons.discard(button)
        if os.environ.get("KB_DESK_DEBUG"):
            with open("/tmp/desk-mouse.log", "a") as log:
                log.write("%s %d at %d,%d drag=%s\n" % (kind, button, mx, my, bool(self.drag)))
        H, W = self.s.size()
        down = kind == "down" and button == 1

        # Moving or resizing: an outline follows the pointer and the window
        # goes there when the button is let go.
        if self.drag:
            what, win, dx, dy = self.drag
            if kind in ("drag", "move", "up"):
                if what == "move" and win.saved and (mx, my) != self.drag_start:
                    # Dragging a maximised window: it takes its normal size
                    # first (a click alone leaves it maximised).
                    self.maximise(win)
                    dx = min(dx, win.w - 2)
                    win.move(mx - dx, my - dy)
                    self.drag = (what, win, dx, dy)
                if what == "move":
                    self.outline = win.clamp_pos(mx - dx, my - dy) + (win.w, win.h)
                else:
                    self.outline = (win.x, win.y) + win.clamp_size(mx - win.x + 1, my - win.y + 1)
            if kind == "up" or down:
                if self.outline and win in self.windows:
                    x, y, w, h = self.outline
                    if what == "move":
                        win.move(x, y)
                    else:
                        win.resize(w, h)
                self.drag = self.outline = None
            return
        # Marking text: it is copied when the button is let go.
        if self.select:
            win = self.select["win"]
            if win in self.windows and kind in ("drag", "move", "up"):
                self.select["b"] = (max(0, min(win.cols() - 1, mx - win.x - 1)),
                                    max(0, min(win.rows() - 1, my - win.y - 1)))
            if kind == "up" or down:
                if win in self.windows and self.select["a"] != self.select["b"]:
                    self.copy(win.text(self.select["a"], self.select["b"]))
                self.select = None
            return
        if self.mode:
            if kind == "down":
                self.mode = None
            return
        if self.menus:
            if self.menu_pointer(mx, my, kind) or kind != "down":
                return
        if self.volume_open:
            x, y, w = self.volume_box()
            if kind in ("down", "drag") and y <= my < y + 4 and x <= mx < x + w:
                bar = w - 12
                if my == y + 1 and x + 2 <= mx <= x + 2 + bar:
                    self.set_volume("set", (mx - x - 2) * 100 // bar)
                return
            if kind == "down":
                self.volume_open = False
            else:
                return
        if kind == "down":
            for x, y, h, n in self.note_boxes():    # a click puts a note away
                if x <= mx < x + self.NOTE_W and y <= my < y + h:
                    self.notes.remove(n)
                    return
        if my == 0:
            if down:
                for x0, x1, action in self.bar_items:
                    if x0 <= mx < x1:
                        self.do(action)
            return
        if my == H - 1:
            if down:
                for x0, x1, win in self.task_buttons:
                    if x0 <= mx < x1:
                        if win is self.active():
                            win.minimised = True
                        else:
                            self.raise_(win)
            return
        # The topmost window under the pointer.
        for win in reversed(self.windows):
            if win.minimised or not win.contains(mx, my):
                continue
            if kind == "down" and win is not self.active():
                self.raise_(win)
            rx, ry = mx - win.x, my - win.y
            if ry == 0:                               # title bar
                if down:
                    now = time.time()
                    double = self.last_click[1] is win and now - self.last_click[0] < 0.45
                    self.last_click = (now, win)
                    if 1 <= rx <= 3:
                        win.close()
                    elif win.w - 7 <= rx <= win.w - 5:
                        win.minimised = True
                    elif win.w - 4 <= rx <= win.w - 2 or double:
                        self.maximise(win)
                    else:
                        self.drag = ("move", win, rx, 0)
                        self.drag_start = (mx, my)
                        self.outline = (win.x, win.y, win.w, win.h)
                return
            if ry == win.h - 1 and rx >= win.w - 2:   # lower right corner
                if down:
                    win.saved = None
                    self.drag = ("size", win, 0, 0)
                    self.outline = (win.x, win.y, win.w, win.h)
                return
            if not (1 <= rx < win.w - 1 and 1 <= ry < win.h - 1):
                return
            if kind == "down" and button == 2:        # middle button: paste
                self.paste()
                return
            listening = win.mouse_on()
            # Mark text: where the program leaves the mouse alone, or with Shift.
            if down and (shift or not listening):
                self.select = {"win": win, "a": (rx - 1, ry - 1), "b": (rx - 1, ry - 1)}
                return
            # Otherwise the event is the program's.
            if listening:
                code = {1: 0, 3: 2, 4: 64, 5: 65}.get(button, 0)
                if kind == "down":
                    win.send(b"\x1b[<%d;%d;%dM" % (code, rx, ry))
                elif kind == "up":
                    win.send(b"\x1b[<%d;%d;%dm" % (code, rx, ry))
                elif kind == "wheel":
                    win.send(b"\x1b[<%d;%d;%dM" % (code, rx, ry))
                elif kind == "drag" and (1002 << 5 in win.screen.mode or 1003 << 5 in win.screen.mode):
                    win.send(b"\x1b[<32;%d;%dM" % (rx, ry))
            return
        # The desktop itself: icons.
        icon = self.icon_at(mx, my)
        if kind == "down" and button == 3:
            self.icon_sel = icon
            if icon and icon["kind"] == "file":
                self.open_menu([("Open", "file:" + icon["path"], None),
                                ("Open with ...", "with:" + icon["path"], None),
                                ("Move to the trash", "trash:" + icon["path"], None)], mx, my)
            elif icon:
                self.open_menu([("Open", "app:" + icon["id"], None),
                                ("Take off the desktop", "unpin:" + icon["id"], None)], mx, my)
            else:
                self.open_menu(self.main_menu(), mx, my)
        elif down:
            now = time.time()
            double = icon is not None and self.last_click[1] is icon and now - self.last_click[0] < 0.6
            self.last_click = (now, icon)
            self.icon_sel = icon
            if double:
                self.open_icon(icon)
                self.last_click = (0, None)

    def key(self, k):
        # An Esc first: it may start a key's escape sequence that curses did
        # not recognise (on a slow machine a sequence can come in pieces).
        # Read the whole key here, so neither a program nor a menu ever sees
        # a lone Esc that was not typed.
        self.last_input = time.time()
        if k == "\x1b":
            seq, extra = self.read_escape()
            if seq == "\x1b\t":                 # Alt+Tab
                if not (self.menus or self.mode or self.volume_open):
                    self.cycle()
            elif seq in RAW_KEYS:                # an arrow, F-key, Home, ...
                self.key(RAW_KEYS[seq])
            elif self.menus or self.mode or self.volume_open:
                if seq == "\x1b":
                    self.modal_key("\x1b")
            elif self.active():
                self.active().send(seq.encode("utf-8"))
            if extra is not None:
                self.key(extra)
            return
        if k == curses.KEY_MOUSE:
            self.mouse()
            return
        if k == curses.KEY_RESIZE:
            H, W = self.area()
            for win in self.windows:
                win.resize(min(win.w, W), min(win.h, H))
                win.move(win.x, win.y)
            self.wall_key = None
            return
        if self.menus or self.mode or self.volume_open:
            self.modal_key(k)
            return
        if k == curses.KEY_F12:
            self.open_menu(self.main_menu(), 0, 1)
            return
        if k == curses.KEY_F11:
            self.paste()
            return
        win = self.active()
        if not win:
            return
        if isinstance(k, str):
            win.send(k.encode("utf-8"))
        elif k in APP_KEYS and DECCKM in win.screen.mode:
            win.send(APP_KEYS[k])
        elif k in KEYS:
            win.send(KEYS[k])

    def modal_key(self, k):
        """A key while a menu, the volume slider or keyboard moving is on."""
        if self.mode:
            win = self.active()
            dx = {curses.KEY_LEFT: -1, curses.KEY_RIGHT: 1}.get(k, 0)
            dy = {curses.KEY_UP: -1, curses.KEY_DOWN: 1}.get(k, 0)
            if win and (dx or dy):
                if self.mode == "move":
                    win.move(win.x + dx * 2, win.y + dy)
                else:
                    win.resize(win.w + dx * 2, win.h + dy)
            elif k in ("\n", "\r", " ", "\x1b", "\x03", "q", "Q", curses.KEY_ENTER, curses.KEY_F12) or not win:
                self.mode = None       # (never trap the keyboard in this mode)
        elif self.volume_open:
            self.volume_key(k)
        elif self.menus:
            self.menu_key(k)

    def read_escape(self):
        """After an Esc: the rest of its escape sequence, if one follows at
        once. Returns (sequence, extra) where extra is a key that arrived
        but does not belong to the sequence (or None)."""
        scr = self.s.scr
        seq, extra = "\x1b", None

        def more(ms):
            scr.timeout(ms)
            try:
                return scr.get_wch()
            except curses.error:
                return None

        c = more(80)
        if isinstance(c, str):
            seq += c
            if c == "O":                        # ESC O x: one more character
                c = more(80)
                if isinstance(c, str):
                    seq += c
                else:
                    extra = c
            elif c == "[":                      # CSI: up to its final byte
                while len(seq) < 16:
                    c = more(80)
                    if not isinstance(c, str):
                        extra = c
                        break
                    seq += c
                    if seq == "\x1b[[":         # the console's F1-F5: ESC [ [ A
                        continue
                    if "\x40" <= c <= "\x7e":
                        break
        elif c is not None:
            extra = c
        scr.nodelay(True)
        return seq, extra

    def log_error(self):
        """Something went wrong: note it and carry on, so one bad event or
        one odd piece of program output never ends every window."""
        import traceback
        try:
            path = os.path.expanduser("~/.cache/kilobyte-desk.log")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a") as log:
                log.write(time.strftime("--- %Y-%m-%d %H:%M:%S\n"))
                traceback.print_exc(file=log)
        except OSError:
            pass

    def run(self):
        errors = 0
        while True:
            for win in [w for w in self.windows if not w.alive]:
                self.windows.remove(win)
                if self.drag and self.drag[1] is win:
                    self.drag = self.outline = None
                if self.select and self.select["win"] is win:
                    self.select = None
                try:
                    os.waitpid(win.pid, os.WNOHANG)
                except ChildProcessError:
                    pass
            # Logging out: leave when the last window has closed (programs
            # that do not go by themselves are ended after three seconds).
            if self.quitting:
                if not self.windows:
                    return
                if time.time() - self.quitting > 3:
                    for w in self.windows:
                        w.close(signal.SIGKILL)
                    self.quitting = time.time()
            try:
                self.step()
                errors = 0
            except Exception:
                # One bad event, one odd piece of program output or a lost
                # mouse must not end every window. (If nothing works any
                # more, give up and let Kilobyte carry on without windows.)
                self.log_error()
                errors += 1
                if errors > 50:
                    raise
                time.sleep(0.05)

    def step(self):
        """Draw, wait for something to happen, deal with it."""
        self.draw()
        # The console mouse: gpm may be restarted (an update does that) or not
        # be running yet; look for it again every two seconds.
        if self.console and not self.gpm and time.time() >= self.gpm_retry:
            self.gpm = Gpm.open()
            self.gpm_retry = time.time() + 2
        self.status.poll()
        self.watch_status()
        self.idle()
        fds = [w.fd for w in self.windows] + [sys.stdin.fileno()]
        if self.gpm:
            fds.append(self.gpm.fd)
        if self.sock:
            fds.append(self.sock)
        try:
            ready, _, _ = select.select(fds, [], [], 1.0)
        except InterruptedError:
            return
        except (OSError, ValueError):
            self.drop_gpm()            # its descriptor went away
            return
        for win in self.windows:
            if win.fd in ready:
                try:
                    win.read()
                except Exception:
                    self.log_error()
        if self.sock and self.sock in ready:
            self.request()
        if self.gpm and self.gpm.fd in ready:
            events = self.gpm.events()
            if events is None:
                self.drop_gpm()
            for x, y, kind, button, shift in events or []:
                try:
                    self.pointer_event(x, y, kind, button, shift)
                except Exception:
                    self.log_error()
        if sys.stdin.fileno() in ready or not ready:
            while True:
                try:
                    k = self.s.scr.get_wch()
                except curses.error:
                    break
                try:
                    self.key(k)
                except Exception:
                    self.log_error()
        # Let more program output arrive before drawing again.
        time.sleep(0.01)

    # --- requests from programs (deskrun.py) -----------------------------------
    def request(self):
        """A program asks for something: the whole screen (kb-play for a
        video in a tiny pixel font or as the real picture, which a window
        cannot show; the lock screen), a window for a program, a note, or
        something for the clipboard."""
        try:
            conn, _ = self.sock.accept()
        except OSError:
            return
        rc = 0
        try:
            conn.settimeout(2)
            data = b""
            while not data.endswith(b"\n") and len(data) < 1 << 20:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data += chunk
            req = json.loads(data.decode("utf-8"))
            what = req.get("run")
            if what == "kb-play":
                args = [str(a) for a in req.get("args", [])]
                rc = self.full_screen([LIB + "/kb-play"] + args, req.get("cwd")) if args else 1
            elif what == "lock":
                rc = self.lock()
            elif what == "window":
                argv = [str(a) for a in req.get("argv", [])]
                if argv:
                    self.open_window(argv, str(req.get("title", ""))[:40], str(req.get("size", "M")))
                else:
                    rc = 1
            elif what == "notify":
                self.note(req.get("title", "Kilobyte"), req.get("text", ""))
            elif what == "clip":
                self.copy(str(req.get("text", "")))
            else:
                rc = 1
        except (OSError, ValueError):
            self.log_error()
            rc = 1
        try:
            conn.settimeout(2)
            conn.sendall(b"%d\n" % rc)
        except OSError:
            pass
        conn.close()

    def full_screen(self, argv, cwd=None):
        """Step aside: the program runs on the console itself, and the
        windows come back when it ends."""
        env = dict(os.environ)
        env.pop("KILOBYTE_DESK", None)
        env["KB_FULL_SCREEN"] = "1"
        curses.def_prog_mode()
        curses.endwin()
        # Ctrl+C is for the program, not for Kilobyte Windows.
        old_int = signal.signal(signal.SIGINT, signal.SIG_IGN)

        def child_signals():
            signal.signal(signal.SIGINT, signal.SIG_DFL)

        try:
            rc = subprocess.call(argv, cwd=cwd if cwd and os.path.isdir(cwd) else None, env=env,
                                 preexec_fn=child_signals)
        except OSError:
            rc = 1
        finally:
            signal.signal(signal.SIGINT, old_int)
            curses.reset_prog_mode()
            self.s.scr.clearok(True)               # paint everything again
            self.s.scr.refresh()
            self.wall_key = None
            if self.gpm:                           # what the mouse did meanwhile is old news
                if self.gpm.events() is None:
                    self.drop_gpm()
            self.drag = self.outline = self.select = None
            self.buttons.clear()
            self.last_input = time.time()
        return rc

    def lock(self):
        self.menus = []
        return self.full_screen(["python3", LIB + "/py/lock.py"])

    def idle(self):
        """The screen saver, after the minutes set in Settings; then the
        lock screen, if that is wanted."""
        now = time.time()
        if now - self.idle_checked < 5:
            return
        self.idle_checked = now

        def setting(name, default):
            try:
                with open(os.path.join(deskbg.CONF, name), encoding="utf-8") as f:
                    return f.read().strip() or default
            except OSError:
                return default

        mode = setting("saver-mode", "random")
        minutes = setting("saver-minutes", "5")
        if mode == "off" or not minutes.isdigit() or int(minutes) < 1:
            return
        if now - self.last_input >= int(minutes) * 60:
            self.full_screen([LIB + "/apps/saver", mode])
            if os.path.exists(os.path.join(deskbg.CONF, "saver-lock")):
                self.lock()

    def drop_gpm(self):
        """The connection to gpm is gone: forget it and any drag in progress."""
        if self.gpm:
            self.gpm.close()
        self.gpm = None
        self.gpm_retry = time.time() + 2
        self.drag = self.outline = self.select = None
        self.buttons.clear()
        self.pointer = None


if __name__ == "__main__":
    argv = sys.argv[1:] or ["kilobyte"]
    os.environ.setdefault("ESCDELAY", "100")
    # On the console Kilobyte Windows reads gpm itself; the curses mouse must
    # stay off there, or ncurses opens gpm too and takes events from the same
    # connection.
    console = os.environ.get("TERM") == "linux"

    def main(s):
        desk = Desk(s, argv)
        try:
            desk.run()
        finally:
            if desk.sock_path:
                try:
                    os.unlink(desk.sock_path)
                except OSError:
                    pass

    kbui.run(main, mouse=not console)
