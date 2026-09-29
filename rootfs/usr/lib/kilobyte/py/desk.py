#!/usr/bin/python3
"""Kilobyte Windows: movable windows and multitasking in text mode.

Every window is a terminal of its own (a pseudo terminal, emulated with
pyte) running a program, normally a Program Manager. Windows have a title
bar, a close box [■], minimise [▼] and maximise [▲] boxes and a shadow; the
active one has a double frame. A taskbar at the bottom lists all windows.

Mouse: drag a title bar to move a window, drag its lower right corner to
resize it, double-click a title bar to maximise. Clicks inside a window go
to its program. Keys: Alt+Tab next window, F12 the window menu (new, move,
resize, maximise, minimise, tile, cascade, close, leave).

    desk [PROGRAM [ARGS...]]     first window runs PROGRAM (default: kilobyte)
"""
import ctypes
import curses
import fcntl
import os
import pty
import select
import signal
import struct
import sys
import termios
import time

sys.path.insert(0, "/usr/lib/kilobyte/py")
import kbui  # noqa: E402
from kbui import (BLACK, BLUE, CYAN, DARKGREY, LIGHTGREY, WHITE, YELLOW,  # noqa: E402
                  RGB, nearest)

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
        """Read one gpm event -> list of (x, y, kind, button)."""
        ev = self.Event()
        if self.lib.Gpm_GetEvent(ctypes.byref(ev)) <= 0:
            return []
        if os.environ.get("KB_DESK_DEBUG"):
            with open("/tmp/desk-mouse.log", "a") as log:
                log.write("raw buttons=%d dx=%d dy=%d x=%d y=%d type=%d clicks=%d vc=%d\n"
                          % (ev.buttons, ev.dx, ev.dy, ev.x, ev.y, ev.type, ev.clicks, ev.vc))
        x, y = ev.x - 1, ev.y - 1
        button = 1 if ev.buttons & self.B_LEFT else 3 if ev.buttons & self.B_RIGHT else 0
        if ev.wdy or ev.buttons & (self.B_UP | self.B_DOWN):
            return [(x, y, "wheel", 4 if (ev.wdy > 0 or ev.buttons & self.B_UP) else 5)]
        if ev.type & self.DOWN:
            return [(x, y, "down", button)]
        if ev.type & self.UP:
            return [(x, y, "up", button or 1)]
        if ev.type & self.DRAG:
            return [(x, y, "drag", button)]
        return [(x, y, "move", 0)]


class Window:
    def __init__(self, desk, argv, x, y, w, h, title="Program Manager"):
        self.desk = desk
        self.x, self.y, self.w, self.h = x, y, w, h
        self.title = title
        self.saved = None                  # position before maximising
        self.minimised = False
        self.screen = pyte.Screen(w - 2, h - 2)
        self.screen.set_mode(pyte.modes.LNM)
        self.stream = pyte.ByteStream(self.screen)
        self.alive = True
        pid, fd = pty.fork()
        if pid == 0:
            env = dict(os.environ, TERM="xterm", KILOBYTE_DESK="1", COLORTERM="",
                       KB_DESK_PID=str(os.getppid()),
                       NCURSES_NO_UTF8_ACS="1")   # real box characters, not VT100 line mode
            env.pop("KILOBYTE", None)
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

    def resize(self, w, h):
        H, W = self.desk.area()
        w, h = max(MIN_W, min(w, W)), max(MIN_H, min(h, H))
        if (w, h) == (self.w, self.h):
            return
        self.w, self.h = w, h
        self.screen.resize(self.rows(), self.cols())
        self.set_size()                    # the kernel sends the program SIGWINCH

    def move(self, x, y):
        H, W = self.desk.area()
        self.x = max(-self.w + 8, min(x, W - 8))
        self.y = max(1, min(y, H))

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

    def close(self):
        try:
            os.killpg(os.getpgid(self.pid), signal.SIGHUP)
        except (ProcessLookupError, PermissionError):
            pass

    def mouse_on(self):
        modes = self.screen.mode
        return any(m << 5 in modes for m in (1000, 1002, 1003))

    def contains(self, mx, my):
        return self.x <= mx < self.x + self.w and self.y <= my < self.y + self.h


