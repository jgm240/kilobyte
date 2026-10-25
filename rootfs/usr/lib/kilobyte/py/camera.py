#!/usr/bin/python3
"""Camera: find the cameras, and scan QR codes (and bar codes) with one.

    camera.py cameras                  the cameras: DEVICE<TAB>NAME, one per line
    camera.py scan DEVICE RESULT       a live picture (coloured half blocks) while
                                       it looks for a code; the code's text is
                                       written to RESULT. Q or Esc stops (status 1).
    camera.py scanfile PICTURE         the codes in a picture, one per line
                                       (status 2 when there are none)
    camera.py wifi TEXT                a Wi-Fi code (WIFI:S:...;T:...;P:...;;) as
                                       NAME<TAB>SECURITY<TAB>PASSWORD<TAB>HIDDEN

DEVICE may also be a video file (for trying it without a camera). Frames come
from ffmpeg; the codes are read by the zbar library (libzbar), called directly.
"""
import ctypes
import ctypes.util
import curses
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kbui  # noqa: E402
from kbui import BLACK, BLUE, CYAN, LIGHTGREY, WHITE, YELLOW  # noqa: E402

W, H = 320, 240                              # the frames scanned (and shown)


class Zbar:
    """The few calls of libzbar a scan needs."""

    def __init__(self):
        name = ctypes.util.find_library("zbar") or "libzbar.so.0"
        z = self.z = ctypes.CDLL(name)
        for fn, res, args in (
                ("zbar_image_scanner_create", ctypes.c_void_p, []),
                ("zbar_image_scanner_set_config", ctypes.c_int, [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int]),
                ("zbar_image_create", ctypes.c_void_p, []),
                ("zbar_image_destroy", None, [ctypes.c_void_p]),
                ("zbar_image_set_format", None, [ctypes.c_void_p, ctypes.c_ulong]),
                ("zbar_image_set_size", None, [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]),
                ("zbar_image_set_data", None, [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p]),
                ("zbar_scan_image", ctypes.c_int, [ctypes.c_void_p, ctypes.c_void_p]),
                ("zbar_image_first_symbol", ctypes.c_void_p, [ctypes.c_void_p]),
                ("zbar_symbol_next", ctypes.c_void_p, [ctypes.c_void_p]),
                ("zbar_symbol_get_data", ctypes.c_void_p, [ctypes.c_void_p]),
                ("zbar_symbol_get_data_length", ctypes.c_uint, [ctypes.c_void_p]),
                ("zbar_symbol_get_type", ctypes.c_int, [ctypes.c_void_p])):
            f = getattr(z, fn)
            f.restype, f.argtypes = res, args
        self.scanner = z.zbar_image_scanner_create()
        z.zbar_image_scanner_set_config(self.scanner, 0, 0, 1)    # every kind of code: on

    def decode(self, gray, w, h):
        """The codes in an 8-bit grey picture: [(kind, bytes)]."""
        z = self.z
        img = z.zbar_image_create()
        buf = ctypes.create_string_buffer(bytes(gray), len(gray))
        try:
            z.zbar_image_set_format(img, int.from_bytes(b"Y800", "little"))
            z.zbar_image_set_size(img, w, h)
            z.zbar_image_set_data(img, buf, len(gray), None)
            out = []
            if z.zbar_scan_image(self.scanner, img) > 0:
                sym = z.zbar_image_first_symbol(img)
                while sym:
                    n = z.zbar_symbol_get_data_length(sym)
                    data = ctypes.string_at(z.zbar_symbol_get_data(sym), n)
                    out.append((z.zbar_symbol_get_type(sym), data))
                    sym = z.zbar_symbol_next(sym)
            return out
        finally:
            z.zbar_image_destroy(img)


def text_of(data):
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def cameras():
    """The capture devices (each camera's first node: index 0)."""
    base = "/sys/class/video4linux"
    try:
        names = sorted(os.listdir(base), key=lambda n: int(re.sub(r"\D", "", n) or 0))
    except OSError:
        return []
    out = []
    for n in names:
        try:
            with open(os.path.join(base, n, "index")) as f:
                if f.read().strip() != "0":
                    continue
        except OSError:
            pass
        try:
            with open(os.path.join(base, n, "name")) as f:
                label = f.read().strip()
        except OSError:
            label = n
        out.append(("/dev/" + n, label))
    return out


