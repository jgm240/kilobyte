#!/usr/bin/python3
"""Kilobyte BBS: a bulletin board system that friends dial into (telnet).

systemd starts one of these for every caller (kilobyte-bbs.socket and
kilobyte-bbs@.service), with the caller's connection as standard input and
output, as the user kbbs. Callers get message boards, file areas (ZMODEM
downloads), games, a few apps, chat with each other and the sysop, who is
here, and the last callers. The sysop sets it all up in Internet > Host a BBS.

    bbs.py                    a caller's session (stdin is the connection)
    bbs.py --sysop chat       the sysop chats with the callers (in a terminal)
    bbs.py --sysop status     who is here, and the last callers
    bbs.py --sysop posts      every board's messages
    bbs.py --sysop delete BOARD ID     delete a message
    bbs.py --sysop users      the users
    bbs.py --sysop deluser NAME        delete a user

Settings: /etc/kilobyte/bbs/bbs.conf (KEY=VALUE), greeting.txt (or
greeting.ans, ANSI art in CP437), news.txt, goodbye.txt. Data:
/var/lib/kilobyte-bbs. Files: /srv/kilobyte-bbs/files/AREA/, text
adventures in /srv/kilobyte-bbs/stories/.

Callers' terminals speak the IBM PC character set (CP437) and ANSI colours,
as BBSes always have.
"""
import calendar
import codecs
import errno
import fcntl
import hashlib
import hmac
import json
import os
import pty
import re
import select
import signal
import socket
import struct
import subprocess
import sys
import termios
import time
import urllib.parse
import urllib.request

ETC = "/etc/kilobyte/bbs"
DATA = os.environ.get("KB_BBS_DATA", "/var/lib/kilobyte-bbs")
FILES = "/srv/kilobyte-bbs/files"
STORIES = "/srv/kilobyte-bbs/stories"
KB_LIB = "/usr/lib/kilobyte"
VERSION = "1.5"
HOME_PAGE = "https://jgm240.github.io/kilobyte"

DEFAULTS = {
    "name": "Kilobyte BBS", "sysop": "Sysop", "tagline": "A small board on a small computer",
    "hosted": "on", "newusers": "on", "guests": "on",
    "features": "boards files games apps chat who callers",
    "games": "adventure hangman robots snake sudoku chess stories",
    "apps": "weather dictionary calculator calendar",
    "boards": "General|Computers|Games|Swap and sell",
    "minutes": "60", "port": "2323", "max": "8", "city": "",
}

GAMES = {
    "adventure": ("Adventure", "Colossal Cave: type GO NORTH, TAKE LAMP; QUIT ends", ["/usr/games/adventure"]),
    "hangman": ("Hangman", "Guess the word, letter by letter", ["/usr/games/hangman"]),
    "robots": ("Robots", "Outwit the robots: hjkl yubn move, t teleports, q quits", ["/usr/games/robots"]),
    "snake": ("Snake", "Eat the numbers: hjkl steer, q quits", ["/usr/games/worm"]),
    "sudoku": ("Sudoku", "Fill the grid with 1 to 9: arrows move, Q quits", ["/usr/games/nudoku"]),
    "chess": ("Chess", "Against GNU Chess: type moves like e2e4, Q quits", ["python3", KB_LIB + "/py/chess.py"]),
    "stories": ("Text adventures", "Interactive stories you play by typing", None),
}
APPS = {
    "weather": ("Weather", "The weather anywhere"),
    "dictionary": ("Dictionary", "Look up an English word"),
    "calculator": ("Calculator", "Type sums like 2*(3+4); quit ends"),
    "calendar": ("Calendar", "This month and the next"),
}
FEATURES = {
    "boards": ("M", "Message boards"), "files": ("F", "Files"), "games": ("G", "Games"),
    "apps": ("A", "Apps"), "chat": ("C", "Chat"), "who": ("W", "Who is here"), "callers": ("L", "Last callers"),
}

IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240
BINARY, ECHO, SGA, TTYPE, NAWS = 0, 1, 3, 24, 31


def conf():
    c = dict(DEFAULTS)
    try:
        with open(os.path.join(ETC, "bbs.conf"), encoding="utf-8", errors="replace") as f:
            for line in f:
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.rstrip("\n").split("=", 1)
                    c[k.strip()] = v.strip()
    except OSError:
        pass
    return c


def on(c, key):
    return c.get(key, "off").lower() in ("on", "yes", "1")


def words(c, key):
    return c.get(key, "").split()


def clean(text, limit=2000):
    """What a caller typed or someone wrote: printable, no terminal codes."""
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", "", str(text))[:limit]


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30] or "board"


class Locked:
    """A JSON file, read and written under a lock (callers are separate processes)."""

    def __init__(self, path, empty):
        self.path, self.empty = path, empty

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.lock = open(self.path + ".lock", "a")
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = self.empty
        return self

    def save(self):
        tmp = self.path + ".new"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f)
        os.replace(tmp, self.path)

    def __exit__(self, *a):
        fcntl.flock(self.lock, fcntl.LOCK_UN)
        self.lock.close()


def read_json(path, empty):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return empty


def pw_hash(password, salt=None):
    salt = salt or os.urandom(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 13, r=8, p=1, dklen=32)
    return salt.hex() + ":" + h.hex()


def pw_ok(password, stored):
    try:
        salt, _ = stored.split(":")
        return hmac.compare_digest(pw_hash(password, bytes.fromhex(salt)), stored)
    except ValueError:
        return False


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def nodes():
    """Who is here: [(pid, info)]."""
    out = []
    d = os.path.join(DATA, "nodes")
    try:
        names = os.listdir(d)
    except OSError:
        return out
    for n in names:
        if not n.endswith(".json"):
            continue
        try:
            pid = int(n[:-5])
        except ValueError:
            continue
        if not alive(pid):
            try:
                os.remove(os.path.join(d, n))
            except OSError:
                pass
            continue
        out.append((pid, read_json(os.path.join(d, n), {})))
    return sorted(out, key=lambda x: x[1].get("since", 0))


