#!/usr/bin/env python3
"""hostbbs - host your own telnet BBS.

Custom name, generated ASCII-art banner, ANSI color on/off, chat rooms,
message boards, private mail, file areas (ZMODEM downloads), games and apps
(text programs run for the caller), a greeting, a goodbye and a time limit per
call. Every feature is switched from the setup dialog, which saves
~/hostbbs/hostbbs.json (flags on `run` override it). Standard library only.

    hostbbs                   open the setup dialog (name, art, rooms, features...)
    hostbbs run               start the BBS straight from the saved settings
    hostbbs art "My Board"    preview the banner without starting a server
    hostbbs passwd [NAME]     set a user's password (default: the sysop's),
                              read from standard input

In Kilobyte it is the server of Internet > Host a BBS: kilobyte-bbs.service
runs it as the user kbbs, with /etc/kilobyte/bbs/hostbbs.json.

hostbbs is free software: you can redistribute it and/or modify it under the
terms of the GNU General Public License, version 3 or later, as all of Kilobyte.
"""

import argparse
import asyncio
import calendar
import codecs
import copy
import fcntl
import hashlib
import hmac
import json
import os
import pty
import re
import secrets
import signal
import struct
import subprocess
import sys
import termios
import textwrap
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path

VERSION = "1.2"
DEFAULT_CONFIG = Path(os.environ.get("HOSTBBS_HOME", "~/hostbbs")).expanduser() / "hostbbs.json"

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

DEFAULTS = {
    "name": "My BBS",
    "tagline": "Dial in, log on, hang out.",
    "host": "0.0.0.0",
    "port": 2323,
    "color": True,  # true | false | "ask" (ask each caller)
    "charset": "utf-8",  # utf-8 | cp437 (IBM PC characters, for BBS programs) | ask
    "features": {
        "chat": True,
        "boards": True,
        "mail": True,
        "guests": True,
        "register": True,
        "files": False,
        "games": False,
        "apps": False,
    },
    "art": {
        "enabled": True,
        "style": "block",  # block | shade | hash | ascii | plain
        "colors": "rainbow",  # preset name or list of color names
        "gradient": "horizontal",  # horizontal | vertical | diagonal | none
        "frame": "double",  # single | double | round | ascii | stars | none
        "frame_color": "cyan",
        "file": "",  # path to your own art; replaces the generated banner
    },
    "sysop": "sysop",
    "data_dir": "data",  # relative paths live next to the config file
    "max_users": 32,
    "idle_timeout": 900,
    "history": 20,
    "motd": ["Be excellent to each other."],
    "greeting": "",  # a text file shown after the banner (.ans: ANSI art, as it is)
    "goodbye": "",  # said when a caller logs off (empty: "Thanks for calling...")
    "hosted": False,  # a "Hosted on Kilobyte" line under the banner and at goodbye
    "minutes": 0,  # longest call in minutes (0: no limit)
    "files_dir": "",  # every folder in it is a file area callers download from
    "stories_dir": "",  # text adventures (.z3-.z8, .zblorb) for the Games
    "games": ["adventure", "hangman", "robots", "snake", "sudoku", "chess", "stories"],
    "apps": ["weather", "dictionary", "calculator", "calendar"],
    "weather_city": "",
    "rooms": [
        {"name": "lobby", "topic": "Say hello!"},
        {"name": "tech", "topic": "Computers, code and gadgets"},
        {"name": "random", "topic": "Anything goes"},
    ],
    "board_list": [
        {"name": "General", "desc": "Open discussion"},
        {"name": "Announcements", "desc": "News from the sysop"},
    ],
}

ANSI = {
    "black": 30, "red": 31, "green": 32, "yellow": 33, "blue": 34,
    "magenta": 35, "cyan": 36, "white": 37, "gray": 90, "bred": 91,
    "bgreen": 92, "byellow": 93, "bblue": 94, "bmagenta": 95,
    "bcyan": 96, "bwhite": 97,
}

PALETTES = {
    "rainbow": ["bred", "byellow", "bgreen", "bcyan", "bblue", "bmagenta"],
    "fire": ["red", "bred", "byellow", "bwhite"],
    "ocean": ["blue", "bblue", "cyan", "bcyan"],
    "matrix": ["green", "bgreen"],
    "sunset": ["magenta", "bred", "byellow"],
    "mono": ["bwhite"],
}

FILLS = {"block": "█", "shade": "▓", "hash": "#", "ascii": "@"}

FRAMES = {  # TL TR BL BR horizontal vertical
    "single": "┌┐└┘─│",
    "double": "╔╗╚╝═║",
    "round": "╭╮╰╯─│",
    "ascii": "++++-|",
    "stars": "******",
}

NAME_RE = re.compile(r"^[A-Za-z0-9_-]{2,16}$")
KILOBYTE = "https://jgm240.github.io/kilobyte"

# Games: (name, what it is, command); found if the command is there.
GAMES = {
    "adventure": ("Adventure", "Colossal Cave: GO NORTH, TAKE LAMP; QUIT ends", ["/usr/games/adventure"]),
    "hangman": ("Hangman", "Guess the word, letter by letter", ["/usr/games/hangman"]),
    "robots": ("Robots", "Outwit the robots: hjkl yubn move, t teleports, q quits", ["/usr/games/robots"]),
    "snake": ("Snake", "Eat the numbers: hjkl steer, q quits", ["/usr/games/worm"]),
    "sudoku": ("Sudoku", "Fill the grid with 1 to 9: arrows move, Q quits", ["/usr/games/nudoku"]),
    "chess": ("Chess", "Against GNU Chess: moves like e2e4, Q quits",
              ["python3", "/usr/lib/kilobyte/py/chess.py"]),
    "stories": ("Text adventures", "Stories you play by typing", None),
}
APPS = {
    "weather": ("Weather", "The weather anywhere (wttr.in)"),
    "dictionary": ("Dictionary", "Look up an English word"),
    "calculator": ("Calculator", "Sums like 2*(3+4); quit ends"),
    "calendar": ("Calendar", "This month and the next"),
}


def printable(ch):
    """A character a caller may send to others: no terminal controls (also
    no 8-bit ones such as CSI), no invisible formatting (text direction)."""
    return ch >= " " and unicodedata.category(ch) not in ("Cc", "Cf", "Cs", "Co")


def merge(base, over):
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            merge(base[k], v)
        else:
            base[k] = v
    return base


def norm_items(items, extra_key):
    """Accept 'name:extra' strings or dicts; return a list of dicts."""
    out = []
    for it in items:
        if isinstance(it, str):
            name, _, rest = it.partition(":")
            it = {"name": name.strip(), extra_key: rest.strip()}
        if it.get("name"):
            out.append(it)
    return out


def normalize(cfg):
    cfg["rooms"] = norm_items(cfg["rooms"], "topic")
    for r in cfg["rooms"]:
        r["name"] = re.sub(r"[^a-z0-9_-]", "", r["name"].lower()) or "room"
    cfg["board_list"] = norm_items(cfg["board_list"], "desc")
    colors = cfg["art"]["colors"]
    if isinstance(colors, str):
        colors = PALETTES.get(colors) or [c.strip() for c in colors.split(",")]
    colors = [c for c in colors if c in ANSI] or PALETTES["rainbow"]
    cfg["art"]["colors"] = colors
    if cfg["art"]["frame_color"] not in ANSI:
        cfg["art"]["frame_color"] = "cyan"
    return cfg


# --------------------------------------------------------------------------
# ASCII art generator
# --------------------------------------------------------------------------

# 5-row bitmap font; '#' is a lit cell.
FONT = {
    "A": [" ### ", "#   #", "#####", "#   #", "#   #"],
    "B": ["#### ", "#   #", "#### ", "#   #", "#### "],
    "C": [" ####", "#    ", "#    ", "#    ", " ####"],
    "D": ["#### ", "#   #", "#   #", "#   #", "#### "],
    "E": ["#####", "#    ", "#### ", "#    ", "#####"],
    "F": ["#####", "#    ", "#### ", "#    ", "#    "],
    "G": [" ####", "#    ", "# ###", "#   #", " ####"],
    "H": ["#   #", "#   #", "#####", "#   #", "#   #"],
    "I": ["###", " # ", " # ", " # ", "###"],
    "J": ["  ###", "    #", "    #", "#   #", " ### "],
    "K": ["#   #", "#  # ", "###  ", "#  # ", "#   #"],
    "L": ["#    ", "#    ", "#    ", "#    ", "#####"],
    "M": ["#   #", "## ##", "# # #", "#   #", "#   #"],
    "N": ["#   #", "##  #", "# # #", "#  ##", "#   #"],
    "O": [" ### ", "#   #", "#   #", "#   #", " ### "],
    "P": ["#### ", "#   #", "#### ", "#    ", "#    "],
    "Q": [" ### ", "#   #", "# # #", "#  # ", " ## #"],
    "R": ["#### ", "#   #", "#### ", "#  # ", "#   #"],
    "S": [" ####", "#    ", " ### ", "    #", "#### "],
    "T": ["#####", "  #  ", "  #  ", "  #  ", "  #  "],
    "U": ["#   #", "#   #", "#   #", "#   #", " ### "],
    "V": ["#   #", "#   #", "#   #", " # # ", "  #  "],
    "W": ["#   #", "#   #", "# # #", "## ##", "#   #"],
    "X": ["#   #", " # # ", "  #  ", " # # ", "#   #"],
    "Y": ["#   #", " # # ", "  #  ", "  #  ", "  #  "],
    "Z": ["#####", "   # ", "  #  ", " #   ", "#####"],
    "0": [" ### ", "#  ##", "# # #", "##  #", " ### "],
    "1": ["  #  ", " ##  ", "  #  ", "  #  ", " ### "],
    "2": [" ### ", "#   #", "  ## ", " #   ", "#####"],
    "3": ["#### ", "    #", " ### ", "    #", "#### "],
    "4": ["#  # ", "#  # ", "#####", "   # ", "   # "],
    "5": ["#####", "#    ", "#### ", "    #", "#### "],
    "6": [" ### ", "#    ", "#### ", "#   #", " ### "],
    "7": ["#####", "    #", "   # ", "  #  ", "  #  "],
    "8": [" ### ", "#   #", " ### ", "#   #", " ### "],
    "9": [" ### ", "#   #", " ####", "    #", " ### "],
    " ": ["   ", "   ", "   ", "   ", "   "],
    "-": ["     ", "     ", " ### ", "     ", "     "],
    "_": ["     ", "     ", "     ", "     ", "#####"],
    "!": ["#", "#", "#", " ", "#"],
    ".": [" ", " ", " ", " ", "#"],
    ":": [" ", "#", " ", "#", " "],
    "'": ["#", "#", " ", " ", " "],
    "?": [" ### ", "#   #", "  ## ", "     ", "  #  "],
}


def paint(text, color, on=True):
    if not on or not color:
        return text
    return "\x1b[%dm%s\x1b[0m" % (ANSI[color], text)


