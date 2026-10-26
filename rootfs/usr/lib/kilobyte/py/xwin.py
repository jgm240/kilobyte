#!/usr/bin/python3
"""Open program in X: the picture of an X server that draws into memory
(Xvfb, started by kb-xwin), shown in this window, as real pixels where the
screen allows (fbwin.py) or else as coloured half blocks; the mouse and the
keys go on to the programs in it (xdotool).

    xwin.py DISPLAY WIDTHxHEIGHT PID TITLE

It ends when the program (PID) and every window it opened are gone, or with
F9 > Close the program. F9 has the menu: the picture (real or blocks), zoom
(the whole X screen, or its pixels one to one, moving along at the edges),
keys that cannot be typed here (Alt+F4, Ctrl+Alt+...) and closing.
"""
import curses
import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fbwin  # noqa: E402
import kbui  # noqa: E402
from kbui import BLACK, BLUE, CYAN, LIGHTGREY, WHITE, YELLOW  # noqa: E402

KEYS = {
    curses.KEY_UP: "Up", curses.KEY_DOWN: "Down", curses.KEY_LEFT: "Left", curses.KEY_RIGHT: "Right",
    curses.KEY_HOME: "Home", curses.KEY_END: "End", curses.KEY_PPAGE: "Prior", curses.KEY_NPAGE: "Next",
    curses.KEY_DC: "Delete", curses.KEY_IC: "Insert", curses.KEY_BACKSPACE: "BackSpace", curses.KEY_ENTER: "Return",
    curses.KEY_BTAB: "shift+Tab", curses.KEY_SR: "shift+Up", curses.KEY_SF: "shift+Down",
    curses.KEY_SLEFT: "shift+Left", curses.KEY_SRIGHT: "shift+Right", curses.KEY_SHOME: "shift+Home",
    curses.KEY_SEND: "shift+End",
    "\n": "Return", "\r": "Return", "\t": "Tab", "\x1b": "Escape", "\x7f": "BackSpace", "\b": "BackSpace",
}
for _n in range(1, 13):
    if _n != 9:                                    # (F9: this program's menu)
        KEYS[curses.KEY_F0 + _n] = "F%d" % _n
MENU_KEYS = [("alt+F4", "Alt+F4: close the program's window"), ("ctrl+alt+Delete", "Ctrl+Alt+Del"),
             ("alt+Tab", "Alt+Tab: the next window"), ("F9", "F9 itself"), ("ctrl+c", "Ctrl+C"),
             ("super", "The Windows key")]


