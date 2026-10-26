#!/usr/bin/python3
"""The real picture in a window: a video (the Video Player's and the Camera's
"Real picture") or graphical programs (Open program in X, Windows programs)
drawn as real pixels straight into the screen (the framebuffer, /dev/fb0),
where the window is.

    fbwin.py check                      status 0 when it can be done here
    fbwin.py xsize                      a good size for an X screen shown in a
                                        window here (WIDTHxHEIGHT: a maximised
                                        window's inside), if it can be done
    fbwin.py play SOURCE [MPV-OPTIONS]  play a video in this window (with
                                        mpv's library); status 125 when the
                                        real picture cannot be shown here

It needs the text console of a computer with a framebuffer of 32 bits a pixel.
In Kilobyte Desktop it draws into the window it runs in; while anything is
over the window (another window, a menu, a note) it draws nothing, and the
window shows its text. The mouse pointer's cells are left free. Without
windows, the whole screen is the window.

Keys while playing: Space pause, arrows seek, 9/0 volume, q or Esc stop.
"""
import ctypes
import curses
import fcntl
import json
import os
import re
import socket
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kbui  # noqa: E402
from kbui import BLACK, BLUE, LIGHTGREY, WHITE, YELLOW  # noqa: E402

FB = "/dev/fb0"
FBIOGET_VSCREENINFO = 0x4600


def console_tty():
    """The text console this runs on (tty3), or None (a terminal window, SSH)."""
    for fd in (0, 1, 2):
        try:
            name = os.ttyname(fd)
        except OSError:
            continue
        m = re.fullmatch(r"/dev/(tty[0-9]+)", name)
        return m.group(1) if m else None
    return None


def active_tty():
    try:
        with open("/sys/class/tty/tty0/active") as f:
            return f.read().strip()
    except OSError:
        return None


class Framebuffer:
    """The screen's pixels: 32 bits each (blue, green, red, unused)."""

    def __init__(self):
        self.f = open(FB, "r+b", buffering=0)
        var = fcntl.ioctl(self.f, FBIOGET_VSCREENINFO, bytes(160))
        self.xres, self.yres, _, _, self.xoff, self.yoff, bpp = struct.unpack_from("7I", var)
        if bpp != 32:
            raise OSError("the screen has %d bits a pixel, not 32" % bpp)
        with open("/sys/class/graphics/fb0/stride") as f:
            self.stride = int(f.read())
        with open("/sys/class/graphics/fb0/virtual_size") as f:
            vh = int(f.read().split(",")[1])
        import mmap
        self.mm = mmap.mmap(self.f.fileno(), self.stride * vh)

    def blit(self, buf, w, h, x, y, hole=None):
        """Draw w x h pixels (rows of 4 bytes a pixel) at x, y on the screen,
        clipped to it; hole: (x0, y0, x1, y1) pixels left alone."""
        mm, stride = self.mm, self.stride
        cx0, cy0 = max(0, -x), max(0, -y)
        cx1, cy1 = min(w, self.xres - x), min(h, self.yres - y)
        if cx0 >= cx1 or cy0 >= cy1:
            return
        row_bytes = w * 4
        for r in range(cy0, cy1):
            src = r * row_bytes
            dst = (self.yoff + y + r) * stride + (self.xoff + x) * 4
            if hole and hole[1] <= y + r < hole[3]:
                a, b = max(cx0, hole[0] - x), min(cx1, hole[2] - x)
                if a < b:
                    if a > cx0:
                        mm[dst + cx0 * 4:dst + a * 4] = buf[src + cx0 * 4:src + a * 4]
                    if b < cx1:
                        mm[dst + b * 4:dst + cx1 * 4] = buf[src + b * 4:src + cx1 * 4]
                    continue
            mm[dst + cx0 * 4:dst + cx1 * 4] = buf[src + cx0 * 4:src + cx1 * 4]