def strip_ansi(text):
    return re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", text)


def bitmap(text):
    glyphs = [FONT.get(ch, FONT["?"]) for ch in text.upper()]
    return [" ".join(g[r] for g in glyphs) for r in range(5)]


def big_rows(text, fill, maxw):
    """Render text in the big font, wrapping words; None if it can't fit."""
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if cur and len(bitmap(trial)[0]) > maxw:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    rows = []
    for i, line in enumerate(lines):
        bm = bitmap(line)
        if len(bm[0]) > maxw:
            return None
        if i:
            rows.append("")
        rows += [r.replace("#", fill) for r in bm]
    return rows or None


def tint(row, y, nrows, colors, mode):
    out, n, w = [], len(colors), max(len(row), 1)
    for x, ch in enumerate(row):
        if ch == " ":
            out.append(ch)
            continue
        if mode == "horizontal":
            i = x * n // w
        elif mode == "vertical":
            i = y * n // max(nrows, 1)
        elif mode == "diagonal":
            i = (x // 3 + y) % n
        else:
            i = 0
        out.append(paint(ch, colors[i]))
    return "".join(out)


def make_banner(cfg, color, width=80):
    art = cfg["art"]
    name, tag = cfg["name"], cfg["tagline"][: width - 8]
    if art["file"]:
        try:
            text = Path(art["file"]).read_text(encoding="utf-8", errors="replace")
            return text if color else strip_ansi(text)
        except OSError:
            pass
    if not art["enabled"]:
        return "\n" + paint(name, "bwhite", color) + "\n" + paint(tag, "gray", color) + "\n"
    rows = None
    if art["style"] in FILLS:
        rows = big_rows(name, FILLS[art["style"]], width - 8)
    if rows is None:
        rows = [" ".join(name.upper())[: width - 8]]
    inner = max(len(r) for r in rows + [tag])
    body = []
    for y, r in enumerate(rows):
        r = r.center(inner)
        body.append(tint(r, y, len(rows), art["colors"], art["gradient"]) if color else r)
    body.append("")
    body.append(paint(tag.center(inner), "gray", color))
    frame = FRAMES.get(art["frame"])
    if frame:
        tl, tr, bl, br, h, v = frame
        fc = art["frame_color"]
        edge = lambda s: paint(s, fc, color)
        lines = [edge(tl + h * (inner + 2) + tr)]
        for b in body:
            pad = " " * (inner - len(strip_ansi(b)))
            lines.append(edge(v) + " " + b + pad + " " + edge(v))
        lines.append(edge(bl + h * (inner + 2) + br))
        total = inner + 4
    else:
        lines, total = body, inner
    margin = " " * max((width - total) // 2, 0)
    return "\n" + "\n".join(margin + ln for ln in lines) + "\n"


# --------------------------------------------------------------------------
# Server state
# --------------------------------------------------------------------------

def fdate(ts):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def duration(secs):
    secs = int(secs)
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d:
        return "%dd %dh" % (d, h)
    if h:
        return "%dh %dm" % (h, m)
    return "%dm %ds" % (m, s) if m else "%ds" % s


NAME_COLORS = ["bred", "bgreen", "byellow", "bblue", "bmagenta", "bcyan"]


def name_color(name):
    return NAME_COLORS[sum(name.encode()) % len(NAME_COLORS)]


class Room:
    def __init__(self, spec, history):
        self.name = spec["name"]
        self.topic = spec.get("topic", "")
        self.password = spec.get("password", "")
        self.guests = spec.get("guests", True)
        self.members = set()
        self.history = deque(maxlen=history)

    def say(self, kind, who, text):
        entry = {"ts": time.time(), "kind": kind, "who": who, "text": text}
        self.history.append(entry)
        for m in list(self.members):
            m.push(m.fmt_chat(entry))


class BBS:
    def __init__(self, cfg):
        self.cfg = cfg
        self.dir = Path(cfg["data_dir"])
        self.dir.mkdir(parents=True, exist_ok=True)
        self.users = self.load("users")
        self.boards = self.load("boards")
        self.mail = self.load("mail")
        self.meta = self.load("meta")
        self.sessions = set()
        self.connections = 0  # callers connected, logged in or not
        self.started = time.time()
        self.rooms = {}
        if cfg["features"]["chat"]:
            self.rooms = {r["name"]: Room(r, cfg["history"]) for r in cfg["rooms"]}

    def load(self, name):
        try:
            return json.loads((self.dir / (name + ".json")).read_text())
        except (OSError, ValueError):
            return {}

    def save(self, name, obj):
        path = self.dir / (name + ".json")
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, indent=1))
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)

    @staticmethod
    def hash_pw(pw, salt):
        return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 150_000).hex()

    async def make_user(self, name, pw):
        salt = secrets.token_hex(16)
        digest = await asyncio.get_running_loop().run_in_executor(None, self.hash_pw, pw, salt)
        user = {"name": name, "salt": salt, "hash": digest, "created": time.time(),
                "last": time.time(), "calls": 0}
        self.users[name.lower()] = user
        self.save("users", self.users)
        return user

    async def check_pw(self, user, pw):
        digest = await asyncio.get_running_loop().run_in_executor(
            None, self.hash_pw, pw, user["salt"])
        return hmac.compare_digest(digest, user["hash"])

    async def set_password(self, name, pw):
        user = self.users.get(name.lower())
        if user is None:
            user = await self.make_user(name, pw)
            if name.lower() == (self.cfg["sysop"] or "").lower():
                user["sysop"] = True
                self.save("users", self.users)
            return
        user["salt"] = secrets.token_hex(16)
        user["hash"] = await asyncio.get_running_loop().run_in_executor(
            None, self.hash_pw, pw, user["salt"])
        self.save("users", self.users)

    async def ensure_sysop(self):
        """Create the sysop account with a random password on first run.
        Only the account made for the sysop is the sysop: a caller whose
        handle the sysop setting is changed to later does not become one."""
        name = self.cfg["sysop"]
        if not name:
            return None
        user = self.users.get(name.lower())
        if user is not None:
            if not self.meta.get("sysop_marked") and not any(u.get("sysop") for u in self.users.values()):
                user["sysop"] = True                        # (data from hostbbs 1.1)
                self.save("users", self.users)
            self.meta["sysop_marked"] = True
            self.save("meta", self.meta)
            return None
        pw = secrets.token_urlsafe(9)
        user = await self.make_user(name, pw)
        user["sysop"] = True
        self.save("users", self.users)
        self.meta["sysop_marked"] = True
        self.save("meta", self.meta)
        return pw

    def write_online(self):
        """Who is on, for the sysop's tools outside the BBS (Host a BBS)."""
        try:
            self.save("online", [{"name": s.name, "where": s.where, "since": s.joined}
                                 for s in sorted(self.sessions, key=lambda s: s.joined)])
        except OSError:
            pass

    def find_session(self, name):
        for s in self.sessions:
            if s.name.lower() == name.lower():
                return s

    def guest_name(self):
        taken = {s.name for s in self.sessions}
        while True:
            n = "guest-%03d" % secrets.randbelow(1000)
            if n not in taken:
                return n

    def broadcast(self, text):
        for s in list(self.sessions):
            s.push(text)

    def unread(self, user):
        return sum(1 for m in self.mail.get(user.lower(), []) if not m["read"])


# --------------------------------------------------------------------------
# One connected caller
# --------------------------------------------------------------------------

class Quit(Exception):
    pass


IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240
NAWS = 31


class TimeUp(Exception):
    pass