def chat_post(who, text):
    path = os.path.join(DATA, "chat.log")
    with open(path, "a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps({"t": time.strftime("%H:%M"), "who": who, "text": clean(text, 300)}) + "\n")
    try:
        if os.path.getsize(path) > 200_000:                  # keep the last part only
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()[-300:]
            with open(path + ".new", "w", encoding="utf-8") as f:
                f.writelines(lines)
            os.replace(path + ".new", path)
    except OSError:
        pass


class Hangup(Exception):
    pass


class Telnet:
    """The caller's connection: telnet options, keys in, CP437 and ANSI out."""

    def __init__(self, sock):
        self.sock = sock
        self.cols, self.rows = 80, 24
        self.buf = b""                       # data (telnet codes removed) not yet used
        self.raw = b""                       # bytes not yet parsed
        self.binary = False
        self.after_cr = False
        self.answered = set()
        self.send_raw(bytes([IAC, WILL, ECHO, IAC, WILL, SGA, IAC, DO, SGA, IAC, DO, NAWS,
                             IAC, WILL, BINARY, IAC, DO, BINARY]))

    def send_raw(self, data):
        try:
            self.sock.sendall(data)
        except OSError:
            raise Hangup()

    def send(self, data):
        self.send_raw(data.replace(b"\xff", b"\xff\xff"))

    def write(self, text):
        self.send(text.replace("\r\n", "\n").replace("\n", "\r\n").encode("cp437", "replace"))

    def answer(self, verb, opt):
        if (verb, opt) not in self.answered:
            self.answered.add((verb, opt))
            self.send_raw(bytes([IAC, verb, opt]))

    def parse(self, transfer=False):
        """Telnet codes out of self.raw, data into self.buf."""
        out = bytearray()
        r = self.raw
        i = 0
        # Enter is CR NUL or CR LF (or CR alone): one CR. The NUL or LF of a
        # CR that ended the last piece of data is dropped here.
        if self.after_cr and r[:1] in (b"\x00", b"\n") and not transfer:
            i = 1
        self.after_cr = False
        while i < len(r):
            b = r[i]
            if b != IAC:
                if not transfer and b == 13:
                    out.append(13)
                    if i + 1 < len(r) and r[i + 1] in (0, 10):
                        i += 2
                    else:
                        i += 1
                        self.after_cr = i == len(r)
                    continue
                out.append(b)
                i += 1
                continue
            if i + 1 >= len(r):
                break
            cmd = r[i + 1]
            if cmd == IAC:
                out.append(IAC)
                i += 2
            elif cmd in (WILL, WONT, DO, DONT):
                if i + 2 >= len(r):
                    break
                opt = r[i + 2]
                if cmd == WILL and opt not in (NAWS, SGA, BINARY, TTYPE):
                    self.answer(DONT, opt)
                elif cmd == DO and opt not in (ECHO, SGA, BINARY):
                    self.answer(WONT, opt)
                if opt == BINARY and cmd in (WILL, DO):
                    self.binary = True
                i += 3
            elif cmd == SB:
                end = r.find(bytes([IAC, SE]), i)
                if end < 0:
                    break
                sub = r[i + 2:end].replace(b"\xff\xff", b"\xff")
                if sub[:1] == bytes([NAWS]) and len(sub) >= 5:
                    w, h = struct.unpack(">HH", sub[1:5])
                    if 20 <= w <= 300 and 10 <= h <= 200:
                        self.cols, self.rows = w, h
                i = end + 2
            else:
                i += 2
        self.raw = r[i:]
        self.buf += bytes(out)

    def fill(self, timeout, transfer=False):
        """Wait up to timeout seconds for data; False if none came."""
        r, _, _ = select.select([self.sock], [], [], timeout)
        if not r:
            return False
        try:
            data = self.sock.recv(4096)
        except OSError:
            data = b""
        if not data:
            raise Hangup()
        self.raw += data
        self.parse(transfer)
        return True

    def key(self, timeout=600):
        """One key: a character, "\\r", "\\b", "ESC", "UP", "DOWN", "LEFT", "RIGHT"; None on timeout."""
        end = time.time() + timeout
        while not self.buf:
            left = end - time.time()
            if left <= 0 or not self.fill(left):
                if time.time() >= end:
                    return None
        b = self.buf[0]
        if b == 27:
            if len(self.buf) < 3:
                self.fill(0.15)
            m = re.match(rb"\x1b\[([0-9;]*)([A-Za-z~])", self.buf)
            if m:
                self.buf = self.buf[m.end():]
                return {b"A": "UP", b"B": "DOWN", b"C": "RIGHT", b"D": "LEFT"}.get(m.group(2), "")
            self.buf = self.buf[1:]
            return "ESC"
        if b in (8, 127):
            self.buf = self.buf[1:]
            return "\b"
        if b in (13, 10):
            self.buf = self.buf[1:]
            return "\r"
        # A character: UTF-8 from modern terminals, else CP437.
        for n in (1, 2, 3, 4):
            if len(self.buf) < n:
                self.fill(0.05)
            try:
                ch = self.buf[:n].decode("utf-8")
                self.buf = self.buf[n:]
                return ch
            except UnicodeDecodeError:
                continue
        ch = self.buf[:1].decode("cp437")
        self.buf = self.buf[1:]
        return ch


# ANSI colours: fg 0-15, bg 0-7.
def A(fg, bg=0):
    return f"\x1b[0;{'1;' if fg >= 8 else ''}{30 + (fg & 7)};{40 + bg}m"


RESET = "\x1b[0m"
CLS = "\x1b[2J\x1b[H"
WHITE, YELLOW, CYAN, GREEN, GREY, DARK, RED, MAGENTA = 15, 11, 14, 10, 7, 8, 12, 13


class Session:
    def __init__(self, t, c):
        self.t, self.c = t, c
        self.user = None                     # the user's name
        self.guest = False
        self.started = time.time()
        self.limit = max(5, int(c.get("minutes", "60") or 60)) * 60
        self.warned = False
        self.node = os.path.join(DATA, "nodes", f"{os.getpid()}.json")

    # --- output and input ---------------------------------------------------
    def w(self, text, fg=GREY, bg=0):
        self.t.write(A(fg, bg) + text)

    def nl(self, n=1):
        self.t.write("\r\n" * n)

    def bar(self, title):
        width = min(self.t.cols, 80) - 1
        self.nl()
        self.w(" " + title.ljust(width - 1)[: width - 1], WHITE, 1)
        self.t.write(RESET)
        self.nl()

    def left(self):
        return self.limit - (time.time() - self.started)

    def check_time(self):
        if self.left() <= 0:
            self.nl()
            self.w("Your time for this call is up. Thank you for calling!", YELLOW)
            self.nl()
            raise Hangup()
        if self.left() < 300 and not self.warned:
            self.warned = True
            self.nl()
            self.w(f"(Five minutes left on this call.)", YELLOW)
            self.nl()

    def key(self, timeout=600):
        self.check_time()
        k = self.t.key(min(timeout, max(1, self.left())))
        if k is None:
            if self.left() <= 0:
                self.check_time()
            self.nl()
            self.w("No key pressed for a long time: hanging up.", YELLOW)
            self.nl()
            raise Hangup()
        return k

    def line(self, prompt, limit=60, mask=False, fg=CYAN, initial=""):
        self.w(prompt, fg)
        self.w("", WHITE)
        text = initial
        self.t.write(text)
        while True:
            k = self.key()
            if k == "\r":
                self.nl()
                return text
            if k == "\b":
                if text:
                    text = text[:-1]
                    self.t.write("\b \b")
            elif k == "ESC":
                self.nl()
                return None
            elif len(k) == 1 and k.isprintable() and len(text) < limit:
                text += k
                self.t.write("*" if mask else k)

    def choose(self, prompt, keys):
        """A one-key choice among keys (upper case); Enter gives ""."""
        self.w(prompt, YELLOW)
        while True:
            k = self.key()
            if k == "\r":
                self.nl()
                return ""
            if k == "ESC":
                self.nl()
                return "Q" if "Q" in keys else ""
            if len(k) == 1 and k.upper() in keys:
                self.w(k.upper(), WHITE)
                self.nl()
                return k.upper()

    def more(self, lines):
        """Show lines a screenful at a time."""
        rows = max(5, self.t.rows - 2)
        for i, ln in enumerate(lines):
            if i and i % rows == 0:
                self.w("-- More: Enter, or Q to stop --", DARK)
                k = self.key()
                self.t.write("\r\x1b[K")
                if k.upper() == "Q" or k == "ESC":
                    return
            self.t.write(ln + RESET + "\r\n")

    def pause(self):
        self.w("Press Enter.", DARK)
        while self.key() not in ("\r", "ESC"):
            pass
        self.nl()

    def doing(self, what):
        try:
            os.makedirs(os.path.dirname(self.node), exist_ok=True)
            with open(self.node, "w") as f:
                json.dump({"name": self.user or "(logging in)", "since": self.started, "doing": what}, f)
        except OSError:
            pass

    # --- arriving -----------------------------------------------------------
    def text_file(self, name):
        """greeting / news / goodbye: NAME.ans as it is, else NAME.txt."""
        ans = os.path.join(ETC, name + ".ans")
        if os.path.exists(ans):
            with open(ans, "rb") as f:
                data = f.read(200_000).split(b"\x1a")[0]   # (SAUCE after Ctrl-Z)
            self.t.send(data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
            self.t.write(RESET + "\r\n")
            return True
        try:
            with open(os.path.join(ETC, name + ".txt"), encoding="utf-8", errors="replace") as f:
                lines = [clean(ln.rstrip("\n"), 200) for ln in f.readlines()[:200]]
        except OSError:
            return False
        if not any(lines):
            return False
        self.more([A(GREY) + ln for ln in lines])
        return True

    def welcome(self):
        c = self.c
        self.t.write(CLS)
        name = clean(c["name"], 40)
        width = min(self.t.cols, 80) - 2
        self.w("╔" + "═" * width + "╗", CYAN)
        self.nl()
        self.w("║", CYAN)
        self.w(name.center(width), WHITE)
        self.w("║", CYAN)
        self.nl()
        tag = clean(c.get("tagline", ""), 70)
        if tag:
            self.w("║", CYAN)
            self.w(tag.center(width), GREY)
            self.w("║", CYAN)
            self.nl()
        self.w("╚" + "═" * width + "╝", CYAN)
        self.nl()
        self.w(f"Your sysop: {clean(c.get('sysop', ''), 30)}", GREY)
        self.nl()
        if on(c, "hosted"):
            self.w(f"Hosted on Kilobyte {VERSION}, the text-mode desktop: {HOME_PAGE}", DARK)
            self.nl()
        self.nl()
        self.text_file("greeting")

    def login(self):
        c = self.c
        hints = []
        if on(c, "newusers"):
            hints.append("NEW to join")
        if on(c, "guests"):
            hints.append("GUEST to look around")
        for attempt in range(3):
            self.nl()
            name = self.line(f"Your name{' (' + ', '.join(hints) + ')' if hints else ''}: ", 20)
            if name is None:
                continue
            name = name.strip()
            if not name:
                continue
            if name.upper() == "NEW" and on(c, "newusers"):
                if self.new_user():
                    return True
                continue
            if name.upper() == "GUEST" and on(c, "guests"):
                self.user, self.guest = "Guest", True
                return True
            users = read_json(os.path.join(DATA, "users.json"), {})
            key = name.lower()
            pw = self.line("Password: ", 40, mask=True)
            if pw is not None and key in users and pw_ok(pw, users[key]["pw"]):
                self.user = users[key]["name"]
                return True
            time.sleep(2)
            self.w("That name and password do not match.", RED)
            self.nl()
        self.w("Goodbye.", GREY)
        self.nl()
        return False

    def new_user(self):
        self.bar("Join " + clean(self.c["name"], 40))
        self.w("Choose a name others see you by: 2 to 20 letters, digits, spaces, . - _", GREY)
        self.nl()
        while True:
            name = self.line("Name: ", 20)
            if not name:
                return False
            name = re.sub(r"\s+", " ", name.strip())
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{1,19}", name) or \
                    name.lower() in ("new", "guest", "sysop", "all", self.c.get("sysop", "").lower()):
                self.w("That name cannot be used. Another one?", RED)
                self.nl()
                continue
            with Locked(os.path.join(DATA, "users.json"), {}) as u:
                if name.lower() in u.data:
                    self.w("Someone has that name. Another one?", RED)
                    self.nl()
                    continue
            break
        while True:
            p1 = self.line("Password (at least 6 characters): ", 40, mask=True)
            if p1 is None:
                return False
            if len(p1) < 6:
                self.w("At least 6 characters.", RED)
                self.nl()
                continue
            if self.line("The same password again: ", 40, mask=True) == p1:
                break
            self.w("They were not the same.", RED)
            self.nl()
        with Locked(os.path.join(DATA, "users.json"), {}) as u:
            if name.lower() in u.data:
                self.w("Someone just took that name. Call again!", RED)
                self.nl()
                return False
            u.data[name.lower()] = {"name": name, "pw": pw_hash(p1), "joined": time.strftime("%Y-%m-%d"),
                                    "calls": 0, "read": {}}
            u.save()
        self.user = name
        self.w(f"Welcome, {name}! Next time, log in with your name and password.", GREEN)
        self.nl()
        return True

    def arrived(self):
        if not self.guest:
            with Locked(os.path.join(DATA, "users.json"), {}) as u:
                rec = u.data.get(self.user.lower())
                if rec:
                    rec["calls"] = rec.get("calls", 0) + 1
                    rec["last"] = time.strftime("%Y-%m-%d %H:%M")
                    u.save()
        with open(os.path.join(DATA, "callers.log"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"name": self.user, "time": time.strftime("%Y-%m-%d %H:%M")}) + "\n")
        self.doing("main menu")
        self.nl()
        self.w(f"Hello, {self.user}. ", WHITE)
        others = [n for p, n in nodes() if p != os.getpid()]
        if others:
            self.w(f"Also here: {', '.join(n.get('name', '?') for n in others)}.", GREY)
        self.nl()
        if self.text_file("news"):
            self.pause()

    # --- the main menu ------------------------------------------------------
    def main_menu(self):
        c = self.c
        have = [f for f in FEATURES if f in words(c, "features")]
        while True:
            self.doing("main menu")
            self.bar(f"{clean(c['name'], 40)}  -  Main menu  ({int(self.left() // 60)} minutes left)")
            for f in have:
                k, label = FEATURES[f]
                self.w(f"  [{k}] ", YELLOW)
                self.w(label, WHITE)
                self.nl()
            if not self.guest:
                self.w("  [P] ", YELLOW)
                self.w("Change your password", WHITE)
                self.nl()
            self.w("  [Q] ", YELLOW)
            self.w("Log off", WHITE)
            self.nl()
            keys = "".join(FEATURES[f][0] for f in have) + ("" if self.guest else "P") + "Q"
            k = self.choose("Your choice: ", keys)
            if k == "Q":
                return
            if k == "P":
                self.change_password()
                continue
            for f in have:
                if FEATURES[f][0] == k:
                    getattr(self, "do_" + f)()

    def change_password(self):
        old = self.line("Your password now: ", 40, mask=True)
        users = read_json(os.path.join(DATA, "users.json"), {})
        rec = users.get(self.user.lower())
        if not old or not rec or not pw_ok(old, rec["pw"]):
            self.w("That is not your password.", RED)
            self.nl()
            return
        new = self.line("New password (at least 6 characters): ", 40, mask=True)
        if not new or len(new) < 6 or self.line("Once more: ", 40, mask=True) != new:
            self.w("Not changed.", RED)
            self.nl()
            return
        with Locked(os.path.join(DATA, "users.json"), {}) as u:
            u.data[self.user.lower()]["pw"] = pw_hash(new)
            u.save()
        self.w("Your password is changed.", GREEN)
        self.nl()

    # --- message boards -----------------------------------------------------
    def boards(self):
        return [(slug(b), clean(b.strip(), 30)) for b in self.c.get("boards", "").split("|") if b.strip()]

    def last_read(self, board):
        if self.guest:
            return 0
        return read_json(os.path.join(DATA, "users.json"), {}).get(self.user.lower(), {}).get("read", {}).get(board, 0)

    def set_read(self, board, n):
        if self.guest:
            return
        with Locked(os.path.join(DATA, "users.json"), {}) as u:
            rec = u.data.get(self.user.lower())
            if rec and n > rec.setdefault("read", {}).get(board, 0):
                rec["read"][board] = n
                u.save()

    def do_boards(self):
        while True:
            self.doing("reading messages")
            bs = self.boards()
            self.bar("Message boards")
            for i, (b, name) in enumerate(bs, 1):
                posts = read_json(os.path.join(DATA, "boards", b + ".json"), [])
                new = sum(1 for p in posts if p["id"] > self.last_read(b))
                self.w(f"  [{i}] ", YELLOW)
                self.w(f"{name:<30}", WHITE)
                self.w(f"{len(posts):4} messages", GREY)
                if new:
                    self.w(f", {new} new", GREEN)
                self.nl()
            self.w("  [Q] ", YELLOW)
            self.w("Back", WHITE)
            self.nl()
            k = self.choose("Which board? ", "".join(str(i) for i in range(1, min(len(bs), 9) + 1)) + "Q")
            if k in ("Q", ""):
                return
            self.board(*bs[int(k) - 1])

    def board(self, b, name):
        path = os.path.join(DATA, "boards", b + ".json")
        while True:
            posts = read_json(path, [])
            self.bar(f"{name}: {len(posts)} messages")
            for p in posts[-15:]:
                new = p["id"] > self.last_read(b)
                self.w(f" {p['id']:4} ", GREEN if new else DARK)
                self.w(f"{p['subject'][:40]:<40} ", WHITE)
                self.w(f"{p['from'][:16]:<16} {p['date'][5:10]}", GREY)
                self.nl()
            keys = "NLQ" + ("" if self.guest else "P")
            self.w(" [N] new messages  [L] read by number  ", YELLOW)
            if not self.guest:
                self.w("[P] post  ", YELLOW)
            self.w("[Q] back", YELLOW)
            self.nl()
            k = self.choose("Your choice: ", keys)
            if k in ("Q", ""):
                return
            if k == "P":
                self.post(b)
            elif k == "N":
                new = [p for p in posts if p["id"] > self.last_read(b)]
                if not new:
                    self.w("No new messages here.", GREY)
                    self.nl()
                else:
                    self.read(b, posts, posts.index(new[0]))
            elif k == "L":
                n = self.line("Message number: ", 6)
                ids = [p["id"] for p in posts]
                if n and n.isdigit() and int(n) in ids:
                    self.read(b, posts, ids.index(int(n)))

    def read(self, b, posts, i):
        while 0 <= i < len(posts):
            p = posts[i]
            self.t.write(CLS)
            self.w(f" #{p['id']}  {p['subject']}".ljust(min(self.t.cols, 80) - 1), WHITE, 1)
            self.t.write(RESET + "\r\n")
            self.w(f" From {p['from']}, {p['date']}", CYAN)
            self.nl(2)
            self.more([A(GREY) + ln for ln in p["body"]])
            self.set_read(b, p["id"])
            keys = "NPQ" + ("" if self.guest else "R")
            k = self.choose("[N]ext  [P]revious  " + ("" if self.guest else "[R]eply  ") + "[Q]uit: ", keys)
            if k in ("N", ""):
                i += 1
            elif k == "P":
                i -= 1
            elif k == "R":
                self.post(b, "Re: " + re.sub(r"^(Re: )+", "", p["subject"]), p)
                return
            else:
                return
        self.w("No more messages.", GREY)
        self.nl()

    def post(self, b, subject=None, reply=None):
        self.doing("writing a message")
        if subject is None:
            subject = self.line("Subject: ", 50)
            if not subject or not subject.strip():
                return
        self.w("Type your message. A line with only /S saves it, /A throws it away.", GREY)
        self.nl()
        body = []
        if reply:
            body = [f"> {ln}"[:76] for ln in reply["body"][:6]] + [""]
            for ln in body:
                self.w(ln, DARK)
                self.nl()
        width = min(self.t.cols, 80) - 4
        while len(body) < 150:
            ln = self.line(f"{len(body) + 1:3}: ", width, fg=DARK)
            if ln is None or ln.strip().upper() == "/A":
                self.w("Thrown away.", GREY)
                self.nl()
                return
            if ln.strip().upper() == "/S":
                break
            body.append(clean(ln, 200))
        if not any(ln.strip() and not ln.startswith(">") for ln in body):
            return
        with Locked(os.path.join(DATA, "boards", b + ".json"), []) as d:
            n = (d.data[-1]["id"] + 1) if d.data else 1
            d.data.append({"id": n, "from": self.user, "subject": clean(subject.strip(), 60),
                           "date": time.strftime("%Y-%m-%d %H:%M"), "body": body})
            d.data = d.data[-500:]
            d.save()
        self.set_read(b, n)
        self.w(f"Message #{n} is on the board.", GREEN)
        self.nl()

    # --- files --------------------------------------------------------------
    def do_files(self):
        try:
            areas = sorted(d for d in os.listdir(FILES) if os.path.isdir(os.path.join(FILES, d)) and not d.startswith("."))
        except OSError:
            areas = []
        if not areas:
            self.w("There are no files here yet.", GREY)
            self.nl()
            return
        while True:
            self.doing("looking at files")
            self.bar("File areas")
            for i, a in enumerate(areas[:9], 1):
                n = len([f for f in os.listdir(os.path.join(FILES, a)) if self.listed(a, f)])
                self.w(f"  [{i}] ", YELLOW)
                self.w(f"{clean(a, 40):<40}", WHITE)
                self.w(f"{n:4} files", GREY)
                self.nl()
            self.w("  [Q] ", YELLOW)
            self.w("Back", WHITE)
            self.nl()
            k = self.choose("Which area? ", "".join(str(i) for i in range(1, min(len(areas), 9) + 1)) + "Q")
            if k in ("Q", ""):
                return
            self.area(areas[int(k) - 1])

    def listed(self, area, f):
        p = os.path.join(FILES, area, f)
        return not f.startswith(".") and f.lower() != "descriptions.txt" and os.path.isfile(p) and not os.path.islink(p)

    def area(self, a):
        d = os.path.join(FILES, a)
        notes = {}
        try:
            with open(os.path.join(d, "descriptions.txt"), encoding="utf-8", errors="replace") as f:
                for ln in f:
                    parts = ln.strip().split(None, 1)
                    if len(parts) == 2:
                        notes[parts[0].lower()] = clean(parts[1], 60)
        except OSError:
            pass
        files = sorted((f for f in os.listdir(d) if self.listed(a, f)), key=str.lower)
        while True:
            self.bar(f"Files: {clean(a, 40)}")
            lines = []
            for i, f in enumerate(files, 1):
                st = os.stat(os.path.join(d, f))
                size = f"{st.st_size / 1024:.0f}K" if st.st_size < 1024 ** 2 else f"{st.st_size / 1024 ** 2:.1f}M"
                lines.append(f"{A(YELLOW)}{i:4} {A(WHITE)}{clean(f, 30):<30} {A(GREY)}{size:>7}  "
                             f"{time.strftime('%Y-%m-%d', time.localtime(st.st_mtime))}  {A(CYAN)}{notes.get(f.lower(), '')}")
            self.more(lines or [A(GREY) + "  (empty)"])
            k = self.choose("[D]ownload  [V]iew a text file  [Q]uit: ", "DVQ")
            if k in ("Q", ""):
                return
            n = self.line("File number: ", 5)
            if not n or not n.isdigit() or not 1 <= int(n) <= len(files):
                continue
            path = os.path.join(d, files[int(n) - 1])
            if k == "V":
                self.view(path)
            else:
                self.download(path)

    def view(self, path):
        if os.path.getsize(path) > 1_000_000:
            self.w("That file is too big to show here: download it.", RED)
            self.nl()
            return
        with open(path, "rb") as f:
            data = f.read()
        if path.lower().endswith(".ans"):
            self.t.send(data.split(b"\x1a")[0].replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
            self.t.write(RESET + "\r\n")
            self.pause()
            return
        if b"\x00" in data[:4096]:
            self.w("That is not a text file: download it.", RED)
            self.nl()
            return
        text = data.decode("utf-8", "replace") if not re.search(rb"[\x80-\xff]", data) or _utf8(data) else data.decode("cp437")
        self.more([A(GREY) + clean(ln.rstrip("\r"), 300) for ln in text.split("\n")])
        self.pause()

    def download(self, path):
        sz = "/usr/bin/sz" if os.path.exists("/usr/bin/sz") else None
        if not sz:
            self.w("Downloads are not available on this BBS (ZMODEM is not installed).", RED)
            self.nl()
            return
        self.doing("downloading")
        self.w(f"Sending {os.path.basename(path)} with ZMODEM. Start ZMODEM in your terminal", WHITE)
        self.nl()
        self.w("(Kilobyte's BBS Dialer and most BBS programs do it by themselves).", GREY)
        self.nl()
        p = subprocess.Popen([sz, "-b", "-q", path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, cwd=os.path.dirname(path))
        out = p.stdout.fileno()
        end = time.time() + max(60, min(self.left(), 3600))
        self.t.buf = b""
        try:
            while p.poll() is None and time.time() < end:
                r, _, _ = select.select([self.t.sock, out], [], [], 1)
                if out in r:
                    data = os.read(out, 16384)
                    if data:
                        self.t.send(data)
                if self.t.sock in r:
                    self.t.fill(0, transfer=True)
                    if self.t.buf:
                        p.stdin.write(self.t.buf)
                        p.stdin.flush()
                        self.t.buf = b""
            data = os.read(out, 65536) if select.select([out], [], [], 0.2)[0] else b""
            if data:
                self.t.send(data)
        except (BrokenPipeError, OSError):
            pass
        finally:
            if p.poll() is None:
                p.kill()
            p.wait()
        time.sleep(0.5)
        self.t.buf = b""
        self.nl()
        self.w("Done." if p.returncode == 0 else "The transfer did not finish.", GREEN if p.returncode == 0 else RED)
        self.nl()

    # --- games and apps (run in a terminal of their own) --------------------
    def door(self, argv, cwd=None, env=None):
        """Run a text program for the caller, in a pseudo-terminal of its size."""
        home = os.path.join(DATA, "home", slug(self.user or "guest"))
        os.makedirs(home, exist_ok=True)
        e = {"PATH": "/usr/games:/usr/bin:/bin", "HOME": home, "TERM": "ansi", "LANG": "C.UTF-8",
             "COLUMNS": str(self.t.cols), "LINES": str(self.t.rows), "ESCDELAY": "25"}
        e.update(env or {})
        pid, fd = pty.fork()
        if pid == 0:
            try:
                os.chdir(cwd or home)
                os.execvpe(argv[0], argv, e)
            finally:
                os._exit(127)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", self.t.rows, self.t.cols, 0, 0))
        dec = codecs.getincrementaldecoder("utf-8")("replace")
        end = time.time() + max(10, self.left())
        try:
            if self.t.buf:
                os.write(fd, self.t.buf)
                self.t.buf = b""
            while time.time() < end:
                r, _, _ = select.select([self.t.sock, fd], [], [], 1)
                if fd in r:
                    try:
                        data = os.read(fd, 8192)
                    except OSError as ex:
                        if ex.errno == errno.EIO:
                            break
                        raise
                    if not data:
                        break
                    self.t.write(dec.decode(data))
                if self.t.sock in r:
                    self.t.fill(0)
                    if self.t.buf:
                        os.write(fd, self.t.buf)
                        self.t.buf = b""
        finally:
            try:
                os.kill(pid, signal.SIGHUP)
                time.sleep(0.2)
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
            os.close(fd)
        self.t.write(RESET + "\r\n")

    def do_games(self):
        games = [g for g in words(self.c, "games") if g in GAMES and self.game_there(g)]
        if not games:
            self.w("There are no games here.", GREY)
            self.nl()
            return
        while True:
            self.doing("in the games")
            self.bar("Games")
            for i, g in enumerate(games, 1):
                self.w(f"  [{i}] ", YELLOW)
                self.w(f"{GAMES[g][0]:<18}", WHITE)
                self.w(GAMES[g][1], GREY)
                self.nl()
            self.w("  [Q] ", YELLOW)
            self.w("Back", WHITE)
            self.nl()
            k = self.choose("Which game? ", "".join(str(i) for i in range(1, len(games) + 1)) + "Q")
            if k in ("Q", ""):
                return
            g = games[int(k) - 1]
            self.doing("playing " + GAMES[g][0])
            if g == "stories":
                self.play_story()
            else:
                self.door(GAMES[g][2])

    def game_there(self, g):
        if g == "stories":
            return bool(self.stories()) and os.path.exists("/usr/games/frotz")
        if g == "chess" and not os.path.exists("/usr/games/gnuchess"):
            return False
        return os.path.exists(GAMES[g][2][-1])

    def stories(self):
        try:
            return sorted(f for f in os.listdir(STORIES) if re.search(r"\.(z[1-8]|zblorb|zlb)$", f, re.I))
        except OSError:
            return []

    def play_story(self):
        st = self.stories()
        self.bar("Text adventures")
        for i, s in enumerate(st[:9], 1):
            self.w(f"  [{i}] ", YELLOW)
            self.w(os.path.splitext(s)[0], WHITE)
            self.nl()
        k = self.choose("Which story? (Q: back) ", "".join(str(i) for i in range(1, min(len(st), 9) + 1)) + "Q")
        if k in ("Q", ""):
            return
        saves = os.path.join(DATA, "saves", slug(self.user))
        os.makedirs(saves, exist_ok=True)
        # -R: saved games only in the caller's own folder.
        self.door(["frotz", "-R", saves, os.path.join(STORIES, st[int(k) - 1])], cwd=saves)

    def do_apps(self):
        apps = [a for a in words(self.c, "apps") if a in APPS]
        while True:
            self.doing("in the apps")
            self.bar("Apps")
            for i, a in enumerate(apps, 1):
                self.w(f"  [{i}] ", YELLOW)
                self.w(f"{APPS[a][0]:<14}", WHITE)
                self.w(APPS[a][1], GREY)
                self.nl()
            self.w("  [Q] ", YELLOW)
            self.w("Back", WHITE)
            self.nl()
            k = self.choose("Which one? ", "".join(str(i) for i in range(1, len(apps) + 1)) + "Q")
            if k in ("Q", ""):
                return
            getattr(self, "app_" + apps[int(k) - 1])()

    def app_weather(self):
        city = self.line("City (Enter: the sysop's): ", 40)
        if city is None:
            return
        city = re.sub(r"[^\w ,.-]", "", city.strip()) or re.sub(r"[^\w ,.-]", "", self.c.get("city", ""))
        url = "https://wttr.in/" + urllib.parse.quote(city) + "?0&T&q&lang=en"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/8 (Kilobyte BBS)"})
            with urllib.request.urlopen(req, timeout=15) as r:
                text = r.read(20000).decode("utf-8", "replace")
            self.more([A(GREY) + clean(ln, 120) for ln in text.splitlines()])
        except OSError:
            self.w("The weather could not be fetched right now.", RED)
            self.nl()
        self.pause()

    def app_dictionary(self):
        while True:
            word = self.line("Word (Enter: back): ", 40)
            if not word or not word.strip():
                return
            word = re.sub(r"[^\w' -]", "", word.strip())[:40]
            r = subprocess.run(["python3", KB_LIB + "/py/dict.py", "define", word, str(min(self.t.cols, 80) - 2)],
                               capture_output=True, text=True, timeout=30)
            out = (r.stdout or r.stderr or "Nothing found.").splitlines()
            if r.returncode == 2:
                out = [f"No such word. Did you mean: {' '.join(out)[:200]}"]
            self.more([A(GREY) + clean(ln, 200) for ln in out])

    def app_calculator(self):
        self.w("Type a sum and Enter; quit ends.", GREY)
        self.nl()
        self.door(["bc", "-q"])

    def app_calendar(self):
        now = time.localtime()
        y, m = now.tm_year, now.tm_mon
        cal = calendar.TextCalendar(calendar.MONDAY)
        lines = cal.formatmonth(y, m).splitlines() + [""] + \
            cal.formatmonth(y + (m == 12), m % 12 + 1).splitlines()
        self.nl()
        for ln in lines:
            self.w("   " + ln, WHITE if re.search(r"[A-Za-z]", ln) else GREY)   # (month and day names)
            self.nl()
        self.w(f"   Today is {time.strftime('%A, %d %B %Y')}.", WHITE)
        self.nl()
        self.pause()

    # --- chat, who is here, last callers ------------------------------------
    def do_chat(self):
        self.doing("chatting")
        path = os.path.join(DATA, "chat.log")
        open(path, "a").close()
        self.bar("Chat  -  type and Enter to talk; /Q leaves, /W shows who is here")
        sysop_here = any(n.get("sysop") for _, n in nodes())
        self.w(f"The sysop is {'here' if sysop_here else 'not here right now'}.", CYAN)
        self.nl()
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            pos = f.tell()
        for ln in lines[-8:]:
            self.show_chat(ln)
        chat_post("*", f"{self.user} joins the chat.")
        typed = ""
        prompt = A(YELLOW) + "> " + A(WHITE)
        self.t.write(prompt)
        try:
            while True:
                self.check_time()
                with open(path, encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    new = f.readlines()
                    pos = f.tell()
                if new:
                    self.t.write("\r\x1b[K")
                    for ln in new:
                        self.show_chat(ln)
                    self.t.write(prompt + typed)
                if not self.t.buf and not self.t.fill(0.5):
                    continue
                while self.t.buf:
                    k = self.t.key(0.1)
                    if k == "\r":
                        text = typed.strip()
                        typed = ""
                        self.t.write("\r\x1b[K" + prompt)
                        if text.upper() == "/Q":
                            return
                        if text.upper() == "/W":
                            self.t.write("\r\x1b[K" + A(CYAN) + "Here: " +
                                         ", ".join(n.get("name", "?") for _, n in nodes()) + "\r\n" + prompt)
                        elif text:
                            chat_post(self.user, text)
                    elif k == "\b":
                        if typed:
                            typed = typed[:-1]
                            self.t.write("\b \b")
                    elif k == "ESC":
                        return
                    elif k and len(k) == 1 and k.isprintable() and len(typed) < 200:
                        typed += k
                        self.t.write(k)
        finally:
            chat_post("*", f"{self.user} leaves the chat.")
            self.nl()

    def show_chat(self, ln):
        try:
            m = json.loads(ln)
        except ValueError:
            return
        if m.get("who") == "*":
            self.t.write(f"{A(DARK)}{m.get('t', '')} {clean(m.get('text', ''), 300)}\r\n")
        else:
            colour = MAGENTA if m.get("sysop") else (GREEN if m.get("who") == self.user else CYAN)
            self.t.write(f"{A(DARK)}{m.get('t', '')} {A(colour)}{clean(m.get('who', ''), 30)}: "
                         f"{A(WHITE)}{clean(m.get('text', ''), 300)}\r\n")

    def do_who(self):
        self.bar("Who is here")
        for _, n in nodes():
            mins = int((time.time() - n.get("since", time.time())) // 60)
            self.w(f"  {clean(n.get('name', '?'), 20):<22}", WHITE)
            self.w(f"{clean(n.get('doing', ''), 30):<32}{mins:3} min", GREY)
            self.nl()
        self.pause()

    def do_callers(self):
        self.bar("Last callers")
        try:
            with open(os.path.join(DATA, "callers.log"), encoding="utf-8") as f:
                lines = f.readlines()[-12:]
        except OSError:
            lines = []
        for ln in reversed(lines):
            try:
                c = json.loads(ln)
            except ValueError:
                continue
            self.w(f"  {clean(c.get('name', '?'), 20):<22}", WHITE)
            self.w(clean(c.get("time", ""), 20), GREY)
            self.nl()
        self.pause()

    # --- leaving ------------------------------------------------------------
    def goodbye(self):
        self.nl()
        if not self.text_file("goodbye"):
            self.w(f"Thank you for calling {clean(self.c['name'], 40)}, {self.user}. Come back soon!", WHITE)
            self.nl()
        if on(self.c, "hosted"):
            self.w(f"{clean(self.c['name'], 40)} is hosted on Kilobyte: {HOME_PAGE}", DARK)
            self.nl()
        self.t.write(RESET)

    def run(self):
        try:
            self.doing("logging in")
            self.welcome()
            if not self.login():
                return
            self.arrived()
            self.main_menu()
            self.goodbye()
        except Hangup:
            pass
        finally:
            try:
                os.remove(self.node)
            except OSError:
                pass


def _utf8(data):
    try:
        data.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


# --- the sysop's side (Internet > Host a BBS, through kb-root as kbbs) ---------

def sysop(args):
    if args == ["status"]:
        here = nodes()
        print(f"Callers here now: {len([1 for _, n in here if not n.get('sysop')])}")
        for _, n in here:
            mins = int((time.time() - n.get("since", time.time())) // 60)
            print(f"  {clean(n.get('name', '?'), 20):<22} {clean(n.get('doing', ''), 30):<32} {mins} min")
        print("\nLast callers:")
        try:
            with open(os.path.join(DATA, "callers.log"), encoding="utf-8") as f:
                for ln in reversed(f.readlines()[-15:]):
                    c = json.loads(ln)
                    print(f"  {clean(c.get('name', '?'), 20):<22} {clean(c.get('time', ''), 20)}")
        except (OSError, ValueError):
            print("  (nobody yet)")
    elif args == ["posts"]:
        for b in sorted(os.listdir(os.path.join(DATA, "boards"))) if os.path.isdir(os.path.join(DATA, "boards")) else []:
            if b.endswith(".json"):
                for p in read_json(os.path.join(DATA, "boards", b), []):
                    print(f"{b[:-5]}\t{p['id']}\t{p['date']}\t{clean(p['from'], 20)}\t{clean(p['subject'], 60)}")
    elif len(args) == 3 and args[0] == "show" and re.fullmatch(r"[a-z0-9-]+", args[1]) and args[2].isdigit():
        for p in read_json(os.path.join(DATA, "boards", args[1] + ".json"), []):
            if p["id"] == int(args[2]):
                print(f"#{p['id']}  {clean(p['subject'], 60)}\nFrom {clean(p['from'], 20)}, {p['date']}\n")
                print("\n".join(clean(ln, 300) for ln in p["body"]))
    elif len(args) == 3 and args[0] == "delete" and re.fullmatch(r"[a-z0-9-]+", args[1]) and args[2].isdigit():
        with Locked(os.path.join(DATA, "boards", args[1] + ".json"), []) as d:
            d.data = [p for p in d.data if p["id"] != int(args[2])]
            d.save()
    elif args == ["users"]:
        for k, u in sorted(read_json(os.path.join(DATA, "users.json"), {}).items()):
            print(f"{clean(u['name'], 20)}\t{u.get('joined', '')}\t{u.get('calls', 0)}\t{u.get('last', '')}")
    elif len(args) == 2 and args[0] == "deluser":
        with Locked(os.path.join(DATA, "users.json"), {}) as u:
            u.data.pop(args[1].lower(), None)
            u.save()
    elif args == ["chat"]:
        sysop_chat()
    elif args == ["init"]:
        for d in ("boards", "nodes", "home", "saves"):
            os.makedirs(os.path.join(DATA, d), exist_ok=True)
    else:
        sys.exit("usage: bbs.py --sysop status | posts | show BOARD ID | delete BOARD ID | users | deluser NAME | chat")


def sysop_chat():
    """The sysop in the chat, from a terminal on the BBS's own computer."""
    import tty
    name = conf().get("sysop", "Sysop")
    node = os.path.join(DATA, "nodes", f"{os.getpid()}.json")
    os.makedirs(os.path.dirname(node), exist_ok=True)
    with open(node, "w") as f:
        json.dump({"name": name + " (sysop)", "since": time.time(), "doing": "chatting", "sysop": True}, f)
    path = os.path.join(DATA, "chat.log")
    open(path, "a").close()
    print(f"\033[1mChat with your callers.\033[0m Type and Enter to talk; /q leaves.\n")
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
        pos = f.tell()

    def show(ln):
        try:
            m = json.loads(ln)
        except ValueError:
            return
        if m.get("who") == "*":
            sys.stdout.write(f"\033[90m{m.get('t', '')} {clean(m.get('text', ''), 300)}\033[0m\r\n")
        else:
            sys.stdout.write(f"\033[90m{m.get('t', '')}\033[0m \033[36m{clean(m.get('who', ''), 30)}:\033[0m {clean(m.get('text', ''), 300)}\r\n")
    for ln in lines[-10:]:
        show(ln)
    old = termios.tcgetattr(0)
    tty.setcbreak(0)
    typed = ""
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.strftime("%H:%M"), "who": "*", "text": f"{name}, the sysop, joins the chat."}) + "\n")
    try:
        sys.stdout.write("> ")
        sys.stdout.flush()
        while True:
            r, _, _ = select.select([0], [], [], 0.5)
            with open(path, encoding="utf-8", errors="replace") as f:
                f.seek(pos)
                new = f.readlines()
                pos = f.tell()
            if new:
                sys.stdout.write("\r\033[K")
                for ln in new:
                    show(ln)
                sys.stdout.write("> " + typed)
                sys.stdout.flush()
            if not r:
                continue
            ch = os.read(0, 64).decode("utf-8", "replace")
            for c in ch:
                if c in "\r\n":
                    text, typed = typed.strip(), ""
                    sys.stdout.write("\r\033[K> ")
                    if text.lower() == "/q":
                        return
                    if text:
                        with open(path, "a", encoding="utf-8") as f:
                            fcntl.flock(f, fcntl.LOCK_EX)
                            f.write(json.dumps({"t": time.strftime("%H:%M"), "who": name, "sysop": True,
                                                "text": clean(text, 300)}) + "\n")
                elif c in "\x7f\b":
                    if typed:
                        typed = typed[:-1]
                        sys.stdout.write("\b \b")
                elif c == "\x1b":
                    return
                elif c.isprintable():
                    typed += c
                    sys.stdout.write(c)
            sys.stdout.flush()
    finally:
        termios.tcsetattr(0, termios.TCSADRAIN, old)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.strftime("%H:%M"), "who": "*", "text": f"{name}, the sysop, leaves the chat."}) + "\n")
        try:
            os.remove(node)
        except OSError:
            pass
        print()


def main():
    if sys.argv[1:2] == ["--sysop"]:
        sysop(sys.argv[2:])
        return
    os.umask(0o077)
    for d in ("boards", "nodes", "home", "saves"):
        os.makedirs(os.path.join(DATA, d), exist_ok=True)
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    sock = socket.socket(fileno=os.dup(0)) if not os.environ.get("KB_BBS_TEST") else None
    if sock is None:                                  # (tests: listen on a port, one caller)
        srv = socket.create_server(("127.0.0.1", int(os.environ["KB_BBS_TEST"])))
        sock, _ = srv.accept()
    c = conf()
    # Too many callers already (the socket allows a few more than the BBS).
    if len([1 for _, n in nodes() if not n.get("sysop")]) >= int(c.get("max", "8") or 8):
        sock.sendall(f"\r\n{clean(c['name'], 40)} is full right now: every line is busy. Call again later!\r\n".encode("cp437", "replace"))
        return
    Session(Telnet(sock), c).run()
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


if __name__ == "__main__":
    main()