class Place:
    """Where this program's window is, in pixels, and whether it can be drawn
    into now: asked from Kilobyte Desktop (desk.py's where) ten times a
    second. bottom: rows at the bottom of the window kept for text."""

    def __init__(self, fb, bottom=1):
        self.fb, self.bottom = fb, bottom
        self.tty = console_tty()
        self.sock = os.environ.get("KB_DESK_SOCK") if os.environ.get("KILOBYTE_DESK") else None
        self.win = os.environ.get("KB_WIN")
        self.asked = 0
        self.info = None

    def ask(self):
        if not self.sock:
            # Without windows: the whole console.
            try:
                rows, cols = struct.unpack("hh", fcntl.ioctl(0, 0x5413, bytes(4)))   # TIOCGWINSZ
            except OSError:
                return None
            return {"ok": True, "x": 0, "y": 0, "cols": cols, "rows": rows, "W": cols, "H": rows,
                    "visible": True, "pointer": None}
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(0.3)                      # (busy with the screen saver: nothing to draw)
            s.connect(self.sock)
            s.sendall(json.dumps({"run": "where", "win": self.win}).encode() + b"\n")
            data = b""
            while not data.endswith(b"\n"):
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
            s.close()
            return json.loads(data.decode())
        except (OSError, ValueError):
            return None

    def repaint(self):
        """Have Kilobyte Desktop draw every character again (over pixels left
        behind)."""
        if not self.sock:
            return
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(0.3)
            s.connect(self.sock)
            s.sendall(b'{"run": "repaint"}\n')
            s.recv(16)
            s.close()
        except OSError:
            pass

    def update(self):
        """(x, y, w, h, hole) in pixels to draw at, or None (not now)."""
        now = time.time()
        if now - self.asked >= 0.1:
            self.asked = now
            self.info = self.ask()
        i = self.info
        if not i or not i.get("ok") or not i.get("visible") or active_tty() != self.tty:
            return None
        cw, ch = self.fb.xres // max(1, i["W"]), self.fb.yres // max(1, i["H"])
        self.cell = (cw, ch)
        rows = i["rows"] - self.bottom
        if rows < 1 or i["cols"] < 1:
            return None
        hole = None
        if i.get("pointer"):
            x0, y0, x1, y1 = i["pointer"]
            hole = (x0 * cw, y0 * ch, (x1 + 1) * cw, (y1 + 1) * ch)
        return i["x"] * cw, i["y"] * ch, i["cols"] * cw, rows * ch, hole


def check():
    """Why the real picture cannot be shown in this window, or None."""
    tty = console_tty()
    if not tty:
        return "This is not the text console of a computer."
    if os.environ.get("KILOBYTE_DESK") and not (os.environ.get("KB_DESK_SOCK") and os.environ.get("KB_WIN")):
        return "Kilobyte Desktop cannot be asked where the window is."
    try:
        Framebuffer()
    except OSError as e:
        return "The screen's pixels cannot be reached (%s)." % (e.strerror or e)
    return None


# --- the video player: mpv's library, drawing into memory --------------------
class MpvRenderParam(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("data", ctypes.c_void_p)]


class MpvEvent(ctypes.Structure):
    _fields_ = [("event_id", ctypes.c_int), ("error", ctypes.c_int),
                ("reply_userdata", ctypes.c_uint64), ("data", ctypes.c_void_p)]


RENDER_API_TYPE, SW_SIZE, SW_FORMAT, SW_STRIDE, SW_POINTER = 1, 17, 18, 19, 20
EVENT_SHUTDOWN, EVENT_END_FILE = 1, 7