class Session:
    def __init__(self, bbs, reader, writer):
        self.bbs, self.r, self.w = bbs, reader, writer
        self.cfg = bbs.cfg
        self.feat = bbs.cfg["features"]
        self.color = bbs.cfg["color"] is True
        self.cp437 = bbs.cfg.get("charset") == "cp437"
        self.cols, self.rows = 80, 24
        self.timeout = min(bbs.cfg["idle_timeout"], 120)  # (longer once logged in)
        minutes = int(bbs.cfg.get("minutes") or 0)
        self.deadline = time.time() + minutes * 60 if minutes > 0 else None
        self.name = "?"
        self.guest = False
        self.sysop = False
        self.telnet = False
        self._where = "Logging in"
        self.joined = time.time()
        self.room = None
        self.buf = ""
        self.prompt = ""
        self._cr = False
        self._dec = codecs.getincrementaldecoder("utf-8")("replace")

    @property
    def where(self):
        return self._where

    @where.setter
    def where(self, place):  # (the sysop's "who is on" outside the BBS sees it too)
        if place != self._where:
            self._where = place
            if self in self.bbs.sessions:
                self.bbs.write_online()

    # ---- output ----------------------------------------------------------
    def c(self, color, text):
        return paint(text, color, self.color)

    def _encode(self, text):
        return text.encode("cp437", "replace") if self.cp437 else text.encode("utf-8")

    def _write(self, text):
        self.w.write(self._encode(text.replace("\r\n", "\n").replace("\n", "\r\n")))

    async def send(self, text):
        try:
            self._write(text)
            await self.w.drain()
        except (ConnectionError, OSError):
            raise Quit

    def push(self, text):
        """Asynchronous message from another caller; redraws the input line."""
        if self.w.is_closing():
            return
        lead = "\r\x1b[K" if self.color else "\r\n"
        typed = self.buf if self.telnet else ""
        try:
            self._write(lead + text + "\n" + self.prompt + typed)
        except (ConnectionError, OSError):
            pass

    async def header(self, title):
        await self.send("\n" + self.c("bcyan", "== %s ==" % title) + "\n")

    # ---- input -----------------------------------------------------------
    async def getch(self):
        while True:
            b = await self.r.read(1)
            if not b:
                raise Quit
            if b[0] == IAC:
                await self._iac()
                continue
            ch = self._dec.decode(b)
            if not ch:
                continue
            prev, self._cr = self._cr, ch == "\r"
            if (ch == "\n" and prev) or ch == "\0":
                continue
            return ch

    async def _iac(self):
        self.telnet = True
        cmd = (await self.r.readexactly(1))[0]
        if cmd in (DO, DONT, WILL, WONT):
            await self.r.readexactly(1)
        elif cmd == SB:
            prev, sub = 0, bytearray()
            while True:
                b = (await self.r.readexactly(1))[0]
                if prev == IAC and b == SE:
                    break
                sub.append(b)
                prev = b
            sub = bytes(sub[:-1]).replace(b"\xff\xff", b"\xff")
            if sub[:1] == bytes([NAWS]) and len(sub) >= 5:  # the caller's window size
                w, h = struct.unpack(">HH", sub[1:5])
                if 20 <= w <= 300 and 10 <= h <= 200:
                    self.cols, self.rows = w, h

    def wait_limit(self):
        """How long to wait for the next key: the idle timeout, or the time
        left on this call."""
        if self.deadline is None:
            return self.timeout
        left = self.deadline - time.time()
        if left <= 0:
            raise TimeUp
        return min(self.timeout, left)

    async def readline(self, prompt="", echo=True, maxlen=200):
        await self.send(prompt)
        self.prompt, self.buf = prompt, ""
        show = echo and self.telnet
        try:
            while True:
                try:
                    ch = await asyncio.wait_for(self.getch(), self.wait_limit())
                except asyncio.TimeoutError:
                    if self.deadline is not None and time.time() >= self.deadline:
                        raise TimeUp
                    raise
                if ch in "\r\n":
                    if self.telnet:
                        await self.send("\r\n")
                    return self.buf
                if ch in "\x03\x04":
                    raise Quit
                if ch == "\x1b":  # swallow arrow keys and other escape sequences
                    try:  # (a lone Esc: nothing follows at once)
                        nxt = await asyncio.wait_for(self.getch(), 0.15)
                    except asyncio.TimeoutError:
                        continue
                    if nxt in "[O":
                        while True:
                            fin = await self.getch()
                            if "@" <= fin <= "~":
                                break
                    elif nxt >= " " and len(self.buf) < maxlen and printable(nxt):
                        self.buf += nxt  # (typed right after Esc)
                        if show:
                            await self.send(nxt)
                    continue
                if ch in "\x7f\x08":
                    if self.buf:
                        self.buf = self.buf[:-1]
                        if show:
                            await self.send("\b \b")
                elif ch == "\x15":
                    if show:
                        await self.send("\b \b" * len(self.buf))
                    self.buf = ""
                elif printable(ch) and len(self.buf) < maxlen:
                    self.buf += ch
                    if show:
                        await self.send(ch)
        finally:
            self.prompt = ""

    async def ask_yn(self, q, default=False):
        a = (await self.readline("%s [%s] " % (q, "Y/n" if default else "y/N"))).strip().lower()
        return default if not a else a[0] == "y"

    async def read_body(self, limit=50):
        await self.send(self.c("gray", "Enter text; a single '.' on its own line finishes (/c cancels).\n"))
        lines = []
        while len(lines) < limit:
            ln = await self.readline("| ", maxlen=300)
            if ln.strip() == ".":
                break
            if ln.strip() == "/c":
                return None
            lines.append(ln)
        return lines

    # ---- lifecycle ---------------------------------------------------------
    async def run(self):
        bbs = self.bbs
        try:
            # We echo, no go-ahead, and the caller's window size, please.
            self.w.write(bytes([IAC, WILL, 1, IAC, WILL, 3, IAC, DO, NAWS]))
            if self.cfg["color"] == "ask":
                self.color = await self.ask_yn("ANSI color supported?", True)
            if self.cfg.get("charset") == "ask":
                self.cp437 = await self.ask_yn(
                    "IBM PC characters (CP437, as BBS programs such as SyncTERM want)?", False)
            await self.send(make_banner(self.cfg, self.color))
            if self.cfg.get("hosted"):
                await self.send(self.c("gray", "  Hosted on Kilobyte, the text-mode desktop: %s\n" % KILOBYTE))
            for line in self.cfg["motd"]:
                await self.send("  " + self.c("byellow", line) + "\n")
            await self.text_file(self.cfg.get("greeting"))
            await self.send("\n  Caller #%d. Press Ctrl-C to disconnect any time.\n"
                            % (bbs.meta.get("calls", 0) + 1))
            await self.login()
            self.timeout = self.cfg["idle_timeout"]
            bbs.sessions.add(self)
            bbs.write_online()
            bbs.meta["calls"] = bbs.meta.get("calls", 0) + 1
            bbs.save("meta", bbs.meta)
            await self.menu()
        except TimeUp:
            try:
                await self.send("\n" + self.c("byellow", "Your time for this call is up. Thanks for calling!") + "\n")
            except Quit:
                pass
        except (Quit, asyncio.TimeoutError, ConnectionError, OSError,
                asyncio.IncompleteReadError):
            pass
        finally:
            bbs.sessions.discard(self)
            bbs.write_online()
            if self.room:
                self.room.members.discard(self)
                self.room.say("sys", self.name, "%s has left" % self.name)
            try:
                self.w.close()
            except OSError:
                pass

    async def login(self):
        bbs = self.bbs
        for _ in range(5):
            opts = []
            if self.feat["guests"]:
                opts.append("'guest'")
            hint = " (%s)" % ", ".join(opts) if opts else ""
            name = (await self.readline("\n%s%s: " % (self.c("bwhite", "Handle"), hint))).strip()
            low = name.lower()
            if low == "guest" and self.feat["guests"]:
                self.name, self.guest = bbs.guest_name(), True
                await self.send("Welcome, %s. Guests are read-only for boards and mail.\n" % self.name)
                return
            user = bbs.users.get(low)
            if user is None:
                user = await self.register(name)
                if user is None:
                    continue
            else:
                ok = False
                for _ in range(3):
                    pw = await self.readline("Password: ", echo=False)
                    if await bbs.check_pw(user, pw):
                        ok = True
                        break
                    await asyncio.sleep(2)  # (guessing takes long)
                    await self.send(self.c("red", "Wrong password.\n"))
                if not ok:
                    raise Quit
            if bbs.find_session(user["name"]):
                await self.send(self.c("red", "That account is already logged in.\n"))
                continue
            self.name = user["name"]
            self.sysop = low == self.cfg["sysop"].lower() and bool(user.get("sysop"))
            if user["calls"]:
                await self.send("\nWelcome back, %s. Last call: %s. Calls: %d.\n"
                                % (self.name, fdate(user["last"]), user["calls"]))
            else:
                await self.send("\nWelcome to %s, %s!\n" % (self.cfg["name"], self.name))
            user["last"], user["calls"] = time.time(), user["calls"] + 1
            bbs.save("users", bbs.users)
            return
        raise Quit

    async def register(self, name):
        if not self.feat["register"]:
            await self.send(self.c("red", "No such user, and registration is closed.\n"))
            return None
        if not NAME_RE.match(name) or name.lower().startswith("guest"):
            await self.send(self.c("red", "Handles are 2-16 letters, digits, _ or -.\n"))
            return None
        if not await self.ask_yn("No account '%s'. Create it?" % name, True):
            return None
        for _ in range(3):
            pw = await self.readline("Choose a password (4+ chars): ", echo=False)
            if len(pw) < 4:
                await self.send(self.c("red", "Too short.\n"))
                continue
            if pw != await self.readline("Again: ", echo=False):
                await self.send(self.c("red", "Passwords don't match.\n"))
                continue
            user = await self.bbs.make_user(name, pw)
            user["calls"] = 0
            return user
        return None

    # ---- main menu ---------------------------------------------------------
    async def menu(self):
        bbs, f = self.bbs, self.feat
        actions = {
            "B": ("Message boards", f["boards"] and bool(self.cfg["board_list"]), self.boards),
            "M": ("Private mail", f["mail"] and not self.guest, self.mailbox),
            "C": ("Chat rooms", f["chat"] and bool(bbs.rooms), self.chat),
            "F": ("Files", f.get("files") and bool(self.areas()), self.files),
            "D": ("Games (doors)", f.get("games") and bool(self.games()), self.games_menu),
            "A": ("Apps", f.get("apps") and bool(self.apps()), self.apps_menu),
            "W": ("Who's online", True, self.who),
            "U": ("User list", True, self.userlist),
            "I": ("System info", True, self.info),
            "T": ("Toggle color", self.cfg["color"] is not False, self.toggle_color),
            "S": ("Sysop tools", self.sysop, self.sysop_tools),
            "G": ("Goodbye", True, None),
        }
        while True:
            self.where = "Main menu"
            await self.header(self.cfg["name"] + " - main menu")
            for k, (label, on, _) in actions.items():
                if on:
                    extra = ""
                    if k == "M" and not self.guest and bbs.unread(self.name):
                        extra = self.c("bgreen", "  (%d new)" % bbs.unread(self.name))
                    await self.send("  [%s] %s%s\n" % (self.c("byellow", k), label, extra))
            key = (await self.readline("\n%s> " % self.c("bwhite", self.name))).strip().upper()[:1]
            if key == "G":
                await self.send("\n" + (self.cfg.get("goodbye") or "Thanks for calling %s. Goodbye!" % self.cfg["name"]) + "\n")
                if self.cfg.get("hosted"):
                    await self.send(self.c("gray", "%s is hosted on Kilobyte: %s\n" % (self.cfg["name"], KILOBYTE)))
                raise Quit
            if key in actions and actions[key][1]:
                await actions[key][2]()

    async def text_file(self, path):
        """A greeting: a text file, or ANSI art (.ans) sent as it is."""
        if not path:
            return
        try:
            data = open(path, "rb").read(200_000)
        except OSError:
            return
        if path.lower().endswith(".ans"):
            data = data.split(b"\x1a")[0]  # (SAUCE after Ctrl-Z)
            text = data.decode("cp437") if not self.cp437 else None
            if text is None:  # CP437 callers get the bytes as they are
                self.w.write(data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n") + b"\x1b[0m\r\n")
                await self.w.drain()
                return
            await self.send(text + "\x1b[0m\n")
            return
        text = data.decode("utf-8", "replace")
        await self.send("\n" + "\n".join("".join(c for c in ln if printable(c)) for ln in text.splitlines()) + "\n")

    # ---- files: every folder in files_dir is an area -----------------------
    def areas(self):
        d = self.cfg.get("files_dir")
        try:
            return sorted(a for a in os.listdir(d) if not a.startswith(".") and os.path.isdir(os.path.join(d, a)))
        except (OSError, TypeError):
            return []

    @staticmethod
    def listed(d, f):
        p = os.path.join(d, f)
        return not f.startswith(".") and f.lower() != "descriptions.txt" and os.path.isfile(p) and not os.path.islink(p)

    async def files(self):
        self.where = "Files"
        while True:
            areas = self.areas()
            await self.header("File areas")
            for i, a in enumerate(areas, 1):
                d = os.path.join(self.cfg["files_dir"], a)
                n = sum(1 for f in os.listdir(d) if self.listed(d, f))
                await self.send(" %s %-30s %4d files\n" % (self.c("byellow", "%2d" % i), a[:30], n))
            k = (await self.readline("\nArea # (Enter = back): ")).strip()
            if not k:
                return
            if k.isdigit() and 1 <= int(k) <= len(areas):
                await self.area(os.path.join(self.cfg["files_dir"], areas[int(k) - 1]), areas[int(k) - 1])

    async def area(self, d, name):
        notes = {}
        try:
            for ln in open(os.path.join(d, "descriptions.txt"), encoding="utf-8", errors="replace"):
                parts = ln.strip().split(None, 1)
                if len(parts) == 2 and not ln.startswith("#"):
                    notes[parts[0].lower()] = "".join(c for c in parts[1] if printable(c))[:50]
        except OSError:
            pass
        while True:
            files = sorted((f for f in os.listdir(d) if self.listed(d, f)), key=str.lower)
            await self.header("Files: " + name)
            if not files:
                await self.send("  (no files yet)\n")
            for i, f in enumerate(files, 1):
                st = os.stat(os.path.join(d, f))
                size = "%dK" % (st.st_size // 1024) if st.st_size < 1024 ** 2 else "%.1fM" % (st.st_size / 1024 ** 2)
                await self.send(" %s %-28s %7s  %s  %s\n" % (
                    self.c("byellow", "%3d" % i), f[:28], size, fdate(st.st_mtime)[:10],
                    self.c("gray", notes.get(f.lower(), ""))))
            parts = (await self.readline("\n[D]ownload #  [V]iew # (text)  [Q]uit\n> ")).strip().split()
            if not parts or parts[0].lower() == "q":
                return
            cmd, arg = parts[0].lower(), (parts[1] if len(parts) > 1 else "")
            if cmd in ("d", "v") and not arg:
                arg = (await self.readline("File #: ")).strip()
            if not arg.isdigit() or not 1 <= int(arg) <= len(files):
                continue
            path = os.path.join(d, files[int(arg) - 1])
            if cmd == "v":
                await self.view(path)
            elif cmd == "d":
                await self.download(path)

    async def view(self, path):
        if os.path.getsize(path) > 1_000_000:
            await self.send(self.c("red", "Too big to show: download it.\n"))
            return
        data = open(path, "rb").read()
        if b"\x00" in data[:4096]:
            await self.send(self.c("red", "That is not a text file: download it.\n"))
            return
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("cp437")
        lines = ["".join(c for c in ln if printable(c)) for ln in text.splitlines()]
        rows = max(5, self.rows - 2)
        for i in range(0, len(lines), rows):
            await self.send("\n".join(lines[i:i + rows]) + "\n")
            if i + rows < len(lines):
                if (await self.readline(self.c("gray", "-- More: Enter, or Q --"))).strip().lower() == "q":
                    return
        await self.readline(self.c("gray", "[Enter to continue]"))

    async def raw_from_caller(self, timeout):
        """What the caller sends, telnet codes taken out (for doors and ZMODEM)."""
        data = await asyncio.wait_for(self.r.read(4096), timeout)
        if not data:
            raise Quit
        out, i = bytearray(), 0
        while i < len(data):
            b = data[i]
            if b == IAC and i + 1 < len(data):
                cmd = data[i + 1]
                if cmd == IAC:
                    out.append(IAC)
                    i += 2
                elif cmd in (DO, DONT, WILL, WONT):
                    i += 3
                elif cmd == SB:
                    end = data.find(bytes([IAC, SE]), i)
                    i = len(data) if end < 0 else end + 2
                else:
                    i += 2
                continue
            out.append(b)
            i += 1
        return bytes(out)

    async def download(self, path):
        sz = "/usr/bin/sz"
        if not os.path.exists(sz):
            await self.send(self.c("red", "Downloads are not available here (ZMODEM is not installed).\n"))
            return
        self.where = "Downloading"
        await self.send("Sending %s with ZMODEM: start ZMODEM in your terminal\n"
                        "(Kilobyte's BBS Dialer and BBS programs do it by themselves).\n" % os.path.basename(path))
        proc = await asyncio.create_subprocess_exec(
            sz, "-b", "-q", path, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            cwd=os.path.dirname(path))
        async def to_caller():
            while True:
                data = await proc.stdout.read(16384)
                if not data:
                    return
                self.w.write(data.replace(b"\xff", b"\xff\xff"))
                await self.w.drain()
        sender = asyncio.ensure_future(to_caller())
        try:
            while proc.returncode is None:
                try:
                    data = await self.raw_from_caller(1)
                except asyncio.TimeoutError:
                    if sender.done():
                        break
                    continue
                proc.stdin.write(data)
                await proc.stdin.drain()
                if sender.done():
                    break
            await asyncio.wait_for(proc.wait(), 10)
        except (asyncio.TimeoutError, BrokenPipeError, ConnectionError):
            pass
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            sender.cancel()
        await asyncio.sleep(0.5)
        await self.send("\n" + (self.c("bgreen", "Done.") if proc.returncode == 0 else
                                 self.c("red", "The transfer did not finish.")) + "\n")

    # ---- games and apps: text programs in a terminal of the caller's size ---
    def games(self):
        out = []
        for g in self.cfg.get("games") or []:
            if g not in GAMES:
                continue
            if g == "stories":
                if self.stories() and os.path.exists("/usr/games/frotz"):
                    out.append(g)
            elif g == "chess":
                if os.path.exists("/usr/games/gnuchess") and os.path.exists(GAMES[g][2][-1]):
                    out.append(g)
            elif os.path.exists(GAMES[g][2][-1]):
                out.append(g)
        return out

    def stories(self):
        try:
            return sorted(f for f in os.listdir(self.cfg.get("stories_dir") or "")
                          if re.search(r"\.(z[1-8]|zblorb|zlb)$", f, re.I))
        except OSError:
            return []

    def apps(self):
        out = []
        for a in self.cfg.get("apps") or []:
            if a == "dictionary" and not os.path.exists("/usr/lib/kilobyte/py/dict.py"):
                continue
            if a == "calculator" and not os.path.exists("/usr/bin/bc"):
                continue
            if a in APPS:
                out.append(a)
        return out

    async def door(self, argv, cwd=None):
        """Run a text program for the caller, as if on their own terminal."""
        home = os.path.join(self.bbs.dir, "home", re.sub(r"[^a-z0-9_-]", "", self.name.lower()) or "guest")
        os.makedirs(home, exist_ok=True)
        env = {"PATH": "/usr/games:/usr/bin:/bin", "HOME": home, "TERM": "ansi", "LANG": "C.UTF-8",
               "COLUMNS": str(self.cols), "LINES": str(self.rows), "ESCDELAY": "25"}
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", self.rows, self.cols, 0, 0))
        try:
            # A session of its own, with this terminal as its own: Ctrl-C there
            # interrupts the program, as on any terminal.
            proc = await asyncio.create_subprocess_exec(
                *argv, stdin=slave, stdout=slave, stderr=slave, cwd=cwd or home, env=env, start_new_session=True,
                preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0))
        except OSError as e:
            os.close(master)
            os.close(slave)
            await self.send(self.c("red", "It could not be started: %s\n" % e))
            return
        os.close(slave)
        loop = asyncio.get_running_loop()
        out = asyncio.Queue()
        dec = codecs.getincrementaldecoder("utf-8")("replace")

        def readable():
            try:
                data = os.read(master, 8192)
            except OSError:
                data = b""
            out.put_nowait(data)
            if not data:
                loop.remove_reader(master)
        loop.add_reader(master, readable)
        after_cr = False
        caller = None  # the one read of the caller's keys under way
        try:
            while True:
                if caller is None:
                    caller = asyncio.ensure_future(self.raw_from_caller(self.wait_limit()))
                getter = asyncio.ensure_future(out.get())
                done, _ = await asyncio.wait({getter, caller}, return_when=asyncio.FIRST_COMPLETED)
                if getter in done:
                    data = getter.result()
                    if not data:
                        break
                    self.w.write(self._encode(dec.decode(data)))
                    await self.w.drain()
                else:
                    getter.cancel()
                if caller in done:
                    keys, caller = caller.result(), None    # (raises when the caller is gone or idle)
                    # Enter is CR LF or CR NUL from telnet: CR for the program
                    # (also when the two come in separate pieces).
                    if after_cr and keys[:1] in (b"\n", b"\x00"):
                        keys = keys[1:]
                    after_cr = keys.endswith(b"\r")
                    keys = keys.replace(b"\r\n", b"\r").replace(b"\r\x00", b"\r")
                    if keys:
                        os.write(master, keys)
        finally:
            if caller is not None:  # (finished before the menu reads again)
                caller.cancel()
                try:
                    await caller
                except BaseException:
                    pass
            loop.remove_reader(master)
            try:
                os.killpg(proc.pid, signal.SIGHUP)
                await asyncio.sleep(0.2)
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            await proc.wait()
            os.close(master)
        await self.send("\x1b[0m\n")

    async def games_menu(self):
        while True:
            self.where = "Games"
            games = self.games()
            await self.header("Games")
            for i, g in enumerate(games, 1):
                await self.send(" %s %-17s %s\n" % (self.c("byellow", "%2d" % i), GAMES[g][0], self.c("gray", GAMES[g][1])))
            k = (await self.readline("\nGame # (Enter = back): ")).strip()
            if not k:
                return
            if not k.isdigit() or not 1 <= int(k) <= len(games):
                continue
            g = games[int(k) - 1]
            self.where = "Playing " + GAMES[g][0]
            if g == "stories":
                await self.play_story()
            else:
                await self.door(GAMES[g][2])

    async def play_story(self):
        st = self.stories()
        await self.header("Text adventures")
        for i, f in enumerate(st, 1):
            await self.send(" %s %s\n" % (self.c("byellow", "%2d" % i), os.path.splitext(f)[0]))
        k = (await self.readline("\nStory # (Enter = back): ")).strip()
        if not k.isdigit() or not 1 <= int(k) <= len(st):
            return
        saves = os.path.join(self.bbs.dir, "saves", re.sub(r"[^a-z0-9_-]", "", self.name.lower()) or "guest")
        os.makedirs(saves, exist_ok=True)
        # -R: saved games only in the caller's own folder.
        await self.door(["frotz", "-R", saves, os.path.join(self.cfg["stories_dir"], st[int(k) - 1])], cwd=saves)

    async def apps_menu(self):
        while True:
            self.where = "Apps"
            apps = self.apps()
            await self.header("Apps")
            for i, a in enumerate(apps, 1):
                await self.send(" %s %-12s %s\n" % (self.c("byellow", "%2d" % i), APPS[a][0], self.c("gray", APPS[a][1])))
            k = (await self.readline("\nApp # (Enter = back): ")).strip()
            if not k:
                return
            if k.isdigit() and 1 <= int(k) <= len(apps):
                await getattr(self, "app_" + apps[int(k) - 1])()

    async def app_weather(self):
        city = await self.readline("City (Enter = the sysop's): ", maxlen=40)
        city = re.sub(r"[^\w ,.-]", "", city.strip() or self.cfg.get("weather_city", ""))
        url = "https://wttr.in/" + urllib.parse.quote(city) + "?0&T&q&lang=en"

        def fetch():
            req = urllib.request.Request(url, headers={"User-Agent": "curl/8 (hostbbs)"})
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.read(20000).decode("utf-8", "replace")
        try:
            text = await asyncio.get_running_loop().run_in_executor(None, fetch)
            await self.send("\n" + "\n".join("".join(c for c in ln if printable(c)) for ln in text.splitlines()) + "\n")
        except OSError:
            await self.send(self.c("red", "The weather could not be fetched right now.\n"))
        await self.readline(self.c("gray", "\n[Enter to continue]"))

    async def app_dictionary(self):
        while True:
            word = re.sub(r"[^\w' -]", "", (await self.readline("Word (Enter = back): ", maxlen=40)).strip())
            if not word:
                return
            proc = await asyncio.create_subprocess_exec(
                "python3", "/usr/lib/kilobyte/py/dict.py", "define", word, str(min(self.cols, 80) - 2),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = await proc.communicate()
            text = (out or err or b"Nothing found.").decode("utf-8", "replace")
            if proc.returncode == 2:
                text = "No such word. Did you mean: " + " ".join(text.split())[:200]
            await self.send("".join(c for c in text if printable(c) or c == "\n") + "\n")

    async def app_calculator(self):
        await self.send(self.c("gray", "Type a sum and Enter; quit ends.\n"))
        await self.door(["bc", "-q"])

    async def app_calendar(self):
        now = time.localtime()
        cal = calendar.TextCalendar(calendar.MONDAY)
        y, m = now.tm_year, now.tm_mon
        text = cal.formatmonth(y, m) + "\n" + cal.formatmonth(y + (m == 12), m % 12 + 1)
        await self.send("\n" + "\n".join("   " + ln for ln in text.splitlines()) + "\n")
        await self.send("   Today is %s.\n" % time.strftime("%A, %d %B %Y"))
        await self.readline(self.c("gray", "\n[Enter to continue]"))

    async def toggle_color(self):
        self.color = not self.color
        await self.send("Color is now %s.\n" % ("ON" if self.color else "OFF"))

    # ---- message boards ------------------------------------------------------
    async def boards(self):
        self.where = "Message boards"
        bl = self.cfg["board_list"]
        while True:
            await self.header("Message boards")
            for i, b in enumerate(bl, 1):
                n = len(self.bbs.boards.get(b["name"], []))
                await self.send(" %s %-18s %3d msgs  %s\n" % (
                    self.c("byellow", "%2d" % i), b["name"], n, self.c("gray", b.get("desc", ""))))
            k = (await self.readline("\nBoard # (Enter = back): ")).strip()
            if not k:
                return
            if k.isdigit() and 1 <= int(k) <= len(bl):
                await self.board(bl[int(k) - 1])

    async def board(self, b):
        msgs = self.bbs.boards.setdefault(b["name"], [])
        while True:
            await self.header("%s - %s" % (b["name"], b.get("desc", "")))
            if not msgs:
                await self.send("  (no messages yet)\n")
            for m in msgs[-20:]:
                await self.send(" %s  %s  %-16s %s\n" % (
                    self.c("byellow", "%4d" % m["id"]), fdate(m["ts"])[:10],
                    m["author"], m["subject"][:36]))
            cmds = "[R]ead #  [P]ost  " + ("[D]elete #  " if self.sysop else "") + "[Q]uit"
            parts = (await self.readline("\n%s\n> " % cmds)).strip().split()
            if not parts:
                continue
            cmd, arg = parts[0].lower(), (parts[1] if len(parts) > 1 else "")
            if cmd.isdigit():
                cmd, arg = "r", cmd
            if cmd == "q":
                return
            if cmd in ("r", "d") and not arg:
                arg = (await self.readline("Message #: ")).strip()
            msg = next((m for m in msgs if str(m["id"]) == arg), None)
            if cmd == "r":
                if not msg:
                    await self.send(self.c("red", "No such message.\n"))
                    continue
                await self.send("\n%s\nFrom: %s   Date: %s\n\n%s\n" % (
                    self.c("bwhite", msg["subject"]), msg["author"], fdate(msg["ts"]),
                    "\n".join(textwrap.fill(ln, 76) if ln else "" for ln in msg["body"])))
                await self.readline(self.c("gray", "\n[Enter to continue]"))
            elif cmd == "p":
                if self.guest:
                    await self.send(self.c("red", "Guests can't post. Register an account!\n"))
                    continue
                subject = (await self.readline("Subject: ", maxlen=60)).strip()
                body = await self.read_body() if subject else None
                if body:
                    msgs.append({"id": (msgs[-1]["id"] + 1) if msgs else 1, "ts": time.time(),
                                 "author": self.name, "subject": subject, "body": body})
                    self.bbs.save("boards", self.bbs.boards)
                    await self.send(self.c("bgreen", "Posted.\n"))
            elif cmd == "d" and self.sysop and msg:
                msgs.remove(msg)
                self.bbs.save("boards", self.bbs.boards)
                await self.send("Deleted.\n")

    # ---- private mail ----------------------------------------------------------
    async def mailbox(self):
        self.where = "Reading mail"
        bbs, me = self.bbs, self.name.lower()
        while True:
            box = bbs.mail.setdefault(me, [])
            await self.header("Mailbox")
            if not box:
                await self.send("  (empty)\n")
            for i, m in enumerate(box, 1):
                flag = self.c("bgreen", "*") if not m["read"] else " "
                await self.send(" %s%3d  %-16s %s  %s\n" % (
                    flag, i, m["from"], fdate(m["ts"])[:10], m["subject"][:34]))
            parts = (await self.readline("\n[R]ead #  [S]end  [D]elete #  [Q]uit\n> ")).strip().split()
            if not parts:
                continue
            cmd, arg = parts[0].lower(), (parts[1] if len(parts) > 1 else "")
            if cmd.isdigit():
                cmd, arg = "r", cmd
            if cmd == "q":
                return
            idx = int(arg) - 1 if arg.isdigit() else -1
            if cmd in ("r", "d") and not 0 <= idx < len(box):
                await self.send(self.c("red", "Give a message number.\n"))
                continue
            if cmd == "r":
                m = box[idx]
                m["read"] = True
                bbs.save("mail", bbs.mail)
                await self.send("\n%s\nFrom: %s   Date: %s\n\n%s\n" % (
                    self.c("bwhite", m["subject"]), m["from"], fdate(m["ts"]),
                    "\n".join(textwrap.fill(ln, 76) if ln else "" for ln in m["body"])))
                await self.readline(self.c("gray", "\n[Enter to continue]"))
            elif cmd == "d":
                box.pop(idx)
                bbs.save("mail", bbs.mail)
            elif cmd == "s":
                await self.send_mail()

    async def send_mail(self):
        bbs = self.bbs
        to = (await self.readline("To: ")).strip()
        rec = bbs.users.get(to.lower())
        if not rec:
            await self.send(self.c("red", "No such user.\n"))
            return
        if len(bbs.mail.get(to.lower(), [])) >= 100:
            await self.send(self.c("red", "Their mailbox is full.\n"))
            return
        subject = (await self.readline("Subject: ", maxlen=60)).strip()
        body = await self.read_body() if subject else None
        if not body:
            return
        bbs.mail.setdefault(to.lower(), []).append({
            "from": self.name, "ts": time.time(), "subject": subject, "body": body, "read": False})
        bbs.save("mail", bbs.mail)
        online = bbs.find_session(rec["name"])
        if online:
            online.push(online.c("bgreen", "[mail] New message from %s: %s" % (self.name, subject)))
        await self.send(self.c("bgreen", "Sent.\n"))

    # ---- chat ------------------------------------------------------------------
    def fmt_chat(self, e):
        stamp = self.c("gray", time.strftime("%H:%M", time.localtime(e["ts"])))
        who = self.c(name_color(e["who"]), e["who"])
        if e["kind"] == "sys":
            return "%s %s" % (stamp, self.c("gray", "* " + e["text"]))
        if e["kind"] == "emo":
            return "%s %s %s %s" % (stamp, self.c("magenta", "*"), who, e["text"])
        if e["kind"] == "pm":
            return "%s %s %s: %s" % (stamp, self.c("bmagenta", "[pm]"), who, e["text"])
        return "%s <%s> %s" % (stamp, who, e["text"])

    def room_list(self):
        out = []
        for r in self.bbs.rooms.values():
            lock = " (locked)" if r.password else ""
            guest = " (members only)" if not r.guests and self.guest else ""
            out.append("  %s %-12s %d here  %s%s%s" % (
                self.c("byellow", "#"), r.name, len(r.members), self.c("gray", r.topic), lock, guest))
        return "\n".join(out)

    async def chat(self):
        self.where = "Chat"
        rooms = self.bbs.rooms
        while True:
            await self.header("Chat rooms")
            await self.send(self.room_list() + "\n")
            first = next(iter(rooms))
            pick = (await self.readline("\nRoom (Enter = %s, Q = back): " % first)).strip().lower()
            if pick == "q":
                return
            room = await self.enter_ok(rooms.get(pick or first))
            while room:
                room = await self.chat_room(room)

    async def enter_ok(self, room, given_pw=""):
        if room is None:
            await self.send(self.c("red", "No such room.\n"))
            return None
        if self.guest and not room.guests:
            await self.send(self.c("red", "That room is for registered users.\n"))
            return None
        if room.password and not self.sysop:
            pw = given_pw or await self.readline("Room password: ", echo=False)
            if not hmac.compare_digest(pw.encode(), room.password.encode()):
                await self.send(self.c("red", "Wrong password.\n"))
                return None
        return room

    async def chat_room(self, room):
        """Run one room session; returns the next Room to switch to, or None."""
        self.room = room
        self.where = "Chat #" + room.name
        await self.send("\n%s  %s\n%s\n" % (
            self.c("bcyan", "#" + room.name), self.c("gray", room.topic),
            self.c("gray", "Type /help for commands, /quit to leave.")))
        for e in list(room.history):
            await self.send(self.fmt_chat(e) + "\n")
        room.members.add(self)
        room.say("sys", self.name, "%s has joined" % self.name)
        try:
            while True:
                line = (await self.readline(self.c("bcyan", "#%s> " % room.name), maxlen=300)).strip()
                if self.telnet and self.color:  # erase our typed line; the room echo replaces it
                    await self.send("\x1b[A\x1b[2K\r")
                if not line:
                    continue
                if not line.startswith("/"):
                    room.say("msg", self.name, line)
                    continue
                cmd, _, arg = line[1:].partition(" ")
                arg = arg.strip()
                cmd = cmd.lower()
                if cmd in ("quit", "leave", "q", "exit"):
                    return None
                if cmd == "join":
                    name, _, pw = arg.partition(" ")
                    target = await self.enter_ok(self.bbs.rooms.get(name.lower()), pw.strip())
                    if target and target is not room:
                        return target
                elif cmd == "me" and arg:
                    room.say("emo", self.name, arg)
                elif cmd == "who":
                    await self.send("In #%s: %s\n" % (room.name, ", ".join(sorted(m.name for m in room.members))))
                elif cmd == "rooms":
                    await self.send(self.room_list() + "\n")
                elif cmd in ("msg", "pm", "w"):
                    to, _, text = arg.partition(" ")
                    target = self.bbs.find_session(to)
                    if not target or not text.strip():
                        await self.send(self.c("red", "Usage: /msg <online user> <text>\n"))
                    else:
                        e = {"ts": time.time(), "kind": "pm", "who": self.name, "text": text.strip()}
                        target.push(target.fmt_chat(e))
                        await self.send(self.c("bmagenta", "[pm to %s] " % target.name) + text.strip() + "\n")
                elif cmd == "topic" and self.sysop:
                    room.topic = arg
                    room.say("sys", self.name, "%s set the topic: %s" % (self.name, arg))
                elif cmd == "help":
                    await self.send(
                        "  /who  /rooms  /join <room> [pw]  /me <action>\n"
                        "  /msg <user> <text>  /quit" + ("  /topic <text>" if self.sysop else "") + "\n")
                else:
                    await self.send(self.c("red", "Unknown command. Try /help.\n"))
        finally:
            room.members.discard(self)
            self.room = None
            room.say("sys", self.name, "%s has left" % self.name)

    # ---- info screens ------------------------------------------------------------
    async def who(self):
        await self.header("Who's online")
        for s in sorted(self.bbs.sessions, key=lambda s: s.joined):
            await self.send(" %-16s %-22s on for %s\n" % (
                s.name + ("*" if s.sysop else ""), s.where, duration(time.time() - s.joined)))
        await self.readline(self.c("gray", "\n[Enter to continue]"))

    async def userlist(self):
        await self.header("Users")
        users = sorted(self.bbs.users.values(), key=lambda u: -u["last"])[:40]
        for u in users:
            await self.send(" %-16s %4d calls   last on %s\n" % (u["name"], u["calls"], fdate(u["last"])))
        await self.readline(self.c("gray", "\n[Enter to continue]"))

    async def info(self):
        bbs, f = self.bbs, self.feat
        await self.header("About " + self.cfg["name"])
        on = lambda b: self.c("bgreen", "on") if b else self.c("red", "off")
        await self.send(
            " hostbbs v%s   up %s   %d online   %d calls   %d users\n"
            " chat: %s   boards: %s   mail: %s   guests: %s   registration: %s\n" % (
                VERSION, duration(time.time() - bbs.started), len(bbs.sessions),
                bbs.meta.get("calls", 0), len(bbs.users),
                on(f["chat"]), on(f["boards"]), on(f["mail"]), on(f["guests"]), on(f["register"])))
        await self.readline(self.c("gray", "\n[Enter to continue]"))

    async def sysop_tools(self):
        self.where = "Sysop tools"
        while True:
            await self.header("Sysop tools")
            cmd = (await self.readline("[K]ick user  [B]roadcast  [Q]uit\n> ")).strip().lower()[:1]
            if cmd == "q" or not cmd:
                return
            if cmd == "b":
                text = (await self.readline("Message: ", maxlen=200)).strip()
                if text:
                    self.bbs.broadcast(self.c("bred", "[SYSOP] " + text))
            elif cmd == "k":
                target = self.bbs.find_session((await self.readline("Kick who: ")).strip())
                if target and target is not self:
                    target.push(target.c("bred", "You have been disconnected by the sysop."))
                    target.w.close()
                    await self.send("Kicked %s.\n" % target.name)
                else:
                    await self.send(self.c("red", "Not online.\n"))


# --------------------------------------------------------------------------
# Setup dialog (curses, raspi-config style)
# --------------------------------------------------------------------------

import curses  # noqa: E402  (only used by the setup dialog)

BTN_KEYS = (10, 13, curses.KEY_ENTER)


def wrap_text(text, w):
    out = []
    for para in text.split("\n"):
        out += textwrap.wrap(para, max(w, 10)) or [""]
    return out


def put(win, y, x, text, attr=0):
    try:
        win.addstr(y, x, text, attr)
    except curses.error:
        pass


class UI:
    """Tiny whiptail-style toolkit: menu, checklist, inputbox, msgbox, yesno."""

    HINT = " Up/Down move   Enter select   Tab buttons   Space toggle   Esc back "

    def __init__(self, scr):
        self.scr = scr
        curses.curs_set(0)
        curses.start_color()
        for n, (fg, bg) in enumerate([
                (curses.COLOR_WHITE, curses.COLOR_BLUE), (curses.COLOR_BLACK, curses.COLOR_WHITE),
                (curses.COLOR_WHITE, curses.COLOR_RED), (curses.COLOR_BLACK, curses.COLOR_BLACK)], 1):
            curses.init_pair(n, fg, bg)
        self.bgc, self.boxc, self.selc, self.shc = (curses.color_pair(i) for i in (1, 2, 3, 4))

    def bg(self):
        s = self.scr
        s.bkgd(" ", self.bgc)
        s.erase()
        h, w = s.getmaxyx()
        put(s, 0, 2, "hostbbs setup v" + VERSION, self.bgc | curses.A_BOLD)
        put(s, h - 1, 0, self.HINT[: w - 1], self.bgc)
        s.noutrefresh()

    def frame(self, h, w, title):
        H, W = self.scr.getmaxyx()
        h, w = min(h, H - 2), min(w, W - 2)
        y, x = (H - h) // 2, (W - w) // 2
        sh, sw = min(h, H - y - 1), min(w, W - x - 2)
        if sh > 0 and sw > 0:
            shadow = curses.newwin(sh, sw, y + 1, x + 2)
            shadow.bkgd(" ", self.shc)
            shadow.noutrefresh()
        win = curses.newwin(h, w, y, x)
        win.bkgd(" ", self.boxc)
        win.box()
        t = " %s " % title[: w - 6]
        put(win, 0, max((w - len(t)) // 2, 1), t, self.boxc | curses.A_BOLD)
        win.keypad(True)
        return win, h, w

    def buttons(self, win, y, w, labels, focus):
        text = "   ".join("<%s>" % lb for lb in labels)
        x = (w - len(text)) // 2
        for i, lb in enumerate(labels):
            label = "<%s>" % lb
            put(win, y, x, label, (self.selc | curses.A_BOLD) if i == focus else self.boxc)
            x += len(label) + 3

    def menu(self, title, text, items, sel=None, checks=None, ok="Select", back="Back"):
        """items: [(tag, description)]. Returns the chosen tag, or None on Back/Esc.
        With checks (a list of bools, mutated in place) it behaves like a checklist."""
        idx = next((i for i, it in enumerate(items) if it[0] == sel), 0)
        top, focus = 0, 0
        tw = max([len(t) for t, _ in items] + [1])
        want = max([len(d) + tw + 8 for _, d in items] + [len(title) + 8, 52])
        while True:
            self.bg()
            lines = wrap_text(text, min(want, 76) - 6) if text else []
            vis = max(1, min(len(items), 10))
            win, h, w = self.frame(len(lines) + vis + 6 + (1 if lines else 0), min(want, 76), title)
            vis = max(1, min(vis, h - len(lines) - 6 - (1 if lines else 0)))
            for i, ln in enumerate(lines):
                put(win, 1 + i, 3, ln)
            base = 2 + len(lines) + (1 if lines else 0) - 1
            top = min(top, idx)
            if idx >= top + vis:
                top = idx - vis + 1
            for r in range(vis):
                i = top + r
                if i >= len(items):
                    break
                tag, desc = items[i]
                label = ("[%s] %s" % ("*" if checks[i] else " ", desc)) if checks is not None \
                    else "%-*s  %s" % (tw, tag, desc)
                attr = (self.selc | curses.A_BOLD) if (i == idx and focus == 0) else self.boxc
                put(win, base + r, 2, (" " + label).ljust(w - 4)[: w - 4], attr)
            if top > 0:
                put(win, base, w - 2, "^")
            if top + vis < len(items):
                put(win, base + vis - 1, w - 2, "v")
            self.buttons(win, h - 3, w, [ok, back], focus - 1 if focus else -1)
            k = win.getch()
            if k in (curses.KEY_UP, curses.KEY_DOWN, curses.KEY_PPAGE, curses.KEY_NPAGE,
                     curses.KEY_HOME, curses.KEY_END) and items:
                step = {curses.KEY_UP: -1, curses.KEY_DOWN: 1, curses.KEY_PPAGE: -vis,
                        curses.KEY_NPAGE: vis, curses.KEY_HOME: -len(items), curses.KEY_END: len(items)}[k]
                idx = max(0, min(len(items) - 1, idx + step))
                focus = 0
            elif k == 9:
                focus = (focus + 1) % 3
            elif k in (curses.KEY_LEFT, curses.KEY_RIGHT) and focus:
                focus = 3 - focus
            elif k in BTN_KEYS:
                if focus == 2 or not items:
                    return None
                return items[idx][0]
            elif k == 27:
                return None
            elif k == 32 and checks is not None and items:
                checks[idx] = not checks[idx]
            elif 32 < k < 127 and checks is None:
                hit = [i for i, (t, _) in enumerate(items) if t.lower().startswith(chr(k).lower())]
                if hit:
                    later = [i for i in hit if i > idx]
                    idx, focus = (later or hit)[0], 0

    def checklist(self, title, text, items):
        """items: [(label, bool)] -> new list of bools, or None if cancelled."""
        checks = [c for _, c in items]
        r = self.menu(title, text, [(str(i), lb) for i, (lb, _) in enumerate(items)],
                      checks=checks, ok="Ok", back="Cancel")
        return None if r is None else checks

    def inputbox(self, title, text, init="", secret=False):
        buf, pos, focus = list(init), len(init), 0
        curses.curs_set(1)
        try:
            while True:
                self.bg()
                lines = wrap_text(text, 58)
                win, h, w = self.frame(len(lines) + 7, 66, title)
                for i, ln in enumerate(lines):
                    put(win, 1 + i, 3, ln)
                fw, fy = w - 6, len(lines) + 2
                shown = ("*" * len(buf)) if secret else "".join(buf)
                start = max(0, pos - fw + 1)
                put(win, fy, 3, shown[start: start + fw].ljust(fw), curses.A_REVERSE)
                self.buttons(win, h - 3, w, ["Ok", "Cancel"], focus - 1 if focus else -1)
                if focus == 0:
                    win.move(fy, 3 + pos - start)
                k = win.getch()
                if k == 27:
                    return None
                if k == 9:
                    focus = (focus + 1) % 3
                elif k in BTN_KEYS:
                    return None if focus == 2 else "".join(buf)
                elif focus and k in (curses.KEY_LEFT, curses.KEY_RIGHT):
                    focus = 3 - focus
                elif k == curses.KEY_LEFT:
                    pos = max(0, pos - 1)
                elif k == curses.KEY_RIGHT:
                    pos = min(len(buf), pos + 1)
                elif k in (curses.KEY_HOME, 1):
                    pos = 0
                elif k in (curses.KEY_END, 5):
                    pos = len(buf)
                elif k in (curses.KEY_BACKSPACE, 127, 8):
                    if pos:
                        del buf[pos - 1]
                        pos -= 1
                elif k == curses.KEY_DC and pos < len(buf):
                    del buf[pos]
                elif k == 21:
                    buf, pos = [], 0
                elif 32 <= k < 127 or 160 <= k < 0x110000 and k != 0x10ffff and k > 255:
                    buf.insert(pos, chr(k))
                    pos += 1
                    focus = 0
        finally:
            curses.curs_set(0)

    def yesno(self, title, text, yes="Yes", no="No"):
        focus = 0
        while True:
            self.bg()
            lines = wrap_text(text, 52)
            win, h, w = self.frame(len(lines) + 6, 60, title)
            for i, ln in enumerate(lines):
                put(win, 2 + i, 3, ln)
            self.buttons(win, h - 3, w, [yes, no], focus)
            k = win.getch()
            if k in (9, curses.KEY_LEFT, curses.KEY_RIGHT):
                focus = 1 - focus
            elif k in BTN_KEYS:
                return focus == 0
            elif k == 27:
                return False
            elif k in (ord("y"), ord("Y")):
                return True
            elif k in (ord("n"), ord("N")):
                return False

    def msgbox(self, title, text):
        while True:
            self.bg()
            lines = wrap_text(text, 52)
            win, h, w = self.frame(len(lines) + 6, 60, title)
            for i, ln in enumerate(lines):
                put(win, 2 + i, 3, ln)
            self.buttons(win, h - 3, w, ["Ok"], 0)
            if win.getch() in BTN_KEYS + (27, 32):
                return

    # ---- forms built from (key, label, kind, extra) specs --------------------
    def show(self, value, kind, extra):
        if kind == "bool":
            return "yes" if value else "no"
        if kind == "pick":
            return next((lb for v, lb in extra if v == value), str(value))
        if kind == "palette":
            return value if isinstance(value, str) else ",".join(value)
        if kind == "motd":
            return " | ".join(value) or "(none)"
        return str(value) if value not in ("", None) else "(none)"

    def edit(self, target, spec):
        key, label, kind, extra = spec
        cur = target.get(key)
        if kind == "bool":
            target[key] = not cur
        elif kind in ("pick", "palette"):
            opts = list(extra) if kind == "pick" else [(n, n) for n in PALETTES] + [("*", "Custom list...")]
            r = self.menu(label, "", [(str(i), lb) for i, (_, lb) in enumerate(opts)],
                          sel=str(next((i for i, (v, _) in enumerate(opts) if v == cur), 0)))
            if r is None:
                return
            val = opts[int(r)][0]
            if val == "*":
                val = self.inputbox(label, "Comma-separated colors (%s):" % ", ".join(ANSI),
                                    cur if isinstance(cur, str) else ",".join(cur))
                if val is None:
                    return
            target[key] = val
        elif kind == "motd":
            val = self.inputbox(label, "Separate lines with |", " | ".join(cur))
            if val is not None:
                target[key] = [p.strip() for p in val.split("|") if p.strip()]
        elif kind == "int":
            val = self.inputbox(label, "Enter a number:", str(cur))
            if val is not None:
                if val.strip().isdigit():
                    target[key] = int(val)
                else:
                    self.msgbox("Invalid", "That is not a number.")
        else:
            val = self.inputbox(label, "", str(cur or ""))
            if val is not None:
                target[key] = val.strip()

    def form(self, title, text, target, specs, actions=()):
        sel = None
        while True:
            items = [(k, "%-24s %s" % (lb, self.show(target.get(k), kind, extra)))
                     for k, lb, kind, extra in specs] + [(t, lb) for t, lb, _ in actions]
            sel = self.menu(title, text, items, sel)
            if sel is None:
                return
            act = next((a for a in actions if a[0] == sel), None)
            if act:
                if act[2]():
                    return
                continue
            self.edit(target, next(sp for sp in specs if sp[0] == sel))


PICK_STYLE = [("block", "Solid blocks"), ("shade", "Shaded blocks"), ("hash", "Hash marks #"),
              ("ascii", "At signs @"), ("plain", "Plain spaced letters")]
PICK_GRAD = [(g, g.capitalize()) for g in ("horizontal", "vertical", "diagonal", "none")]
PICK_FRAME = [(f, f.capitalize()) for f in (*FRAMES, "none")]
PICK_COLOR = [(c, c) for c in ANSI]
PICK_COLORMODE = [(True, "Always on"), (False, "Always off (plain text)"),
                  ("ask", "Ask each caller")]

SPEC_IDENT = [("name", "BBS name", "str", None), ("tagline", "Tagline", "str", None),
              ("motd", "Message of the day", "motd", None),
              ("greeting", "Greeting file (.txt, .ans)", "str", None),
              ("goodbye", "Goodbye message", "str", None),
              ("hosted", "\"Hosted on Kilobyte\" line", "bool", None)]
SPEC_ART = [("enabled", "Generated banner", "bool", None), ("style", "Letter style", "pick", PICK_STYLE),
            ("colors", "Colors", "palette", None), ("gradient", "Gradient", "pick", PICK_GRAD),
            ("frame", "Frame", "pick", PICK_FRAME), ("frame_color", "Frame color", "pick", PICK_COLOR),
            ("file", "Custom art file", "str", None)]
PICK_CHARSET = [("utf-8", "UTF-8 (modern terminals, Kilobyte)"), ("cp437", "CP437 (IBM PC, BBS programs)"),
                ("ask", "Ask each caller")]
SPEC_NET = [("host", "Listen address", "str", None), ("port", "Port", "int", None),
            ("max_users", "Max callers", "int", None), ("idle_timeout", "Idle timeout (seconds)", "int", None),
            ("minutes", "Call minutes (0: any)", "int", None),
            ("charset", "Characters", "pick", PICK_CHARSET),
            ("history", "Chat history lines", "int", None)]
SPEC_SYSOP = [("sysop", "Sysop handle", "str", None), ("data_dir", "Data folder", "str", None),
              ("files_dir", "File areas folder", "str", None), ("stories_dir", "Text adventures folder", "str", None),
              ("weather_city", "Weather app's city", "str", None)]
SPEC_ROOM = [("name", "Name", "str", None), ("topic", "Topic", "str", None),
             ("password", "Password (blank = open)", "str", None), ("guests", "Guests allowed", "bool", None)]
SPEC_BOARD = [("name", "Name", "str", None), ("desc", "Description", "str", None)]
FEATURES = [("chat", "Chat rooms"), ("boards", "Message boards"), ("mail", "Private mail"),
            ("files", "File areas (downloads)"), ("games", "Games"), ("apps", "Apps"),
            ("guests", "Guest logins"), ("register", "New user registration")]


class Setup:
    def __init__(self, ui, cfg, path):
        self.ui, self.cfg, self.path = ui, cfg, path
        cfg["rooms"] = norm_items(cfg["rooms"], "topic")
        cfg["board_list"] = norm_items(cfg["board_list"], "desc")
        self.saved = self.snapshot()

    def snapshot(self):
        return json.dumps(self.cfg, sort_keys=True)

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.cfg, indent=2, ensure_ascii=False) + "\n")
        self.saved = self.snapshot()

    def preview(self):
        cfg = finalize(self.cfg, self.path.parent)
        curses.def_prog_mode()
        curses.endwin()
        print(make_banner(cfg, cfg["color"] is not False))
        input("  Banner preview - press Enter to return to setup...")
        curses.reset_prog_mode()
        self.ui.scr.refresh()

    def games_apps(self):
        ui, c = self.ui, self.cfg
        while True:
            sel = ui.menu("Games & apps", "Text programs callers run, each in a terminal of its own.",
                          [("G", "Games: " + (", ".join(c.get("games") or []) or "none")),
                           ("A", "Apps: " + (", ".join(c.get("apps") or []) or "none"))])
            if sel is None:
                return
            table, key = (GAMES, "games") if sel == "G" else (APPS, "apps")
            res = ui.checklist("Games" if sel == "G" else "Apps", "Space toggles, Enter confirms.",
                               [(v[0], k in (c.get(key) or [])) for k, v in table.items()])
            if res is not None:
                c[key] = [k for k, on in zip(table, res) if on]

    def sysop_password(self):
        ui, c = self.ui, self.cfg
        data = Path(finalize(c, self.path.parent)["data_dir"])
        if data.exists() and not os.access(data, os.W_OK):
            ui.msgbox("Sysop password", "The BBS's data belongs to the BBS service. In Kilobyte, set the "
                      "password in Internet > Host a BBS > Sysop password.")
            return
        pw = ui.inputbox("Sysop password", "New password for '%s' (4+ characters):" % c["sysop"], secret=True)
        if pw is None:
            return
        if len(pw) < 4:
            ui.msgbox("Too short", "Use at least 4 characters.")
            return
        cfg = finalize(c, self.path.parent)
        asyncio.run(BBS(cfg).set_password(cfg["sysop"], pw))
        ui.msgbox("Sysop password", "Password for '%s' updated." % c["sysop"])

    def list_editor(self, title, key, specs, describe, blank):
        ui, items_, sel = self.ui, self.cfg[key], None
        while True:
            rows = [(str(i), describe(it)) for i, it in enumerate(items_, 1)] + [("+", "Add a new one")]
            sel = ui.menu(title, "", rows, sel)
            if sel is None:
                return
            if sel == "+":
                items_.append(dict(blank))
                item = items_[-1]
            else:
                item = items_[int(sel) - 1]

            def delete(item=item):
                if ui.yesno("Delete", "Really delete '%s'?" % item["name"]):
                    items_.remove(item)
                    return True
            ui.form(title, "", item, specs, [("D", "Delete this one", delete)])
            if key == "rooms" and item in items_:
                item["name"] = re.sub(r"[^a-z0-9_-]", "", item["name"].lower()) or "room"

    def summary(self):
        c = self.cfg
        return [
            ("1", "Identity", "%s" % c["name"]),
            ("2", "ASCII art", "%s, %s frame" % (c["art"]["style"] if c["art"]["enabled"] else "off", c["art"]["frame"])),
            ("3", "Colors", self.ui.show(c["color"], "pick", PICK_COLORMODE)),
            ("4", "Features", ", ".join(k for k, _ in FEATURES if c["features"][k]) or "none"),
            ("5", "Chat rooms", "%d rooms%s" % (len(c["rooms"]), "" if c["features"]["chat"] else " (chat is off)")),
            ("6", "Message boards", "%d boards%s" % (len(c["board_list"]), "" if c["features"]["boards"] else " (boards are off)")),
            ("7", "Network & limits", "port %d, %d callers" % (c["port"], c["max_users"])),
            ("8", "Sysop & storage", "sysop: %s" % c["sysop"]),
            ("9", "Games & apps", "%d games, %d apps" % (len(c.get("games") or []), len(c.get("apps") or []))),
        ]

    def run(self):
        ui, c, sel = self.ui, self.cfg, None
        while True:
            items = [(t, "%-17s %s" % (n, d)) for t, n, d in self.summary()] + [
                ("P", "Preview banner"), ("W", "Save settings"),
                ("S", "Save and restart the BBS" if SERVICE else "Save and start the BBS"), ("Q", "Quit")]
            sel = ui.menu("hostbbs configuration", "Configure your BBS. Esc goes back, Q quits.", items, sel)
            if sel == "1":
                ui.form("Identity", "", c, SPEC_IDENT)
            elif sel == "2":
                ui.form("ASCII art", "The banner is generated from your BBS name.", c["art"], SPEC_ART,
                        [("P", "Preview banner", lambda: self.preview() and False)])
            elif sel == "3":
                ui.edit(c, ("color", "Color mode", "pick", PICK_COLORMODE))
            elif sel == "4":
                res = ui.checklist("Features", "Space toggles, Enter confirms.",
                                   [(lb, c["features"][k]) for k, lb in FEATURES])
                if res is not None:
                    for (k, _), v in zip(FEATURES, res):
                        c["features"][k] = v
            elif sel == "5":
                self.list_editor("Chat rooms", "rooms", SPEC_ROOM,
                                 lambda r: "#%-12s %s%s" % (r["name"], r.get("topic", ""),
                                                            "  [locked]" if r.get("password") else ""),
                                 {"name": "newroom", "topic": "", "password": "", "guests": True})
            elif sel == "6":
                self.list_editor("Message boards", "board_list", SPEC_BOARD,
                                 lambda b: "%-16s %s" % (b["name"], b.get("desc", "")),
                                 {"name": "New board", "desc": ""})
            elif sel == "7":
                ui.form("Network & limits", "", c, SPEC_NET)
            elif sel == "8":
                ui.form("Sysop & storage", "The sysop account is created on first start with a random "
                        "password unless you set one here.", c, SPEC_SYSOP,
                        [("P", "Set sysop password", lambda: self.sysop_password() and False)])
            elif sel == "9":
                self.games_apps()
            elif sel == "P":
                self.preview()
            elif sel == "W":
                self.save()
                ui.msgbox("Saved", "Settings written to\n%s" % self.path)
            elif sel == "S":
                self.save()
                return True
            elif sel in ("Q", None):
                if self.snapshot() != self.saved and ui.yesno("Quit", "Save changes before quitting?"):
                    self.save()
                return False


# Run by a service (Kilobyte's kilobyte-bbs.service): "Save and start" in the
# dialog saves and ends with status 10, for the service to be restarted.
SERVICE = bool(os.environ.get("HOSTBBS_SERVICE"))


def run_setup(path):
    """Open the dialog; return the raw config if the user chose to start the BBS."""
    os.environ.setdefault("ESCDELAY", "25")
    cfg = load_file(path)
    result = {}

    def app(scr):
        setup = Setup(UI(scr), cfg, path)
        result["start"] = setup.run()

    curses.wrapper(app)
    return cfg if result.get("start") else None


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    B = argparse.BooleanOptionalAction
    common.add_argument("-c", "--config", help="config file (default: ~/hostbbs/hostbbs.json)")
    common.add_argument("-n", "--name", help="BBS name")
    common.add_argument("--tagline", help="line shown under the banner")
    common.add_argument("-H", "--host", help="address to bind (default 0.0.0.0)")
    common.add_argument("-p", "--port", type=int, help="TCP port (default 2323)")
    common.add_argument("--color", action=B, default=None, help="force ANSI color on/off for everyone")
    common.add_argument("--ask-color", action="store_true", help="ask each caller about ANSI support")
    common.add_argument("--chat", action=B, default=None, help="enable/disable chat")
    common.add_argument("--boards", action=B, default=None, help="enable/disable message boards")
    common.add_argument("--mail", action=B, default=None, help="enable/disable private mail")
    common.add_argument("--guests", action=B, default=None, help="allow/deny guest logins")
    common.add_argument("--register", action=B, default=None, help="allow/deny new accounts")
    common.add_argument("--rooms", help='chat rooms, e.g. "lobby:Say hi,dev:Code talk"')
    common.add_argument("--board-list", help='message boards, e.g. "General:Chat,News:Updates"')
    common.add_argument("--art", action=B, default=None, dest="art_enabled", help="generated ASCII banner")
    common.add_argument("--art-style", choices=[*FILLS, "plain"], help="letter style")
    common.add_argument("--art-colors", help="preset (%s) or comma list of colors" % ", ".join(PALETTES))
    common.add_argument("--art-gradient", choices=["horizontal", "vertical", "diagonal", "none"])
    common.add_argument("--art-frame", choices=[*FRAMES, "none"])
    common.add_argument("--art-file", help="use your own art file instead of generating one")
    common.add_argument("--data-dir", help="where users/boards/mail are stored")
    common.add_argument("--max-users", type=int)
    common.add_argument("--motd", help="message of the day")

    p = argparse.ArgumentParser(prog="hostbbs", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version="hostbbs " + VERSION)
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("run", parents=[common], help="start the BBS (default)")
    setup = sub.add_parser("setup", help="interactive settings dialog (default)")
    setup.add_argument("-c", "--config", help="config file (default: ~/hostbbs/hostbbs.json)")
    art = sub.add_parser("art", parents=[common], help="preview the banner")
    art.add_argument("text", nargs="?", help="text to render (default: the BBS name)")
    pw = sub.add_parser("passwd", help="set a password (read from standard input)")
    pw.add_argument("-c", "--config", help="config file (default: ~/hostbbs/hostbbs.json)")
    pw.add_argument("--data-dir", help="where users/boards/mail are stored")
    pw.add_argument("user", nargs="?", help="whose (default: the sysop)")
    return p


def load_file(path, must_exist=False):
    cfg = copy.deepcopy(DEFAULTS)
    if path.exists():
        try:
            merge(cfg, json.loads(path.read_text()))
        except ValueError as e:
            sys.exit("hostbbs: bad config %s: %s" % (path, e))
    elif must_exist:
        sys.exit("hostbbs: config file not found: %s" % path)
    return cfg


def finalize(cfg, base):
    """Copy of cfg ready to run: normalized, with paths resolved against base."""
    cfg = normalize(copy.deepcopy(cfg))
    for key in ("data_dir",):
        p = Path(cfg[key]).expanduser()
        cfg[key] = str(p if p.is_absolute() else base / p)
    if cfg["art"]["file"]:
        p = Path(cfg["art"]["file"]).expanduser()
        cfg["art"]["file"] = str(p if p.is_absolute() else base / p)
    return cfg


def build_config(args):
    path = Path(args.config).expanduser() if args.config else DEFAULT_CONFIG
    cfg = load_file(path, bool(args.config))
    for k in ("name", "tagline", "host", "port", "data_dir", "max_users"):
        if getattr(args, k, None) is not None:
            cfg[k] = getattr(args, k)
    if args.color is not None:
        cfg["color"] = args.color
    if args.ask_color:
        cfg["color"] = "ask"
    if args.motd is not None:
        cfg["motd"] = [args.motd]
    for k in cfg["features"]:
        if getattr(args, k, None) is not None:
            cfg["features"][k] = getattr(args, k)
    if args.rooms is not None:
        cfg["rooms"] = args.rooms.split(",")
    if args.board_list is not None:
        cfg["board_list"] = args.board_list.split(",")
    for k, v in (("enabled", args.art_enabled), ("style", args.art_style),
                 ("colors", args.art_colors), ("gradient", args.art_gradient),
                 ("frame", args.art_frame), ("file", args.art_file)):
        if v is not None:
            cfg["art"][k] = v
    return cfg, path.parent


async def serve(cfg):
    sys.stdout.reconfigure(line_buffering=True)
    bbs = BBS(cfg)
    sysop_pw = await bbs.ensure_sysop()

    async def handle(reader, writer):
        # Every connection counts, logged in or not: no one can hold more
        # lines than the BBS has by connecting and saying nothing.
        if bbs.connections >= cfg["max_users"]:
            try:
                writer.write(b"System full, try again later.\r\n")
                await writer.drain()
                # (What the caller sent first must be read: closing on unread
                # data would throw the message away.)
                await asyncio.wait_for(reader.read(1024), 0.5)
            except (asyncio.TimeoutError, ConnectionError, OSError):
                pass
            writer.close()
            return
        bbs.connections += 1
        try:
            await Session(bbs, reader, writer).run()
        finally:
            bbs.connections -= 1

    server = await asyncio.start_server(handle, cfg["host"], cfg["port"])
    f = cfg["features"]
    print("hostbbs %s: \"%s\" listening on %s:%d" % (VERSION, cfg["name"], cfg["host"], cfg["port"]))
    print("  connect with: telnet localhost %d   (use a UTF-8 terminal)" % cfg["port"])
    print("  color: %s | %s" % (cfg["color"], " ".join(
        "%s=%s" % (k, "on" if v else "off") for k, v in f.items())))
    if f["chat"]:
        print("  rooms: " + ", ".join("#" + r for r in bbs.rooms))
    if sysop_pw:
        print("  sysop account created: %s / %s   (shown once; change it in setup > Sysop & storage)"
              % (cfg["sysop"], sysop_pw))
    async with server:
        await server.serve_forever()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        argv = ["setup"] if sys.stdin.isatty() else ["--help"]
    elif argv[0].startswith("-") and argv[0] not in ("-h", "--help", "--version"):
        argv = ["run"] + argv
    args = build_parser().parse_args(argv)
    if args.cmd is None:
        build_parser().print_help()
        return 0

    if args.cmd == "setup":
        path = Path(args.config).expanduser() if args.config else DEFAULT_CONFIG
        raw = run_setup(path)
        if raw is None:
            return 0
        if SERVICE:
            return 10
        cfg = finalize(raw, path.parent)
    elif args.cmd == "passwd":
        path = Path(args.config).expanduser() if args.config else DEFAULT_CONFIG
        cfg = load_file(path)
        if args.data_dir:
            cfg["data_dir"] = args.data_dir
        cfg = finalize(cfg, path.parent)
        who = args.user or cfg["sysop"]
        pw = sys.stdin.readline().rstrip("\n")
        if len(pw) < 4:
            sys.exit("hostbbs: a password has at least 4 characters")
        bbs = BBS(cfg)
        asyncio.run(bbs.set_password(who, pw))
        if who.lower() == cfg["sysop"].lower():
            bbs.users[who.lower()]["sysop"] = True
            bbs.save("users", bbs.users)
            bbs.meta["sysop_marked"] = True
            bbs.save("meta", bbs.meta)
        print("hostbbs: the password of %s is set" % who)
        return 0
    else:
        raw, base = build_config(args)
        cfg = finalize(raw, base)

    if args.cmd == "art":
        if args.text:
            cfg["name"] = args.text
        print(make_banner(cfg, cfg["color"] is not False and sys.stdout.isatty() or cfg["color"] is True))
        return 0

    try:
        asyncio.run(serve(cfg))
    except KeyboardInterrupt:
        print("\nhostbbs: shutting down")
    except OSError as e:
        sys.exit("hostbbs: cannot listen on %s:%s: %s" % (cfg["host"], cfg["port"], e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