def xdo(display, *args):
    try:
        subprocess.run(["xdotool"] + list(args), env=dict(os.environ, DISPLAY=display),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


def alive(pid):
    try:
        with open("/proc/%d/stat" % pid) as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return False


class Grab:
    """Frames of a part of the X screen from ffmpeg (x11grab), scaled: only
    the newest one is kept."""

    def __init__(self, display, region, out, fmt, fps):
        rx, ry, rw, rh = region
        self.size = out[0] * out[1] * (4 if fmt == "bgr0" else 3)
        self.frame, self.count, self.error = None, 0, None
        self.p = subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", "-nostdin", "-f", "x11grab", "-draw_mouse", "0",
             "-framerate", str(fps), "-video_size", "%dx%d" % (rw, rh), "-i", "%s+%d,%d" % (display, rx, ry),
             "-vf", "scale=%d:%d:flags=area" % out, "-pix_fmt", fmt, "-f", "rawvideo", "-"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        while True:
            data = self.p.stdout.read(self.size)
            if len(data) < self.size:
                err = self.p.stderr.read().decode("utf-8", "replace").strip().splitlines()
                self.error = err[-1] if err else "the picture stopped"
                return
            self.frame = data
            self.count += 1

    def stop(self):
        try:
            self.p.kill()
            self.p.wait(timeout=2)
        except (OSError, subprocess.SubprocessError):
            pass


class View:
    def __init__(self, s, display, size, pid, title):
        self.s, self.display, self.pid, self.title = s, display, pid, title
        self.xw, self.xh = (int(v) for v in size.split("x"))
        self.fb = self.place = None
        self.real = False
        if not fbwin.check():
            try:
                self.fb = fbwin.Framebuffer()
                self.place = fbwin.Place(self.fb)
                self.real = True
            except OSError:
                pass
        self.zoom = False
        self.origin = [0, 0]                       # zoomed in: the X screen's pixel at the top left
        self.grab = None
        self.geometry = None                       # what the grab was made for
        self.colours = {}
        self.shown = []                            # blocks: the rows last drawn
        self.layout = None                         # (region, out, offset) as last used
        self.menu = None
        self.typed = ""
        self.mouse_at = None
        self.buttons = 0
        self.gone_since = None
        self.message = ""

    # --- the picture ------------------------------------------------------------
    def fit(self, w, h):
        """The size the whole X screen takes in w x h, keeping its shape."""
        scale = min(w / self.xw, h / self.xh)
        return max(2, int(self.xw * scale) // 2 * 2), max(2, int(self.xh * scale) // 2 * 2)

    def plan(self):
        """(region of the X screen, output size, offset in the output units,
        pixel format), or None when there is nothing to show now."""
        if self.real:
            where = self.place.update()
            if not where:
                return None
            _, _, w, h, _ = where
        else:
            hh, ww = self.s.size()
            w, h = ww, (hh - 1) * 2
        if self.zoom:
            rw, rh = min(w, self.xw), min(h, self.xh)
            ox = max(0, min(self.origin[0], self.xw - rw))
            oy = max(0, min(self.origin[1], self.xh - rh))
            self.origin = [ox, oy]
            region, out = (ox, oy, rw, rh), (rw, rh)
        else:
            region, out = (0, 0, self.xw, self.xh), self.fit(w, h)
        offset = ((w - out[0]) // 2, (h - out[1]) // 2 // 2 * 2)
        return region, out, offset, ("bgr0" if self.real else "rgb24")

    def picture(self):
        plan = self.plan() if not self.menu else None
        if plan != self.geometry:
            if self.grab:
                self.grab.stop()
                self.grab = None
            if self.real and self.place:
                self.place.repaint()
            self.geometry, self.shown = plan, []
            if plan:
                region, out, _, fmt = plan
                self.grab = Grab(self.display, region, out, fmt, 12 if self.real else 8)
                self.drawn = (-1, 0)
            if not self.real:
                self.s.fill(LIGHTGREY, BLACK)
            self.layout = plan
        if not self.grab:
            return
        if self.grab.error:
            self.message = "The picture stopped: " + self.grab.error
            return
        frame, count = self.grab.frame, self.grab.count
        if frame is None:
            return
        region, out, offset, _ = plan
        if self.real:
            # Again even without a new frame, now and then: something may have
            # been drawn over it (the pointer's old place).
            if count != self.drawn[0] or time.time() - self.drawn[1] > 0.2:
                x, y, _, _, hole = self.place.update() or (0, 0, 0, 0, None)
                self.fb.blit(frame, out[0], out[1], x + offset[0], y + offset[1], hole)
                self.drawn = (count, time.time())
        elif count != self.drawn[0]:
            self.blocks(frame, out, offset)
            self.drawn = (count, time.time())

    def blocks(self, raw, out, offset):
        """Two rows of pixels a line of half blocks; only lines that changed."""
        w, h = out
        x0, y0 = offset[0], offset[1] // 2
        put, colours = self.s.put, self.colours
        row_bytes = w * 3
        if len(self.shown) != h // 2:
            self.shown = [None] * (h // 2)
        for cy in range(h // 2):
            a = 2 * cy * row_bytes
            pair = raw[a:a + 2 * row_bytes]
            if pair == self.shown[cy]:
                continue
            self.shown[cy] = pair
            run, run_attr, run_x = [], None, 0
            for cx in range(w):
                cells = []
                for i in (cx * 3, row_bytes + cx * 3):
                    key = pair[i:i + 3]
                    c = colours.get(key)
                    if c is None:
                        c = colours[key] = kbui.nearest((key[0], key[1], key[2]))
                    cells.append(c)
                top, bot = cells
                if top == bot:
                    cell = (kbui.FULL if top >= 8 else " ", top, top & 7)
                elif top >= 8 or bot < 8:
                    cell = (kbui.UPPER, top, bot & 7)
                else:
                    cell = (kbui.LOWER, bot, top & 7)
                if cell[1:] != run_attr:
                    if run:
                        put(y0 + cy, x0 + run_x, "".join(run), *run_attr)
                    run, run_attr, run_x = [], cell[1:], cx
                run.append(cell[0])
            if run:
                put(y0 + cy, x0 + run_x, "".join(run), *run_attr)

    # --- the mouse and the keys -------------------------------------------------
    def to_x(self, mx, my):
        """The X screen's pixel under the cell mx, my of this window."""
        if not self.layout:
            return None
        region, out, offset, _ = self.layout
        if self.real:
            cw, ch = getattr(self.place, "cell", (8, 16))
            u, v = (mx + 0.5) * cw - offset[0], (my + 0.5) * ch - offset[1]
        else:
            u, v = mx - offset[0] + 0.5, my * 2 + 1 - offset[1]
        if not (0 <= u < out[0] and 0 <= v < out[1]):
            return None
        return int(region[0] + u * region[2] / out[0]), int(region[1] + v * region[3] / out[1])

    def pan(self, mx, my):
        """Zoomed in: the mouse at an edge of the picture moves it along."""
        if not self.zoom or not self.layout:
            return
        hh, ww = self.s.size()
        region = self.layout[0]
        dx = -region[2] // 4 if mx <= 0 else region[2] // 4 if mx >= ww - 1 else 0
        dy = -region[3] // 4 if my <= 0 else region[3] // 4 if my >= hh - 2 else 0
        if dx or dy:
            self.origin = [self.origin[0] + dx, self.origin[1] + dy]

    def mouse(self):
        try:
            _, mx, my, _, b = curses.getmouse()
        except curses.error:
            return
        if self.menu:
            if b & (curses.BUTTON1_CLICKED | curses.BUTTON1_RELEASED):
                self.menu_click(mx, my)
            return
        self.pan(mx, my)
        at = self.to_x(mx, my)
        if not at:
            return
        d = self.display
        if at != self.mouse_at:
            xdo(d, "mousemove", str(at[0]), str(at[1]))
            self.mouse_at = at
        for n, (press, release, click, double) in enumerate((
                (curses.BUTTON1_PRESSED, curses.BUTTON1_RELEASED, curses.BUTTON1_CLICKED, curses.BUTTON1_DOUBLE_CLICKED),
                (curses.BUTTON2_PRESSED, curses.BUTTON2_RELEASED, curses.BUTTON2_CLICKED, curses.BUTTON2_DOUBLE_CLICKED),
                (curses.BUTTON3_PRESSED, curses.BUTTON3_RELEASED, curses.BUTTON3_CLICKED, curses.BUTTON3_DOUBLE_CLICKED)), 1):
            if b & press:
                xdo(d, "mousedown", str(n))
                self.buttons |= 1 << n
            if b & release:
                xdo(d, "mouseup", str(n))
                self.buttons &= ~(1 << n)
            if b & click:
                xdo(d, "click", str(n))
            if b & double:
                xdo(d, "click", "--repeat", "2", str(n))
        if b & curses.BUTTON4_PRESSED:
            xdo(d, "click", "4")
        if b & getattr(curses, "BUTTON5_PRESSED", 0x200000):
            xdo(d, "click", "5")

    def key(self, k):
        if k == curses.KEY_F9:
            self.open_menu()
            return
        if k == curses.KEY_RESIZE:
            self.geometry = "again"                 # (a new size: a new grab)
            self.s.fill(LIGHTGREY, BLACK)
            return
        if k == curses.KEY_MOUSE:
            self.mouse()
            return
        if self.menu:
            self.menu_key(k)
            return
        if isinstance(k, str) and k.isprintable():
            self.typed += k
            return
        self.flush_typed()
        if k in KEYS:
            xdo(self.display, "key", "--clearmodifiers", KEYS[k])
        elif isinstance(k, str) and len(k) == 1 and 1 <= ord(k) <= 26:
            xdo(self.display, "key", "--clearmodifiers", "ctrl+" + chr(ord(k) + 96))

    def flush_typed(self):
        if self.typed:
            xdo(self.display, "type", "--clearmodifiers", "--delay", "0", "--", self.typed)
            self.typed = ""

    # --- F9: the menu -----------------------------------------------------------
    def menu_items(self):
        items = []
        if self.fb:
            items.append(("real", "Picture: %s" % ("real pixels (B: blocks instead)" if self.real else "blocks (R: real pixels instead)")))
        items.append(("zoom", "Zoom: %s" % ("pixels one to one (Z: the whole screen)" if self.zoom else "the whole screen (Z: pixels one to one)")))
        items += [("key:" + k, "Press " + t) for k, t in MENU_KEYS]
        items += [("close", "Close the program"), ("back", "Back to the program (Esc)")]
        return items

    def open_menu(self):
        self.menu = {"sel": 0}

    def menu_box(self):
        hh, ww = self.s.size()
        items = self.menu_items()
        w = min(ww - 2, max(len(t) for _, t in items) + 6)
        h = len(items) + 2
        return max(0, (ww - w) // 2), max(0, (hh - 1 - h) // 2), w, h, items

    def draw_menu(self):
        x, y, w, h, items = self.menu_box()
        self.s.box(y, x, h, w, BLACK, LIGHTGREY, title=" " + self.title[:w - 6] + " ")
        for i, (_, text) in enumerate(items):
            on = i == self.menu["sel"]
            self.s.put(y + 1 + i, x + 1, (" " + text).ljust(w - 2)[:w - 2], WHITE if on else BLACK, BLUE if on else LIGHTGREY)

    def menu_click(self, mx, my):
        x, y, w, h, items = self.menu_box()
        if x < mx < x + w - 1 and y < my < y + h - 1:
            self.menu["sel"] = my - y - 1
            self.menu_do(items[self.menu["sel"]][0])
        else:
            self.close_menu()

    def menu_key(self, k):
        items = self.menu_items()
        if k == curses.KEY_UP:
            self.menu["sel"] = (self.menu["sel"] - 1) % len(items)
        elif k == curses.KEY_DOWN:
            self.menu["sel"] = (self.menu["sel"] + 1) % len(items)
        elif k in ("\n", "\r", curses.KEY_ENTER):
            self.menu_do(items[self.menu["sel"]][0])
        elif k == "\x1b":
            self.close_menu()
        elif isinstance(k, str) and k.lower() in "brz":
            self.menu_do({"b": "real", "r": "real", "z": "zoom"}[k.lower()])

    def close_menu(self):
        self.menu = None
        self.s.fill(LIGHTGREY, BLACK)
        self.shown = []

    def menu_do(self, what):
        if what == "real":
            self.real = not self.real and bool(self.fb)
        elif what == "zoom":
            self.zoom = not self.zoom
        elif what.startswith("key:"):
            xdo(self.display, "key", what[4:])
        elif what == "close":
            self.closing = True
        self.close_menu()

    # --- the program -------------------------------------------------------------
    def windows_left(self):
        try:
            out = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", "."],
                                 env=dict(os.environ, DISPLAY=self.display),
                                 capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            return False
        return bool(out.split())

    def finished(self):
        if alive(self.pid):
            self.gone_since = None
            return False
        # The program may have started others and ended (a launcher): their windows count.
        now = time.time()
        if self.gone_since is None or now - self.gone_since > 2:
            if self.windows_left():
                self.gone_since = now
                return False
            return True
        return False

    def status(self):
        hh, ww = self.s.size()
        if self.message:
            text, fg = " " + self.message, YELLOW
        else:
            text, fg = " %s   F9: picture, zoom, keys, close" % self.title, WHITE
        self.s.put(hh - 1, 0, text[:ww - 1].ljust(ww - 1), fg, BLUE if not self.menu else CYAN)

    def run(self):
        s = self.s
        curses.raw()                               # (Ctrl+C and the others go to the program)
        s.scr.timeout(30)
        s.fill(LIGHTGREY, BLACK)
        self.closing = False
        last_check = 0
        while not self.closing:
            self.picture()
            if self.menu:
                self.draw_menu()
            self.status()
            s.scr.refresh()
            try:
                k = s.scr.get_wch()
            except curses.error:
                k = None
            if k is not None:
                self.key(k)
                s.scr.timeout(0)                    # (what was typed: in one go)
                continue
            s.scr.timeout(30)
            self.flush_typed()
            now = time.time()
            if now - last_check > 0.5:
                last_check = now
                if self.finished():
                    break
        if self.grab:
            self.grab.stop()
        if self.place:
            self.place.repaint()


def main(argv):
    if len(argv) < 4:
        sys.exit(__doc__)
    os.environ.setdefault("ESCDELAY", "25")
    try:
        curses.wrapper(lambda scr: View(kbui.Screen(scr, mouse=True), argv[0], argv[1], int(argv[2]), argv[3]).run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