class Desk:
    def __init__(self, s, argv):
        self.s = s
        self.first_argv = argv
        self.windows = []                  # bottom to top; the last is active
        self.drag = None                   # ("move"|"size", window, dx, dy)
        self.pointer = None                # where the mouse is, drawn as a block
        self.buttons = set()               # mouse buttons held down
        # The console mouse straight from gpm (ncurses' gpm is off, see main).
        self.gpm = Gpm.open() if os.environ.get("TERM") == "linux" else None
        if not self.gpm and os.environ.get("TERM") == "linux":
            curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)   # clicks at least
        self.last_click = (0, None)
        self.menu = None
        s.scr.nodelay(True)
        s.scr.keypad(True)
        curses.raw()
        signal.signal(signal.SIGCHLD, lambda *a: None)
        # "Log out" in any window: close them all.
        signal.signal(signal.SIGUSR1, lambda *a: [w.close() for w in self.windows])
        self.new_window(argv, maximised=True)

    def area(self):
        H, W = self.s.size()
        return H - 2, W                    # rows 1..H-2 are the desktop

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

    # --- drawing --------------------------------------------------------
    def draw_desktop(self):
        H, W = self.s.size()
        for y in range(1, H - 1):
            self.s.put(y, 0, "░" * W, LIGHTGREY, BLUE)

    def draw_bars(self):
        """Menu bar and taskbar: drawn last, so windows never cover them."""
        H, W = self.s.size()
        clock = time.strftime("%a %d %b  %H:%M")
        bar = " ■ Kilobyte  │  [New window]  │  F12 window menu   Alt+Tab next window"
        self.s.put(0, 0, bar.ljust(W - len(clock) - 1)[:max(0, W - len(clock) - 1)] + clock + " ", BLACK, LIGHTGREY)
        self.s.put(0, 1, "■", kbui.RED, LIGHTGREY)
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
        s.put(y, x + 1, "[■]", frame_fg, frame_bg)
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

    def draw(self):
        self.draw_desktop()
        act = self.active()
        for win in self.windows:
            if not win.minimised:
                self.draw_window(win, win is act)
        self.draw_bars()
        if self.menu:
            self.draw_menu()
        # The mouse pointer: the cell under it in reverse colours.
        if self.pointer:
            px, py = self.pointer
            H, W = self.s.size()
            if 0 <= px < W and 0 <= py < H:
                try:
                    self.s.scr.chgat(py, px, 1, curses.A_REVERSE)
                except curses.error:
                    pass
        # The cursor of the active window's program.
        if act and not act.screen.cursor.hidden and not self.menu:
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

    # --- the F12 window menu -------------------------------------------
    MENU = [("n", "New window"), ("m", "Move (arrow keys, Enter)"), ("r", "Resize (arrow keys, Enter)"),
            ("x", "Maximise / restore"), ("i", "Minimise"), ("t", "Tile all windows"), ("c", "Cascade windows"),
            ("w", "Close this window"), ("q", "Leave windows (close all)")]

    def draw_menu(self):
        H, W = self.s.size()
        w = 34
        x, y = (W - w) // 2, max(1, (H - len(self.MENU) - 2) // 2)
        self.s.box(y, x, len(self.MENU) + 2, w, BLACK, LIGHTGREY, title="Window")
        for i, (key, label) in enumerate(self.MENU):
            sel = i == self.menu["sel"]
            fg, bg = (WHITE, BLACK) if sel else (BLACK, LIGHTGREY)
            self.s.put(y + 1 + i, x + 1, f" {key.upper()}  {label}".ljust(w - 2), fg, bg)
            self.s.put(y + 1 + i, x + 2, key.upper(), kbui.RED if not sel else YELLOW, bg)
        self.menu["box"] = (x, y, w)

    def menu_key(self, k):
        m = self.menu
        if m.get("mode") in ("move", "resize"):
            win = self.active()
            dx = {curses.KEY_LEFT: -1, curses.KEY_RIGHT: 1}.get(k, 0)
            dy = {curses.KEY_UP: -1, curses.KEY_DOWN: 1}.get(k, 0)
            if win and (dx or dy):
                if m["mode"] == "move":
                    win.move(win.x + dx * 2, win.y + dy)
                else:
                    win.resize(win.w + dx * 2, win.h + dy)
            elif k in (10, 13, 27, curses.KEY_ENTER):
                self.menu = None
            return
        if k in (27, curses.KEY_F12):
            self.menu = None
        elif k == curses.KEY_UP:
            m["sel"] = (m["sel"] - 1) % len(self.MENU)
        elif k == curses.KEY_DOWN:
            m["sel"] = (m["sel"] + 1) % len(self.MENU)
        elif k in (10, 13, curses.KEY_ENTER):
            self.menu_do(self.MENU[m["sel"]][0])
        elif isinstance(k, str) and k.lower() in dict(self.MENU):
            self.menu_do(k.lower())

    def menu_do(self, key):
        win = self.active()
        self.menu = None
        if key == "n":
            self.new_window()
        elif key in ("m", "r") and win:
            if win.saved:
                self.maximise(win)
            self.menu = {"mode": "move" if key == "m" else "resize", "sel": 0}
        elif key == "x" and win:
            self.maximise(win)
        elif key == "i" and win:
            win.minimised = True
        elif key == "t":
            self.tile()
        elif key == "c":
            self.cascade()
        elif key == "w" and win:
            win.close()
        elif key == "q":
            for w in self.windows:
                w.close()

    # --- input ----------------------------------------------------------
    def mouse(self):
        """A curses mouse event (terminal emulators) -> pointer events."""
        try:
            _, mx, my, _, b = curses.getmouse()
        except curses.error:
            return
        B = curses
        events = []
        for bit, button in ((B.BUTTON1_PRESSED, 1), (B.BUTTON3_PRESSED, 3)):
            if b & bit:
                events.append(("down", button))
        for bit, button in ((B.BUTTON1_RELEASED, 1), (B.BUTTON3_RELEASED, 3)):
            if b & bit:
                events.append(("up", button))
        for bit, button, times in ((B.BUTTON1_CLICKED, 1, 1), (B.BUTTON1_DOUBLE_CLICKED, 1, 2), (B.BUTTON3_CLICKED, 3, 1)):
            if b & bit:
                events += [("down", button), ("up", button)] * times
        for name, button in (("BUTTON4_PRESSED", 4), ("BUTTON5_PRESSED", 5)):
            if b & getattr(B, name, 0):
                events.append(("wheel", button))
        if b & B.REPORT_MOUSE_POSITION and not events:
            events.append(("drag" if self.buttons else "move", 0))
        for kind, button in events:
            self.pointer_event(mx, my, kind, button)

    def pointer_event(self, mx, my, kind, button):
        """One mouse event: kind is down, up, move, drag or wheel; button
        1 (left), 3 (right), 4/5 (wheel up/down). Coordinates start at 0."""
        self.pointer = (mx, my)
        if kind == "down":
            self.buttons.add(button)
        elif kind == "up":
            self.buttons.discard(button)
        if os.environ.get("KB_DESK_DEBUG"):
            with open("/tmp/desk-mouse.log", "a") as log:
                log.write("%s %d at %d,%d drag=%s\n" % (kind, button, mx, my, bool(self.drag)))
        H, W = self.s.size()
        down = kind == "down" and button == 1

        # A window being moved or resized follows the pointer.
        if self.drag:
            what, win, dx, dy = self.drag
            if kind in ("drag", "move", "up"):
                if what == "move":
                    win.move(mx - dx, my - dy)
                else:
                    win.resize(mx - win.x + 1, my - win.y + 1)
            if kind == "up" or down:
                self.drag = None
            return
        if self.menu:
            if down:
                x, y, w = self.menu.get("box", (0, 0, 0))
                if x <= mx < x + w and y < my <= y + len(self.MENU):
                    self.menu_do(self.MENU[my - y - 1][0])
                else:
                    self.menu = None
            return
        if my == 0:
            if down:
                if 14 <= mx < 29:
                    self.new_window()
                elif mx < 40:
                    self.menu = {"sel": 0}
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
            if down and win is not self.active():
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
                        if win.saved:                 # dragging a maximised window restores it
                            self.maximise(win)
                            win.move(mx - min(rx, win.w - 2), my)
                            rx = mx - win.x
                        self.drag = ("move", win, rx, 0)
                return
            if ry == win.h - 1 and rx >= win.w - 2:   # lower right corner
                if down:
                    win.saved = None
                    self.drag = ("size", win, 0, 0)
                return
            # Inside: hand the event to the program if it listens to the mouse.
            if 1 <= rx < win.w - 1 and 1 <= ry < win.h - 1 and win.mouse_on():
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

    def key(self, k):
        if self.menu:
            self.menu_key(k)
            return
        if k == curses.KEY_F12:
            self.menu = {"sel": 0}
            return
        if k == curses.KEY_MOUSE:
            self.mouse()
            return
        if k == curses.KEY_RESIZE:
            H, W = self.area()
            for win in self.windows:
                win.resize(min(win.w, W), min(win.h, H))
                win.move(win.x, win.y)
            return
        win = self.active()
        if k == "\x1b":
            self.escape(win)
            return
        if not win:
            return
        if isinstance(k, str):
            win.send(k.encode("utf-8"))
        elif k in APP_KEYS and DECCKM in win.screen.mode:
            win.send(APP_KEYS[k])
        elif k in KEYS:
            win.send(KEYS[k])

    def escape(self, win):
        """An Esc arrived on its own: curses did not recognise what follows
        (on a slow machine a key's escape sequence can come in pieces). Read
        the rest of the sequence here and pass the whole key on in one write,
        so the program never sees a lone Esc (which closes dialogs)."""
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
        if seq == "\x1b\t":
            self.cycle()
        elif RAW_KEYS.get(seq) == curses.KEY_F12:
            self.menu = {"sel": 0}
        elif win:
            key = RAW_KEYS.get(seq)
            if key is not None and key in APP_KEYS and DECCKM in win.screen.mode:
                win.send(APP_KEYS[key])
            elif key is not None and key in KEYS:
                win.send(KEYS[key])
            else:
                win.send(seq.encode("utf-8"))
        if extra is not None:
            self.key(extra)

    def run(self):
        while True:
            for win in [w for w in self.windows if not w.alive]:
                self.windows.remove(win)
                try:
                    os.waitpid(win.pid, os.WNOHANG)
                except ChildProcessError:
                    pass
            if not self.windows:
                return
            self.draw()
            fds = [w.fd for w in self.windows] + [sys.stdin.fileno()]
            if self.gpm:
                fds.append(self.gpm.fd)
            try:
                ready, _, _ = select.select(fds, [], [], 1.0)
            except InterruptedError:
                continue
            for win in self.windows:
                if win.fd in ready:
                    win.read()
            if self.gpm and self.gpm.fd in ready:
                for x, y, kind, button in self.gpm.events():
                    try:
                        self.pointer_event(x, y, kind, button)
                    except Exception:
                        import traceback
                        with open(os.path.expanduser("~/.cache/kilobyte-desk.log"), "a") as log:
                            traceback.print_exc(file=log)
            if sys.stdin.fileno() in ready or not ready:
                while True:
                    try:
                        k = self.s.scr.get_wch()
                    except curses.error:
                        break
                    try:
                        self.key(k)
                    except Exception:           # one bad key must not end every window
                        import traceback
                        with open(os.path.expanduser("~/.cache/kilobyte-desk.log"), "a") as log:
                            traceback.print_exc(file=log)
            # Let more program output arrive before drawing again.
            time.sleep(0.01)


if __name__ == "__main__":
    argv = sys.argv[1:] or ["kilobyte"]
    os.environ.setdefault("ESCDELAY", "100")
    # On the console Kilobyte Windows reads gpm itself; the curses mouse must
    # stay off there, or ncurses opens gpm too and takes events from the same
    # connection.
    console = os.environ.get("TERM") == "linux"
    kbui.run(lambda s: Desk(s, argv).run(), mouse=not console)