def frames(source):
    """ffmpeg reading the camera (or a video file), as W x H RGB frames."""
    if source.startswith("/dev/"):
        inp = ["-f", "v4l2", "-i", source]
    else:
        inp = ["-re", "-stream_loop", "-1", "-i", source]
    cmd = ["ffmpeg", "-loglevel", "error", "-nostdin"] + inp + [
        "-vf", "scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2,fps=8" % (W, H, W, H),
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def gray_of(rgb):
    """A good-enough grey picture for zbar: the green of each pixel."""
    return rgb[1::3]


def scan(s, source, result):
    p = frames(source)
    zb = Zbar()
    colours = {}
    s.scr.nodelay(True)
    size = W * H * 3
    message = "Hold a QR code (or a bar code) in front of the camera.  Q stops."
    try:
        while True:
            k = s.scr.getch()
            if k in (ord("q"), ord("Q"), 27):
                return 1
            raw = p.stdout.read(size)
            if len(raw) < size:
                err = p.stderr.read().decode("utf-8", "replace").strip().splitlines()
                raise SystemExit("The camera could not be read%s" % (": " + err[-1] if err else "."))
            found = zb.decode(gray_of(raw), W, H)
            h, w = s.size()
            # The picture: the largest 4:3 that fits, in half blocks (two pixels a cell).
            cols = min(w - 2, (h - 4) * 2 * 4 // 3)
            rows = max(1, cols * 3 // 4 // 2)
            x0, y0 = (w - cols) // 2, 1
            s.put(0, 0, " Camera: scanning ".ljust(w), WHITE, BLUE)
            for cy in range(rows):
                line = []
                for cx in range(cols):
                    sx = cx * W // cols
                    top = (2 * cy * H // (rows * 2)) * W + sx
                    bot = ((2 * cy + 1) * H // (rows * 2)) * W + sx
                    pair = []
                    for i in (top, bot):
                        key = (raw[3 * i] >> 4, raw[3 * i + 1] >> 4, raw[3 * i + 2] >> 4)
                        c = colours.get(key)
                        if c is None:
                            c = colours[key] = kbui.nearest((key[0] * 17, key[1] * 17, key[2] * 17))
                        pair.append(c)
                    line.append(pair)
                for cx, (a, b) in enumerate(line):
                    if a == b:
                        s.put(y0 + cy, x0 + cx, kbui.FULL if a >= 8 else " ", a, a & 7)
                    elif a >= 8 or b < 8:
                        s.put(y0 + cy, x0 + cx, kbui.UPPER, a, b & 7)
                    else:
                        s.put(y0 + cy, x0 + cx, kbui.LOWER, b, a & 7)
            s.put(h - 1, 0, (" " + message)[: w - 1].ljust(w - 1), YELLOW, BLUE)
            s.scr.refresh()
            if found:
                text = text_of(found[0][1])
                with open(result, "w", encoding="utf-8") as f:
                    f.write(text)
                kbui.play_sound("post-beep.wav")
                s.put(h - 1, 0, " Found it!".ljust(w - 1), BLACK, CYAN)
                s.scr.refresh()
                time.sleep(0.6)
                return 0
    finally:
        p.kill()
        p.wait()


def scanfile(path):
    """The codes in a picture file (any ffmpeg reads): decoded at several sizes."""
    zb = Zbar()
    seen = []
    for width in (0, 1280, 640, 320):
        vf = ("scale=%d:-2," % width if width else "") + "format=gray"
        try:
            probe = subprocess.run(["ffmpeg", "-loglevel", "error", "-nostdin", "-i", path, "-frames:v", "1",
                                    "-vf", vf, "-f", "image2pipe", "-c:v", "pgm", "-"],
                                   capture_output=True, timeout=60).stdout
        except (OSError, subprocess.SubprocessError):
            break
        m = re.match(rb"P5\s+(\d+)\s+(\d+)\s+(\d+)\s", probe)
        if not m:
            continue
        w, h = int(m.group(1)), int(m.group(2))
        for _, data in zb.decode(probe[m.end():m.end() + w * h], w, h):
            t = text_of(data)
            if t not in seen:
                seen.append(t)
        if seen:
            break
    return seen


def wifi(text):
    """WIFI:T:WPA;S:name;P:secret;H:false;; (with \\; \\: \\\\ escapes)."""
    if not text.startswith("WIFI:"):
        return None
    fields, key, val, i, body = {}, "", "", 0, text[5:]
    cur = None
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            val += body[i + 1]
            i += 2
            continue
        if cur is None and ch == ":":
            cur, key, val = key, key, ""
        elif ch == ";":
            if cur is not None:
                fields[cur.upper()] = val
            cur, key, val = None, "", ""
        elif cur is None:
            key += ch
        else:
            val += ch
        i += 1
    return fields.get("S", ""), fields.get("T", "nopass") or "nopass", fields.get("P", ""), fields.get("H", "false")


def main(args):
    cmd = args[0] if args else ""
    if cmd == "cameras":
        for dev, name in cameras():
            print("%s\t%s" % (dev, name))
    elif cmd == "scan" and len(args) == 3:
        try:
            Zbar()
        except OSError:
            sys.exit("QR codes need the zbar library (libzbar0t64): kbutils dl camera")
        rc = []
        os.environ.setdefault("ESCDELAY", "25")
        try:
            curses.wrapper(lambda stdscr: rc.append(scan(kbui.Screen(stdscr, False), args[1], args[2])))
        except KeyboardInterrupt:
            rc.append(1)
        sys.exit(rc[0] if rc else 1)
    elif cmd == "scanfile" and len(args) == 2:
        try:
            found = scanfile(args[1])
        except OSError:
            sys.exit("QR codes need the zbar library (libzbar0t64): kbutils dl camera")
        for t in found:
            print(t.replace("\n", "\\n"))
        sys.exit(0 if found else 2)
    elif cmd == "wifi" and len(args) == 2:
        w = wifi(args[1])
        if not w:
            sys.exit(2)
        print("\t".join(w))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