class Mpv:
    def __init__(self, options):
        m = self.m = ctypes.CDLL("libmpv.so.2")
        m.mpv_create.restype = ctypes.c_void_p
        m.mpv_set_option_string.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        m.mpv_initialize.argtypes = [ctypes.c_void_p]
        m.mpv_command.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_char_p)]
        m.mpv_wait_event.argtypes = [ctypes.c_void_p, ctypes.c_double]
        m.mpv_wait_event.restype = ctypes.POINTER(MpvEvent)
        m.mpv_get_property_string.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        m.mpv_get_property_string.restype = ctypes.c_void_p
        m.mpv_free.argtypes = [ctypes.c_void_p]
        m.mpv_render_context_create.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
                                                ctypes.POINTER(MpvRenderParam)]
        m.mpv_render_context_update.argtypes = [ctypes.c_void_p]
        m.mpv_render_context_update.restype = ctypes.c_uint64
        m.mpv_render_context_render.argtypes = [ctypes.c_void_p, ctypes.POINTER(MpvRenderParam)]
        m.mpv_render_context_free.argtypes = [ctypes.c_void_p]
        m.mpv_terminate_destroy.argtypes = [ctypes.c_void_p]
        h = self.h = m.mpv_create()
        if not h:
            raise OSError("mpv could not start")
        for k, v in [("vo", "libmpv"), ("terminal", "no"), ("input-default-bindings", "no"),
                     ("osc", "no"), ("keep-open", "no")] + options:
            m.mpv_set_option_string(h, k.encode(), v.encode())
        if m.mpv_initialize(h) < 0:
            raise OSError("mpv could not start")
        self.ctx = ctypes.c_void_p()
        sw = ctypes.c_char_p(b"sw")
        params = (MpvRenderParam * 2)((RENDER_API_TYPE, ctypes.cast(sw, ctypes.c_void_p)), (0, None))
        if m.mpv_render_context_create(ctypes.byref(self.ctx), h, params) < 0:
            raise OSError("mpv cannot draw into memory")
        self.size = None

    def command(self, *args):
        argv = (ctypes.c_char_p * (len(args) + 1))(*[str(a).encode() for a in args], None)
        self.m.mpv_command(self.h, argv)

    def get(self, name):
        p = self.m.mpv_get_property_string(self.h, name.encode())
        if not p:
            return None
        v = ctypes.string_at(p).decode("utf-8", "replace")
        self.m.mpv_free(p)
        return v

    def events(self):
        """True while playing; False once the video ended or was stopped."""
        while True:
            e = self.m.mpv_wait_event(self.h, 0).contents
            if e.event_id == 0:
                return True
            if e.event_id in (EVENT_SHUTDOWN, EVENT_END_FILE):
                return False

    def render(self, w, h):
        """A new picture of w x h, if there is one: bytes, else None."""
        if self.size != (w, h):
            self.size = (w, h)
            self.buf = ctypes.create_string_buffer(w * h * 4)
            self.c_size = (ctypes.c_int * 2)(w, h)
            self.c_stride = ctypes.c_size_t(w * 4)
            self.fmt = ctypes.c_char_p(b"bgr0")
            self.fresh = True
        else:
            self.fresh = bool(self.m.mpv_render_context_update(self.ctx) & 1)
        if not self.fresh:
            return None
        params = (MpvRenderParam * 5)(
            (SW_SIZE, ctypes.cast(self.c_size, ctypes.c_void_p)),
            (SW_FORMAT, ctypes.cast(self.fmt, ctypes.c_void_p)),
            (SW_STRIDE, ctypes.cast(ctypes.pointer(self.c_stride), ctypes.c_void_p)),
            (SW_POINTER, ctypes.cast(self.buf, ctypes.c_void_p)),
            (0, None))
        self.m.mpv_render_context_render(self.ctx, params)
        return self.buf.raw

    def close(self):
        self.m.mpv_render_context_free(self.ctx)
        self.m.mpv_terminate_destroy(self.h)


def mpv_options(args):
    """mpv's command line options (--name=value, --flag) as (name, value)."""
    opts = []
    for a in args:
        if a.startswith("--"):
            k, _, v = a[2:].partition("=")
            if k in ("really-quiet", "input-terminal", "vo", "terminal"):
                continue
            opts.append((k, v if "=" in a else "yes"))
    return opts


def clock(t):
    try:
        t = int(float(t))
    except (TypeError, ValueError):
        return "--:--"
    return "%d:%02d:%02d" % (t // 3600, t // 60 % 60, t % 60) if t >= 3600 else "%d:%02d" % (t // 60, t % 60)


def play(s, src, args):
    fb = Framebuffer()
    place = Place(fb)
    player = Mpv(mpv_options(args))
    player.command("loadfile", src)
    name = os.path.basename(src.rstrip("/")) or src
    s.scr.nodelay(True)
    last, drawn, frame, status_at = None, None, None, 0
    try:
        while player.events():
            k = s.scr.getch()
            if k in (ord("q"), ord("Q"), 27, 3):
                break
            if k == ord(" "):
                player.command("cycle", "pause")
            elif k in (curses.KEY_LEFT, curses.KEY_RIGHT, curses.KEY_UP, curses.KEY_DOWN):
                player.command("seek", {curses.KEY_LEFT: -5, curses.KEY_RIGHT: 5,
                                        curses.KEY_UP: 60, curses.KEY_DOWN: -60}[k])
            elif k in (ord("9"), ord("0")):
                player.command("add", "volume", -5 if k == ord("9") else 5)
            where = place.update()
            if where != last:
                if last is not None:
                    place.repaint()                # (what is left of the picture where the window was)
                last, drawn = where, None
            if where:
                x, y, w, h, hole = where
                pic = player.render(w, h)
                if pic is not None:
                    frame = pic
                if frame is not None and len(frame) == w * h * 4 and (pic is not None or time.time() - (drawn or 0) > 0.1):
                    fb.blit(frame, w, h, x, y, hole)
                    drawn = time.time()
            now = time.time()
            if now - status_at > 0.5:
                status_at = now
                hh, ww = s.size()
                paused = player.get("pause") == "yes"
                line = " %s  %s / %s%s   Space pause, arrows seek, 9/0 volume, q stops" % (
                    name, clock(player.get("time-pos")), clock(player.get("duration")), "  (paused)" if paused else "")
                s.put(hh - 1, 0, line[:ww - 1].ljust(ww - 1), YELLOW if paused else WHITE, BLUE)
                if not where:
                    s.put(hh // 2, 2, "(The picture shows when nothing is over this window.)"[:ww - 3], LIGHTGREY, BLACK)
                else:
                    s.put(hh // 2, 2, " " * (ww - 3), BLACK, BLACK)
                s.scr.refresh()
            time.sleep(0.008)
    finally:
        player.close()
        place.repaint()
    return 0


def main(argv):
    if not argv:
        sys.exit(__doc__)
    if argv[0] == "check":
        why = check()
        if why:
            print(why)
        return 1 if why else 0
    if argv[0] == "xsize":
        if check():
            return 1
        fb = Framebuffer()
        i = Place(fb).ask()
        if not i or not i.get("ok"):
            return 1
        cw, ch = fb.xres // max(1, i["W"]), fb.yres // max(1, i["H"])
        # A maximised window: all but its frame, the menu bar, the task bar
        # and a line for the status.
        cols, rows = (i["W"] - 2, i["H"] - 5) if os.environ.get("KILOBYTE_DESK") else (i["W"], i["H"] - 1)
        print("%dx%d" % (cols * cw // 2 * 2, rows * ch // 2 * 2))
        return 0
    if argv[0] == "play" and len(argv) >= 2:
        if check():
            return 125
        try:
            ctypes.CDLL("libmpv.so.2")
        except OSError:
            return 125
        os.environ.setdefault("ESCDELAY", "25")

        def run(scr):
            s = kbui.Screen(scr, mouse=False)
            s.fill(LIGHTGREY, BLACK)
            s.scr.refresh()
            return play(s, argv[1], argv[2:])
        try:
            return curses.wrapper(run)
        except KeyboardInterrupt:
            return 0
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
