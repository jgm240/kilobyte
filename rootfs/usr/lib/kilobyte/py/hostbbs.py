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
    hostbbs op kick NAME      operator commands for a running BBS: kick, ban, force
                              (an urgent message on every screen), polls, elections...
                              `hostbbs op help` lists them
    hostbbs art --save DIR    write rotating banners (connect, rooms, boards) into DIR

In Kilobyte it is the server of Internet > Host a BBS: kilobyte-bbs.service
runs it as the user kbbs, with /etc/kilobyte/bbs/hostbbs.json.

hostbbs is free software: you can redistribute it and/or modify it under the
terms of the GNU General Public License, version 3 or later, as all of Kilobyte.
"""

import argparse
import ast
import asyncio
import base64
import calendar
import codecs
import copy
import datetime
import hashlib
import hmac
import html
import ipaddress
import json
import math
import operator
import os
import random
import re
import secrets
import shlex
import socket
import shutil
import signal
import struct
import subprocess
import sys
import textwrap
import time
import unicodedata
import xml.etree.ElementTree as ET
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path

try:
    import fcntl, pty, termios
except ImportError:      # no terminal control (a browser, Windows): the door programs (stories) are off
    fcntl = pty = termios = None

VERSION = "1.3"
PBKDF2_ITERATIONS = 150_000   # (the browser demo uses fewer: there is no OpenSSL there)
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
        "polls": True,         # the voting booth
        "elections": False,    # callers can elect deputy sysops
        "multiplayer": True,   # Tic-Tac-Toe and Hangman against other callers
        "achievements": True,
        "daily": True,         # the "Today" screen: fortune, tip, this day in history
        "lastcallers": True,
        "trivia": True,        # weekly question, quiz, leaderboard
        "stats": True,         # statistics and caller of the month
        "oneliners": True,     # the wall of short messages
        "profiles": True,      # calling cards: computer, location, bio
        "page": True,          # page the sysop into a private chat room
        "pastebin": True,      # share text by a short code
        "news": True,          # RSS/Atom news channels
    },
    "art": {
        "enabled": True,
        "style": "block",  # block | shade | hash | ascii | plain
        "colors": "rainbow",  # preset name or list of color names
        "gradient": "horizontal",  # horizontal | vertical | diagonal | none
        "frame": "double",  # single | double | round | ascii | stars | none
        "frame_color": "cyan",
        "file": "",  # path to your own art; replaces the generated banner
        "small": False,  # a generated banner for rooms and boards that have no art files
    },
    "art_dir": "",  # folder of art to rotate: connect/, rooms/<room>/, boards/<board>/ (see `hostbbs art --save`)
    "art_rotation": "random",  # random | sequential | daily
    "election": {"days": 7, "seats": 1, "min_calls": 3},  # sysop elections in the voting booth
    "tips": [],  # your own lines for the Today screen
    "modem": {"baud": 0, "ask": False, "handshake": True},  # baud 0 = full speed; 300 ... 14400 slows output
    "music": {"enabled": False, "ask": True,  # ANSI music (ESC[M ... ^N): only some terminals play it
              "connect": "T200 O4 L8 C E G O5 L4 C", "achievement": "T240 O5 L16 E G O6 L8 C"},
    "autoreload": True,  # apply the config file when it is saved (also: kill -HUP, hostbbs op reload)
    "websocket": {"enabled": False, "host": "127.0.0.1", "port": 8080,  # for the web terminal
                  "origins": [], "cert": "", "key": ""},  # origins: pages allowed to connect, e.g. ["https://jgm240.github.io"]
    "schedule": [],  # [{"at": "22:00", "days": "daily", "mode": "force|broadcast|room:lobby", "message": "..."}]
    "phone": "555-0199",  # shown in the modem handshake
    "sysop_hours": "",  # e.g. "18:00-23:00": when the sysop answers pages (empty: always)
    "birthday": "",  # "MM-DD": shows events/birthday*.ans on that day
    "news_channels": [  # the news reader's channels for everyone (any RSS or Atom feed)
        {"name": "Hacker News", "url": "https://hnrss.org/frontpage"},
        {"name": "BBC News", "url": "https://feeds.bbci.co.uk/news/rss.xml"},
        {"name": "Ars Technica", "url": "https://feeds.arstechnica.com/arstechnica/index"},
        {"name": "Slashdot", "url": "http://rss.slashdot.org/Slashdot/slashdotMain"},
        {"name": "LWN.net", "url": "https://lwn.net/headlines/rss"},
        {"name": "The Register", "url": "https://www.theregister.com/headlines.atom"},
        {"name": "NASA", "url": "https://www.nasa.gov/rss/dyn/breaking_news.rss"},
        {"name": "xkcd", "url": "https://xkcd.com/atom.xml"},
    ],
    "news": {"custom": True, "per_user": 8, "cache_minutes": 15, "allow_private": False},  # callers may add own feeds
    "paste": {"per_user": 50, "max_lines": 300},
    "trivia_file": "",  # your own questions: [{"q": "...", "a": ["right", "wrong", "wrong", "wrong"]}]
    "log": True,  # data/hostbbs.log: logins, bans, operator commands (rotated), and what callers do
                  # in public (menus, chat rooms, posts); never private mail or private messages
    "log_echo": True,  # the same lines on the console (the journal, for a service)
    # Kids mode: callers say their age, and the features they get go by it.
    # Parent mode: parents make their children's accounts and choose who else
    # may write to them.
    "kids": {
        "enabled": False,
        "join_age": 0,  # the youngest who may call
        "filter_under": 18,  # rude words are hidden from callers younger than this
        "words": [],  # more words to hide
        "parents": True,  # Parent mode (with Kids mode)
        "min_age": {"boards": 0, "post": 0, "mail": 13, "pm": 13, "chat": 0, "files": 0, "games": 0,
                    "apps": 0, "multiplayer": 0, "pastebin": 0, "news": 0, "oneliners": 0, "profiles": 0},
    },
    "update_url": "",  # where `op update` gets the newest hostbbs (empty: rBBS's repository on GitHub)
    "force": {  # how `hostbbs op force` messages look on the caller's screen
        "title": "!! MESSAGE FROM THE SYSOP !!",  # empty: no title
        "style": "block",  # block (filled) | box (framed) | line (one line)
        "color": "red",  # the block's background; the frame's or line's color
        "text_color": "bwhite",  # text on a block
        "center": True,
        "bell": True,
        "seconds": 15,  # how long it stays on screens that redraw (games)
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
    "games": ["adventure", "hangman", "robots", "snake", "sudoku", "chess", "minesweeper", "solitaire", "stories"],
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

# Games: (name, what it is, command); command None = bundled in hostbbs, run inside the call.
GAMES = {
    "adventure": ("Adventure", "Explore a cave, bring home the treasure: GO NORTH, TAKE LAMP", None),
    "hangman": ("Hangman", "Guess the word, letter by letter", None),
    "robots": ("Robots", "Outwit the robots: hjkl yubn move, t teleports", None),
    "snake": ("Snake", "Eat the numbers and grow: arrows steer", None),
    "sudoku": ("Sudoku", "Fill the grid with 1 to 9: arrows move", None),
    "chess": ("Chess", "You are white; the computer has three strengths", None),
    "minesweeper": ("Minesweeper", "Clear the field without touching a mine", None),
    "solitaire": ("Solitaire", "Klondike: build four piles from ace to king", None),
    "stories": ("Text adventures", "Z-machine stories (needs frotz and story files)", None),
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


CALC_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
            ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
CALC_NAMES = {"pi": math.pi, "e": math.e}
CALC_FUNCS = {n: getattr(math, n) for n in ("sqrt", "sin", "cos", "tan", "log", "log10", "exp", "floor", "ceil")}
CALC_FUNCS.update(abs=abs, round=round)


def calc_eval(text):
    """A sum such as 2*(3+4) or sqrt(2)**3, evaluated without eval()."""
    def go(n):
        if isinstance(n, ast.Expression):
            return go(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return n.value
        if isinstance(n, ast.Name) and n.id in CALC_NAMES:
            return CALC_NAMES[n.id]
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            return -go(n.operand) if isinstance(n.op, ast.USub) else go(n.operand)
        if isinstance(n, ast.BinOp) and type(n.op) in CALC_OPS:
            a, b = go(n.left), go(n.right)
            if isinstance(n.op, ast.Pow) and (abs(b) > 1000 or abs(a) > 1e9):
                raise ValueError("too big")
            return CALC_OPS[type(n.op)](a, b)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in CALC_FUNCS \
                and len(n.args) in (1, 2) and not n.keywords:
            return CALC_FUNCS[n.func.id](*[go(a) for a in n.args])
        raise ValueError("not a sum")
    if len(text) > 200:
        raise ValueError("too long")
    v = go(ast.parse(text.strip(), mode="eval"))
    return int(v) if isinstance(v, float) and v.is_integer() and abs(v) < 1e15 else round(v, 10) if isinstance(v, float) else v


def pbkdf2_sha256(password, salt, iterations):
    """PBKDF2-HMAC-SHA256, 32 bytes: hashlib's where there is OpenSSL, else the same thing in Python."""
    if hasattr(hashlib, "pbkdf2_hmac"):
        return hashlib.pbkdf2_hmac("sha256", password, salt, iterations)
    base = hmac.new(password, digestmod=hashlib.sha256)
    h = base.copy()
    h.update(salt + b"\x00\x00\x00\x01")
    u = h.digest()
    acc = int.from_bytes(u, "big")
    for _ in range(iterations - 1):
        h = base.copy()
        h.update(u)
        u = h.digest()
        acc ^= int.from_bytes(u, "big")
    return acc.to_bytes(32, "big")


async def offload(fn, *args):
    """Run slow work off the event loop in a thread; where there are no threads (a browser) just run it."""
    if sys.platform == "emscripten":
        return fn(*args)
    return await asyncio.get_running_loop().run_in_executor(None, fn, *args)


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


# ---- Kids mode ------------------------------------------------------------------------------------
# Who a room or a board is for.
AGES = [("all", "Everyone"), ("kids", "Kids only (under 13)"), ("teens", "Teens only (13 to 17)"),
        ("minors", "Under 18 only"), ("adults", "18 and up")]
KID, ADULT = 13, 18
# Hidden from callers under kids.filter_under (the sysop can add more words).
RUDE = ["fuck", "fucker", "fucking", "motherfucker", "shit", "shitty", "bullshit", "bitch", "bastard",
        "asshole", "arsehole", "cunt", "dick", "dickhead", "piss", "pissed", "crap", "slut", "whore",
        "wanker", "twat", "bollocks", "prick", "cock", "pussy", "porn", "nazi", "retard", "fag", "faggot"]


def age_fits(age, ages):
    """Is someone of this age (None: not known) let in where `ages` says?"""
    if ages in (None, "", "all"):
        return True
    if age is None:
        return ages == "adults"
    return {"kids": age < KID, "teens": KID <= age < ADULT, "minors": age < ADULT,
            "adults": age >= ADULT}.get(ages, True)


# ---- updating: the newest hostbbs from rBBS's repository -------------------------------------------
UPDATE_URL = "https://raw.githubusercontent.com/jgm240/rbbs/main/hostbbs"
# Where the BBS may not change its own program (Kilobyte), it asks for an
# update by making this file; a service of the system does it.
UPDATE_REQUEST = os.environ.get("HOSTBBS_UPDATE_REQUEST", "")


def fetch_update(url=None):
    """The newest hostbbs: (version, its text), checked to be a whole one."""
    req = urllib.request.Request(url or UPDATE_URL, headers={"User-Agent": "hostbbs/" + VERSION})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read(4_000_001)
    if len(data) > 4_000_000:
        raise ValueError("too big to be hostbbs")
    text = data.decode("utf-8")
    m = re.search(r'^VERSION = "([0-9.]+)"', text, re.M)
    if not m or "def main(" not in text or not text.startswith("#!/usr/bin/env python3"):
        raise ValueError("that is not hostbbs")
    compile(text, "hostbbs", "exec")  # (it must at least be whole Python)
    return m.group(1), text


def program_path():
    me = sys.argv[0] if sys.argv and os.path.basename(sys.argv[0]).startswith("hostbbs") else __file__
    return os.path.realpath(me)


def self_update(url=None):
    """Replace this program with the newest one. Returns a sentence for people."""
    version, text = fetch_update(url)
    me = program_path()
    with open(me, encoding="utf-8") as f:
        if f.read() == text:
            return "hostbbs %s is the newest already." % VERSION
    vt = lambda v: tuple(int(x) for x in v.split(".") if x.isdigit())
    if vt(version) < vt(VERSION):  # (an update never goes back)
        return "hostbbs %s here is newer than the one there (%s): kept." % (VERSION, version)
    if not os.access(me, os.W_OK) or not os.access(os.path.dirname(me), os.W_OK):
        raise PermissionError("this hostbbs (%s) may not be changed by its user" % me)
    st = os.stat(me)
    tmp = me + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(tmp, st.st_mode)
    if os.geteuid() == 0:  # (an update by root keeps the file the service user's)
        os.chown(tmp, st.st_uid, st.st_gid)
    try:
        os.replace(me, me + ".old")  # (the one before is kept)
    except OSError:
        pass
    os.replace(tmp, me)
    return "hostbbs %s is installed (it was %s)." % (version, VERSION)


def normalize(cfg):
    cfg["rooms"] = norm_items(cfg["rooms"], "topic")
    for r in cfg["rooms"]:
        r["name"] = re.sub(r"[^a-z0-9_-]", "", r["name"].lower()) or "room"
    cfg["board_list"] = norm_items(cfg["board_list"], "desc")
    for it in cfg["rooms"] + cfg["board_list"]:
        if it.get("ages") not in dict(AGES):
            it["ages"] = "all"
    k = cfg["kids"]
    k["words"] = [w.strip().lower() for w in (k.get("words") or []) if str(w).strip()]
    for key, v in list(k["min_age"].items()):
        try:
            k["min_age"][key] = max(0, int(v))
        except (TypeError, ValueError):
            k["min_age"][key] = 0
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



# --------------------------------------------------------------------------
# BBS-wide extras: bans, polls, elections, scores, last callers
# --------------------------------------------------------------------------

class BBSExtras:
    def init_extras(self):
        self.bans = self.load("bans")
        for k in ("names", "ips", "muted"):
            self.bans.setdefault(k, {})
        self.polls = self.load("polls")
        self.polls.setdefault("polls", [])
        self.polls.setdefault("next", 1)
        self.elect = self.load("elections")
        self.elect.setdefault("current", None)
        self.elect.setdefault("history", [])
        self.scores = self.load("scores")
        self.tables = {}
        self.next_table = 1

    # ---- bans and mutes
    def is_banned(self, name=None, ip=None):
        if name and name.lower() in self.bans["names"]:
            return self.bans["names"][name.lower()]["reason"]
        if ip and ip in self.bans["ips"]:
            return self.bans["ips"][ip]["reason"]
        return None

    def is_muted(self, name):
        until = self.bans["muted"].get(name.lower())
        if until is not None and until <= time.time():
            del self.bans["muted"][name.lower()]
            self.save("bans", self.bans)
            return False
        return until is not None

    def broadcast_sysop(self, text):
        for s in list(self.sessions):
            s.push(s.c("bred", "[SYSOP] " + text))

    def in_sysop_hours(self):
        """Is it within sysop_hours ("18:00-23:00", may wrap past midnight)? True when none are set."""
        m = re.match(r"^\s*(\d{1,2}):(\d\d)\s*-\s*(\d{1,2}):(\d\d)\s*$", self.cfg.get("sysop_hours") or "")
        if not m:
            return True
        a, b = int(m.group(1)) * 60 + int(m.group(2)), int(m.group(3)) * 60 + int(m.group(4))
        t = time.localtime()
        now = t.tm_hour * 60 + t.tm_min
        return a <= now < b if a <= b else (now >= a or now < b)

    def who_color(self, name):
        u = self.users.get(name.lower())
        return u["color"] if u and u.get("color") in ANSI else name_color(name)

    # ---- last callers and scores
    def record_caller(self, name, since):
        log = self.meta.setdefault("callers", [])
        log.append({"name": name, "ts": since, "secs": int(time.time() - since)})
        del log[:-50]
        self.save("meta", self.meta)

    def add_score(self, game, name, score, low=False):
        table = self.scores.setdefault(game, [])
        table.append({"name": name, "score": score, "ts": time.time(), "low": low})
        table.sort(key=lambda e: e["score"] if low else -e["score"])
        del table[10:]
        self.save("scores", self.scores)

    # ---- polls
    def poll_add(self, question, options):
        p = {"id": self.polls["next"], "question": question, "options": options,
             "votes": {}, "closed": False, "ts": time.time()}
        self.polls["next"] += 1
        self.polls["polls"].append(p)
        self.save("polls", self.polls)
        return p

    def poll_vote(self, poll, voter, idx):
        if poll["closed"]:
            return False, "This poll is closed."
        if voter in poll["votes"]:
            return False, "You have voted in this poll."
        if not 0 <= idx < len(poll["options"]):
            return False, "No such choice."
        poll["votes"][voter] = idx
        self.save("polls", self.polls)
        return True, "Vote counted."

    # ---- sysop elections
    def mail_from_bbs(self, to, subject, lines):
        self.mail.setdefault(to.lower(), []).append({
            "from": "The BBS", "ts": time.time(), "subject": subject, "body": lines, "read": False})
        self.save("mail", self.mail)

    def elect_start(self, days):
        cur = self.elect["current"]
        if cur:
            return False, "an election is already running"
        now = time.time()
        self.elect["current"] = {
            "id": len(self.elect["history"]) + 1, "start": now, "end": now + max(days, 1) * 86400,
            "seats": self.cfg["election"]["seats"], "candidates": {}, "votes": {}}
        self.save("elections", self.elect)
        self.broadcast_sysop("A sysop election is open for %d days. Stand or vote in the voting booth." % days)
        return True, "election opened for %d days" % days

    def elect_nominate(self, name, by, force=False):
        cur = self.elect["current"]
        if not cur:
            return False, "No election is running."
        u = self.users.get(name.lower())
        if not u:
            return False, "No such user."
        if u.get("sysop") or u["name"].lower() == (self.cfg["sysop"] or "").lower():
            return False, "A sysop is not up for election."
        need = self.cfg["election"]["min_calls"]
        if not force and u["calls"] < need:
            return False, "%s needs %d calls to stand." % (u["name"], need)
        if name.lower() in cur["candidates"]:
            return False, "%s is already standing." % u["name"]
        cur["candidates"][name.lower()] = {"name": u["name"], "by": by}
        self.save("elections", self.elect)
        s = self.find_session(u["name"])
        if s:
            s.award("candidate")
        return True, "%s is standing for sysop." % u["name"]

    def elect_vote(self, voter, cand):
        cur = self.elect["current"]
        v = self.users.get(voter.lower())
        if not cur or not v:
            return False, "No election, or you have no account."
        if v["calls"] < self.cfg["election"]["min_calls"]:
            return False, "You need %d calls to vote." % self.cfg["election"]["min_calls"]
        if cand not in cur["candidates"]:
            return False, "No such candidate."
        cur["votes"][voter.lower()] = cand
        self.save("elections", self.elect)
        return True, "Your vote for %s is counted (you may change it until the end)." % cur["candidates"][cand]["name"]

    def elect_counts(self, cur):
        counts = {c: 0 for c in cur["candidates"]}
        for c in cur["votes"].values():
            counts[c] = counts.get(c, 0) + 1
        return counts

    def elect_end(self):
        cur = self.elect["current"]
        if not cur:
            return False, "no election is running"
        counts = self.elect_counts(cur)
        ranked = sorted(cur["candidates"], key=lambda c: (-counts[c], self.users[c]["created"]))
        winners = [c for c in ranked if counts[c] > 0][:cur["seats"]]
        for c in winners:
            u = self.users[c]
            u["deputy"] = True
            self.mail_from_bbs(c, "You were elected deputy sysop", [
                "The callers have elected you. You may now delete posts, kick callers and set topics.",
                "Please use it kindly."])
            s = self.find_session(u["name"])
            if s:
                s.deputy = True
                s.award("elected")
                s.push(s.c("bgreen", "You were elected deputy sysop!"))
        cur["winners"] = winners
        cur["counts"] = counts
        self.elect["history"].append(cur)
        self.elect["current"] = None
        self.save("users", self.users)
        self.save("elections", self.elect)
        text = "Election closed. Elected: " + (", ".join(self.users[c]["name"] for c in winners) or "nobody")
        self.broadcast_sysop(text)
        return True, text

    def elect_status(self):
        cur = self.elect["current"]
        if not cur:
            last = self.elect["history"][-1] if self.elect["history"] else None
            return "no election is running" + ((" (last: elected %s)" % (
                ", ".join(self.users[c]["name"] for c in last["winners"] if c in self.users) or "nobody")) if last else "")
        counts = self.elect_counts(cur)
        rows = ["election open until %s for %d seat%s" % (fdate(cur["end"]), cur["seats"], "" if cur["seats"] == 1 else "s")]
        for c, info in sorted(cur["candidates"].items(), key=lambda kv: -counts[kv[0]]):
            rows.append("  %-16s %d vote%s" % (info["name"], counts[c], "" if counts[c] == 1 else "s"))
        return "\n".join(rows)

    def elect_check(self):
        cur = self.elect["current"]
        if cur and time.time() >= cur["end"]:
            self.elect_end()


# --------------------------------------------------------------------------
# Multiplayer tables (Tic-Tac-Toe, Hangman)
# --------------------------------------------------------------------------

TTT_LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6))

WORDS5 = """about above actor adapt admit adopt adult after again agent agree ahead alarm album alert alien align alike
alive allow alone along alter among angel anger angle angry ankle apart apple apply arena argue arise armor array
arrow aside asset audio avoid awake award aware badge bacon baker basic basin basis beach beard beast begin being
bench berry birth black blade blame blank blast blaze bleed blend bless blind block blood bloom board boast bonus
boost booth bound brain brake brand brave bread break breed brick bride brief bring broad broke brown brush build
built bunch burst buyer cabin cable candy carry catch cause chain chair chalk charm chart chase cheap check cheek
chess chest chief child chill chord civic claim class clean clear clerk click cliff climb clock close cloth cloud
coach coast color couch could count court cover crack craft crane crash crawl crazy cream crime crisp cross crowd
crown crush curve cycle daily dance death delay depth dirty doubt dozen draft drain drama drank dream dress drift
drill drink drive eager early earth eight elite empty enemy enjoy enter equal error essay event every exact exist
extra faith false fancy fault feast fence fever field fifth fight final flame flash fleet flesh float flood floor
flour fluid focus force forge forth forty forum frame frank fresh front frost fruit fully giant given glass globe
glory grace grade grain grand grant grape graph grasp grass great green greet grief gross group grown guard guess
guest guide habit happy harsh heart heavy hello honey honor horse hotel house human humor ideal image index inner
input irony issue ivory joint judge juice knife known label labor large laser later laugh layer learn lease least
leave legal lemon level light limit linen liver local logic loose lover lower loyal lucky lunch magic major maker
march match maybe mayor media mercy merit metal meter might minor minus mixed model modem money month moral motor
mount mouse mouth movie music nerve never night noble noise north novel nurse ocean offer often olive onion opera
orbit order other outer owner paint panel paper party pasta patch pause peace pearl phase phone photo piano piece
pilot pitch pixel place plain plane plant plate point polar pound power press price pride prime print prior prize
proof proud prove pulse punch pupil queen quest quick quiet quite radio raise range rapid ratio reach ready realm
rebel refer relax reply rider ridge right rigid risky rival river robot rocky rough round route royal rural salad
sauce scale scene scope score sense serve seven shade shake shape share sharp sheep sheet shelf shell shift shine
shirt shock shoot shore short shout sight silly since skill sleep slice slide small smart smile smoke snake solid
solve sorry sound south space spare speak speed spend spice spine split spoke sport staff stage stair stake stamp
stand start state steam steel steep stick still stock stone stood store storm story strip study stuff style sugar
suite super sweet swing table taste teach tease teeth thank theme there thick thing think third those three throw
thumb tiger tight timer tired title toast today token tooth topic total touch tough tower trace track trade trail
train treat trend trial tribe trick truck truly trust truth twice uncle under union unity until upper upset urban
usage usual vague valid value video virus visit vital vivid vocal voice waste watch water weary weigh weird wheel
where which while white whole whose woman world worry worth would wound write wrong yield young youth zebra""".split()


class MPGame:
    """One kind of table game. The Table owns the players; the game owns the rules."""
    title, min, max = "?", 2, 2
    manual = False                     # started by the host's S key (else when the table is full)
    quit_keys = ("ESC", "q", "Q")
    leave_hint = "Q leaves."

    def __init__(self, table):
        self.t = table

    @classmethod
    async def prepare(cls, session):
        """Ask the host what is needed to open a table; None cancels."""
        return {}

    def setup(self, opts, host):
        pass

    def start(self):
        pass

    def current(self):
        return None

    def handle(self, me, k):
        pass

    def render(self, me):
        return ""

    def on_leave(self, s):
        t = self.t
        if t.state == "playing" and len(t.players) < self.min:
            t.finish(list(t.players), "%s left the table." % s.name)

    def head(self, me):
        return ["", "  %s   table %d" % (me.sgr("96;1", self.title.upper()), self.t.id), ""]

    def waiting(self, me):
        t = self.t
        lines = self.head(me) + ["  Players: " + ", ".join(p.name for p in t.players), ""]
        if self.manual:
            lines.append("  " + (me.sgr("92;1", "Press S to start") + " (%d or more players), Q or Esc leaves." % self.min
                                 if me is t.players[0] else "Waiting for %s to start. Q or Esc leaves." % t.players[0].name))
        else:
            lines.append("  Waiting for an opponent...   Q or Esc leaves.")
        return "\n".join(lines)

    def turn_line(self, me, verb="press 1-9"):
        t = self.t
        if t.state == "over":
            return "  " + me.sgr("93;1", t.msg) + "   (any key)"
        cur = self.current()
        if cur is me:
            return "  " + me.sgr("92;1", "Your turn: %s." % verb) + "   " + self.leave_hint
        return "  Waiting for %s..." % (cur.name if cur else "?")


class TicTacToe(MPGame):
    title = "Tic-Tac-Toe"

    def start(self):
        self.board, self.turn = [" "] * 9, 0

    def current(self):
        return self.t.players[self.turn % len(self.t.players)]

    def handle(self, me, k):
        t = self.t
        if not (k.isdigit() and k != "0" and self.current() is me):
            return
        i = int(k) - 1
        if self.board[i] != " ":
            return
        mark = "X" if t.players.index(me) == 0 else "O"
        self.board[i] = mark
        for a, b, c in TTT_LINES:
            if self.board[a] == self.board[b] == self.board[c] == mark:
                return t.finish([me], "%s wins!" % me.name)
        if " " not in self.board:
            return t.finish([], "A draw.")
        self.turn += 1
        t.notify()

    def render(self, me):
        t, sg = self.t, me.sgr
        if t.state == "waiting":
            return self.waiting(me)

        def cell(i):
            v = self.board[i]
            return sg("91;1", "X") if v == "X" else sg("96;1", "O") if v == "O" else sg("90", str(i + 1))
        out = self.head(me)
        out.append("  X: %s    O: %s" % (t.players[0].name, t.players[1].name if len(t.players) > 1 else "(gone)"))
        out.append("")
        for r in range(3):
            out.append("        %s | %s | %s" % (cell(r * 3), cell(r * 3 + 1), cell(r * 3 + 2)))
            if r < 2:
                out.append("       ---+---+---")
        return "\n".join(out + ["", self.turn_line(me)])


class Hangman(MPGame):
    title, min, max, manual = "Hangman", 2, 6, True
    quit_keys = ("ESC",)
    leave_hint = "Esc leaves."

    @classmethod
    async def prepare(cls, s):
        word = (await s.readline("Secret word for the others to guess (hidden; Enter = pick one at random): ",
                                 echo=False, maxlen=20)).strip().upper()
        if word and not re.fullmatch(r"[A-Z]{3,20}", word):
            await s.send(s.c("red", "Letters only, 3 or more.\n"))
            return None
        return {"word": word}

    def setup(self, opts, host):
        self.word = opts.get("word") or secrets.choice(HANGWORDS).upper()
        self.setter = host if opts.get("word") else None
        self.used, self.wrong, self.turn = [], 0, 0

    def guessers(self):
        return [p for p in self.t.players if p is not self.setter]

    def current(self):
        g = self.guessers()
        return g[self.turn % len(g)] if g and self.t.state == "playing" else None

    def on_leave(self, s):
        t = self.t
        if t.state != "playing":
            return
        if s is self.setter or not self.guessers():
            t.finish(self.guessers(), "%s left the table." % s.name)
        elif len(t.players) < 2:
            t.finish(list(t.players), "%s left the table." % s.name)

    def handle(self, me, k):
        t = self.t
        if not (self.current() is me and len(k) == 1 and k.isalpha() and k.upper() not in self.used):
            return
        ch = k.upper()
        self.used.append(ch)
        if ch in self.word:
            t.msg = "%s found %s." % (me.name, ch)
            if all(c in self.used for c in self.word):
                return t.finish(self.guessers(), "The word was %s. The guessers win!" % self.word)
        else:
            self.wrong += 1
            self.turn += 1
            t.msg = "%s: no %s." % (me.name, ch)
            if self.wrong >= 6:
                return t.finish([self.setter] if self.setter else [], "Hanged! The word was %s." % self.word)
        t.notify()

    def render(self, me):
        t, sg = self.t, me.sgr
        if t.state == "waiting":
            note = "You set the word." if self.setter is me else "A secret word is waiting." if self.setter else "Random word."
            return self.waiting(me) + "\n  " + note
        shown = " ".join(c if (c in self.used or me is self.setter or t.state == "over") else "_" for c in self.word)
        out = self.head(me)
        out.append("\n".join("  " + ln for ln in HANGMAN_ART[min(self.wrong, 6)].split("\n")))
        out += ["", "   " + shown, "", "  Used: " + (" ".join(sorted(self.used)) or "-") + "   Lives left: %d" % (6 - self.wrong),
                "  Players: " + ", ".join(p.name + ("*" if p is self.setter else "") for p in t.players)
                + ("   (*sets the word)" if self.setter else ""), ""]
        if t.msg and t.state == "playing":
            out.append("  " + t.msg)
        if me is self.setter and t.state == "playing":
            out.append("  You watch. It is %s's turn." % (self.current().name if self.current() else "?"))
        else:
            out.append(self.turn_line(me, "press a letter"))
        return "\n".join(out)


class ConnectFour(MPGame):
    title = "Connect Four"
    ROWS, COLS = 6, 7

    def start(self):
        self.grid = [[0] * self.COLS for _ in range(self.ROWS)]
        self.turn = 0
        self.last = None

    def current(self):
        return self.t.players[self.turn % 2]

    def four(self, r, c, v):
        for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
            n = 1
            for sgn in (1, -1):
                rr, cc = r + dr * sgn, c + dc * sgn
                while 0 <= rr < self.ROWS and 0 <= cc < self.COLS and self.grid[rr][cc] == v:
                    n += 1
                    rr, cc = rr + dr * sgn, cc + dc * sgn
            if n >= 4:
                return True
        return False

    def handle(self, me, k):
        t = self.t
        if not (k in "1234567" and len(k) == 1 and self.current() is me):
            return
        c = int(k) - 1
        r = next((r for r in range(self.ROWS - 1, -1, -1) if self.grid[r][c] == 0), None)
        if r is None:
            return
        v = 1 + t.players.index(me)
        self.grid[r][c] = v
        self.last = (r, c)
        if self.four(r, c, v):
            return t.finish([me], "%s connects four!" % me.name)
        if all(self.grid[0]):
            return t.finish([], "A draw.")
        self.turn += 1
        t.notify()

    def render(self, me):
        t, sg = self.t, me.sgr
        if t.state == "waiting":
            return self.waiting(me)
        out = self.head(me)
        out.append("  %s: %s    %s: %s" % (sg("91;1", "red O"), t.players[0].name, sg("93;1", "yellow O"),
                                           t.players[1].name if len(t.players) > 1 else "(gone)"))
        out.append("")
        for r in range(self.ROWS):
            cells = ""
            for c in range(self.COLS):
                v = self.grid[r][c]
                ch = sg("91;1" if v == 1 else "93;1", "O") if v else sg("90", ".")
                cells += " " + ch + " "
            out.append("      |" + cells + "|")
        out.append("      +" + "-" * (3 * self.COLS) + "+")
        out.append("       " + "".join(" %d " % (c + 1) for c in range(self.COLS)))
        return "\n".join(out + ["", self.turn_line(me, "press a column 1-7")])


class Battleship(MPGame):
    title = "Battleship"
    FLEET = (5, 4, 3, 3, 2)

    def start(self):
        self.ships = [self.place(), self.place()]          # per player: list of sets of cells
        self.shots = [{}, {}]                              # shots fired BY player i: cell -> True (hit) / False
        self.turn, self.pend = 0, {}

    def place(self):
        taken, ships = set(), []
        for size in self.FLEET:
            while True:
                horiz = secrets.randbelow(2) == 0
                r, c = secrets.randbelow(10 if horiz else 11 - size), secrets.randbelow(11 - size if horiz else 10)
                cells = {(r + (0 if horiz else i)) * 10 + c + (i if horiz else 0) for i in range(size)}
                if not cells & taken:
                    taken |= cells
                    ships.append(cells)
                    break
        return ships

    def current(self):
        return self.t.players[self.turn % 2]

    def handle(self, me, k):
        t = self.t
        if self.current() is not me or len(k) != 1:
            return
        if k.upper() in "ABCDEFGHIJ" and k.isalpha():
            self.pend[me] = "ABCDEFGHIJ".index(k.upper())
            t.notify()
            return
        if not k.isdigit() or me not in self.pend:
            return
        me_i = t.players.index(me)
        foe = 1 - me_i
        cell = int(k) * 10 + self.pend.pop(me)
        if cell in self.shots[me_i]:
            t.msg = "You already fired at %s%d." % ("ABCDEFGHIJ"[cell % 10], cell // 10)
            return t.notify()
        hit = any(cell in s for s in self.ships[foe])
        self.shots[me_i][cell] = hit
        label = "%s%d" % ("ABCDEFGHIJ"[cell % 10], cell // 10)
        if hit:
            ship = next(s for s in self.ships[foe] if cell in s)
            sunk = all(c in self.shots[me_i] for c in ship)
            t.msg = "%s fires at %s: %s" % (me.name, label, "HIT and SUNK a ship of %d!" % len(ship) if sunk else "HIT!")
            if all(c in self.shots[me_i] for s in self.ships[foe] for c in s):
                return t.finish([me], "%s sank the whole fleet!" % me.name)
        else:
            t.msg = "%s fires at %s: miss." % (me.name, label)
        self.turn += 1
        t.notify()

    def grid(self, me, mine):
        """Rows of text for one 10x10 board: my fleet with their shots, or their waters with mine."""
        sg = me.sgr
        t = self.t
        mi = t.players.index(me) if me in t.players else 0
        foe = 1 - mi
        rows = ["   " + " ".join("ABCDEFGHIJ")]
        for r in range(10):
            line = "%d  " % r
            for c in range(10):
                cell = r * 10 + c
                if mine:
                    ship = any(cell in s for s in self.ships[mi])
                    shot = self.shots[foe].get(cell)
                    ch = sg("91;1", "X") if shot else sg("94", "o") if shot is False else sg("97", "#") if ship else sg("90", ".")
                else:
                    shot = self.shots[mi].get(cell)
                    ch = sg("91;1", "X") if shot else sg("94", "o") if shot is False else sg("90", ".")
                line += ch + " "
            rows.append(line)
        return rows

    def render(self, me):
        t = self.t
        if t.state == "waiting":
            return self.waiting(me)
        out = self.head(me)
        left, right = self.grid(me, True), self.grid(me, False)
        out.append("  " + "Your fleet".ljust(26) + "Enemy waters")
        for a, b in zip(left, right):
            pad = " " * (26 - len(re.sub(r"\x1b\[[0-9;]*m", "", a)))
            out.append("  " + a + pad + b)
        if t.msg:
            out += ["", "  " + t.msg]
        pend = self.pend.get(me)
        verb = "type a column letter, then a row digit" if pend is None else "now the row digit for column %s" % "ABCDEFGHIJ"[pend]
        return "\n".join(out + ["", self.turn_line(me, verb)])


class Reversi(MPGame):
    title = "Reversi"
    DIRS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

    def start(self):
        self.b = [[0] * 8 for _ in range(8)]
        self.b[3][3] = self.b[4][4] = 2
        self.b[3][4] = self.b[4][3] = 1
        self.turn, self.pend = 0, {}

    def current(self):
        return self.t.players[self.turn % 2]

    def flips(self, r, c, v):
        if self.b[r][c]:
            return []
        out = []
        for dr, dc in self.DIRS:
            run, rr, cc = [], r + dr, c + dc
            while 0 <= rr < 8 and 0 <= cc < 8 and self.b[rr][cc] == 3 - v:
                run.append((rr, cc))
                rr, cc = rr + dr, cc + dc
            if run and 0 <= rr < 8 and 0 <= cc < 8 and self.b[rr][cc] == v:
                out += run
        return out

    def moves(self, v):
        return [(r, c) for r in range(8) for c in range(8) if self.flips(r, c, v)]

    def counts(self):
        flat = [x for row in self.b for x in row]
        return flat.count(1), flat.count(2)

    def handle(self, me, k):
        t = self.t
        if self.current() is not me or len(k) != 1:
            return
        if k.lower() in "abcdefgh" and k.isalpha():
            self.pend[me] = "abcdefgh".index(k.lower())
            return t.notify()
        if not (k in "12345678") or me not in self.pend:
            return
        c, r = self.pend.pop(me), int(k) - 1
        v = 1 + t.players.index(me)
        fl = self.flips(r, c, v)
        if not fl:
            t.msg = "That is not a legal move."
            return t.notify()
        self.b[r][c] = v
        for rr, cc in fl:
            self.b[rr][cc] = v
        t.msg = "%s plays %s%d and turns %d." % (me.name, "abcdefgh"[c], r + 1, len(fl))
        self.turn += 1
        nxt = 1 + (self.turn % 2)
        if not self.moves(nxt):
            if not self.moves(3 - nxt):
                black, white = self.counts()
                win = [t.players[0]] if black > white else [t.players[1]] if white > black else []
                return t.finish(win, "Final score %d to %d. %s" % (black, white, (win[0].name + " wins!") if win else "A draw."))
            t.msg += " %s has no move and passes." % self.current().name
            self.turn += 1
        t.notify()

    def render(self, me):
        t, sg = self.t, me.sgr
        if t.state == "waiting":
            return self.waiting(me)
        black, white = self.counts()
        out = self.head(me)
        out.append("  %s %s (%d)    %s %s (%d)" % (sg("30;42", " X "), t.players[0].name, black,
                                                  sg("97;42;1", " O "), t.players[1].name if len(t.players) > 1 else "(gone)", white))
        out.append("")
        mv = set(self.moves(1 + t.players.index(me))) if (t.state == "playing" and self.current() is me) else set()
        out.append("     " + "".join(" %s " % ch for ch in "abcdefgh"))
        for r in range(8):
            row = " %d  " % (r + 1)
            for c in range(8):
                v = self.b[r][c]
                if v == 1:
                    row += sg("30;42;1", " X ")
                elif v == 2:
                    row += sg("97;42;1", " O ")
                elif (r, c) in mv:
                    row += sg("93;42", " . ")
                else:
                    row += sg("42", "   ")
            out.append(row)
        if t.msg:
            out += ["", "  " + t.msg]
        pend = self.pend.get(me)
        verb = "type a column letter, then a row digit" if pend is None else "now the row 1-8"
        return "\n".join(out + ["", self.turn_line(me, verb)])


class WordRace(MPGame):
    title, min, max, manual = "Word Race", 2, 4, True
    quit_keys = ("ESC",)

    def start(self):
        self.word = secrets.choice(WORDS5).upper()
        self.g = {p: [] for p in self.t.players}
        self.buf = {p: "" for p in self.t.players}

    def feedback(self, guess):
        res, rest = ["x"] * 5, list(self.word)
        for i in range(5):
            if guess[i] == self.word[i]:
                res[i] = "g"
                rest[i] = None
        for i in range(5):
            if res[i] == "x" and guess[i] in rest:
                res[i] = "y"
                rest[rest.index(guess[i])] = None
        return "".join(res)

    def on_leave(self, s):
        t = self.t
        if t.state == "playing":
            if len(t.players) < 2:
                t.finish(list(t.players), "%s left the table." % s.name)
            elif all(len(self.g.get(p, [])) >= 6 for p in t.players):
                t.finish([], "Nobody got it. The word was %s." % self.word)

    def handle(self, me, k):
        t = self.t
        if me not in self.g or len(self.g[me]) >= 6:
            return
        buf = self.buf[me]
        if k in ("\x7f", "\x08") and buf:
            self.buf[me] = buf[:-1]
        elif len(k) == 1 and k.isalpha() and len(buf) < 5:
            self.buf[me] = buf + k.upper()
        elif k in ("\r", "\n") and len(buf) == 5:
            fb = self.feedback(buf)
            self.g[me].append((buf, fb))
            self.buf[me] = ""
            if buf == self.word:
                return t.finish([me], "%s solved it in %d!" % (me.name, len(self.g[me])))
            if all(len(self.g[p]) >= 6 for p in t.players):
                return t.finish([], "Nobody got it. The word was %s." % self.word)
        t.notify()

    def render(self, me):
        t, sg = self.t, me.sgr
        if t.state == "waiting":
            return self.waiting(me)
        out = self.head(me)
        codes = {"g": "30;42", "y": "30;43", "x": "97;100"}
        mine = self.g.get(me, [])
        for i in range(6):
            if i < len(mine):
                w, fb = mine[i]
                out.append("      " + "".join(sg(codes[f], " %s " % ch) + " " for ch, f in zip(w, fb)))
            elif i == len(mine) and me in self.buf:
                b = self.buf[me].ljust(5, "_")
                out.append("      " + "".join(sg("97", " %s " % ch) + " " for ch in b))
            else:
                out.append("      " + "".join(sg("90", " . ") + " " for _ in range(5)))
        out.append("")
        for p in t.players:
            if p is me:
                continue
            marks = "  ".join("".join({"g": "#", "y": "+", "x": "."}[f] for f in fb) for _, fb in self.g.get(p, []))
            out.append("  %-12s %s" % (p.name, marks or "(thinking)"))
        out.append("")
        if t.state == "over":
            out.append("  " + sg("93;1", t.msg) + "   (any key)")
        else:
            out.append("  Type letters, Enter to guess. Same word for everyone: first to solve it wins.   Esc leaves.")
        return "\n".join(out)


MP_GAMES = {"ttt": TicTacToe, "hang": Hangman, "c4": ConnectFour, "ship": Battleship, "rev": Reversi, "word": WordRace}
MP_KEYS = {"t": "ttt", "h": "hang", "c": "c4", "b": "ship", "r": "rev", "w": "word"}
MP_ALIASES = {"ttt": "ttt", "tictactoe": "ttt", "hangman": "hang", "hang": "hang", "c4": "c4", "connect4": "c4",
              "connectfour": "c4", "ship": "ship", "battleship": "ship", "rev": "rev", "reversi": "rev",
              "word": "word", "wordrace": "word"}


class Table:
    def __init__(self, tid, game, host, opts=None):
        self.id, self.game = tid, game
        self.impl = MP_GAMES[game](self)
        self.players = [host]
        self.events = {host: asyncio.Event()}
        self.state = "waiting"          # waiting | playing | over
        self.msg = ""
        self.winners = []
        self.impl.setup(opts or {}, host)

    @property
    def title(self):
        return self.impl.title

    @property
    def max_players(self):
        return self.impl.max

    def notify(self):
        for ev in self.events.values():
            ev.set()

    def join(self, s):
        self.players.append(s)
        self.events[s] = asyncio.Event()
        if not self.impl.manual and len(self.players) >= self.impl.max:
            self.start()
        self.notify()

    def start(self):
        self.state = "playing"
        self.msg = ""
        self.impl.start()
        self.notify()

    def finish(self, winners, msg):
        self.state, self.msg, self.winners = "over", msg, winners
        key = self.game
        for p in list(self.players):
            p.game_over({"hang": "mphang", "ttt": "ttt"}.get(key, "mp_" + key), won=p in winners)
        self.notify()

    def leave(self, s):
        if s not in self.players:
            return
        self.players.remove(s)
        self.impl.on_leave(s)
        self.notify()

    def current(self):
        return self.impl.current() if self.state == "playing" else None

    def handle(self, me, k):
        if k in self.impl.quit_keys or (self.state == "waiting" and k in ("q", "Q")):
            return "leave"
        if self.state == "over":
            return "leave"
        if self.state == "waiting":
            if self.impl.manual and k in ("s", "S") and me is self.players[0] and len(self.players) >= self.impl.min:
                self.start()
            return None
        self.impl.handle(me, k)
        return None

    def render(self, me):
        return self.impl.render(me)



# --------------------------------------------------------------------------
# Trivia, quiz, statistics, caller of the month, event log
# --------------------------------------------------------------------------

TRIVIA = [  # question, the right answer, three wrong ones (the order is shuffled when shown)
    ("What does BBS stand for?", "Bulletin Board System", ["Basic Boot System", "Binary Broadcast Service", "Buffered Bit Stream"]),
    ("Which Hayes-style command makes a modem dial with tones?", "ATDT", ["ATDP", "ATZ", "ATH"]),
    ("About how many characters per second does a 2400 baud modem carry?", "240", ["24", "2400", "24000"]),
    ("Who created the ZMODEM and YMODEM file transfer protocols?", "Chuck Forsberg", ["Ward Christensen", "Phil Katz", "Tom Jennings"]),
    ("Who wrote the XMODEM protocol in 1977?", "Ward Christensen", ["Bill Gates", "Dennis Ritchie", "Ken Thompson"]),
    ("Which was the first BBS, started in Chicago in 1978?", "CBBS", ["FidoNet", "CompuServe", "Usenet"]),
    ("Which network of BBSes did Tom Jennings start in 1984?", "FidoNet", ["ARPANET", "Usenet", "BITNET"]),
    ("The extended character set of the IBM PC, used for ANSI art, is called?", "CP437", ["ASCII-7", "UTF-8", "EBCDIC"]),
    ("Which key combination reboots a DOS PC?", "Ctrl+Alt+Del", ["Alt+F4", "Ctrl+C", "Shift+Esc"]),
    ("In the traditional computing sense, how many bytes are in a kilobyte?", "1024", ["1000", "1204", "1042"]),
    ("Which processor powered the original IBM PC?", "Intel 8088", ["Motorola 68000", "Zilog Z80", "MOS 6502"]),
    ("The Commodore 64 used a CPU from which family?", "6502", ["Z80", "8086", "68000"]),
    ("How much did a standard high-density 3.5-inch floppy disk hold?", "1.44 MB", ["360 KB", "720 KB", "2.88 GB"]),
    ("Which sound card brand dominated PC audio in the early 1990s?", "Sound Blaster", ["Voodoo", "GeForce", "Radeon"]),
    ("On a DOS PC, what does the drive letter A: usually mean?", "The first floppy drive", ["The first hard disk", "The CD-ROM", "The network"]),
    ("Which of these is a DOS program extension?", ".EXE", [".DOCX", ".PDF", ".MP4"]),
    ("Who created the PKZIP compression format that BBSes used everywhere?", "Phil Katz", ["Ward Christensen", "Chuck Forsberg", "Linus Torvalds"]),
    ("ANSI colors and cursor moves begin with which control character?", "ESC", ["TAB", "BEL", "NUL"]),
    ("How many bits are in a byte?", "8", ["4", "12", "16"]),
    ("Which early graphical web browser, released in 1993, set off the web boom?", "Mosaic", ["Netscape", "Opera", "Safari"]),
    ("Which company made the Game Boy?", "Nintendo", ["Sega", "Atari", "Sony"]),
    ("What is the Linux mascot?", "A penguin", ["A fox", "A whale", "A gnu"]),
    ("Which 1975 kit computer started the home computer boom?", "Altair 8800", ["Apple I", "TRS-80", "ZX80"]),
    ("In which year was the first iPhone released?", "2007", ["2005", "2009", "2010"]),
    ("What does URL stand for?", "Uniform Resource Locator", ["Universal Remote Link", "Unified Routing Layer", "User Route List"]),
    ("Which of these is not a programming language?", "Router", ["Python", "Rust", "COBOL"]),
    ("What is the default port for HTTPS?", "443", ["80", "8080", "21"]),
    ("What is the default port for telnet?", "23", ["21", "22", "25"]),
    ("What is decimal 5 in binary?", "101", ["110", "011", "111"]),
    ("Who is credited with creating the C programming language?", "Dennis Ritchie", ["Linus Torvalds", "Guido van Rossum", "Bjarne Stroustrup"]),
    ("In 1977 Atari released which famous console?", "Atari 2600", ["Atari ST", "Atari Jaguar", "Atari Lynx"]),
    ("A modem's baud rate measures:", "Signal changes per second", ["Bytes per minute", "Bits per page", "Packets per hour"]),
    ("Which year did the Commodore 64 launch?", "1982", ["1979", "1985", "1988"]),
    ("Which spreadsheet is credited with making the Apple II a business machine?", "VisiCalc", ["Lotus 1-2-3", "Excel", "Quattro"]),
    ("What is 0xFF in decimal?", "255", ["15", "127", "256"]),
    ("What does RAM stand for?", "Random Access Memory", ["Read And Modify", "Rapid Access Module", "Remote Array Memory"]),
    ("Which protocol carries email between servers?", "SMTP", ["HTTP", "FTP", "DHCP"]),
    ("Which chess piece moves in an L shape?", "The knight", ["The bishop", "The rook", "The pawn"]),
    ("How many squares are on a chessboard?", "64", ["32", "49", "81"]),
    ("Which planet is called the Red Planet?", "Mars", ["Venus", "Jupiter", "Mercury"]),
    ("Which is the largest ocean?", "The Pacific", ["The Atlantic", "The Indian", "The Arctic"]),
    ("Which gas do plants take in for photosynthesis?", "Carbon dioxide", ["Oxygen", "Nitrogen", "Helium"]),
    ("Who painted the Mona Lisa?", "Leonardo da Vinci", ["Michelangelo", "Raphael", "Rembrandt"]),
    ("What is the capital of Austria?", "Vienna", ["Salzburg", "Graz", "Linz"]),
    ("What is the capital of Switzerland?", "Bern", ["Zurich", "Geneva", "Basel"]),
    ("What is the chemical symbol for gold?", "Au", ["Ag", "Go", "Gd"]),
    ("How many continents are there?", "7", ["5", "6", "8"]),
    ("Which is the fastest land animal?", "The cheetah", ["The lion", "The horse", "The greyhound"]),
    ("What is the square root of 144?", "12", ["11", "13", "14"]),
    ("Which language does a web page use for its structure?", "HTML", ["SQL", "COBOL", "BASIC"]),
    ("What did the 'DOS' in MS-DOS stand for?", "Disk Operating System", ["Digital Output Stream", "Data Online Service", "Direct Open Socket"]),
    ("Which key was used to enter BIOS setup on most PCs?", "Del", ["Tab", "Home", "Insert"]),
]


def history_pool():
    """Every history line and fact, in a fixed order (what `op sf` chooses from)."""
    return [v for _, v in sorted(HISTORY.items())] + list(FACTS)


def daily_seed(now=None):
    d = now or time.localtime()
    return d.tm_year * 400 + d.tm_yday


def tr_present(entry, seed=None):
    """(question, options, index of the right one), options shuffled (the same way for the same seed)."""
    q, right, wrong = entry
    opts = [right] + list(wrong)
    rnd = random.Random(seed) if seed is not None else secrets.SystemRandom()
    rnd.shuffle(opts)
    return q, opts, opts.index(right)


def week_key(offset=0):
    d = datetime.date.today() - datetime.timedelta(weeks=-offset)
    y, w, _ = d.isocalendar()
    return "%d-W%02d" % (y, w)


class BBSMore:
    def init_more(self):
        self.pastes = self.load("pastes")
        self.pastes.setdefault("items", [])
        self.meta.setdefault("daily", {})
        self.meta.setdefault("hours", [0] * 24)
        self.meta.setdefault("trivia", {"weeks": {}, "scores": {}})
        self.meta.setdefault("cotm", {})
        self.log_handler = None
        if self.cfg.get("log", True):
            try:
                from logging.handlers import RotatingFileHandler
                self.log_handler = RotatingFileHandler(str(self.dir / "hostbbs.log"), maxBytes=512 * 1024,
                                                       backupCount=3, encoding="utf-8")
            except OSError:
                self.log_handler = None

    def log(self, event):
        """One line in data/hostbbs.log (rotated at 512 KB, three old files kept), and on the
        console. Private mail and private messages never come here."""
        if not self.cfg.get("log", True):
            return
        line = "%s  %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), "".join(c for c in str(event) if printable(c)))
        if self.cfg.get("log_echo", True):
            try:
                print(line, flush=True)
            except (OSError, ValueError):
                pass
        h = self.log_handler
        if not h:
            return
        try:
            import logging
            h.emit(logging.LogRecord("hostbbs", logging.INFO, "", 0, line, (), None))
        except Exception:
            pass

    # ---- counting
    def daily_picks(self, now=None):
        """(fortune index, history pool index) shown today: the operator's pick (`op sf`), else by date.
        The history index is None when today's own date entry is used."""
        now = now or time.localtime()
        pick = self.meta.get("daily_pick") or {}
        if pick.get("date") != time.strftime("%Y-%m-%d", now):
            pick = {}
        f = pick.get("fortune")
        h = pick.get("history")
        return (f if f is not None else daily_seed(now) % len(FORTUNES)), h

    def daily_texts(self, now=None):
        now = now or time.localtime()
        f, h = self.daily_picks(now)
        pool = history_pool()
        if h is not None:
            history = pool[h % len(pool)]
        else:
            history = HISTORY.get((now.tm_mon, now.tm_mday)) or FACTS[daily_seed(now) % len(FACTS)]
        return FORTUNES[f % len(FORTUNES)], history

    def month_key(self, ts=None):
        return time.strftime("%Y-%m", time.localtime(ts))

    def track(self, name, field, n=1, save=True):
        u = self.users.get(name.lower())
        if not u:
            return
        m = u.setdefault("month", {}).setdefault(self.month_key(), {})
        m[field] = m.get(field, 0) + n
        if save:
            self.save("users", self.users)

    def count_call(self):
        day = time.strftime("%Y-%m-%d")
        self.meta["daily"][day] = self.meta["daily"].get(day, 0) + 1
        for k in sorted(self.meta["daily"])[:-60]:
            del self.meta["daily"][k]
        self.meta["hours"][time.localtime().tm_hour] += 1

    POINTS = {"calls": 3, "posts": 5, "chats": 0.2, "games": 1, "mails": 2, "votes": 1, "trivia": 4}

    def month_scores(self, month):
        rows = []
        for u in self.users.values():
            m = u.get("month", {}).get(month)
            if not m or u.get("sysop") or u["name"].lower() == (self.cfg["sysop"] or "").lower():
                continue
            pts = sum(m.get(k, 0) * w for k, w in self.POINTS.items())
            rows.append((round(pts), u["name"], m))
        rows.sort(key=lambda r: -r[0])
        return rows

    def cotm_settle(self):
        """Record last month's winner once the month has turned."""
        prev = self.month_key(time.time() - 86400 * (time.localtime().tm_mday + 1))
        if prev not in self.meta["cotm"]:
            rows = self.month_scores(prev)
            self.meta["cotm"][prev] = {"name": rows[0][1], "points": rows[0][0]} if rows else None
            self.save("meta", self.meta)
        return prev, self.meta["cotm"][prev]

    # ---- trivia
    def trivia_bank(self):
        bank = list(TRIVIA)
        path = self.cfg.get("trivia_file")
        if path:
            try:
                for e in json.load(open(path)):
                    bank.append((e["q"], e["a"][0], e["a"][1:4]))
            except (OSError, ValueError, KeyError, IndexError, TypeError):
                pass
        return bank

    def trivia_week(self, key=None):
        """The question for a week (stored once so later changes of the bank do not change it)."""
        key = key or week_key()
        weeks = self.meta["trivia"]["weeks"]
        if key not in weeks:
            bank = self.trivia_bank()
            used = {w["q"] for w in weeks.values()}
            pool = [i for i in range(len(bank)) if i not in used] or list(range(len(bank)))
            rnd = random.Random(key)
            weeks[key] = {"q": rnd.choice(pool), "ans": {}}
            self.save("meta", self.meta)
        w = weeks[key]
        q, opts, right = tr_present(self.trivia_bank()[w["q"]], seed=key)
        return key, w, q, opts, right

    def trivia_answer(self, name, choice):
        key, w, q, opts, right = self.trivia_week()
        low = name.lower()
        if low in w["ans"]:
            return None
        w["ans"][low] = choice
        sc = self.meta["trivia"]["scores"].setdefault(low, {"name": name, "points": 0, "correct": 0, "answered": 0})
        sc["answered"] += 1
        if choice == right:
            sc["correct"] += 1
            sc["points"] += 10
        self.save("meta", self.meta)
        self.track(name, "trivia")
        return choice == right




# ---- BBS-side: hot reload and scheduled messages ------------------------------------------------

def replace_inplace(old, new):
    """Make the dict old equal to new without replacing the dicts inside it (sessions hold on to them)."""
    for k in list(old):
        if k not in new:
            del old[k]
    for k, v in new.items():
        if isinstance(v, dict) and isinstance(old.get(k), dict):
            replace_inplace(old[k], v)
        else:
            old[k] = v


def sched_matches(item, now):
    if item.get("at") != time.strftime("%H:%M", now):
        return False
    days = str(item.get("days") or "daily").lower().replace(" ", "")
    if days in ("daily", "everyday", "all"):
        return True
    if days == "weekdays":
        return now.tm_wday < 5
    if days == "weekends":
        return now.tm_wday >= 5
    if re.fullmatch(r"\d\d-\d\d", days):
        return days == time.strftime("%m-%d", now)
    return ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[now.tm_wday] in days.split(",")


class BBSReach:
    def init_reach(self):
        self.loader = None             # () -> a fresh finished config, set by serve()
        self.sched_extra = self.load("schedule")
        self.sched_extra.setdefault("items", [])
        self.sched_extra.setdefault("next", 1)
        self.fired = set()

    def reload(self):
        """Read the configuration again and apply it to the running BBS."""
        if not self.loader:
            return False, "this BBS was not started from a config file"
        try:
            new = self.loader()
        except SystemExit as e:
            return False, "config not reloaded: %s" % e
        except Exception as e:
            return False, "config not reloaded: %s" % e
        keep = {k: self.cfg.get(k) for k in ("host", "port", "websocket")}
        replace_inplace(self.cfg, new)
        self.sync_rooms()
        notes = []
        if any(keep[k] != self.cfg.get(k) for k in keep):
            notes.append("address and port changes need a restart")
        self.log("configuration reloaded")
        return True, "configuration reloaded" + ("; " + "; ".join(notes) if notes else "")

    def sync_rooms(self):
        want = {r["name"]: r for r in self.cfg["rooms"]} if self.cfg["features"]["chat"] else {}
        for name, spec in want.items():
            room = self.rooms.get(name)
            if room is None:
                self.rooms[name] = Room(spec, self.cfg["history"])
            else:
                room.topic, room.password, room.guests = spec.get("topic", ""), spec.get("password", ""), spec.get("guests", True)
        for name in list(self.rooms):
            if name not in want and not name.startswith("page-") and not self.rooms[name].members:
                del self.rooms[name]

    def schedule_items(self):
        items = [dict(i, source="config") for i in (self.cfg.get("schedule") or [])]
        return items + [dict(i, source="op") for i in self.sched_extra["items"]]

    def run_schedule(self, now=None):
        now = now or time.localtime()
        stamp = time.strftime("%Y-%m-%d %H:%M", now)
        for i, item in enumerate(self.schedule_items()):
            key = (item.get("id", "c%d" % i), stamp)
            if key in self.fired or not item.get("message") or not sched_matches(item, now):
                continue
            self.fired.add(key)
            if len(self.fired) > 300:
                self.fired = {k for k in self.fired if k[1] == stamp}
            msg, mode = clean_text(str(item["message"])), str(item.get("mode") or "broadcast")
            if mode == "force":
                Ops(self, True).run(["force", msg])
            elif mode.startswith("room:") and mode[5:] in self.rooms:
                self.rooms[mode[5:]].say("msg", self.cfg["sysop"] or "sysop", msg)
            else:
                self.broadcast_sysop(msg)
            self.log("scheduled %s: %s" % (mode, msg))




class Room:
    def __init__(self, spec, history):
        self.name = spec["name"]
        self.topic = spec.get("topic", "")
        self.password = spec.get("password", "")
        self.guests = spec.get("guests", True)
        self.ages = spec.get("ages", "all")
        self.members = set()
        self.history = deque(maxlen=history)
        self.count = 0

    def say(self, kind, who, text):
        entry = {"ts": time.time(), "kind": kind, "who": who, "text": text}
        self.history.append(entry)
        if kind in ("msg", "emo"):
            self.count += 1
        for m in list(self.members):
            if kind in ("msg", "emo") and who.lower() in m.ignored:
                continue
            m.push(m.fmt_chat(entry))


class BBS(BBSExtras, BBSMore, BBSReach):
    def __init__(self, cfg):
        self.cfg = cfg
        self.dir = Path(cfg["data_dir"])
        self.dir.mkdir(parents=True, exist_ok=True)
        self.users = self.load("users")
        self.boards = self.load("boards")
        self.mail = self.load("mail")
        self.meta = self.load("meta")
        self.init_extras()
        self.init_more()
        self.init_reach()
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
        return pbkdf2_sha256(pw.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS).hex()

    async def make_user(self, name, pw):
        salt = secrets.token_hex(16)
        digest = await offload(self.hash_pw, pw, salt)
        user = {"name": name, "salt": salt, "hash": digest, "created": time.time(),
                "last": time.time(), "calls": 0}
        self.users[name.lower()] = user
        self.save("users", self.users)
        return user

    async def check_pw(self, user, pw):
        digest = await offload(self.hash_pw, pw, user["salt"])
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
        user["hash"] = await offload(self.hash_pw, pw, user["salt"])
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

    # ---- kids and families ----------------------------------------------
    def age_of(self, name):
        """A user's age (from the birth year), or None if not known."""
        u = self.users.get((name or "").lower())
        if not u or u.get("born") is None:
            return None
        return time.localtime().tm_year - int(u["born"])

    def is_sysop(self, name):
        u = self.users.get((name or "").lower())
        return bool(u and u.get("sysop"))

    def family(self, a, b):
        """Parent and child, or a child and someone their parent approved."""
        k = self.cfg["kids"]
        if not k["enabled"] or not k.get("parents"):
            return False
        ua, ub = self.users.get(a.lower(), {}), self.users.get(b.lower(), {})
        low = lambda lst: [x.lower() for x in lst or []]
        return (a.lower() in low(ub.get("parents")) or b.lower() in low(ua.get("parents")) or
                a.lower() in low(ub.get("approved")) or b.lower() in low(ua.get("approved")))

    def children(self, parent):
        return sorted(u["name"] for u in self.users.values()
                      if parent.lower() in [p.lower() for p in u.get("parents") or []])

    def may_meet(self, a, a_age, b, b_age):
        """With Kids mode, adults and under-18s are kept apart (private contact, tables),
        except family. The sysops may always."""
        if not self.cfg["kids"]["enabled"] or self.is_sysop(a) or self.is_sysop(b):
            return True
        if self.family(a, b):
            return True
        for name in (a, b):
            if self.users.get(name.lower(), {}).get("family_only"):
                return False
        minor = lambda age: age is not None and age < ADULT
        return minor(a_age) == minor(b_age)

    def may_contact(self, a, a_age, b, b_age, what):
        """May a write privately to b (what: "mail" or "pm")? Both must also be old enough
        for it, unless they are family."""
        if not self.may_meet(a, a_age, b, b_age):
            return False
        k = self.cfg["kids"]
        if not k["enabled"] or self.is_sysop(a) or self.is_sysop(b) or self.family(a, b):
            return True
        need = k["min_age"].get(what, 0)
        return (a_age if a_age is not None else ADULT) >= need and (b_age if b_age is not None else ADULT) >= need

    def rude_re(self):
        words = RUDE + self.cfg["kids"].get("words", [])
        key = tuple(words)
        if getattr(self, "_rude_key", None) != key:
            self._rude_key = key
            self._rude = re.compile(r"\b(?:%s)(?:s|es|ed|er|ers|ing|y)?\b" % "|".join(
                re.escape(w) for w in sorted(set(words), key=len, reverse=True)), re.I)
        return self._rude

    async def restart(self, by, why="The BBS restarts now"):
        """Tell everyone, hang up, and start this program again (in the same process)."""
        self.log("restart by %s" % by)
        self.broadcast(paint("[SYSOP] %s: call again in a moment." % why, "bred"))
        await asyncio.sleep(3)
        for sess in list(self.sessions):
            try:
                sess.w.close()
            except OSError:
                pass
        await asyncio.sleep(0.5)
        sys.stdout.flush()
        os.execv(sys.executable, [sys.executable, program_path()] + sys.argv[1:])

    async def update(self, by):
        """op update: the newest hostbbs, then a restart with it."""
        if UPDATE_REQUEST:
            # (In Kilobyte: a service of the system installs it and restarts the BBS.)
            with open(UPDATE_REQUEST, "w") as f:
                f.write(by + "\n")
            self.log("update asked for by %s" % by)
            return "Asked for the newest hostbbs: the BBS restarts by itself if there is a new one."
        try:
            msg = await asyncio.get_running_loop().run_in_executor(None, self_update, self.cfg.get("update_url") or None)
        except (OSError, ValueError, SyntaxError, UnicodeDecodeError) as e:
            self.log("update by %s did not work: %s" % (by, e))
            return "The update did not work: %s" % e
        self.log("update by %s: %s" % (by, msg))
        if "installed" in msg:
            asyncio.ensure_future(self.restart(by, "The BBS restarts with a new version"))
        return msg

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
# Bundled games (chess, hangman, robots, snake, sudoku, adventure)
# --------------------------------------------------------------------------

CHESS_START = "rnbqkbnrpppppppp" + "." * 32 + "PPPPPPPPRNBQKBNR"   # a8 ... h1
CHESS_KNIGHT = (-17, -15, -10, -6, 6, 10, 15, 17)
CHESS_STEPS = {"n": CHESS_KNIGHT, "b": (-9, -7, 7, 9), "r": (-8, -1, 1, 8), "q": (-9, -8, -7, -1, 1, 7, 8, 9),
         "k": (-9, -8, -7, -1, 1, 7, 8, 9)}


def chess_sq(name):
    return (8 - int(name[1])) * 8 + "abcdefgh".index(name[0])


def chess_name(i):
    return "abcdefgh"[i % 8] + str(8 - i // 8)


class ChessPosition:
    """A position: board (64 characters, a8 first), side to move, castling
    rights, en passant square. Moves are UCI strings such as e2e4, e7e8q."""

    def __init__(self):
        self.b = list(CHESS_START)
        self.white = True
        self.castle = set("KQkq")
        self.ep = None
        self.history = []          # positions before each move, for undo
        self.moves = []
        self.seen = {}             # position -> how often (for repetition)
        self.halfmoves = 0
        self.note()

    def key(self):
        return "".join(self.b) + ("w" if self.white else "b") + "".join(sorted(self.castle)) + str(self.ep)

    def note(self):
        k = self.key()
        self.seen[k] = self.seen.get(k, 0) + 1

    def mine(self, p, white):
        return p != "." and p.isupper() == white

    def attacked(self, i, by_white):
        """Is square i attacked by the side by_white?"""
        b = self.b
        r, c = divmod(i, 8)
        # Pawns
        dr = 1 if by_white else -1
        for dc in (-1, 1):
            rr, cc = r + dr, c + dc
            if 0 <= rr < 8 and 0 <= cc < 8 and b[rr * 8 + cc] == ("P" if by_white else "p"):
                return True
        for kind in ("n", "k"):
            for d in CHESS_STEPS[kind]:
                j = i + d
                if 0 <= j < 64 and abs(j % 8 - c) <= 2 and b[j] == (kind.upper() if by_white else kind):
                    return True
        for kinds, dirs in (("rq", (-8, -1, 1, 8)), ("bq", (-9, -7, 7, 9))):
            for d in dirs:
                j = i
                while True:
                    pc = j % 8
                    j += d
                    if not 0 <= j < 64 or abs(j % 8 - pc) > 1:
                        break
                    p = b[j]
                    if p != ".":
                        if p.isupper() == by_white and p.lower() in kinds:
                            return True
                        break
        return False

    def king(self, white):
        return self.b.index("K" if white else "k")

    def in_check(self, white=None):
        white = self.white if white is None else white
        return self.attacked(self.king(white), not white)

    def pseudo(self):
        b, w = self.b, self.white
        out = []
        for i, p in enumerate(b):
            if not self.mine(p, w):
                continue
            k = p.lower()
            c = i % 8
            if k == "p":
                d = -8 if w else 8
                last = 0 if w else 7
                first = 6 if w else 1
                j = i + d
                if 0 <= j < 64 and b[j] == ".":
                    out += self.promos(i, j, last)
                    if i // 8 == first and b[j + d] == ".":
                        out.append(chess_name(i) + chess_name(j + d))
                for dc in (-1, 1):
                    j = i + d + dc
                    if 0 <= j < 64 and abs(j % 8 - c) == 1:
                        if (b[j] != "." and not self.mine(b[j], w)) or j == self.ep:
                            out += self.promos(i, j, last)
            elif k in ("n", "k"):
                for d in CHESS_STEPS[k]:
                    j = i + d
                    if 0 <= j < 64 and abs(j % 8 - c) <= 2 and not self.mine(b[j], w):
                        out.append(chess_name(i) + chess_name(j))
                if k == "k":
                    out += self.castles()
            else:
                for d in CHESS_STEPS[k]:
                    j = i
                    while True:
                        pc = j % 8
                        j += d
                        if not 0 <= j < 64 or abs(j % 8 - pc) > 1 or self.mine(b[j], w):
                            break
                        out.append(chess_name(i) + chess_name(j))
                        if b[j] != ".":
                            break
        return out

    def promos(self, i, j, last):
        m = chess_name(i) + chess_name(j)
        return [m + q for q in "qrbn"] if j // 8 == last else [m]

    def castles(self):
        b, w, out = self.b, self.white, []
        row = 7 if w else 0
        e = row * 8 + 4
        if self.in_check():
            return out
        for flag, path, through in (("K", (5, 6), (5, 6)), ("Q", (1, 2, 3), (3, 2))):
            if (flag if w else flag.lower()) not in self.castle:
                continue
            if all(b[row * 8 + f] == "." for f in path) and \
               not any(self.attacked(row * 8 + f, not w) for f in through):
                out.append(chess_name(e) + chess_name(row * 8 + through[-1]))
        return out

    def play(self, m, check=True):
        """Make move m (UCI). Returns False if it is not legal."""
        if check and m not in self.legal():
            return False
        self.history.append((self.b[:], self.white, set(self.castle), self.ep, self.halfmoves))
        self.moves.append(m)
        b = self.b
        i, j = chess_sq(m[:2]), chess_sq(m[2:4])
        p = b[i]
        capture = b[j] != "."
        if p.lower() == "p" and j == self.ep:            # en passant
            b[j + (8 if p.isupper() else -8)] = "."
            capture = True
        if p.lower() == "k" and abs(j - i) == 2:         # castling: the rook too
            ri, rj = (j + 1, j - 1) if j > i else (j - 2, j + 1)
            b[rj], b[ri] = b[ri], "."
        b[j], b[i] = p, "."
        if len(m) == 5:
            b[j] = m[4].upper() if p.isupper() else m[4]
        self.ep = (i + j) // 2 if p.lower() == "p" and abs(j - i) == 16 else None
        for s, flags in ((60, "KQ"), (4, "kq"), (63, "K"), (56, "Q"), (7, "k"), (0, "q")):
            if i == s or j == s:
                self.castle -= set(flags)
        self.halfmoves = 0 if capture or p.lower() == "p" else self.halfmoves + 1
        self.white = not self.white
        self.note()
        return True

    def undo(self):
        if not self.history:
            return
        k = self.key()
        self.seen[k] -= 1
        self.b, self.white, self.castle, self.ep, self.halfmoves = self.history.pop()
        self.moves.pop()

    def legal(self):
        out = []
        for m in self.pseudo():
            self.play(m, check=False)
            if not self.in_check(not self.white):
                out.append(m)
            self.undo()
        return out

    def outcome(self):
        """None while the game goes on, else a sentence."""
        if not self.legal():
            if self.in_check():
                return "Checkmate: " + ("black" if self.white else "white") + " wins"
            return "Stalemate: a draw"
        if self.halfmoves >= 100:
            return "Fifty moves without a capture: a draw"
        if self.seen.get(self.key(), 0) >= 3:
            return "The same position three times: a draw"
        pieces = sorted(p.lower() for p in self.b if p not in ".kK")
        if pieces in ([], ["b"], ["n"]):
            return "Not enough pieces left: a draw"
        return None

    def san(self, m):
        """The move in the usual notation (Nf3, exd5, O-O, e8=Q+)."""
        i, j = chess_sq(m[:2]), chess_sq(m[2:4])
        p = self.b[i].lower()
        if p == "k" and abs(j - i) == 2:
            s = "O-O" if j > i else "O-O-O"
        else:
            capture = self.b[j] != "." or (p == "p" and j == self.ep)
            if p == "p":
                s = (m[0] + "x" if capture else "") + m[2:4]
                if len(m) == 5:
                    s += "=" + m[4].upper()
            else:
                same = [o for o in self.legal() if o[2:4] == m[2:4] and o != m and self.b[chess_sq(o[:2])].lower() == p]
                dis = ""
                if same:
                    if all(o[0] != m[0] for o in same):
                        dis = m[0]
                    elif all(o[1] != m[1] for o in same):
                        dis = m[1]
                    else:
                        dis = m[:2]
                s = p.upper() + dis + ("x" if capture else "") + m[2:4]
        self.play(m, check=False)
        if self.in_check():
            s += "#" if not self.legal() else "+"
        self.undo()
        return s


def chess_clone(pos):
    """A copy of the position for the engine to search (no history)."""
    c = ChessPosition()
    c.b, c.white, c.castle, c.ep = pos.b[:], pos.white, set(pos.castle), pos.ep
    c.halfmoves, c.seen = pos.halfmoves, {}
    c.history, c.moves = [], []
    return c


CHESS_VALUE = {"p": 100, "n": 320, "b": 330, "r": 500, "q": 900, "k": 0}
CHESS_MATE = 100000


class ChessTimeUp(Exception):
    pass


def chess_eval(pos):
    """Material and a little placement, for the side to move."""
    score = 0
    for i, p in enumerate(pos.b):
        if p == ".":
            continue
        k, r, c = p.lower(), i // 8, i % 8
        v = CHESS_VALUE[k]
        centre = 3 - max(abs(r - 3.5), abs(c - 3.5)) + 0.5   # 0..3 towards the middle
        if k == "p":
            adv = (6 - r) if p.isupper() else (r - 1)
            v += adv * 6 + (centre * 4 if 2 <= adv <= 4 else 0)
        elif k in "nb":
            v += centre * 9
        elif k == "q":
            v += centre * 2
        score += v if p.isupper() else -v
    return score if pos.white else -score


def chess_search(pos, depth, alpha, beta, ply, t_end):
    if time.time() > t_end:
        raise ChessTimeUp
    if depth == 0:
        return chess_eval(pos)
    moves = pos.pseudo()
    moves.sort(key=lambda m: -(CHESS_VALUE.get(pos.b[chess_sq(m[2:4])].lower(), 0) * 10
                               - CHESS_VALUE[pos.b[chess_sq(m[:2])].lower()] // 10)
               if pos.b[chess_sq(m[2:4])] != "." else 0)
    legal, best = 0, -CHESS_MATE
    for m in moves:
        pos.play(m, check=False)
        if pos.in_check(not pos.white):
            pos.undo()
            continue
        legal += 1
        try:
            s = -chess_search(pos, depth - 1, -beta, -alpha, ply + 1, t_end)
        finally:
            pos.undo()
        if s > best:
            best = s
        alpha = max(alpha, s)
        if alpha >= beta:
            break
    if not legal:
        return (-CHESS_MATE + ply) if pos.in_check() else 0
    return best


def chess_best(pos, level):
    """The computer's move (UCI) at strength 1 to 3, or None if it has none."""
    root = chess_clone(pos)
    moves = []
    for m in root.pseudo():
        root.play(m, check=False)
        ok = not root.in_check(not root.white)
        root.undo()
        if ok:
            moves.append(m)
    if not moves:
        return None
    t_end = time.time() + {1: 1.0, 2: 3.0, 3: 7.0}[level]
    best = secrets.choice(moves)
    for depth in range(1, level + 1):
        scored = []
        try:
            for m in moves:
                root.play(m, check=False)
                try:
                    s = -chess_search(root, depth - 1, -CHESS_MATE, CHESS_MATE, 1, t_end)
                finally:
                    root.undo()
                scored.append((s, m))
        except ChessTimeUp:
            break
        top = max(s for s, _ in scored)
        slack = 25 if level == 1 else 0
        best = secrets.choice([m for s, m in scored if s >= top - slack])
        moves = [m for _, m in sorted(scored, key=lambda t: -t[0])]
    return best


HANGWORDS = """absent academy account active actor adventure airport alarm almost alone amber anchor ancient angle
animal answer anvil apple arcade arrow artist asteroid atlas autumn avenue bacon badge balance bamboo banana
banner barrel basket battery beacon beaver bicycle biscuit blanket blossom bonfire border bottle boundary bracket
bridge bronze bucket buffalo bundle butter cabinet cactus camera canyon captain carpet castle cavern chapter
cheese cherry chimney circle citizen climate clover cobweb coffee compass copper cottage cricket crystal curtain
dancer dazzle delta desert diamond dinner dolphin dragon drawer eagle echo editor engine evening factory falcon
feather fiddle fountain freedom galaxy garden gazebo ginger glacier goblin gravity guitar hammer harbor harvest
helmet horizon hunter iceberg island jacket jungle kettle kingdom ladder lantern lemon letter library lizard
lumber magnet marble meadow mirror monitor mountain muffin mystery needle nickel orchard oyster paddle palace
parcel pebble penguin pepper pillow planet pocket puzzle quartz rabbit rainbow ribbon river rocket saddle
sailor salmon sandbox scarlet shadow signal silver socket spider spiral sponge statue storm summer sunset
surface teapot temple thunder ticket timber tomato tunnel turtle umbrella valley velvet village violin voyage
walnut whistle window winter wizard wonder yellow zephyr zigzag modem keyboard terminal protocol bulletin
download carrier handshake archive monitor network packet router server telnet""".split()

HANGMAN_ART = [
    "  +---+\n  |   |\n      |\n      |\n      |\n      |\n=========",
    "  +---+\n  |   |\n  O   |\n      |\n      |\n      |\n=========",
    "  +---+\n  |   |\n  O   |\n  |   |\n      |\n      |\n=========",
    "  +---+\n  |   |\n  O   |\n /|   |\n      |\n      |\n=========",
    "  +---+\n  |   |\n  O   |\n /|\\  |\n      |\n      |\n=========",
    "  +---+\n  |   |\n  O   |\n /|\\  |\n /    |\n      |\n=========",
    "  +---+\n  |   |\n  O   |\n /|\\  |\n / \\  |\n      |\n=========",
]

# ---- the cave (an original small adventure in the spirit of Colossal Cave) ----
ADV_ROOMS = {
    "clearing": ("Forest clearing", "You are in a sunny clearing. A ramshackle shack stands to the north, "
                 "a creek chatters to the south and a trail leads east to a cliff.",
                 {"n": "shack", "s": "creek", "e": "cliff"}, False),
    "shack": ("Old shack", "A one-room shack, empty but for dust. A chalk circle on the floor is labelled "
              "DROP TREASURE HERE. The only way out is south.", {"s": "clearing", "out": "clearing"}, False),
    "creek": ("Creek bank", "A cold creek runs over smooth stones. Reeds grow thick on the bank. "
              "The clearing lies north.", {"n": "clearing"}, False),
    "cliff": ("Cliff edge", "You stand at the edge of a cliff. Set into the rock face is a stout wooden door "
              "with a rusty padlock. A trail leads west.", {"w": "clearing"}, False),
    "mouth": ("Cave mouth", "Daylight spills through the open door behind you. A passage slopes down "
              "into the dark.", {"out": "cliff", "w": "cliff", "d": "gallery"}, False),
    "gallery": ("Echoing gallery", "A long gallery; every sound comes back twice. Passages lead east, west "
                "and south. A slope leads up to the cave mouth.",
                {"u": "mouth", "e": "crystal", "w": "bats", "s": "pit"}, True),
    "bats": ("Bat cave", "A low cave, the ceiling alive with bats. The floor is deep in guano. "
             "The only way out is east.", {"e": "gallery", "out": "gallery"}, True),
    "crystal": ("Crystal chamber", "Crystals glitter on every wall. Someone has scratched a word into "
                "the rock: PLUGH. The way out is west.", {"w": "gallery", "out": "gallery"}, True),
    "pit": ("Edge of a pit", "You stand at the edge of a deep pit. A thick stalagmite by your feet would "
            "hold a rope well. The gallery is north.", {"n": "gallery"}, True),
    "lower": ("Bottom of the pit", "A damp cavern at the bottom of the pit. A rope hangs down from above. "
              "To the east lies the shore of an underground lake.", {"u": "pit", "e": "lake"}, True),
    "lake": ("Lakeshore", "The shore of a black lake. A shallow ford leads to a stone altar where "
             "something gleams. The cavern lies west.", {"w": "lower"}, True),
}
ADV_ITEMS = {  # key: (name, text, start room, treasure)
    "lantern": ("brass lantern", "A sturdy brass lantern. It can be lit.", "shack", False),
    "key": ("rusty key", "A rusty iron key.", "shack", False),
    "rope": ("coil of rope", "Thirty feet of strong rope.", "creek", False),
    "sandwich": ("cheese sandwich", "A slightly squashed cheese sandwich.", "clearing", False),
    "coin": ("silver coin", "A heavy silver coin, very old.", "bats", True),
    "crystal": ("great crystal", "A crystal as big as a fist, glowing softly.", "crystal", True),
    "idol": ("golden idol", "A small, heavy idol of a smiling cat.", "lake", True),
    "ring": ("emerald ring", "A ring set with a green stone.", "lake", True),
}
ADV_DIRS = {"n": "n", "north": "n", "s": "s", "south": "s", "e": "e", "east": "e", "w": "w", "west": "w",
            "u": "u", "up": "u", "d": "d", "down": "d", "in": "in", "enter": "in", "out": "out",
            "exit": "out", "leave": "out"}


class GamesMixin:
    """Games that run inside the call: no programs of the host system needed.
    They draw with ANSI cursor codes and read keys with self.key()."""

    # ---- keys and screen ------------------------------------------------------
    async def key(self, tick=None):
        """The next key: a character, or UP DOWN LEFT RIGHT ESC. With tick: None
        when that many seconds pass without one."""
        limit = self.wait_limit()
        waiting = tick if tick is not None and tick < limit else limit
        try:
            ch = await asyncio.wait_for(self.getch(), waiting)
        except asyncio.TimeoutError:
            if waiting is not limit and tick is not None:
                return None
            if self.deadline is not None and time.time() >= self.deadline:
                raise TimeUp
            raise
        if ch in "\x03\x04":
            raise Quit
        if ch != "\x1b":
            return ch
        try:
            nxt = await asyncio.wait_for(self.getch(), 0.12)
        except asyncio.TimeoutError:
            return "ESC"
        if nxt in "[O":
            while True:
                fin = await self.getch()
                if "@" <= fin <= "~":
                    return {"A": "UP", "B": "DOWN", "C": "RIGHT", "D": "LEFT"}.get(fin, "?")
        return nxt

    async def draw(self, text):
        """Redraw the whole screen from the top without clearing it first."""
        if self.alert and time.time() < self.alert[1]:
            text += "\n\n" + self.alert_block(self.alert[0])
        await self.send("\x1b[H" + text.replace("\n", "\x1b[K\n") + "\x1b[K\x1b[J", fast=True)

    async def game_start(self, hide=True):
        if not self.color:
            await self.send(self.c("red", "Games need ANSI (cursor codes). Turn color on with T in the main menu.\n"))
            return False
        await self.send(("\x1b[?25l" if hide else "") + "\x1b[2J\x1b[H")
        return True

    async def game_end(self):
        try:
            await self.send("\x1b[0m\x1b[?25h\x1b[2J\x1b[H")
        except Quit:
            pass

    def game_over(self, game, won=False, score=0):
        """Hook for results (achievements, high scores)."""

    @staticmethod
    def sgr(code, text):
        return "\x1b[%sm%s\x1b[0m" % (code, text)

    async def yes_key(self, text):
        await self.send(text + " [y/n] ")
        while True:
            k = await self.key()
            if k in ("y", "Y"):
                return True
            if k in ("n", "N", "ESC", "q", "Q"):
                return False

    # ---- hangman ------------------------------------------------------------------
    async def game_hangman(self):
        if not await self.game_start():
            return
        try:
            while True:
                word = secrets.choice(HANGWORDS).upper()
                used, wrong, msg = set(), 0, ""
                while True:
                    shown = " ".join(ch if ch in used else "_" for ch in word)
                    won = all(ch in used for ch in word)
                    lost = wrong >= 6
                    if won:
                        msg = self.sgr("92;1", "You got it!")
                    elif lost:
                        msg = self.sgr("91;1", "Hanged! The word was " + word)
                    await self.draw("\n  %s\n\n%s\n\n   %s\n\n  Wrong: %s  (%d left)\n  Used: %s\n\n  %s\n\n  %s" % (
                        self.sgr("96;1", "H A N G M A N"), "\n".join("  " + ln for ln in HANGMAN_ART[wrong].split("\n")),
                        shown, " ".join(sorted(u for u in used if u not in word)) or "-", 6 - wrong,
                        " ".join(sorted(used)) or "-", msg,
                        "Press a letter. Esc quits." if not (won or lost) else ""))
                    if won or lost:
                        self.game_over("hangman", won=won, score=6 - wrong)
                        break
                    k = await self.key()
                    if k == "ESC":
                        return
                    if len(k) == 1 and k.isalpha() and k.upper() not in used:
                        used.add(k.upper())
                        if k.upper() not in word:
                            wrong += 1
                if not await self.yes_key("\n  Another word?"):
                    return
        finally:
            await self.game_end()

    # ---- robots -----------------------------------------------------------------------
    async def game_robots(self):
        if not await self.game_start():
            return
        W, H = 60, 20
        moves = {"h": (-1, 0), "l": (1, 0), "k": (0, -1), "j": (0, 1), "y": (-1, -1), "u": (1, -1),
                 "b": (-1, 1), "n": (1, 1), "LEFT": (-1, 0), "RIGHT": (1, 0), "UP": (0, -1),
                 "DOWN": (0, 1), ".": (0, 0), " ": (0, 0)}
        score, level, msg = 0, 1, ""
        try:
            while True:
                px, py = W // 2, H // 2
                robots, heaps = set(), set()
                while len(robots) < min(5 + 5 * level, 120):
                    p = (secrets.randbelow(W), secrets.randbelow(H))
                    if abs(p[0] - px) > 2 or abs(p[1] - py) > 2:
                        robots.add(p)
                dead = False
                while robots and not dead:
                    rows = []
                    for y in range(H):
                        rows.append("".join(
                            self.sgr("93;1", "@") if (x, y) == (px, py) else
                            self.sgr("91", "+") if (x, y) in robots else
                            self.sgr("90;1", "*") if (x, y) in heaps else "." for x in range(W)))
                    await self.draw("  %s  level %d  score %d  robots %d\n %s\n%s\n %s\n  %s" % (
                        self.sgr("96;1", "ROBOTS"), level, score, len(robots), "+" + "-" * W + "+",
                        "\n".join(" |" + r + "|" for r in rows), "+" + "-" * W + "+",
                        msg or "hjkl yubn / arrows move, . stays, t teleports, w waits, Esc quits"))
                    msg = ""
                    k = await self.key()
                    wait = False
                    if k == "ESC" or k == "q":
                        return
                    if k == "t":
                        while True:
                            px, py = secrets.randbelow(W), secrets.randbelow(H)
                            if (px, py) not in robots and (px, py) not in heaps:
                                break
                    elif k == "w":
                        wait = True
                    elif k in moves:
                        nx, ny = px + moves[k][0], py + moves[k][1]
                        if not (0 <= nx < W and 0 <= ny < H):
                            continue
                        px, py = nx, ny
                    else:
                        continue
                    while True:
                        if (px, py) in robots or (px, py) in heaps:
                            dead = True
                            break
                        new = {}
                        for (x, y) in robots:
                            t = (x + (px > x) - (px < x), y + (py > y) - (py < y))
                            new[t] = new.get(t, 0) + 1
                        robots = set()
                        for pos, n in new.items():
                            if pos in heaps:
                                score += 10 * n
                            elif n > 1:
                                heaps.add(pos)
                                score += 10 * n
                            else:
                                robots.add(pos)
                        if (px, py) in robots or (px, py) in heaps:
                            dead = True
                            break
                        if not (wait and robots):
                            break
                if dead:
                    await self.draw("\n\n   %s\n\n   A robot got you on level %d. Final score: %d\n" % (
                        self.sgr("91;1", "CRUNCH!"), level, score))
                    self.game_over("robots", won=False, score=score)
                    if not await self.yes_key("   Play again?"):
                        return
                    score, level = 0, 1
                else:
                    score += 20 * level
                    level += 1
                    msg = "Level cleared! +%d" % (20 * (level - 1))
        finally:
            await self.game_end()

    # ---- snake ("worm") ------------------------------------------------------------------
    async def game_snake(self):
        if not await self.game_start():
            return
        W, H = 60, 20
        dirs = {"h": (-1, 0), "a": (-1, 0), "LEFT": (-1, 0), "l": (1, 0), "d": (1, 0), "RIGHT": (1, 0),
                "k": (0, -1), "w": (0, -1), "UP": (0, -1), "j": (0, 1), "s": (0, 1), "DOWN": (0, 1)}
        try:
            while True:
                snake = [(W // 2 - i, H // 2) for i in range(4)]
                dx, dy, grow, score = 1, 0, 0, 0
                food = None

                def place():
                    while True:
                        p = (secrets.randbelow(W), secrets.randbelow(H))
                        if p not in snake:
                            return p, 1 + secrets.randbelow(9)
                food = place()
                tick = 0.13
                next_t = time.monotonic() + tick
                alive = True
                while alive:
                    now = time.monotonic()
                    if now >= next_t:
                        next_t = now + max(0.05, tick - len(snake) * 0.0007)
                        head = (snake[0][0] + dx, snake[0][1] + dy)
                        if not (0 <= head[0] < W and 0 <= head[1] < H) or head in snake[:-1]:
                            alive = False
                            break
                        snake.insert(0, head)
                        if head == food[0]:
                            grow += food[1]
                            score += food[1]
                            food = place()
                        if grow:
                            grow -= 1
                        else:
                            snake.pop()
                        body = set(snake[1:])
                        rows = []
                        for y in range(H):
                            rows.append("".join(
                                self.sgr("93;1", "@") if (x, y) == snake[0] else
                                self.sgr("92", "o") if (x, y) in body else
                                self.sgr("95;1", str(food[1])) if (x, y) == food[0] else " " for x in range(W)))
                        await self.draw("  %s  score %d  length %d\n %s\n%s\n %s\n  arrows / hjkl / wasd steer, Esc quits" % (
                            self.sgr("96;1", "SNAKE"), score, len(snake), "+" + "-" * W + "+",
                            "\n".join(" |" + r + "|" for r in rows), "+" + "-" * W + "+"))
                    k = await self.key(max(0.001, next_t - time.monotonic()))
                    if k == "ESC" or k == "q":
                        return
                    if k in dirs and (dirs[k][0] != -dx or dirs[k][1] != -dy):
                        dx, dy = dirs[k]
                await self.draw("\n\n   %s\n\n   You crashed with a length of %d. Score: %d\n" % (
                    self.sgr("91;1", "GAME OVER"), len(snake), score))
                self.game_over("snake", won=score >= 100, score=score)
                if not await self.yes_key("   Play again?"):
                    return
        finally:
            await self.game_end()

    # ---- sudoku ----------------------------------------------------------------------------
    @staticmethod
    def sudoku_solutions(g, limit=2):
        """Count solutions of grid g (81 ints, 0 = empty), up to limit."""
        g = g[:]
        count = 0

        def cands(i):
            r, c = divmod(i, 9)
            used = {g[r * 9 + k] for k in range(9)} | {g[k * 9 + c] for k in range(9)}
            br, bc = r // 3 * 3, c // 3 * 3
            used |= {g[(br + a) * 9 + bc + b] for a in range(3) for b in range(3)}
            return [v for v in range(1, 10) if v not in used]

        def solve():
            nonlocal count
            best, opts = None, None
            for i in range(81):
                if g[i] == 0:
                    o = cands(i)
                    if best is None or len(o) < len(opts):
                        best, opts = i, o
                        if len(o) <= 1:
                            break
            if best is None:
                count += 1
                return count >= limit
            for v in opts:
                g[best] = v
                if solve():
                    g[best] = 0
                    return True
            g[best] = 0
            return False
        solve()
        return count

    @classmethod
    def sudoku_make(cls, holes):
        full = [0] * 81

        def fill(i):
            if i == 81:
                return True
            r, c = divmod(i, 9)
            order = list(range(1, 10))
            secrets.SystemRandom().shuffle(order)
            for v in order:
                if all(full[r * 9 + k] != v and full[k * 9 + c] != v for k in range(9)) and all(
                        full[(r // 3 * 3 + a) * 9 + c // 3 * 3 + b] != v for a in range(3) for b in range(3)):
                    full[i] = v
                    if fill(i + 1):
                        return True
                    full[i] = 0
            return False
        fill(0)
        puzzle = full[:]
        cells = list(range(81))
        secrets.SystemRandom().shuffle(cells)
        removed = 0
        for i in cells:
            if removed >= holes:
                break
            keep = puzzle[i]
            puzzle[i] = 0
            if cls.sudoku_solutions(puzzle) == 1:
                removed += 1
            else:
                puzzle[i] = keep
        return puzzle, full

    async def game_sudoku(self):
        if not await self.game_start():
            return
        loop = asyncio.get_running_loop()
        levels = [("easy", 32), ("medium", 40), ("hard", 48)]
        lv, msg = 1, ""
        try:
            while True:
                await self.draw("\n  Making a puzzle...")
                puzzle, full = await offload(self.sudoku_make, levels[lv][1])
                grid, cur, t0 = puzzle[:], 40, time.time()
                while True:
                    bad = set()
                    for i in range(81):
                        v = grid[i]
                        if v:
                            r, c = divmod(i, 9)
                            for j in range(81):
                                if j != i and grid[j] == v and (j // 9 == r or j % 9 == c or (
                                        j // 27 == i // 27 and (j % 9) // 3 == c // 3)):
                                    bad.add(i)
                    lines = []
                    for r in range(9):
                        if r % 3 == 0:
                            lines.append("  +-------+-------+-------+")
                        row = "  |"
                        for c in range(9):
                            i, v = r * 9 + c, grid[r * 9 + c]
                            cell = str(v) if v else "."
                            code = "0"
                            if puzzle[i]:
                                code = "97;1"
                            elif i in bad:
                                code = "91;1"
                            elif v:
                                code = "96"
                            if i == cur:
                                code += ";7"
                            row += " " + self.sgr(code, cell)
                            if c % 3 == 2:
                                row += " |"
                        lines.append(row)
                    lines.append("  +-------+-------+-------+")
                    solved = all(grid) and not bad
                    status = msg or ("%d empty, %s" % (grid.count(0), levels[lv][0]))
                    if solved:
                        status = self.sgr("92;1", "Solved in %d:%02d!" % divmod(int(time.time() - t0), 60))
                    await self.draw("\n  %s\n%s\n\n  %s\n  arrows/hjkl move  1-9 set  0/space clear  ? hint  c check  n new (cycles difficulty)  Esc quits" % (
                        self.sgr("96;1", "S U D O K U"), "\n".join(lines), status))
                    msg = ""
                    if solved:
                        self.game_over("sudoku", won=True, score=int(time.time() - t0))
                        break
                    k = await self.key()
                    r, c = divmod(cur, 9)
                    if k in ("ESC", "q"):
                        return
                    if k in ("UP", "k"):
                        cur = ((r - 1) % 9) * 9 + c
                    elif k in ("DOWN", "j"):
                        cur = ((r + 1) % 9) * 9 + c
                    elif k in ("LEFT", "h"):
                        cur = r * 9 + (c - 1) % 9
                    elif k in ("RIGHT", "l"):
                        cur = r * 9 + (c + 1) % 9
                    elif k.isdigit() and not puzzle[cur]:
                        grid[cur] = int(k)
                    elif k in (" ", "\x7f", "\x08") and not puzzle[cur]:
                        grid[cur] = 0
                    elif k == "?" and not puzzle[cur]:
                        grid[cur] = full[cur]
                    elif k == "c":
                        wrong = sum(1 for i in range(81) if grid[i] and grid[i] != full[i])
                        msg = "%d wrong number%s" % (wrong, "" if wrong == 1 else "s") if wrong else "All correct so far."
                    elif k == "n":
                        lv = (lv + 1) % 3
                        break
                if all(grid) and not bad:
                    k = await self.yes_key("\n  Another puzzle?")
                    if not k:
                        return
        finally:
            await self.game_end()

    # ---- chess ---------------------------------------------------------------------------------
    def chess_parse(self, pos, text):
        """A typed move (e2e4, e2-e4, Nf3, O-O, e7e8q) -> UCI string, or None."""
        t = text.strip().replace(" ", "").replace("-", "").replace("=", "").rstrip("+#!?")
        legal = pos.legal()
        low = t.lower()
        if re.fullmatch(r"[a-h][1-8][a-h][1-8][qrbn]?", low):
            if low in legal:
                return low
            if low + "q" in legal:
                return low + "q"
            return None
        low = low.replace("0", "o")
        for m in legal:
            s = pos.san(m).replace("-", "").replace("=", "").rstrip("+#").lower()
            if s == low:
                return m
        return None

    def chess_board(self, pos, flip, last=None):
        lines = []
        rows = range(7, -1, -1) if flip else range(8)
        cols = range(7, -1, -1) if flip else range(8)
        for r in rows:
            row = " %d " % (8 - r)
            for c in cols:
                p = pos.b[r * 8 + c]
                bg = 43 if (r + c) % 2 == 0 else 42
                fg = "97" if p.isupper() else "30"
                row += "\x1b[%d;%s;1m %s \x1b[0m" % (bg, fg, p.upper() if p != "." else " ")
            lines.append(row)
        files = "abcdefgh"[::-1] if flip else "abcdefgh"
        lines.append("   " + "".join(" %s " % f for f in files))
        return lines

    async def game_chess(self):
        if not await self.game_start(hide=False):
            return
        loop = asyncio.get_running_loop()
        save = os.path.join(self.bbs.dir, "saves", re.sub(r"[^a-z0-9_-]", "", self.name.lower()) or "guest")
        save_file = os.path.join(save, "chess.json")
        pos, level, flip, msg = ChessPosition(), 2, False, ""
        if not self.guest:
            try:
                data = json.load(open(save_file))
                level = int(data.get("level", 2))
                for m in data.get("moves", []):
                    pos.play(m)
            except (OSError, ValueError, TypeError):
                pos = ChessPosition()

        def keep():
            if self.guest:
                return
            try:
                os.makedirs(save, exist_ok=True)
                json.dump({"level": level, "moves": pos.moves}, open(save_file, "w"))
            except OSError:
                pass
        try:
            while True:
                board = self.chess_board(pos, flip)
                side = ["", "  " + self.sgr("96;1", "C H E S S"), "  You are white. Strength %d." % level, ""]
                hist = []
                replay = ChessPosition()
                for i, m in enumerate(pos.moves):
                    hist.append(("%d. " % (i // 2 + 1) if i % 2 == 0 else "") + replay.san(m))
                    replay.play(m, check=False)
                for i in range(0, len(hist), 2):
                    side.append("  " + " ".join(hist[i:i + 2]))
                side = side[:4] + side[4:][-9:]
                out = pos.outcome()
                lines = ["%s %s" % (b + "\x1b[0m", s) for b, s in zip(board + [""] * 10, side + [""] * 20)]
                status = out or (("Check! " if pos.in_check() else "") + ("Your move." if pos.white else "Thinking..."))
                await self.send("\x1b[2J\x1b[H\n" + "\n".join(lines[: max(len(board), len(side))]) +
                                "\n\n  " + (msg or status) + "\n")
                msg = ""
                if out:
                    self.game_over("chess", won=out.startswith("Checkmate: white"))
                    if os.path.exists(save_file):
                        try:
                            os.remove(save_file)
                        except OSError:
                            pass
                    if await self.yes_key("  New game?"):
                        pos = ChessPosition()
                        continue
                    return
                if pos.white:
                    line = (await self.readline("  Move (e2e4, Nf3, ? help): ", maxlen=20)).strip()
                    low = line.lower()
                    if low in ("q", "quit", "exit"):
                        keep()
                        return
                    if low in ("?", "help"):
                        msg = "Type a move like e2e4 or Nf3. u undo, n new, t turn board, 1/2/3 strength, q quit."
                    elif low == "u":
                        if len(pos.moves) >= 2:
                            pos.undo()
                            pos.undo()
                        elif pos.moves:
                            pos.undo()
                    elif low == "n":
                        pos = ChessPosition()
                    elif low == "t":
                        flip = not flip
                    elif low in ("1", "2", "3"):
                        level = int(low)
                    elif low:
                        m = self.chess_parse(pos, low)
                        if m is None:
                            msg = self.sgr("91", "Not a legal move: " + line[:20])
                        else:
                            pos.play(m, check=False)
                    keep()
                else:
                    m = await offload(chess_best, pos, level)
                    if m:
                        san = pos.san(m)
                        pos.play(m, check=False)
                        msg = "I play " + san + "."
                    keep()
        finally:
            await self.game_end()

    # ---- adventure -------------------------------------------------------------------------------
    async def game_adventure(self):
        S = {"room": "clearing", "inv": [], "where": {k: v[2] for k, v in ADV_ITEMS.items()},
             "lit": False, "oil": 260, "door": False, "bats": True, "score": 0, "moves": 0,
             "saved": set(), "secret": False, "roped": False}
        out = lambda t: self.send(t + "\n")

        def here(room):
            return [k for k, r in S["where"].items() if r == room]

        def dark():
            return ADV_ROOMS[S["room"]][3] and not S["lit"]

        def name(k):
            return ADV_ITEMS[k][0]

        def match(noun, keys):
            noun = noun.strip()
            for k in keys:
                n = name(k)
                if noun and (noun == k or noun in n.split() or n.startswith(noun)):
                    return k
            return None

        async def look():
            if dark():
                await out(self.c("byellow", "It is pitch black.") + " You can't see a thing.")
                return
            title, text, exits, _ = ADV_ROOMS[S["room"]]
            await out("\n" + self.c("bcyan", title) + "\n" + textwrap.fill(text, 76))
            if S["room"] == "cliff" and S["door"]:
                await out("The wooden door stands open to the north-east: IN.")
            if S["room"] == "bats" and S["bats"]:
                await out("Bats flutter angrily around you, tugging at your hair.")
            if S["room"] == "lower" and not S["roped"]:
                pass
            for k in here(S["room"]):
                await out("There is %s %s here." % ("an" if name(k)[0] in "aeiou" else "a", name(k)))

        def exit_for(d):
            room = S["room"]
            if room == "cliff" and d == "in":
                return "mouth" if S["door"] else "locked"
            if room == "pit" and d == "d":
                return "lower" if S["roped"] else "jump"
            if room == "lower" and d == "u":
                return "pit"
            return ADV_ROOMS[room][2].get(d)

        async def finish(text):
            await out(self.c("bred", text))
            await out("You scored %d of 115 points in %d moves." % (S["score"], S["moves"]))
            self.game_over("adventure", won=S["score"] >= 100, score=S["score"])

        if not await self.game_start(hide=False):
            return
        try:
            await out(self.c("bwhite", "CAVE ADVENTURE") + self.c("gray", "  (type HELP for words; QUIT ends)"))
            await out(textwrap.fill("Somewhere near here is a cave full of treasure. Find it, and bring the "
                                    "treasures to the shack. Good luck!", 76))
            await look()
            while True:
                line = (await self.readline("\n> ", maxlen=60)).lower().strip()
                words = [w for w in re.findall(r"[a-z]+", line) if w not in ("the", "a", "an", "to", "at", "with", "on", "my")]
                if not words:
                    continue
                verb, noun = words[0], " ".join(words[1:])
                S["moves"] += 1
                if S["lit"]:
                    S["oil"] -= 1
                    if S["oil"] == 30:
                        await out(self.c("byellow", "Your lantern is getting dim."))
                    if S["oil"] <= 0:
                        S["lit"] = False
                        await out(self.c("byellow", "Your lantern has run out of oil and goes out."))
                if verb == "say" and noun:
                    verb, noun = noun.split()[0], ""
                if verb == "go" and noun:
                    verb, noun = noun.split()[0], ""
                if verb in ADV_DIRS:
                    d = ADV_DIRS[verb]
                    was_dark = dark()
                    dest = exit_for(d)
                    if dest == "locked":
                        await out("The door is locked.")
                    elif dest == "jump":
                        await finish("It's a long way down. You step off the edge and that is the end of you.")
                        return
                    elif not dest:
                        await out("You can't go that way.")
                    elif was_dark and secrets.randbelow(4) == 0:
                        await finish("You stumble in the dark and fall to your death.")
                        return
                    else:
                        S["room"] = dest
                        if dest == "bats" and S["bats"] and secrets.randbelow(3) == 0:
                            S["room"] = "gallery"
                            await out("The bats swarm you and carry you back to the gallery!")
                        await look()
                elif verb in ("look", "l"):
                    await look()
                elif verb in ("inventory", "inv", "i"):
                    await out("You carry: " + (", ".join(name(k) for k in S["inv"]) or "nothing") + ".")
                elif verb in ("take", "get", "grab", "pick"):
                    if dark():
                        await out("It is too dark to find anything.")
                    elif noun == "all" or not noun:
                        items = [k for k in here(S["room"])]
                        if not items:
                            await out("Nothing to take.")
                        for k in items:
                            if len(S["inv"]) >= 6:
                                await out("You can't carry any more.")
                                break
                            S["where"][k] = "you"
                            S["inv"].append(k)
                            await out("%s: taken." % name(k))
                    else:
                        k = match(noun, here(S["room"]))
                        if not k:
                            await out("You don't see that here.")
                        elif len(S["inv"]) >= 6:
                            await out("You can't carry any more.")
                        else:
                            S["where"][k] = "you"
                            S["inv"].append(k)
                            await out("Taken.")
                            if k == "idol":
                                await out("The cavern rumbles for a moment, then is still.")
                elif verb in ("drop", "leave", "put", "deposit"):
                    k = match(noun, S["inv"])
                    if not k:
                        await out("You aren't carrying that.")
                        continue
                    S["inv"].remove(k)
                    S["where"][k] = S["room"]
                    if k == "lantern":
                        S["lit"] = False
                    if S["room"] == "shack" and ADV_ITEMS[k][3] and k not in S["saved"]:
                        S["saved"].add(k)
                        S["score"] += 25
                        await out(self.c("bgreen", "Safe! The %s is yours. (+25)" % name(k)))
                        if len(S["saved"]) == 4:
                            await finish("You have found every treasure. You are a master adventurer!")
                            return
                    else:
                        await out("Dropped.")
                elif verb in ("examine", "x", "read", "inspect"):
                    k = match(noun, S["inv"] + here(S["room"]))
                    if k:
                        await out(ADV_ITEMS[k][1])
                    elif S["room"] == "crystal" and noun in ("wall", "word", "writing", "plugh", "rock"):
                        await out("The scratched word says PLUGH. It looks like a magic word.")
                    elif S["room"] == "cliff" and noun in ("door", "padlock", "lock"):
                        await out("A stout door held shut by a rusty padlock." if not S["door"] else "The door is open.")
                    else:
                        await out("You see nothing special.")
                elif verb in ("light", "lamp", "lantern") or (verb == "turn" and noun.startswith("on")):
                    if "lantern" not in S["inv"]:
                        await out("You have no lantern.")
                    elif S["oil"] <= 0:
                        await out("The lantern is out of oil.")
                    else:
                        S["lit"] = True
                        await out("The lantern is now lit.")
                        await look()
                elif verb in ("extinguish", "douse", "off") or (verb == "turn" and noun.startswith("off")):
                    S["lit"] = False
                    await out("The lantern is off.")
                elif verb in ("unlock", "open"):
                    if S["room"] != "cliff" or "door" not in noun + "door":
                        await out("There is nothing to open here.")
                    elif S["door"]:
                        await out("It is already open.")
                    elif "key" in S["inv"]:
                        S["door"] = True
                        S["score"] += 5
                        await out(self.c("bgreen", "The padlock clicks open and the door swings wide. (+5)"))
                    else:
                        await out("You need a key.")
                elif verb in ("tie", "attach", "lower", "climb") or (verb == "use" and "rope" in noun):
                    if S["room"] == "pit" and "rope" in S["inv"]:
                        S["roped"] = True
                        await out("You tie the rope to the stalagmite and let it drop. You can climb DOWN now.")
                    elif S["room"] == "pit":
                        await out("You have nothing to climb with.")
                    else:
                        await out("Nothing to do that with here.")
                elif verb in ("feed", "give", "throw", "eat"):
                    if "sandwich" in S["inv"] and S["room"] == "bats" and verb != "eat" and S["bats"]:
                        S["inv"].remove("sandwich")
                        del S["where"]["sandwich"]
                        S["bats"] = False
                        S["score"] += 5
                        await out(self.c("bgreen", "The bats fall on the sandwich and leave you in peace. (+5)"))
                    elif verb == "eat" and "sandwich" in S["inv"]:
                        S["inv"].remove("sandwich")
                        del S["where"]["sandwich"]
                        await out("Delicious.")
                    else:
                        await out("That doesn't help.")
                elif verb == "plugh":
                    if S["room"] in ("gallery", "shack"):
                        S["room"] = "shack" if S["room"] == "gallery" else "gallery"
                        if not S["secret"]:
                            S["secret"] = True
                            S["score"] += 5
                            await out(self.c("bgreen", "A hollow voice says PLUGH. (+5)"))
                        await look()
                    else:
                        await out("Nothing happens.")
                elif verb == "score":
                    await out("Score %d of 115 in %d moves." % (S["score"], S["moves"]))
                elif verb in ("help", "?"):
                    await out("Words: N S E W U D IN OUT, LOOK, TAKE, DROP, INVENTORY, EXAMINE, LIGHT, "
                              "OFF, UNLOCK DOOR, TIE ROPE, FEED, EAT, SCORE, QUIT. "
                              "Drop treasures in the shack to score.")
                elif verb in ("quit", "q", "stop"):
                    await finish("You give up.")
                    return
                else:
                    await out("I don't know how to %s." % verb)
        finally:
            await self.game_end()


# --------------------------------------------------------------------------
# Session extras: art rotation, voting, achievements, daily screen, chat extras
# --------------------------------------------------------------------------

class ExtrasMixin:
    # ---- art rotation -----------------------------------------------------------
    def art_files(self, *parts):
        base = self.cfg.get("art_dir")
        if not base:
            return []
        d = os.path.join(base, *parts)
        try:
            if os.path.isdir(d):
                return sorted(os.path.join(d, f) for f in os.listdir(d)
                              if f.lower().endswith((".ans", ".txt", ".asc", ".nfo")) and not f.startswith("."))
        except OSError:
            return []
        return [d + e for e in (".ans", ".txt", ".asc") if os.path.isfile(d + e)]

    def art_choose(self, files, key):
        if not files:
            return None
        mode = self.cfg.get("art_rotation", "random")
        if mode == "daily":
            idx = int(time.time() // 86400)
        elif mode == "sequential":
            seq = self.bbs.meta.setdefault("art_seq", {})
            idx = seq.get(key, 0)
            seq[key] = idx + 1
        else:
            idx = secrets.randbelow(len(files))
        return files[idx % len(files)]

    async def show_art(self, kind, name="", title="", tagline=""):
        """Art for a room or board: one of its files, or a small generated banner."""
        parts = (kind, name) if name else (kind,)
        path = self.art_choose(self.art_files(*parts), "/".join(parts))
        if path:
            await self.text_file(path)
        elif self.cfg["art"].get("small") and name:
            cfg = copy.deepcopy(self.cfg)
            cfg["name"], cfg["tagline"] = title or name, tagline
            cfg["art"]["file"] = ""
            await self.send(make_banner(cfg, self.color, min(self.cols, 80)))

    # ---- who we are ---------------------------------------------------------------
    def user_rec(self):
        return None if self.guest else self.bbs.users.get(self.name.lower())

    @property
    def mod(self):
        return self.sysop or self.deputy

    def award(self, key):
        u = self.user_rec()
        if not u or key not in ACHIEVEMENTS or not self.feat.get("achievements", True):
            return
        got = u.setdefault("ach", {})
        if key in got:
            return
        got[key] = time.time()
        self.bbs.save("users", self.bbs.users)
        self.toasts.append(self.c("byellow", "** Achievement unlocked: %s - %s **" % ACHIEVEMENTS[key]))

    async def flush_toasts(self):
        if self.toasts and self.music:
            await self.send(self.music_seq("achievement"), fast=True)
        while self.toasts:
            await self.send(self.toasts.pop(0) + "\n")

    def game_over(self, game, won=False, score=0):
        if self.guest:
            return
        bbs = self.bbs
        if game in ("robots", "snake", "adventure") and score > 0:
            bbs.add_score(game, self.name, score)
        if game == "sudoku" and won:
            bbs.add_score(game, self.name, score, low=True)
        if game.startswith("minesweeper") and won:
            bbs.add_score(game, self.name, score, low=True)
            self.award("mines")
        if game == "solitaire" and won:
            bbs.add_score(game, self.name, score, low=True)
            self.award("solitaire")
        if game.startswith("mp_") and won:
            self.award("mpwin")
        if game == "quiz":
            bbs.add_score("quiz", self.name, score)
            if won:
                self.award("quiz")
        bbs.track(self.name, "games")
        if game == "hangman" and won:
            self.award("hangman")
        elif game == "robots" and score >= 500:
            self.award("robots")
        elif game == "snake" and score >= 100:
            self.award("snake")
        elif game in ("sudoku", "chess", "ttt") and won:
            self.award(game)
        elif game == "adventure" and won:
            self.award("adventure")
        elif game == "mphang" and won:
            self.award("mphang")

    # ---- an urgent message from the operator -----------------------------------------------
    def alert_block(self, text):
        return force_block(self.cfg.get("force") or {}, text, self.cols, self.color)

    def force(self, text, kick=False):
        """Show text on this caller's screen now, whatever they are doing."""
        self.alert = (text, time.time() + int((self.cfg.get("force") or {}).get("seconds", 15)))
        if not self.w.is_closing():
            typed = self.buf if self.telnet else ""
            try:
                self._write("\r\n" + self.alert_block(text) + "\n\n" + self.prompt + typed)
            except (ConnectionError, OSError):
                pass
        if kick:
            asyncio.get_running_loop().call_later(1.0, self.w.close)

    # ---- last callers, today, hall ---------------------------------------------------------------
    async def last_callers(self):
        await self.header("Last callers")
        rows = [r for r in self.bbs.meta.get("callers", [])
                if self.sees(r["name"], self.bbs.age_of(r["name"]))][-15:][::-1]
        for r in rows:
            await self.send(" %-16s %s  stayed %s\n" % (r["name"], fdate(r["ts"]), duration(r["secs"])))
        if not rows:
            await self.send("  (nobody has called yet)\n")
        await self.readline(self.c("gray", "\n[Enter to continue]"))

    def daily_seed(self):
        return daily_seed()

    def update_streak(self):
        u = self.user_rec()
        if not u:
            return
        today = time.strftime("%Y-%m-%d")
        yesterday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
        if u.get("day") != today:
            u["streak"] = u.get("streak", 0) + 1 if u.get("day") == yesterday else 1
            u["day"] = today
            u["best_streak"] = max(u.get("best_streak", 0), u["streak"])
            self.bbs.save("users", self.bbs.users)
        if u["streak"] >= 3:
            self.award("streak3")
        if u["streak"] >= 7:
            self.award("streak7")

    async def today(self, brief=False):
        seed = self.daily_seed()
        now = time.localtime()
        tips = list(self.cfg.get("tips") or []) + TIPS
        fortune, history = self.bbs.daily_texts(now)
        await self.header("Today, " + time.strftime("%A %d %B %Y"))
        await self.send("  %s %s\n" % (self.c("byellow", "Fortune:"), fortune))
        await self.send("  %s %s\n" % (self.c("byellow", "Tip:"), tips[seed % len(tips)]))
        await self.send("  %s %s\n" % (self.c("byellow", "History:"), history))
        await self.send("  %s %s     %s %d\n" % (self.c("byellow", "Word of the day:"),
                                                 HANGWORDS[seed % len(HANGWORDS)], self.c("byellow", "Lucky number:"),
                                                 seed * 7919 % 99 + 1))
        u = self.user_rec()
        if u:
            await self.send("  %s %d day%s in a row (best %d)\n" % (
                self.c("byellow", "Your streak:"), u.get("streak", 1), "" if u.get("streak", 1) == 1 else "s",
                u.get("best_streak", 1)))
        polls = [p for p in self.bbs.polls["polls"] if not p["closed"]]
        if polls and self.feat.get("polls", True):
            await self.send("  %s %d open poll%s in the voting booth.\n" % (
                self.c("byellow", "Vote:"), len(polls), "" if len(polls) == 1 else "s"))
        if not brief:
            await self.readline(self.c("gray", "\n[Enter to continue]"))

    async def hall(self):
        await self.header("Hall of achievements")
        u = self.user_rec()
        got = (u or {}).get("ach", {})
        for k, (title, how) in ACHIEVEMENTS.items():
            mark = self.c("bgreen", "[*]") if k in got else "[ ]"
            await self.send(" %s %-20s %s%s\n" % (mark, title, self.c("gray", how),
                                                   ("  " + fdate(got[k])[:10]) if k in got else ""))
        await self.send("\n  %d of %d earned.\n" % (len(got), len(ACHIEVEMENTS)))
        await self.readline(self.c("gray", "\n[Enter to continue]"))

    async def high_scores(self):
        await self.header("High scores")
        any_ = False
        for g, rows in self.bbs.scores.items():
            if not rows:
                continue
            any_ = True
            await self.send(self.c("byellow", " %s\n" % (GAMES[g][0] if g in GAMES else g.replace("-", " ").title())))
            for i, r in enumerate(rows[:5], 1):
                val = "%d:%02d" % divmod(int(r["score"]), 60) if r.get("low") else str(r["score"])
                await self.send("   %d. %-16s %8s   %s\n" % (i, r["name"], val, fdate(r["ts"])[:10]))
        if not any_:
            await self.send("  No scores yet. Play something!\n")
        await self.readline(self.c("gray", "\n[Enter to continue]"))

    # ---- voting booth ---------------------------------------------------------------------------------
    def poll_bars(self, p):
        counts = [0] * len(p["options"])
        for v in p["votes"].values():
            counts[v] += 1
        total = max(len(p["votes"]), 1)
        rows = []
        for i, (o, n) in enumerate(zip(p["options"], counts), 1):
            bar = "#" * int(n * 24 / total)
            rows.append("  %s %-24s %s %d (%d%%)" % (self.c("byellow", str(i)), o[:24], self.c("bgreen", bar.ljust(24)),
                                                      n, round(100 * n / total) if p["votes"] else 0))
        return rows

    async def voting_booth(self):
        bbs = self.bbs
        while True:
            self.where = "Voting booth"
            bbs.elect_check()
            await self.header("Voting booth")
            polls = sorted(bbs.polls["polls"], key=lambda p: (p["closed"], -p["id"]))[:12]
            for i, p in enumerate(polls, 1):
                mine = " " + self.c("bgreen", "[voted]") if p["votes"].get(self.name.lower()) is not None else ""
                state = self.c("gray", "(closed)") if p["closed"] else ""
                await self.send(" %s %-44s %3d vote%s %s%s\n" % (
                    self.c("byellow", "%2d" % i), p["question"][:44], len(p["votes"]),
                    " " if len(p["votes"]) == 1 else "s", state, mine))
            if not polls:
                await self.send("  (no polls yet)\n")
            show_el = bbs.elect["current"] or self.feat.get("elections")
            if show_el:
                await self.send("  %s Sysop election%s\n" % (self.c("byellow", " E"),
                                                           " - OPEN, until " + fdate(bbs.elect["current"]["end"])
                                                           if bbs.elect["current"] else " (none running)"))
            if self.mod:
                await self.send("  %s Add a poll\n" % self.c("byellow", " A"))
            k = (await self.readline("\nPoll # (Enter = back): ")).strip().lower()
            if not k:
                return
            if k == "e" and show_el:
                await self.election_screen()
            elif k == "a" and self.mod:
                await self.add_poll()
            elif k.isdigit() and 1 <= int(k) <= len(polls):
                await self.poll_screen(polls[int(k) - 1])

    async def add_poll(self):
        q = (await self.readline("Question: ", maxlen=100)).strip()
        if not q:
            return
        opts = []
        while len(opts) < 8:
            o = (await self.readline("Choice %d (Enter = done): " % (len(opts) + 1), maxlen=40)).strip()
            if not o:
                break
            opts.append(o)
        if len(opts) < 2:
            await self.send(self.c("red", "A poll needs at least two choices.\n"))
            return
        p = self.bbs.poll_add(q, opts)
        self.bbs.broadcast_sysop("New poll in the voting booth: " + q)
        await self.send(self.c("bgreen", "Poll %d opened.\n" % p["id"]))

    async def poll_screen(self, p):
        bbs = self.bbs
        while True:
            await self.send("\n" + self.c("bwhite", p["question"]) + (self.c("gray", "  (closed)") if p["closed"] else "") + "\n")
            for ln in self.poll_bars(p):
                await self.send(ln + "\n")
            mine = p["votes"].get(self.name.lower())
            if self.mod and not p["closed"]:
                extra = "  C closes the poll"
            else:
                extra = ""
            if p["closed"] or mine is not None or self.guest:
                if mine is not None:
                    await self.send(self.c("gray", "  You voted for %s.\n" % p["options"][mine]))
                elif self.guest and not p["closed"]:
                    await self.send(self.c("gray", "  Register an account to vote.\n"))
                ans = (await self.readline(self.c("gray", "\n[Enter]" + extra))).strip().lower()
                if ans == "c" and self.mod and not p["closed"]:
                    p["closed"] = True
                    bbs.save("polls", bbs.polls)
                    continue
                return
            ans = (await self.readline("\nYour vote (1-%d, Enter = just look)%s: " % (len(p["options"]), extra))).strip().lower()
            if ans == "c" and self.mod:
                p["closed"] = True
                bbs.save("polls", bbs.polls)
                continue
            if not ans:
                return
            if ans.isdigit():
                ok, msg = bbs.poll_vote(p, self.name.lower(), int(ans) - 1)
                await self.send(self.c("bgreen" if ok else "red", msg + "\n"))
                if ok:
                    self.award("voter")
                    self.bbs.track(self.name, "votes")

    async def election_screen(self):
        bbs = self.bbs
        while True:
            cur = bbs.elect["current"]
            await self.header("Sysop election")
            if not cur:
                await self.send("  No election is running.\n")
                if self.sysop:
                    ans = (await self.readline("  Open one? Days (Enter = no): ")).strip()
                    if ans.isdigit():
                        ok, msg = bbs.elect_start(int(ans))
                        await self.send(msg + "\n")
                        continue
                else:
                    await self.send(self.c("gray", "  The sysop can open an election; callers then stand and vote.\n"))
                await self.readline(self.c("gray", "\n[Enter]"))
                return
            counts = bbs.elect_counts(cur)
            await self.send("  Open until %s. %d seat%s. Callers with %d+ calls may stand and vote.\n" % (
                fdate(cur["end"]), cur["seats"], "" if cur["seats"] == 1 else "s", self.cfg["election"]["min_calls"]))
            cands = sorted(cur["candidates"].items(), key=lambda kv: (-counts[kv[0]], kv[1]["name"].lower()))
            mine = cur["votes"].get(self.name.lower())
            for i, (c, info) in enumerate(cands, 1):
                await self.send(" %s %-16s %3d vote%s%s\n" % (
                    self.c("byellow", "%2d" % i), info["name"], counts[c], " " if counts[c] == 1 else "s",
                    self.c("bgreen", "  <- your vote") if mine == c else ""))
            if not cands:
                await self.send("  (nobody is standing yet)\n")
            cmds = "[S]tand yourself  [V]ote #" + ("  [E]nd now" if self.sysop else "") + "  [Q]uit"
            parts = (await self.readline("\n%s\n> " % cmds)).strip().lower().split()
            if not parts or parts[0] == "q":
                return
            if self.guest:
                await self.send(self.c("red", "Guests can't take part. Register an account!\n"))
                continue
            if parts[0] == "s":
                ok, msg = bbs.elect_nominate(self.name, "self")
                await self.send(self.c("bgreen" if ok else "red", msg + "\n"))
            elif parts[0] == "v" or parts[0].isdigit():
                num = parts[1] if parts[0] == "v" and len(parts) > 1 else parts[0]
                if num.isdigit() and 1 <= int(num) <= len(cands):
                    ok, msg = bbs.elect_vote(self.name, cands[int(num) - 1][0])
                    await self.send(self.c("bgreen" if ok else "red", msg + "\n"))
                    if ok:
                        self.award("voter")
                else:
                    await self.send(self.c("red", "Give a candidate number.\n"))
            elif parts[0] == "e" and self.sysop:
                ok, msg = bbs.elect_end()
                await self.send(msg + "\n")

    # ---- multiplayer lobby ----------------------------------------------------------------------------------
    async def mp_play(self, table):
        """Sit at a table until it is over or we leave; redraws when anyone moves."""
        ev = table.events[self]
        kt = None
        try:
            while True:
                ev.clear()
                await self.draw(table.render(self))
                if kt is None:
                    kt = asyncio.ensure_future(self.key())
                if table.state == "over":
                    await kt
                    kt = None
                    return
                et = asyncio.ensure_future(ev.wait())
                done, _ = await asyncio.wait({kt, et}, return_when=asyncio.FIRST_COMPLETED)
                if et not in done:
                    et.cancel()
                if kt in done:
                    k = kt.result()
                    kt = None
                    if table.handle(self, k) == "leave":
                        return
        finally:
            if kt is not None:
                kt.cancel()
            table.leave(self)
            if not table.players:
                self.bbs.tables.pop(table.id, None)

    def open_table(self, game, opts=None):
        bbs = self.bbs
        t = Table(bbs.next_table, game, self, opts)
        bbs.next_table += 1
        bbs.tables[t.id] = t
        return t

    def announce_table(self, t):
        for s in list(self.bbs.sessions):
            if s is not self and s.where in ("Multiplayer lobby",) and self.bbs.may_meet(self.name, self.age, s.name, s.age):
                s.push(s.c("bcyan", "[lobby] %s opened a %s table (#%d)" % (self.name, t.title, t.id)))

    async def multiplayer(self):
        bbs = self.bbs
        if not await self.game_start(hide=False):
            return
        await self.send("\x1b[0m\x1b[2J\x1b[H")
        while True:
            self.where = "Multiplayer lobby"
            await self.header("Multiplayer games")
            tables = [t for t in bbs.tables.values() if t.state == "waiting"
                      and all(bbs.may_meet(self.name, self.age, p.name, p.age) for p in t.players)]
            for t in tables:
                await self.send(" %s table %d  %-13s %s  (%d/%d)\n" % (
                    self.c("byellow", "%2d" % t.id), t.id, t.title, ", ".join(p.name for p in t.players),
                    len(t.players), t.max_players))
            if not tables:
                await self.send("  (no open tables - host one!)\n")
            hosts = "  ".join("[%s] %s" % (k.upper(), MP_GAMES[g].title) for k, g in MP_KEYS.items())
            k = (await self.readline("\nHost: %s\n[#] join a table   [Q]uit\n> " % hosts)).strip().lower()
            if k == "q":
                return
            if k in MP_KEYS:
                game = MP_KEYS[k]
                opts = await MP_GAMES[game].prepare(self)
                if opts is None:
                    continue
                t = self.open_table(game, opts)
                self.announce_table(t)
                await self.mp_play(t)
            elif k.isdigit():
                t = bbs.tables.get(int(k))
                if t and not all(bbs.may_meet(self.name, self.age, p.name, p.age) for p in t.players):
                    t = None
                if not t or t.state != "waiting" or len(t.players) >= t.max_players:
                    await self.send(self.c("red", "That table is not open.\n"))
                    continue
                t.join(self)
                await self.mp_play(t)

    # ---- extra chat commands (return True if handled) ---------------------------------------------------------
    async def chat_extra(self, room, cmd, arg):
        bbs, me = self.bbs, self.name
        if cmd == "ignore":
            if not arg:
                await self.send("Ignoring: %s\n" % (", ".join(sorted(self.ignored)) or "nobody"))
            elif arg.lower() in self.ignored:
                self.ignored.discard(arg.lower())
                await self.send("No longer ignoring %s.\n" % arg)
            else:
                self.ignored.add(arg.lower())
                await self.send("Ignoring %s.\n" % arg)
            u = self.user_rec()
            if u is not None:
                u["ignore"] = sorted(self.ignored)
                bbs.save("users", bbs.users)
        elif cmd == "color":
            if arg.lower() in ANSI and arg.lower() not in ("black",):
                u = self.user_rec()
                if u is None:
                    await self.send(self.c("red", "Guests can't keep a color.\n"))
                else:
                    u["color"] = arg.lower()
                    bbs.save("users", bbs.users)
                    self.award("colorful")
                    await self.send("Your name is now %s.\n" % self.c(arg.lower(), me))
            else:
                await self.send("Colors: " + " ".join(self.c(c, c) for c in ANSI if c != "black") + "\n")
        elif cmd == "roll":
            m = re.fullmatch(r"(\d{1,2})?d(\d{1,4})", (arg or "d6").lower().replace(" ", ""))
            if not m:
                await self.send("Usage: /roll 2d6\n")
            else:
                n, sides = int(m.group(1) or 1), int(m.group(2))
                if sides < 2:
                    await self.send("Dice need at least 2 sides.\n")
                else:
                    rolls = [1 + secrets.randbelow(sides) for _ in range(n)]
                    room.say("emo", me, "rolls %dd%d: %s = %d" % (n, sides, " + ".join(map(str, rolls)), sum(rolls)))
                    self.award("roller")
        elif cmd == "8ball":
            room.say("emo", me, "shakes the magic 8-ball and sees: " + secrets.choice([
                "It is certain.", "Without a doubt.", "Most likely.", "Ask again later.", "Cannot predict now.",
                "Don't count on it.", "My sources say no.", "Very doubtful.", "Signs point to yes."]))
        elif cmd == "fortune":
            room.say("emo", me, "reads a fortune: " + secrets.choice(FORTUNES))
        elif cmd == "shrug":
            room.say("emo", me, "shrugs.")
        elif cmd == "tableflip":
            room.say("emo", me, "flips the table. (>_<)")
        elif cmd == "afk":
            self.afk = arg or "away"
            room.say("sys", me, "%s is away: %s" % (me, self.afk))
        elif cmd == "seen":
            u = bbs.users.get(arg.lower())
            s = bbs.find_session(arg)
            if u and not self.sees(u["name"], bbs.age_of(u["name"])):
                u, s = None, None
            await self.send(("%s is online now.\n" % s.name) if s else
                            ("%s was last here %s.\n" % (u["name"], fdate(u["last"])) if u else "No such user.\n"))
        elif cmd == "history":
            n = int(arg) if arg.isdigit() else 10
            for e in list(room.history)[-min(n, 50):]:
                await self.send(self.fmt_chat(e) + "\n")
        elif cmd == "time":
            await self.send(time.strftime("It is %H:%M:%S on %A %d %B.\n"))
        elif cmd == "kick" and self.mod:
            target = bbs.find_session(arg)
            if target and target is not self and not target.sysop:
                target.force("You were disconnected by %s." % me, kick=True)
                await self.send("Kicked %s.\n" % target.name)
            else:
                await self.send(self.c("red", "Not online.\n"))
        elif cmd in ("challenge", "invite") and bbs is not None:
            who, _, game = arg.partition(" ")
            game = MP_ALIASES.get(game.strip().lower().replace("-", "").replace(" ", ""))
            target = bbs.find_session(who)
            if not target or not game or not self.feat.get("multiplayer", True):
                await self.send("Usage: /challenge <online user> <ttt|hangman|c4|battleship|reversi|word>\n")
            elif not self.may("multiplayer") or not bbs.may_meet(me, self.age, target.name, target.age):
                await self.send(self.c("red", "You can't challenge %s.\n" % target.name))
            else:
                t = self.open_table(game)
                target.push(target.c("bcyan", "%s challenges you to %s! Open Multiplayer (P) from the main menu "
                                              "and join table %d." % (me, t.title, t.id)))
                await self.send("Challenge sent. Taking your seat at table %d...\n" % t.id)
                self.after_chat = t
                return "leave"
        else:
            return False
        return True


# --------------------------------------------------------------------------
# Content for achievements, the daily screen and the voting booth
# --------------------------------------------------------------------------

ACHIEVEMENTS = {  # key: (title, how)
    "hello": ("Hello, world", "Log in for the first time"),
    "regular": ("Regular", "Call 10 times"),
    "veteran": ("Veteran", "Call 50 times"),
    "streak3": ("On a roll", "Call 3 days in a row"),
    "streak7": ("Creature of habit", "Call 7 days in a row"),
    "night": ("Night owl", "Call between midnight and 5 am"),
    "poster": ("Say something", "Post on a message board"),
    "writer": ("Pen pal", "Send private mail"),
    "chatter": ("Chatterbox", "Say something in chat"),
    "roller": ("Roll the dice", "Use /roll in chat"),
    "colorful": ("Colorful", "Pick your chat color with /color"),
    "voter": ("Civic duty", "Vote in a poll or election"),
    "candidate": ("Throw your hat", "Stand in a sysop election"),
    "elected": ("Your honour", "Be elected deputy sysop"),
    "hangman": ("Last-letter hero", "Win a game of Hangman"),
    "robots": ("Robot wrecker", "Score 500 in Robots"),
    "snake": ("Long worm", "Score 100 in Snake"),
    "sudoku": ("Number cruncher", "Solve a Sudoku"),
    "chess": ("Checkmate", "Beat the computer at chess"),
    "adventure": ("Treasure hunter", "Bring home the treasure in the cave adventure"),
    "ttt": ("Three in a row", "Win a multiplayer Tic-Tac-Toe game"),
    "mphang": ("Gallows humour", "Win a multiplayer Hangman game"),
    "mpwin": ("Table talk", "Win Connect Four, Battleship, Reversi or Word Race"),
    "mines": ("Sweeper", "Clear a Minesweeper field"),
    "paste": ("Paste it", "Share something on the pastebin"),
    "newsy": ("Well informed", "Read a news channel"),
    "scholar": ("Scholar", "Answer the weekly trivia question correctly"),
    "quiz": ("Quiz whiz", "Get 8 of 10 right in the quiz"),
    "cotm": ("Caller of the month", "Be the top caller of a month"),
    "oneliner": ("Short and sweet", "Write on the oneliner wall"),
    "profile": ("Know thyself", "Fill in your profile"),
    "solitaire": ("Patience", "Win a game of Solitaire"),
}

FORTUNES = [
    "There is no place like 127.0.0.1.",
    "A watched modem never connects.",
    "Today's bug is tomorrow's feature.",
    "The best backup is the one you tested.",
    "Slow is smooth, and smooth is fast. Also, 2400 baud is fine.",
    "Someone somewhere is reading your last post and smiling.",
    "You will soon find a file that was exactly where you left it.",
    "Be conservative in what you send, liberal in what you accept.",
    "Turn it off and on again. It is traditional.",
    "An empty message board is a blank canvas.",
    "The network is the computer, the BBS is the neighbourhood.",
    "Your next idea will be a good one. Write it down.",
    "Never trust a progress bar. Always trust a friend.",
    "Read the manual. Then write the manual.",
    "Good things come to those who dial.",
    "Fortune favours the one who saves often.",
    "Every expert once typed their first command.",
    "It works on my machine, and now on yours too.",
    "Be kind: every user is also somebody's sysop.",
    "A small program that works beats a grand one that doesn't.",
    "The cursor blinks; it is waiting for you.",
    "Hint: the answer is usually in the log.",
    "May your pings be low and your uptime high.",
    "Learn one new command today.",
    "Your next call will connect on the first ring.",
    "A backup in the hand is worth two on the disk that just failed.",
    "The best interface is the one that fits in 80 columns.",
    "You will soon receive mail from someone who has been meaning to write.",
    "Somebody's oneliner will make you smile today.",
    "Patience: the download is at 99%, and has been for a while.",
    "Fix the bug, not the blame.",
    "Ctrl-C is not a failure; it is a decision.",
    "A clean prompt is a clear mind.",
    "Even a 300 baud message arrives.",
    "Today is a good day to read the readme.",
    "The file you want is in the other directory.",
    "Enjoy the quiet: the boards will be busy tomorrow.",
    "Someone will answer your question before you finish asking it.",
    "Trust the checksum.",
    "Don't panic; check the logs.",
    "A short post well made beats a long one half read.",
    "Your high score is closer than it looks.",
    "Be the sysop you wish to call.",
    "The best time to document it was when you wrote it. The second best is now.",
    "Good manners compress well.",
    "A quiet line is not a dead line.",
    "May all your sectors be good.",
    "Leave the board a little tidier than you found it.",
    "You will find what you are looking for in the last place you check, because then you stop.",
    "Speed is nice. Reliability is nicer.",
    "Never underestimate the power of a good welcome screen.",
    "The cursor knows what you will type next. It is not telling.",
    "Somewhere, someone is stuck on the last letter in Hangman. Be kind.",
    "An unread message is a small adventure.",
    "The modem screeches because it is excited to meet you.",
    "Today's goal: one new command.",
    "Plan for the power cut.",
    "A good password is long, strange and yours alone.",
    "Take a break. The BBS will still be here.",
    "Beware of anything that needs just one more reboot.",
    "Small steps compile.",
    "If at first you don't succeed, read the error message.",
    "The best feature is the one your callers actually use.",
    "Keep your lines short and your uptime long.",
]

TIPS = [
    "In chat, /me waves sends an action; /roll 2d6 rolls dice.",
    "Type /ignore NAME in chat to stop seeing someone, and /ignore again to undo it.",
    "Your chat name color is yours to choose: /color cyan.",
    "Press Ctrl-C at any time to disconnect.",
    "Mail is private; boards are public. Use the right one.",
    "The voting booth is open: vote once per poll.",
    "Come back tomorrow to keep your calling streak going.",
    "Tic-Tac-Toe and Hangman can be played against other callers in Multiplayer.",
    "Press T in the main menu to switch colors on or off.",
    "The Hall lists every achievement and how to earn it.",
]

HISTORY = {  # (month, day): what happened (each line checked against Wikipedia and the Computer History Museum)
    (1, 1): '1983: the ARPANET switched to TCP/IP, the day many call the birthday of the Internet.',
    (1, 3): '1977: Apple Computer, Inc. was incorporated.',
    (1, 9): '2007: Steve Jobs introduced the iPhone.',
    (1, 15): '2001: Wikipedia went online.',
    (1, 24): '1984: Apple introduced the Macintosh.',
    (1, 31): '1958: the United States launched its first satellite, Explorer 1.',
    (2, 4): '2004: Facebook was launched at Harvard.',
    (2, 14): '1946: ENIAC, one of the first general-purpose computers, was unveiled.',
    (2, 20): '1962: John Glenn became the first American to orbit the Earth.',
    (3, 10): '1876: Alexander Graham Bell made the first telephone call.',
    (3, 12): '1989: Tim Berners-Lee proposed the World Wide Web to CERN.',
    (3, 14): 'Pi day: 3.14159 26535 89793...',
    (3, 15): '1985: symbolics.com became the first registered .com domain name.',
    (3, 16): '1926: Robert Goddard launched the first liquid-fueled rocket.',
    (3, 18): '1965: Alexei Leonov made the first spacewalk.',
    (4, 1): '1976: Apple Computer was founded.',
    (4, 4): '1975: Microsoft was founded.',
    (4, 7): '1964: IBM announced the System/360 family of computers.',
    (4, 12): '1961: Yuri Gagarin became the first human in space.',
    (4, 13): '1970: an oxygen tank exploded on Apollo 13, almost 56 hours into the flight.',
    (4, 21): '1993: the Mosaic web browser, version 1.0, was released.',
    (4, 30): '1993: CERN put the World Wide Web software in the public domain.',
    (5, 5): '1961: Alan Shepard became the first American in space.',
    (5, 11): "1997: IBM's Deep Blue beat Garry Kasparov in a six-game chess match.",
    (5, 22): '1973: Bob Metcalfe wrote the memo that described Ethernet.',
    (5, 24): "1844: Samuel Morse sent 'What hath God wrought' over the first telegraph line, from Washington to Baltimore.",
    (6, 7): '1954: Alan Turing died.',
    (6, 10): '1977: the Apple II went on sale.',
    (6, 16): '1963: Valentina Tereshkova became the first woman in space.',
    (6, 23): '1912: Alan Turing was born.',
    (7, 1): '1979: Sony introduced the Walkman.',
    (7, 4): '1997: Mars Pathfinder landed on Mars.',
    (7, 20): '1969: Apollo 11 landed on the Moon.',
    (8, 6): '1991: Tim Berners-Lee posted a summary of the World Wide Web project, making the Web public.',
    (8, 12): '1981: IBM introduced the Personal Computer.',
    (8, 24): '1995: Microsoft released Windows 95.',
    (8, 25): '1991: Linus Torvalds announced his new operating system, Linux.',
    (9, 4): '1998: Larry Page and Sergey Brin incorporated Google.',
    (9, 9): "1947: operators of Harvard's Mark II taped a moth found in a relay into their log: 'First actual case of bug being found.'",
    (9, 12): '1958: Jack Kilby demonstrated the first integrated circuit.',
    (9, 17): '1991: Linux 0.01, the first version of the kernel, was released.',
    (10, 1): '1958: NASA began operations.',
    (10, 4): '1957: the Soviet Union launched Sputnik 1.',
    (10, 5): '2011: Steve Jobs died.',
    (10, 23): '2001: Apple introduced the iPod.',
    (10, 25): '2001: Microsoft released Windows XP.',
    (10, 29): '1969: the first message was sent over the ARPANET.',
    (11, 3): '1957: Sputnik 2 carried the dog Laika into orbit.',
    (11, 20): '1985: Microsoft released Windows 1.0.',
    (12, 2): '1942: Chicago Pile-1 achieved the first controlled nuclear chain reaction.',
    (12, 9): "1968: Douglas Engelbart gave the 'Mother of All Demos'.",
    (12, 10): '1815: Ada Lovelace was born.',
    (12, 17): '1903: the Wright brothers made the first powered flights.',
    (12, 20): '1990: the first web pages, describing the World Wide Web project itself, were published at CERN.',
    (12, 21): '1968: Apollo 8 launched on the first crewed flight to the Moon.',
}
FACTS = [
    "The first BBS, CBBS, went online in Chicago in February 1978.",
    "Early modems ran at 300 bits per second: about 30 characters a second.",
    "The first computer mouse was made of wood.",
    "ASCII has 128 characters; the IBM PC's CP437 added box-drawing for BBS art.",
    "FidoNet, a network of BBSes, began in 1984.",
]


# --------------------------------------------------------------------------
# `hostbbs op`: commands for the operator, live (over a socket) or offline
# --------------------------------------------------------------------------

def op_socket_path(cfg):
    """Where the running BBS listens for `hostbbs op` (short enough for a socket)."""
    p = Path(cfg["data_dir"]) / "op.sock"
    if len(str(p)) < 100:
        return str(p)
    return "/tmp/hostbbs-%s.sock" % hashlib.sha1(str(p).encode()).hexdigest()[:12]


def clean_text(text, limit=400):
    return "".join(ch for ch in text if printable(ch))[:limit].strip()


def force_block(f, text, cols, color):
    """A forced message as the sysop styled it (settings: Forced messages)."""
    width = max(20, min(cols - 8, 64))
    title, style = f.get("title", ""), f.get("style", "block")
    bell = "\a" if f.get("bell", True) else ""
    col, fg = ANSI.get(f.get("color"), 31), ANSI.get(f.get("text_color"), 97)
    align = (lambda t, w: t.center(w)) if f.get("center", True) else (lambda t, w: t.ljust(w))
    if style == "line":
        line = (title + " " if title else "") + text
        return bell + ("\x1b[%d;1m%s\x1b[0m" % (col, line) if color else line)
    lines = ([title, ""] if title else []) + textwrap.wrap(text, width)
    w = max(len(ln) for ln in lines)
    if color and style == "block":
        sgr = "\x1b[%d;%d;1m" % (fg, col + 10)
        pad = sgr + " " * (w + 4) + "\x1b[0m"
        return bell + "\n".join([pad] + [sgr + "  " + align(ln, w) + "  \x1b[0m" for ln in lines] + [pad])
    rows = ["*" * (w + 4)] + ["* " + align(ln, w) + " *" for ln in lines] + ["*" * (w + 4)]
    if color:
        rows = ["\x1b[%d;1m%s\x1b[0m" % (col, r) for r in rows]
    return bell + "\n".join(rows)


class Ops:
    """The operator's commands. `live` when run inside the BBS (can reach callers)."""

    HELP = """hostbbs op COMMAND [ARGS]
  status                     who is on, uptime, locks
  who                        the callers online (with where they are)
  kick USER [reason]         disconnect a caller now
  ban USER [reason] [--ip]   ban the account (and its last address with --ip), disconnect
  unban USER|ADDRESS         lift a ban
  bans                       list bans and mutes
  force MESSAGE [--to USER]  put an important message on the screen of every caller,
                             whatever they are doing
  broadcast MESSAGE          a gentler line, shown at the caller's prompt
  say ROOM MESSAGE           speak in a chat room as the sysop
  mute USER [minutes]        stop a caller posting, chatting and mailing (default 60)
  unmute USER
  sysop add|remove|list [USER]    more sysops: full sysop tools (the main sysop stays)
  deputy add|remove|list [USER]   deputy sysops may delete posts, kick and set topics
  poll add "QUESTION" OPTION OPTION...   open a poll
  poll list | close ID | delete ID
  election start [days] | end | status | candidate USER
  lock | unlock              refuse (or allow) new logins
  sf [fortune|history|both] [N|show|reset]   switch today's fortune and/or history line for everyone
  reload                     read the config file again and apply it now
  restart                    restart the BBS (callers are told first)
  update                     get the newest hostbbs (from rBBS on GitHub) and restart with it
  schedule add HH:MM MESSAGE [--days daily|weekdays|weekends|mon,fri|MM-DD] [--mode force|broadcast|room:NAME]
  schedule list | remove ID  timed messages (also: "schedule" in the config file)"""

    def __init__(self, bbs, live):
        self.bbs, self.live = bbs, live

    def run(self, words):
        if not words or words[0] in ("help", "-h", "--help"):
            return True, self.HELP
        cmd, args = words[0].lower(), words[1:]
        fn = getattr(self, "c_" + cmd.replace("-", "_"), None)
        if fn is not None and cmd not in ("status", "who", "bans"):
            self.bbs.log("op %s" % " ".join(words)[:200])
        if fn is None:
            return False, "unknown command '%s'. Try: hostbbs op help" % cmd
        try:
            return fn(args)
        except (IndexError, ValueError):
            return False, "usage problem; see: hostbbs op help"

    @staticmethod
    def flag(args, name):
        if name in args:
            return [a for a in args if a != name], True
        return args, False

    def need_live(self):
        return None if self.live else "the BBS is not running (this command needs it)"

    # ---- information
    def c_status(self, args):
        b = self.bbs
        return True, "up %s, %d online, %d calls, %d users%s" % (
            duration(time.time() - b.started), len(b.sessions), b.meta.get("calls", 0), len(b.users),
            ", logins LOCKED" if b.bans.get("locked") else "")

    def c_who(self, args):
        if err := self.need_live():
            return False, err
        rows = ["%-16s %-22s %-16s on %s" % (s.name + ("*" if s.sysop else ""), s.where, s.ip,
                                                duration(time.time() - s.joined))
                for s in sorted(self.bbs.sessions, key=lambda s: s.joined)]
        return True, "\n".join(rows) or "nobody is online"

    # ---- discipline
    def c_kick(self, args):
        if err := self.need_live():
            return False, err
        s = self.bbs.find_session(args[0])
        if not s:
            return False, "%s is not online" % args[0]
        s.force("You have been disconnected by the sysop. " + clean_text(" ".join(args[1:])), kick=True)
        return True, "kicked %s" % s.name

    def c_ban(self, args):
        args, with_ip = self.flag(args, "--ip")
        name = args[0].lower()
        b = self.bbs
        if (b.users.get(name) or {}).get("sysop"):
            return False, "%s is a sysop; remove that first: hostbbs op sysop remove %s" % (args[0], args[0])
        reason = clean_text(" ".join(args[1:])) or "banned by the sysop"
        b.bans["names"][name] = {"reason": reason, "ts": time.time()}
        notes = ["banned " + args[0]]
        ips = set()
        user = b.users.get(name)
        if user and user.get("ip"):
            ips.add(user["ip"])
        s = b.find_session(name)
        if s:
            ips.add(s.ip)
        if with_ip:
            for ip in ips:
                b.bans["ips"][ip] = {"reason": reason, "ts": time.time()}
                notes.append("address " + ip)
        b.save("bans", b.bans)
        if s:
            s.force("You have been banned. " + reason, kick=True)
            notes.append("disconnected")
        return True, ", ".join(notes)

    def c_unban(self, args):
        b, key = self.bbs, args[0]
        gone = b.bans["names"].pop(key.lower(), None) or b.bans["ips"].pop(key, None)
        b.save("bans", b.bans)
        return (True, "unbanned " + key) if gone else (False, "no such ban: " + key)

    def c_bans(self, args):
        b, rows = self.bbs, []
        for n, v in b.bans["names"].items():
            rows.append("user    %-18s %s  %s" % (n, fdate(v["ts"]), v["reason"]))
        for ip, v in b.bans["ips"].items():
            rows.append("address %-18s %s  %s" % (ip, fdate(v["ts"]), v["reason"]))
        for n, until in b.bans["muted"].items():
            if until > time.time():
                rows.append("muted   %-18s until %s" % (n, fdate(until)))
        return True, "\n".join(rows) or "no bans or mutes"

    def c_mute(self, args):
        minutes = int(args[1]) if len(args) > 1 else 60
        self.bbs.bans["muted"][args[0].lower()] = time.time() + minutes * 60
        self.bbs.save("bans", self.bbs.bans)
        s = self.bbs.find_session(args[0])
        if s:
            s.push(s.c("bred", "[SYSOP] You are muted for %d minutes." % minutes))
        return True, "muted %s for %d minutes" % (args[0], minutes)

    def c_unmute(self, args):
        gone = self.bbs.bans["muted"].pop(args[0].lower(), None)
        self.bbs.save("bans", self.bbs.bans)
        return (True, "unmuted " + args[0]) if gone else (False, args[0] + " was not muted")

    # ---- messages
    def c_force(self, args):
        if err := self.need_live():
            return False, err
        args, _ = self.flag(args, "--ack")
        to = None
        if "--to" in args:
            i = args.index("--to")
            to = args[i + 1]
            args = args[:i] + args[i + 2:]
        text = clean_text(" ".join(args))
        if not text:
            return False, "give a message"
        targets = [self.bbs.find_session(to)] if to else list(self.bbs.sessions)
        targets = [t for t in targets if t]
        for t in targets:
            t.force(text)
        return True, "shown to %d caller%s" % (len(targets), "" if len(targets) == 1 else "s")

    def c_broadcast(self, args):
        if err := self.need_live():
            return False, err
        text = clean_text(" ".join(args))
        self.bbs.broadcast_sysop(text)
        return True, "sent"

    def c_say(self, args):
        if err := self.need_live():
            return False, err
        room = self.bbs.rooms.get(args[0].lower())
        text = clean_text(" ".join(args[1:]))
        if not room or not text:
            return False, "usage: say ROOM MESSAGE (rooms: %s)" % ", ".join(self.bbs.rooms)
        room.say("msg", self.bbs.cfg["sysop"] or "sysop", text)
        return True, "said in #" + room.name

    def c_lock(self, args):
        self.bbs.bans["locked"] = True
        self.bbs.save("bans", self.bbs.bans)
        return True, "new logins are refused"

    def c_unlock(self, args):
        self.bbs.bans["locked"] = False
        self.bbs.save("bans", self.bbs.bans)
        return True, "logins are open"

    # ---- deputies, polls, elections
    def c_sf(self, args):
        """sf [fortune|history|both] [N|reset|show]: switch today's fortune and/or history line for everyone."""
        b, rest, what = self.bbs, list(args), "both"
        if rest and rest[0].lower() in ("fortune", "history", "both"):
            what = rest.pop(0).lower()
        arg = rest[0].lower() if rest else ""
        now = time.localtime()
        today = time.strftime("%Y-%m-%d", now)
        pick = dict(b.meta.get("daily_pick") or {})
        if pick.get("date") != today:
            pick = {"date": today}
        pool = history_pool()
        cur_f, cur_h = b.daily_picks(now)
        if cur_h is None:
            own = HISTORY.get((now.tm_mon, now.tm_mday)) or FACTS[daily_seed(now) % len(FACTS)]
            cur_h = pool.index(own) if own in pool else -1

        def choose(cur, n):
            if arg.isdigit():
                return (int(arg) - 1) % n
            i = secrets.randbelow(n)
            while n > 1 and i == cur:
                i = secrets.randbelow(n)
            return i
        if arg == "reset":
            for k in (("fortune", "history") if what == "both" else (what,)):
                pick.pop(k, None)
        elif arg != "show":
            if what in ("fortune", "both"):
                pick["fortune"] = choose(cur_f, len(FORTUNES))
            if what in ("history", "both"):
                pick["history"] = choose(cur_h, len(pool))
        if arg != "show":
            b.meta["daily_pick"] = pick
            b.save("meta", b.meta)
            b.log("sf %s %s" % (what, arg))
        fortune, history = b.daily_texts(now)
        f, h = b.daily_picks(now)
        return True, "Fortune #%d of %d: %s\nHistory: %s\n(%s)" % (
            f % len(FORTUNES) + 1, len(FORTUNES), fortune, history,
            "everyone sees these today; `hostbbs op sf reset` goes back to the usual pick" if pick.get("fortune") is not None or pick.get("history") is not None
            else "the usual pick for today")

    def c_reload(self, args):
        return self.bbs.reload()

    def c_restart(self, args):
        if err := self.need_live():
            return False, err
        asyncio.ensure_future(self.bbs.restart("the operator"))
        return True, "restarting: callers are told, then the BBS starts again"

    def c_update(self, args):
        if not self.live:  # (not running: update the file here)
            if UPDATE_REQUEST:
                return False, "this BBS is updated by its system (in Kilobyte: Internet > Host a BBS > Update)"
            try:
                return True, self_update(self.bbs.cfg.get("update_url") or None)
            except (OSError, ValueError, SyntaxError, UnicodeDecodeError) as e:
                return False, "the update did not work: %s" % e
        task = asyncio.ensure_future(self.bbs.update("the operator"))
        return True, "getting the newest hostbbs; the BBS restarts by itself if there is one (see the log)"

    def c_schedule(self, args):
        b, sub = self.bbs, args[0].lower()
        if sub == "list":
            rows = ["%-4s %s %-9s %-14s %s" % (i.get("id", "cfg"), i.get("at"), i.get("days", "daily"), i.get("mode", "broadcast"), i.get("message"))
                    for i in b.schedule_items()]
            return True, "\n".join(rows) or "nothing scheduled"
        if sub == "add":
            at, rest, days, mode, words = args[1], args[2:], "daily", "broadcast", []
            i = 0
            while i < len(rest):
                if rest[i] in ("--days", "--mode") and i + 1 < len(rest):
                    if rest[i] == "--days":
                        days = rest[i + 1]
                    else:
                        mode = rest[i + 1]
                    i += 2
                else:
                    words.append(rest[i])
                    i += 1
            if not re.fullmatch(r"\d\d:\d\d", at) or not words:
                return False, "usage: schedule add HH:MM MESSAGE [--days daily|weekdays|weekends|mon,fri|MM-DD] [--mode force|broadcast|room:NAME]"
            item = {"id": "s%d" % b.sched_extra["next"], "at": at, "days": days, "mode": mode, "message": clean_text(" ".join(words))}
            b.sched_extra["next"] += 1
            b.sched_extra["items"].append(item)
            b.save("schedule", b.sched_extra)
            return True, "scheduled %s as %s" % (at, item["id"])
        if sub == "remove":
            before = len(b.sched_extra["items"])
            b.sched_extra["items"] = [i for i in b.sched_extra["items"] if i["id"] != args[1]]
            b.save("schedule", b.sched_extra)
            return (True, "removed " + args[1]) if len(b.sched_extra["items"]) < before else (False, "no such entry (config entries are edited in the config file)")
        return False, "usage: schedule add|list|remove"

    def c_sysop(self, args):
        """sysop add|remove|list [USER]: accounts with the sysop flag may use all the sysop tools."""
        b, sub = self.bbs, args[0].lower()
        primary = (b.cfg["sysop"] or "").lower()
        if sub == "list":
            names = [u["name"] + (" (main)" if u["name"].lower() == primary else "") for u in b.users.values() if u.get("sysop")]
            return True, ", ".join(names) or "no sysops"
        user = b.users.get(args[1].lower())
        if not user:
            return False, "no such user"
        if sub == "add":
            user["sysop"], user["deputy"] = True, False
        elif sub == "remove":
            if user["name"].lower() == primary:
                return False, "%s is the main sysop (the 'sysop' setting); change that in setup first" % user["name"]
            user["sysop"] = False
        else:
            return False, "usage: sysop add|remove|list [USER]"
        b.save("users", b.users)
        s_ = b.find_session(user["name"])
        if s_:
            s_.sysop = bool(user["sysop"])
            s_.push(s_.c("bgreen" if s_.sysop else "red", "You are %s a sysop." % ("now" if s_.sysop else "no longer")))
        return True, "%s is %s a sysop" % (user["name"], "now" if user["sysop"] else "no longer")

    def c_deputy(self, args):
        b, sub = self.bbs, args[0].lower()
        if sub == "list":
            names = [u["name"] for u in b.users.values() if u.get("deputy")]
            return True, ", ".join(names) or "no deputies"
        user = b.users.get(args[1].lower())
        if not user:
            return False, "no such user"
        user["deputy"] = sub == "add"
        b.save("users", b.users)
        return True, "%s is %s a deputy" % (user["name"], "now" if user["deputy"] else "no longer")

    def c_poll(self, args):
        b, sub = self.bbs, args[0].lower()
        if sub == "add":
            q, opts = clean_text(args[1], 100), [clean_text(a, 40) for a in args[2:] if a.strip()]
            if len(opts) < 2:
                return False, 'usage: poll add "QUESTION" OPTION OPTION...'
            p = b.poll_add(q, opts[:8])
            return True, "poll %d opened" % p["id"]
        if sub == "list":
            return True, "\n".join("%d %s %s (%d votes)" % (p["id"], "open  " if not p["closed"] else "closed",
                                                         p["question"], len(p["votes"]))
                                   for p in b.polls["polls"]) or "no polls"
        pid = int(args[1])
        p = next((p for p in b.polls["polls"] if p["id"] == pid), None)
        if not p:
            return False, "no such poll"
        if sub == "close":
            p["closed"] = True
        elif sub == "delete":
            b.polls["polls"].remove(p)
        else:
            return False, "usage: poll add|list|close|delete"
        b.save("polls", b.polls)
        return True, "poll %d %s" % (pid, "closed" if sub == "close" else "deleted")

    def c_election(self, args):
        b, sub = self.bbs, args[0].lower()
        if sub == "start":
            days = int(args[1]) if len(args) > 1 else b.cfg["election"]["days"]
            return b.elect_start(days)
        if sub == "end":
            return b.elect_end()
        if sub == "status":
            return True, b.elect_status()
        if sub == "candidate":
            return b.elect_nominate(args[1], by="the sysop", force=True)
        return False, "usage: election start [days] | end | status | candidate USER"


# --------------------------------------------------------------------------
# One connected caller
# --------------------------------------------------------------------------

class Quit(Exception):
    pass


IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240
NAWS = 31


class TimeUp(Exception):
    pass


class MoreGamesMixin:
    """Minesweeper and Klondike Solitaire, in the call like the other bundled games."""

    # ---- minesweeper -------------------------------------------------------------
    MINE_LEVELS = [("easy", 9, 9, 10), ("medium", 16, 12, 30), ("hard", 30, 16, 99)]

    async def game_minesweeper(self):
        if not await self.game_start():
            return
        lv, msg = 0, ""
        try:
            while True:
                name, W, H, N = self.MINE_LEVELS[lv]
                mines, shown, flags = None, set(), set()
                cx, cy, t0, state = W // 2, H // 2, None, "play"

                def around(x, y):
                    return [(x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                            if (dx or dy) and 0 <= x + dx < W and 0 <= y + dy < H]

                def count(x, y):
                    return sum(1 for p in around(x, y) if p in mines)

                def reveal(x, y):
                    todo = [(x, y)]
                    while todo:
                        p = todo.pop()
                        if p in shown or p in flags:
                            continue
                        shown.add(p)
                        if count(*p) == 0:
                            todo += [q for q in around(*p) if q not in shown]
                while True:
                    secs = int(time.time() - t0) if t0 else 0
                    colors = {1: "94;1", 2: "32;1", 3: "91;1", 4: "35;1", 5: "33", 6: "36", 7: "37", 8: "90"}
                    rows = []
                    for y in range(H):
                        line = ""
                        for x in range(W):
                            if (x, y) in shown:
                                n = count(x, y)
                                cell = self.sgr(colors[n], str(n)) if n else " "
                            elif state == "lost" and mines and (x, y) in mines:
                                cell = self.sgr("91;1", "*")
                            elif (x, y) in flags:
                                cell = self.sgr("93;1", "F")
                            else:
                                cell = self.sgr("90", "#")
                            if (x, y) == (cx, cy):
                                cell = "\x1b[7m[" + cell + "\x1b[7m]\x1b[0m"
                            else:
                                cell = " " + cell + " "
                            line += cell
                        rows.append("  " + line)
                    left = N - len(flags)
                    status = msg or ("arrows/hjkl move  Space or Enter opens  f flags  c opens around a number  n new  Esc quits")
                    await self.draw("\n  %s  %s  mines left %d   time %d:%02d\n\n%s\n\n  %s" % (
                        self.sgr("96;1", "MINESWEEPER"), name, left, secs // 60, secs % 60, "\n".join(rows), status))
                    msg = ""
                    if state != "play":
                        break
                    k = await self.key(1.0 if t0 else None)
                    if k is None:
                        continue
                    if k in ("ESC", "q"):
                        return
                    if k in ("UP", "k", "w"):
                        cy = max(0, cy - 1)
                    elif k in ("DOWN", "j", "s"):
                        cy = min(H - 1, cy + 1)
                    elif k in ("LEFT", "h", "a"):
                        cx = max(0, cx - 1)
                    elif k in ("RIGHT", "l", "d"):
                        cx = min(W - 1, cx + 1)
                    elif k == "n":
                        lv = (lv + 1) % 3
                        state = "again"
                        break
                    elif k == "f" and (cx, cy) not in shown:
                        flags.symmetric_difference_update({(cx, cy)})
                    elif k in (" ", "\r", "o", "c"):
                        if mines is None:                       # the first click is never a mine
                            safe = {(cx, cy), *around(cx, cy)}
                            pool = [(x, y) for x in range(W) for y in range(H) if (x, y) not in safe]
                            secrets.SystemRandom().shuffle(pool)
                            mines, t0 = set(pool[:N]), time.time()
                        if k == "c" and (cx, cy) in shown:
                            nb = around(cx, cy)
                            if sum(1 for p in nb if p in flags) == count(cx, cy):
                                for p in nb:
                                    if p not in flags and p not in shown:
                                        if p in mines:
                                            state = "lost"
                                        else:
                                            reveal(*p)
                        elif (cx, cy) not in flags and (cx, cy) not in shown:
                            if (cx, cy) in mines:
                                state = "lost"
                            else:
                                reveal(cx, cy)
                        if state == "play" and len(shown) == W * H - N:
                            state = "won"
                    if state == "won":
                        flags = set(mines)
                if state == "again":
                    continue
                secs = int(time.time() - t0) if t0 else 0
                if state == "won":
                    self.game_over("minesweeper-" + name, won=True, score=secs)
                    msg = self.sgr("92;1", "Cleared in %d:%02d!" % (secs // 60, secs % 60))
                else:
                    self.game_over("minesweeper-" + name, won=False, score=0)
                    msg = self.sgr("91;1", "BOOM!")
                await self.send("\n  %s " % msg)
                if not await self.yes_key("Another?"):
                    return
                if state == "won" and lv < 2:
                    lv += 1
        finally:
            await self.game_end()

    # ---- solitaire (Klondike, draw one) ------------------------------------------------
    @staticmethod
    def card_name(c):
        return {1: "A", 11: "J", 12: "Q", 13: "K"}.get(c[0], str(c[0])) + "SHDC"[c[1]]

    def card_color(self, c, text):
        return self.sgr("91;1" if c[1] in (1, 2) else "97;1", text)

    async def game_solitaire(self):
        if not await self.game_start():
            return
        sel, msg, undo = None, "", []

        def deal():
            deck = [(r, s) for r in range(1, 14) for s in range(4)]
            secrets.SystemRandom().shuffle(deck)
            tab = []
            for i in range(7):
                col = [[deck.pop(), False] for _ in range(i + 1)]
                col[-1][1] = True
                tab.append(col)
            return {"stock": deck, "waste": [], "found": [[], [], [], []], "tab": tab, "moves": 0}
        g = deal()

        def snap():
            undo.append(copy.deepcopy(g))
            del undo[:-100]

        def can_tab(card, col):
            if not col:
                return card[0] == 13
            top = col[-1][0]
            return top[0] == card[0] + 1 and (top[1] in (1, 2)) != (card[1] in (1, 2))

        def can_found(card):
            pile = g["found"][card[1]]
            return card[0] == len(pile) + 1

        def flip(col):
            if col and not col[-1][1]:
                col[-1][1] = True

        def auto():
            n = 0
            moved = True
            while moved:
                moved = False
                if g["waste"] and can_found(g["waste"][-1]):
                    c = g["waste"].pop()
                    g["found"][c[1]].append(c)
                    moved = True
                    n += 1
                for col in g["tab"]:
                    if col and col[-1][1] and can_found(col[-1][0]):
                        c = col.pop()[0]
                        g["found"][c[1]].append(c)
                        flip(col)
                        moved = True
                        n += 1
            return n
        try:
            while True:
                lines = []
                stock = self.sgr("34;1", "[##]") + "%-3d" % len(g["stock"]) if g["stock"] else "[  ]   "
                waste = self.card_color(g["waste"][-1], "[%-3s]" % self.card_name(g["waste"][-1])) if g["waste"] else "[   ]"
                found = "".join((self.card_color(p[-1], "[%-3s]" % self.card_name(p[-1])) if p else self.sgr("90", "[ " + "SHDC"[i] + " ]")) + " "
                                for i, p in enumerate(g["found"]))
                lines.append("  stock %s   waste %s        foundations %s" % (stock, waste, found))
                lines.append("")
                lines.append("   " + "".join("  %s   " % (self.sgr("93;1", str(i + 1)) if sel != i else self.sgr("7", str(i + 1))) for i in range(7)))
                depth = max(len(c) for c in g["tab"])
                for r in range(max(depth, 1)):
                    row = "  "
                    for col in g["tab"]:
                        if r < len(col):
                            card, up = col[r]
                            row += " " + (self.card_color(card, "[%-3s]" % self.card_name(card)) if up else self.sgr("34", "[###]")) + " "
                        else:
                            row += "       "
                    lines.append(row)
                won = all(len(p) == 13 for p in g["found"])
                if won:
                    status = self.sgr("92;1", "You won in %d moves!" % g["moves"])
                else:
                    status = msg or ("source then destination: w or 1-7, then 1-7 or f.  d deals, a auto, u undo, n new, Esc quits"
                                     if sel is None else "from %s: now the destination (1-7 or f), or the same key to cancel" % (sel if sel == "w" else sel + 1))
                await self.draw("\n  %s   moves %d\n\n%s\n\n  %s" % (self.sgr("96;1", "SOLITAIRE"), g["moves"], "\n".join(lines), status))
                msg = ""
                if won:
                    self.game_over("solitaire", won=True, score=g["moves"])
                    if not await self.yes_key("\n  Play again?"):
                        return
                    g.clear()
                    g.update(deal())
                    undo.clear()
                    continue
                k = await self.key()
                if k in ("ESC", "q"):
                    return
                if k == "n":
                    g.clear()
                    g.update(deal())
                    undo.clear()
                    sel = None
                elif k == "u" and undo:
                    g.clear()
                    g.update(undo.pop())
                    sel = None
                elif k == "a":
                    snap()
                    n = auto()
                    g["moves"] += n
                    msg = "%d card%s to the foundations." % (n, "" if n == 1 else "s")
                elif k == "d":
                    snap()
                    sel = None
                    if g["stock"]:
                        g["waste"].append(g["stock"].pop())
                    elif g["waste"]:
                        g["stock"] = g["waste"][::-1]
                        g["waste"] = []
                    g["moves"] += 1
                elif sel is None:
                    if k == "w" and g["waste"]:
                        sel = "w"
                    elif k.isdigit() and 1 <= int(k) <= 7 and g["tab"][int(k) - 1]:
                        sel = int(k) - 1
                else:
                    src = sel
                    sel = None
                    if (k == "w" and src == "w") or (k.isdigit() and src != "w" and int(k) - 1 == src):
                        continue
                    dest = "f" if k in ("f", "\r", " ") else int(k) - 1 if k.isdigit() and 1 <= int(k) <= 7 else None
                    if dest is None:
                        continue
                    snap()
                    ok = False
                    if src == "w":
                        card = g["waste"][-1]
                        if dest == "f" and can_found(card):
                            g["found"][card[1]].append(g["waste"].pop())
                            ok = True
                        elif dest != "f" and can_tab(card, [x for x in g["tab"][dest]]):
                            g["tab"][dest].append([g["waste"].pop(), True])
                            ok = True
                    else:
                        col = g["tab"][src]
                        first = next(i for i, c in enumerate(col) if c[1])
                        if dest == "f":
                            if can_found(col[-1][0]):
                                c = col.pop()[0]
                                g["found"][c[1]].append(c)
                                flip(col)
                                ok = True
                        else:
                            for i in range(first, len(col)):            # the longest run that fits
                                if can_tab(col[i][0], g["tab"][dest]):
                                    g["tab"][dest].extend(col[i:])
                                    del col[i:]
                                    flip(col)
                                    ok = True
                                    break
                    if ok:
                        g["moves"] += 1
                    else:
                        undo.pop()
                        msg = self.sgr("91", "That move is not allowed.")
        finally:
            await self.game_end()


class QuizMixin:
    async def trivia_menu(self):
        while True:
            self.where = "Trivia"
            bbs = self.bbs
            await self.header("Trivia & quiz")
            key, w, q, opts, right = bbs.trivia_week()
            done = self.name.lower() in w["ans"]
            await self.send("  %s This week's question%s\n" % (self.c("byellow", "[W]"), self.c("gray", "  (answered)" if done else "")))
            await self.send("  %s Play a quiz: 10 questions, 15 seconds each\n" % self.c("byellow", "[Q]"))
            await self.send("  %s Leaderboard\n" % self.c("byellow", "[L]"))
            k = (await self.readline("\n> ")).strip().lower()[:1]
            if not k:
                return
            if k == "w":
                await self.trivia_week_screen()
            elif k == "q":
                await self.game_quiz()
            elif k == "l":
                await self.trivia_board()

    async def trivia_week_screen(self):
        bbs = self.bbs
        key, w, q, opts, right = bbs.trivia_week()
        await self.header("Trivia of the week (%s)" % key)
        await self.send("  %s\n\n" % self.c("bwhite", q))
        for i, o in enumerate(opts):
            await self.send("   %s %s\n" % (self.c("byellow", str(i + 1)), o))
        low = self.name.lower()
        if self.guest:
            await self.send(self.c("gray", "\n  Register an account to answer and collect points.\n"))
        elif low in w["ans"]:
            mine = w["ans"][low]
            await self.send("\n  You answered %s: %s\n" % (opts[mine], self.c("bgreen", "correct!") if mine == right else self.c("red", "not quite. It was " + opts[right])))
        else:
            ans = (await self.readline("\nYour answer (1-4, Enter = later): ")).strip()
            if ans.isdigit() and 1 <= int(ans) <= len(opts):
                ok = bbs.trivia_answer(self.name, int(ans) - 1)
                await self.send("\n  " + (self.c("bgreen", "Correct! +10 points.") if ok else self.c("red", "Not quite. It was: " + opts[right])) + "\n")
                if ok:
                    self.award("scholar")
        n = len(w["ans"])
        if n:
            good = sum(1 for c in w["ans"].values() if c == right)
            await self.send(self.c("gray", "  %d caller%s answered, %d%% got it right.\n" % (n, "" if n == 1 else "s", round(100 * good / n))))
        prev = week_key(-1)
        if prev in bbs.meta["trivia"]["weeks"] and prev != key:
            pq, popts, pright = tr_present(bbs.trivia_bank()[bbs.meta["trivia"]["weeks"][prev]["q"]], seed=prev)
            await self.send(self.c("gray", "\n  Last week: %s  ->  %s\n" % (pq, popts[pright])))
        await self.readline(self.c("gray", "\n[Enter to continue]"))

    async def trivia_board(self):
        await self.header("Trivia leaderboard")
        rows = sorted(self.bbs.meta["trivia"]["scores"].values(), key=lambda s: (-s["points"], s["name"].lower()))[:10]
        for i, s in enumerate(rows, 1):
            await self.send(" %2d. %-16s %4d points   %d of %d right\n" % (i, s["name"], s["points"], s["correct"], s["answered"]))
        if not rows:
            await self.send("  (nobody has answered yet)\n")
        await self.readline(self.c("gray", "\n[Enter to continue]"))

    async def game_quiz(self):
        if not await self.game_start():
            return
        try:
            bank = self.bbs.trivia_bank()
            picks = secrets.SystemRandom().sample(range(len(bank)), min(10, len(bank)))
            score = right_n = 0
            for n, idx in enumerate(picks, 1):
                q, opts, right = tr_present(bank[idx])
                end = time.monotonic() + 15
                chosen = None
                while chosen is None:
                    left = max(0, int(end - time.monotonic() + 0.99))
                    body = "\n".join("   %s %s" % (self.sgr("93;1", str(i + 1)), o) for i, o in enumerate(opts))
                    await self.draw("\n  %s   question %d of 10   score %d\n\n  %s\n\n%s\n\n  %s" % (
                        self.sgr("96;1", "QUIZ"), n, score, self.sgr("97;1", q), body,
                        self.sgr("91;1" if left <= 5 else "92", "%2d seconds left" % left) + "   (1-4 answers, Esc quits)"))
                    if left <= 0:
                        chosen = -1
                        break
                    k = await self.key(1.0)
                    if k == "ESC":
                        return
                    if k and k in "1234":
                        chosen = int(k) - 1
                if chosen == right:
                    score += 100 + 5 * max(0, int(end - time.monotonic()))
                    right_n += 1
                    verdict = self.sgr("92;1", "Right!")
                else:
                    verdict = self.sgr("91;1", "It was: " + opts[right])
                await self.send("\n  %s " % verdict)
                await asyncio.sleep(1.2)
            await self.draw("\n\n  %s\n\n  %d of 10 right. Score: %d\n" % (self.sgr("96;1", "QUIZ DONE"), right_n, score))
            self.game_over("quiz", won=right_n >= 8, score=score)
            await self.send("\n")
            await self.yes_key("  Press a key")
        finally:
            await self.game_end()

    # ---- statistics and caller of the month
    async def stats_screen(self):
        bbs = self.bbs
        await self.header("Statistics")
        days = sorted(bbs.meta["daily"].items())[-14:]
        top = max([n for _, n in days] + [1])
        await self.send(self.c("byellow", "  Calls per day (last %d days with calls)\n" % len(days)))
        for d, n in days:
            await self.send("   %s %s %d\n" % (d[5:], self.c("bgreen", ("#" * round(n * 40 / top)).ljust(40)), n))
        if not days:
            await self.send("   (no calls recorded yet)\n")
        hours = bbs.meta["hours"]
        top = max(hours + [1])
        await self.send(self.c("byellow", "\n  Busiest hours (all calls)\n   "))
        bars = " .:-=+*#%@"
        await self.send("".join(bars[min(9, round(h * 9 / top))] for h in hours) + "\n")
        await self.send("   " + "".join("%-3d" % h if h % 3 == 0 else "" for h in range(24))[:72] + "\n")
        posters = {}
        for msgs in bbs.boards.values():
            for m in msgs:
                posters[m["author"]] = posters.get(m["author"], 0) + 1
        await self.send(self.c("byellow", "\n  Top posters\n"))
        for name, n in sorted(posters.items(), key=lambda kv: -kv[1])[:5]:
            await self.send("   %-16s %d post%s\n" % (name, n, "" if n == 1 else "s"))
        if not posters:
            await self.send("   (no posts yet)\n")
        await self.send("\n  %d calls in all, %d users, %d messages, up %s.\n" % (
            bbs.meta.get("calls", 0), len(bbs.users), sum(len(v) for v in bbs.boards.values()),
            duration(time.time() - bbs.started)))
        await self.readline(self.c("gray", "\n[Enter to continue]"))

    async def cotm_screen(self):
        bbs = self.bbs
        await self.header("Caller of the month")
        month = bbs.month_key()
        await self.send(self.c("gray", "  Points: call 3, post 5, mail 2, trivia 4, vote 1, game 1, 5 chat lines 1\n\n"))
        rows = bbs.month_scores(month)[:10]
        for i, (pts, name, m) in enumerate(rows, 1):
            await self.send(" %2d. %-16s %5d pts   %d calls, %d posts, %d chat lines\n" % (
                i, name, pts, m.get("calls", 0), m.get("posts", 0), m.get("chats", 0)))
        if not rows:
            await self.send("  (nobody has scored yet this month)\n")
        prev, win = bbs.cotm_settle()
        if win:
            await self.send("\n  %s %s: %s with %d points.\n" % (self.c("byellow", "Caller of last month,"), prev, self.c("bwhite", win["name"]), win["points"]))
        await self.readline(self.c("gray", "\n[Enter to continue]"))

    async def stats_menu(self):
        self.where = "Statistics"
        await self.stats_screen()
        if (await self.readline("[C]aller of the month, or Enter to go back: ")).strip().lower().startswith("c"):
            await self.cotm_screen()


class SocialMixin:
    """Oneliners, profiles, and the threaded message boards."""

    # ---- oneliner wall ---------------------------------------------------------------
    def oneliners(self):
        return self.bbs.meta.setdefault("oneliners", [])

    async def show_oneliners(self, n=5):
        rows = self.oneliners()[-n:]
        if not rows:
            return
        await self.send(self.c("byellow", "  Oneliners\n"))
        for r in rows:
            await self.send("   %s %s\n" % (self.c(self.bbs.who_color(r["name"]), "%-12s" % r["name"][:12]), self.tidy(r["text"])))

    async def oneliner_wall(self):
        self.where = "Oneliner wall"
        bbs = self.bbs
        while True:
            await self.header("Oneliner wall")
            rows = self.oneliners()[-15:]
            for r in rows:
                await self.send(" %s  %s %s\n" % (self.c("gray", time.strftime("%m-%d %H:%M", time.localtime(r["ts"]))),
                                                  self.c(bbs.who_color(r["name"]), "%-14s" % r["name"]), self.tidy(r["text"])))
            if not rows:
                await self.send("  (the wall is empty - be the first)\n")
            if self.guest:
                await self.readline(self.c("gray", "\n  Register an account to write on the wall. [Enter]"))
                return
            text = (await self.readline("\nSay something, 70 characters (Enter = back): ", maxlen=70)).strip()
            if not text:
                return
            if bbs.is_muted(self.name):
                await self.send(self.c("red", "You are muted.\n"))
                continue
            self.oneliners().append({"name": self.name, "ts": time.time(), "text": text})
            del self.oneliners()[:-100]
            bbs.save("meta", bbs.meta)
            self.award("oneliner")

    # ---- profiles --------------------------------------------------------------------------
    def calling_card(self, u):
        """A framed card for one user, as lines of text."""
        p = u.get("profile", {})
        w = 50
        name = u["name"] + (" (sysop)" if u.get("sysop") else " (deputy)" if u.get("deputy") else "")
        online = self.bbs.find_session(u["name"])
        since = time.strftime("%Y-%m-%d", time.localtime(u["created"]))
        ach = len(u.get("ach", {}))
        row = lambda t="", color=None: self.c("cyan", "║") + " " + (self.c(color, t.ljust(w - 4)) if color else t.ljust(w - 4)) + " " + self.c("cyan", "║")
        lines = [self.c("cyan", "╔" + "═" * (w - 2) + "╗"),
                 row(name + ("   [online]" if online else ""), self.bbs.who_color(u["name"])),
                 row("member since " + since + "   last on " + time.strftime("%Y-%m-%d", time.localtime(u["last"])), "gray"),
                 row("-" * (w - 4), "gray"),
                 row("Computer: " + (p.get("computer") or "(not set)")[:34]),
                 row("From:     " + (p.get("location") or "(not set)")[:34]),
                 row("Calls %d   Streak %d (best %d)   Achievements %d/%d" % (
                     u.get("calls", 0), u.get("streak", 0), u.get("best_streak", 0), ach, len(ACHIEVEMENTS))),
                 row("-" * (w - 4), "gray")]
        for ln in (p.get("bio") or ["(no bio yet)"])[:4]:
            lines.append(row(self.tidy(ln)[: w - 4], "byellow"))
        lines.append(self.c("cyan", "╚" + "═" * (w - 2) + "╝"))
        return lines

    async def profiles(self):
        self.where = "Profiles"
        bbs = self.bbs
        while True:
            await self.header("Profiles")
            who = (await self.readline("Handle to look up  (Enter = back%s): " % ("; E edits yours" if not self.guest else ""))).strip()
            if not who:
                return
            if who.lower() == "e" and not self.guest:
                await self.edit_profile()
                who = self.name
            u = bbs.users.get(who.lower())
            if u and not self.sees(u["name"], bbs.age_of(u["name"])):
                u = None
            if not u:
                await self.send(self.c("red", "No such user.\n"))
                continue
            for ln in self.calling_card(u):
                await self.send("  " + ln + "\n")

    async def edit_profile(self):
        u = self.user_rec()
        p = u.setdefault("profile", {})
        await self.send(self.c("gray", "Enter keeps what is there.\n"))
        for key, label, n in (("computer", "Your computer", 34), ("location", "Where you are", 34)):
            v = (await self.readline("%s [%s]: " % (label, p.get(key, "")), maxlen=n)).strip()
            if v:
                p[key] = v
        await self.send("Bio: up to 4 lines of 46 characters; an empty line ends (a single - clears it).\n")
        bio = []
        while len(bio) < 4:
            ln = (await self.readline("| ", maxlen=46)).strip()
            if not ln:
                break
            if ln == "-":
                bio = []
                p["bio"] = []
                break
            bio.append(ln)
        if bio:
            p["bio"] = bio
        self.bbs.save("users", self.bbs.users)
        self.award("profile")
        await self.send(self.c("bgreen", "Saved.\n"))

    # ---- threaded boards -----------------------------------------------------------------------
    def board_seen(self, b):
        u = self.user_rec()
        return (u or {}).get("seen", {}).get(b["name"], 0)

    def mark_seen(self, b, mid):
        u = self.user_rec()
        if u is not None:
            seen = u.setdefault("seen", {})
            if mid > seen.get(b["name"], 0):
                seen[b["name"]] = mid

    def thread_order(self, msgs):
        """[(depth, msg)] with every reply under the message it answers."""
        by_parent = {}
        ids = {m["id"] for m in msgs}
        for m in msgs:
            parent = m.get("reply") if m.get("reply") in ids else None
            by_parent.setdefault(parent, []).append(m)
        out = []

        def walk(parent, depth):
            for m in by_parent.get(parent, []):
                out.append((depth, m))
                walk(m["id"], min(depth + 1, 4))
        walk(None, 0)
        return out

    def my_boards(self):
        return [b for b in self.cfg["board_list"] if self.fits(b.get("ages", "all"))]

    def my_rooms(self):
        """The rooms this caller may see: by age, and a page room only its caller's."""
        mine = "page-" + re.sub(r"[^a-z0-9]", "", self.name.lower())
        return {n: r for n, r in self.bbs.rooms.items()
                if self.fits(r.ages) and (not n.startswith("page-") or self.sysop or n == mine)}

    async def boards(self):
        self.where = "Message boards"
        bl = self.my_boards()
        while True:
            await self.header("Message boards")
            for i, b in enumerate(bl, 1):
                msgs = self.bbs.boards.get(b["name"], [])
                new = sum(1 for m in msgs if m["id"] > self.board_seen(b) and m["author"] != self.name) if not self.guest else 0
                await self.send(" %s %-18s %3d msgs  %s%s\n" % (
                    self.c("byellow", "%2d" % i), b["name"], len(msgs), self.c("gray", b.get("desc", "")),
                    self.c("bgreen", "  (%d new)" % new) if new else ""))
            k = (await self.readline("\nBoard # (Enter = back): ")).strip()
            if not k:
                return
            if k.isdigit() and 1 <= int(k) <= len(bl):
                await self.board(bl[int(k) - 1])

    async def show_message(self, b, msgs, msg):
        parent = next((m for m in msgs if m["id"] == msg.get("reply")), None)
        kids = [m for m in msgs if m.get("reply") == msg["id"]]
        head = "\n%s\nFrom: %s   Date: %s" % (self.c("bwhite", self.tidy(msg["subject"])), msg["author"], fdate(msg["ts"]))
        if parent:
            head += "\nIn reply to #%d by %s" % (parent["id"], parent["author"])
        await self.send(head + "\n\n" + "\n".join(textwrap.fill(self.tidy(ln), 76) if ln else "" for ln in msg["body"]) + "\n")
        if kids:
            await self.send(self.c("gray", "\nReplies: " + ", ".join("#%d %s" % (m["id"], m["author"]) for m in kids) + "\n"))
        self.mark_seen(b, msg["id"])

    async def board(self, b):
        bbs = self.bbs
        msgs = bbs.boards.setdefault(b["name"], [])
        await self.show_art("boards", b["name"], b["name"], b.get("desc", ""))
        while True:
            seen = self.board_seen(b)
            fresh = [m for m in msgs if m["id"] > seen and m["author"] != self.name] if not self.guest else []
            await self.header("%s - %s%s" % (b["name"], b.get("desc", ""), ("   (%d new)" % len(fresh)) if fresh else ""))
            if not msgs:
                await self.send("  (no messages yet)\n")
            ordered = self.thread_order(msgs[-40:])
            for depth, m in ordered:
                mark = self.c("bgreen", "*") if m in fresh else " "
                indent = "  " * depth + ("└ " if depth else "")
                subj = (indent + self.tidy(m["subject"]))[:40]
                await self.send(" %s%s %s  %-14s %s\n" % (mark, self.c("byellow", "%4d" % m["id"]), fdate(m["ts"])[:10], m["author"][:14], subj))
            cmds = "[R]ead #  " + ("[A]nswer #  [P]ost  " if self.may("post") else "") + ("[N]ew (%d)  " % len(fresh) if fresh else "") + ("[D]elete #  " if self.mod else "") + "[Q]uit"
            parts = (await self.readline("\n%s\n> " % cmds)).strip().split()
            if not parts:
                continue
            cmd, arg = parts[0].lower(), (parts[1] if len(parts) > 1 else "")
            if cmd.isdigit():
                cmd, arg = "r", cmd
            if cmd == "q":
                return
            if cmd in ("r", "d", "a") and not arg:
                arg = (await self.readline("Message #: ")).strip()
            msg = next((m for m in msgs if str(m["id"]) == arg), None)
            if cmd == "n":
                for m in fresh:
                    await self.show_message(b, msgs, m)
                    if (await self.readline(self.c("gray", "\n[Enter = next, Q = stop]"))).strip().lower().startswith("q"):
                        break
                bbs.save("users", bbs.users)
            elif cmd == "r":
                if not msg:
                    await self.send(self.c("red", "No such message.\n"))
                    continue
                await self.show_message(b, msgs, msg)
                bbs.save("users", bbs.users)
                await self.readline(self.c("gray", "\n[Enter to continue]"))
            elif cmd in ("p", "a"):
                if self.guest:
                    await self.send(self.c("red", "Guests can't post. Register an account!\n"))
                    continue
                if not self.may("post"):
                    continue
                if bbs.is_muted(self.name):
                    await self.send(self.c("red", "You are muted.\n"))
                    continue
                if cmd == "a" and not msg:
                    await self.send(self.c("red", "No such message.\n"))
                    continue
                if cmd == "a":
                    subject = msg["subject"] if msg["subject"].lower().startswith("re:") else ("Re: " + msg["subject"])[:60]
                    await self.send(self.c("gray", "Answering #%d. Your reply will quote the start of it.\n" % msg["id"]))
                else:
                    subject = (await self.readline("Subject: ", maxlen=60)).strip()
                body = await self.read_body() if subject else None
                if body:
                    if cmd == "a":
                        quote = ["> " + ln for ln in msg["body"][:3] if ln.strip()]
                        body = ["%s wrote:" % msg["author"]] + quote + [""] + body
                    new = {"id": (msgs[-1]["id"] + 1) if msgs else 1, "ts": time.time(), "author": self.name,
                           "subject": subject, "body": body}
                    if cmd == "a":
                        new["reply"] = msg["id"]
                    msgs.append(new)
                    bbs.log("%s posted on %s: %s" % (self.name, b["name"], subject))
                    self.mark_seen(b, new["id"])
                    bbs.save("boards", bbs.boards)
                    bbs.save("users", bbs.users)
                    await self.send(self.c("bgreen", "Posted.\n"))
                    self.award("poster")
                    bbs.track(self.name, "posts")
                    if cmd == "a" and msg["author"].lower() != self.name.lower():
                        other = bbs.find_session(msg["author"])
                        if other:
                            other.push(other.c("bgreen", "[%s] %s answered your message #%d" % (b["name"], self.name, msg["id"])))
            elif cmd == "d" and self.mod and msg:
                msgs.remove(msg)
                bbs.log("%s deleted message %s on %s" % (self.name, msg["id"], b["name"]))
                bbs.save("boards", bbs.boards)
                await self.send("Deleted.\n")


class RetroMixin:
    """Modem speed, ANSI music, event screens, and paging the sysop."""

    SPEEDS = [("300", 300), ("1200", 1200), ("2400", 2400), ("9600", 9600), ("14400", 14400), ("full speed", 0)]

    async def modem_connect(self):
        """Pick a connect speed (if asked) and act out the handshake."""
        modem = self.cfg.get("modem") or {}
        self.baud = int(modem.get("baud") or 0)
        if modem.get("ask"):
            opts = "  ".join("%d=%s" % (i + 1, n) for i, (n, _) in enumerate(self.SPEEDS))
            pick = (await self.readline("Connect speed?  %s  [Enter = %s] " % (opts, self.baud or "full speed"))).strip()
            if pick.isdigit() and 1 <= int(pick) <= len(self.SPEEDS):
                self.baud = self.SPEEDS[int(pick) - 1][1]
        if self.baud and modem.get("handshake", True):
            await self.send("ATDT %s\n" % (self.cfg.get("phone") or "555-0199"), fast=True)
            await asyncio.sleep(0.7)
            await self.send("RINGING\n", fast=True)
            await asyncio.sleep(0.9)
            await self.send("CONNECT %d/ARQ/V42BIS\n\n" % self.baud, fast=True)
            await asyncio.sleep(0.4)

    def music_seq(self, which):
        m = (self.cfg.get("music") or {}).get(which)
        return ("\x1b[MB" + m.replace(" ", "") + "\x0e") if (self.music and m) else ""

    async def music_ask(self):
        music = self.cfg.get("music") or {}
        if not music.get("enabled"):
            return
        self.music = True
        if music.get("ask", True):
            self.music = await self.ask_yn("ANSI music (a few terminals play it, others show junk)?", False)

    def art_event(self):
        """Today's event screen: art_dir/events/MM-DD[_MM-DD][_name].ans (the range may wrap the year)."""
        base = self.cfg.get("art_dir")
        if not base:
            return None
        d = os.path.join(base, "events")
        now = (time.localtime().tm_mon, time.localtime().tm_mday)
        try:
            names = sorted(os.listdir(d))
        except OSError:
            return None
        for f in names:
            m = re.match(r"^(\d\d)-(\d\d)(?:_(\d\d)-(\d\d))?(?:_.*)?\.(ans|txt|asc)$", f)
            if not m:
                continue
            a = (int(m.group(1)), int(m.group(2)))
            b = (int(m.group(3)), int(m.group(4))) if m.group(3) else a
            hit = a <= now <= b if a <= b else (now >= a or now <= b)
            if hit:
                return os.path.join(d, f)
        b = self.cfg.get("birthday")
        if b and b == time.strftime("%m-%d"):
            for f in names:
                if f.lower().startswith("birthday"):
                    return os.path.join(d, f)
        return None

    # ---- paging the sysop ----------------------------------------------------------------
    async def page_sysop(self):
        bbs = self.bbs
        hours = self.cfg.get("sysop_hours") or ""
        sysop = next((s for s in bbs.sessions if s.sysop), None)
        await self.header("Page the sysop")
        if hours and not bbs.in_sysop_hours():
            await self.send("  The sysop answers pages from %s. Leave a message instead.\n" % hours)
            sysop = None
        elif not sysop:
            await self.send("  The sysop is not online right now.\n")
        elif time.time() - getattr(self, "last_page", 0) < 120:
            await self.send("  You paged a moment ago. Give the sysop a minute.\n")
            return
        if not sysop:
            if not self.guest and self.feat["mail"] and await self.ask_yn("  Send the sysop a mail?", True):
                await self.send_mail(to=self.cfg["sysop"])
            return
        self.last_page = time.time()
        room_name = "page-" + re.sub(r"[^a-z0-9]", "", self.name.lower())
        room = bbs.rooms.get(room_name)
        if room is None:
            room = bbs.rooms[room_name] = Room({"name": room_name, "topic": "Private chat with the sysop"}, self.cfg["history"])
        sysop.push(sysop.c("bred", "\a** %s is paging you! Join the chat: /join %s **" % (self.name, room_name)))
        bbs.log("page from %s" % self.name)
        await self.send("  Paging the sysop... you are in #%s now. Leave with /quit.\n" % room_name)
        self.where = "Paging the sysop"
        r = room
        while r:
            r = await self.chat_room(r)


class ConfigMixin:
    """Sysops change the BBS's settings from inside the BBS: saved to the config file, applied at once."""

    async def cfg_pick(self, label, options, current):
        await self.send("\n  %s\n" % self.c("bwhite", label))
        for i, (v, lb) in enumerate(options, 1):
            await self.send("   %s %s%s\n" % (self.c("byellow", "%2d" % i), lb, self.c("bgreen", "   <- now") if v == current else ""))
        a = (await self.readline("Number (Enter = keep): ")).strip()
        if a.isdigit() and 1 <= int(a) <= len(options):
            return options[int(a) - 1][0]
        return current

    async def cfg_edit(self, target, spec):
        key, label, kind, extra = spec
        cur = target.get(key)
        if kind == "bool":
            target[key] = not cur
        elif kind == "pick":
            target[key] = await self.cfg_pick(label, extra, cur)
        elif kind == "palette":
            v = await self.cfg_pick(label, [(n, n) for n in PALETTES] + [("*", "Your own list of colors")], cur if isinstance(cur, str) else None)
            if v == "*":
                v = (await self.readline("Colors, comma-separated (%s): " % ", ".join(ANSI), maxlen=200)).strip() or cur
            target[key] = v if v is not None else cur
        elif kind == "int":
            v = (await self.readline("%s [%s]: " % (label, cur), maxlen=9)).strip()
            if v.isdigit():
                target[key] = int(v)
            elif v:
                await self.send(self.c("red", "That is not a number.\n"))
        else:
            shown = " | ".join(cur) if kind == "motd" else cur
            v = await self.readline("%s%s [%s] ('-' clears): " % (label, " (lines separated by |)" if kind == "motd" else "", shown), maxlen=300)
            if v.strip() == "-":
                target[key] = [] if kind == "motd" else ""
            elif v.strip():
                target[key] = [p.strip() for p in v.split("|") if p.strip()] if kind == "motd" else v.strip()

    async def cfg_form(self, title, target, specs, extra_rows=()):
        while True:
            await self.header(title)
            for i, (k, lb, kind, extra) in enumerate(specs, 1):
                await self.send(" %s %-36s %s\n" % (self.c("byellow", "%2d" % i), lb, self.c("bcyan", UI.show(None, target.get(k), kind, extra))))
            a = (await self.readline("\nNumber to change (Enter = back): ")).strip()
            if not a:
                return
            if a.isdigit() and 1 <= int(a) <= len(specs):
                await self.cfg_edit(target, specs[int(a) - 1])

    async def cfg_features(self, raw):
        while True:
            await self.header("Features")
            for i, (k, lb) in enumerate(FEATURES, 1):
                await self.send(" %s [%s] %s\n" % (self.c("byellow", "%2d" % i), self.c("bgreen", "x") if raw["features"].get(k) else " ", lb))
            a = (await self.readline("\nNumber to switch on or off (Enter = back): ")).strip()
            if not a:
                return
            if a.isdigit() and 1 <= int(a) <= len(FEATURES):
                k = FEATURES[int(a) - 1][0]
                raw["features"][k] = not raw["features"].get(k)

    async def cfg_list(self, title, items, specs, describe, blank):
        while True:
            await self.header(title)
            for i, it in enumerate(items, 1):
                await self.send(" %s %s\n" % (self.c("byellow", "%2d" % i), describe(it)))
            a = (await self.readline("\nNumber to edit, + to add, - then number to delete (Enter = back): ")).strip()
            if not a:
                return
            if a == "+":
                items.append(dict(blank))
                await self.cfg_form(title + ": new", items[-1], specs)
            elif a.startswith("-") and a[1:].strip().isdigit() and 1 <= int(a[1:]) <= len(items):
                del items[int(a[1:]) - 1]
            elif a.isdigit() and 1 <= int(a) <= len(items):
                await self.cfg_form(title, items[int(a) - 1], specs)
            for it in items:
                if "name" in it and title == "Chat rooms":
                    it["name"] = re.sub(r"[^a-z0-9_-]", "", it["name"].lower()) or "room"

    async def sysop_manage(self):
        """Add or remove sysops from inside the BBS."""
        while True:
            await self.header("Sysops")
            ok, who = Ops(self.bbs, True).run(["sysop", "list"])
            await self.send("  Now: %s\n" % who)
            cmd = (await self.readline("\n[A]dd a sysop  [R]emove one  [Q]uit\n> ")).strip().lower()[:1]
            if cmd in ("a", "r"):
                name = (await self.readline("Handle: ")).strip()
                if name and await self.ask_yn("%s %s as a sysop?" % ("Make" if cmd == "a" else "Remove", name), cmd == "a"):
                    ok, out = Ops(self.bbs, True).run(["sysop", "add" if cmd == "a" else "remove", name])
                    await self.send(self.c("bgreen" if ok else "red", out + "\n"))
            else:
                return

    async def sysop_config(self):
        bbs = self.bbs
        path = getattr(bbs, "config_path", None)
        if not path:
            await self.send(self.c("red", "This BBS was not started from a config file, so settings can't be saved.\n"))
            return
        raw = load_file(path)
        raw["rooms"] = norm_items(raw["rooms"], "topic")
        raw["board_list"] = norm_items(raw["board_list"], "desc")
        snap = lambda: json.dumps(raw, sort_keys=True)
        start = snap()
        limits = [("idle_timeout", "Idle timeout (seconds)", "int", None), ("minutes", "Minutes per call (0 = any)", "int", None),
                  ("max_users", "Most callers at once", "int", None), ("history", "Chat history lines", "int", None)]
        sections = [
            ("1", "Identity", lambda: self.cfg_form("Identity", raw, SPEC_IDENT)),
            ("2", "ASCII art", lambda: self.cfg_form("ASCII art", raw["art"], SPEC_ART)),
            ("3", "Colors", lambda: self.cfg_form("Colors", raw, [("color", "Color mode", "pick", PICK_COLORMODE)])),
            ("4", "Features", lambda: self.cfg_features(raw)),
            ("5", "Chat rooms", lambda: self.cfg_list("Chat rooms", raw["rooms"], SPEC_ROOM,
                                                      lambda r: "#%-12s %s%s" % (r["name"], r.get("topic", ""), "  [locked]" if r.get("password") else ""),
                                                      {"name": "newroom", "topic": "", "password": "", "guests": True})),
            ("6", "Message boards", lambda: self.cfg_list("Message boards", raw["board_list"], SPEC_BOARD,
                                                          lambda b: "%-16s %s" % (b["name"], b.get("desc", "")), {"name": "New board", "desc": ""})),
            ("7", "Forced messages", lambda: self.cfg_form("Forced messages", raw["force"], SPEC_FORCE)),
            ("8", "Modem", lambda: self.cfg_form("Modem", raw["modem"], SPEC_MODEM)),
            ("9", "ANSI music", lambda: self.cfg_form("ANSI music", raw["music"], SPEC_MUSIC)),
            ("A", "Voting & elections", lambda: self.cfg_form("Voting & elections", raw["election"], SPEC_ELECT)),
            ("B", "Events & hours", lambda: self.cfg_form("Events & hours", raw, SPEC_EVENTS)),
            ("C", "Timed messages", lambda: self.cfg_list("Timed messages", raw["schedule"], SPEC_SCHED,
                                                          lambda i: "%s %-9s %-9s %s" % (i.get("at", ""), i.get("days", "daily"), i.get("mode", ""), str(i.get("message", ""))[:36]),
                                                          {"at": "22:00", "days": "daily", "mode": "broadcast", "message": ""})),
            ("D", "Limits", lambda: self.cfg_form("Limits", raw, limits)),
            ("F", "News channels", lambda: self.cfg_list("News channels", raw["news_channels"], SPEC_FEED,
                                                         lambda i: "%-16s %s" % (i.get("name", ""), i.get("url", "")[:46]),
                                                         {"name": "New channel", "url": "https://"})),
            ("G", "News settings", lambda: self.cfg_form("News settings", raw["news"], SPEC_NEWS)),
            ("H", "Pastebin settings", lambda: self.cfg_form("Pastebin settings", raw["paste"], SPEC_PASTE)),
            ("E", "Art rotation", lambda: self.cfg_form("Art rotation", raw, [("art_dir", "Art folder", "str", None), ("art_rotation", "Rotation", "pick", PICK_ROT)])),
            ("K", "Kids mode", lambda: self.cfg_form("Kids mode", raw["kids"], SPEC_KIDS)),
            ("L", "Kids mode: ages for each feature", lambda: self.cfg_form("Ages", raw["kids"]["min_age"], SPEC_AGES)),
        ]
        while True:
            self.where = "Configuring"
            await self.header("Settings" + ("  (unsaved changes)" if snap() != start else ""))
            for k, label, _ in sections:
                await self.send("  [%s] %s\n" % (self.c("byellow", k), label))
            await self.send("  [%s] Save and apply    [%s] Quit\n" % (self.c("byellow", "S"), self.c("byellow", "Q")))
            await self.send(self.c("gray", "  (address, port, data folder and the web terminal are set in the setup dialog on the server)\n"))
            k = (await self.readline("\nsettings> ")).strip().upper()[:1]
            sec = next((s for s in sections if s[0] == k), None)
            if sec:
                await sec[2]()
            elif k == "S":
                path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
                start = snap()
                ok, msg = bbs.reload()
                bbs.log("settings saved by %s: %s" % (self.name, msg))
                await self.send(self.c("bgreen" if ok else "red", msg + ".\n"))
            elif k == "Q" or not k:
                if snap() != start and await self.ask_yn("Quit without saving?", False) is False:
                    continue
                return


# --------------------------------------------------------------------------
# News reader (RSS and Atom) and pastebin
# --------------------------------------------------------------------------

class NewsError(Exception):
    pass


def feed_url_ok(url, allow_private=False):
    """Only http(s) addresses of hosts on the public internet (callers may add their own feeds)."""
    u = urllib.parse.urlsplit(url.strip())
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        raise NewsError("only plain http:// or https:// addresses")
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        raise NewsError("cannot find that host")
    for info in infos:
        if not allow_private and not ipaddress.ip_address(info[4][0].split("%")[0]).is_global:
            raise NewsError("that address is not on the public internet")
    return u.geturl()


class _CheckedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, allow_private):
        self.allow_private = allow_private

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        feed_url_ok(newurl, self.allow_private)      # every hop is checked, not just the first
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _plain(html_text, width=76):
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html_text or "", flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>|</li>|</div>", "\n", text, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    text = "".join(ch for ch in text if printable(ch) or ch == "\n")
    return [ln for para in re.split(r"\n\s*\n|\n", text.strip()) if para.strip() for ln in textwrap.wrap(para.strip(), width)][:40]


def _when(text):
    if not text:
        return 0
    text = text.strip()
    try:
        import email.utils
        return email.utils.parsedate_to_datetime(text).timestamp()
    except (TypeError, ValueError, IndexError):
        pass
    try:
        return datetime.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0


def parse_feed(data):
    """(feed title, [ {title, link, ts, text} ]) from RSS 2.0, RSS 1.0 (RDF) or Atom."""
    if b"<!ENTITY" in data:
        raise NewsError("that feed uses features I will not parse")
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise NewsError("that does not look like an RSS or Atom feed")
    kind = _local(root.tag)
    if kind == "rss":
        chan = next((c for c in root if _local(c.tag) == "channel"), root)
        nodes = [i for i in chan if _local(i.tag) == "item"]
    elif kind == "RDF":
        chan = next((c for c in root if _local(c.tag) == "channel"), root)
        nodes = [i for i in root if _local(i.tag) == "item"]
    elif kind == "feed":
        chan, nodes = root, [e for e in root if _local(e.tag) == "entry"]
    else:
        raise NewsError("that does not look like an RSS or Atom feed")
    def child(node, *names):
        for c in node:
            if _local(c.tag) in names:
                return c
    title_el = child(chan, "title")
    items = []
    for n in nodes[:60]:
        link = ""
        for c in n:
            if _local(c.tag) == "link":
                link = c.get("href") or (c.text or "").strip()
                if link and c.get("rel", "alternate") == "alternate":
                    break
        body = child(n, "encoded", "content", "description", "summary")
        items.append({"title": " ".join(((child(n, "title").text if child(n, "title") is not None else "") or "(no title)").split())[:200],
                      "link": link[:500],
                      "ts": _when((child(n, "pubDate", "date", "updated", "published").text) if child(n, "pubDate", "date", "updated", "published") is not None else ""),
                      "text": _plain(body.text if body is not None else "")})
    return " ".join((title_el.text or "").split())[:80] if title_el is not None else "", items


def fetch_feed(url, allow_private=False, limit=1_000_000):
    """Download and parse a feed. Blocking: run it with offload()."""
    feed_url_ok(url, allow_private)
    opener = urllib.request.build_opener(_CheckedRedirect(allow_private))
    req = urllib.request.Request(url, headers={"User-Agent": "rBBS-news/1.0 (+https://github.com/jgm240/rbbs)",
                                               "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"})
    try:
        with opener.open(req, timeout=8) as r:
            data = r.read(limit + 1)
    except NewsError:
        raise
    except (OSError, ValueError) as e:
        raise NewsError("could not download it (%s)" % (getattr(e, "reason", None) or e))
    if len(data) > limit:
        raise NewsError("that feed is too big")
    return parse_feed(data)


class PasteMixin:
    """The pastebin: share text by a short code; listed for everyone, or unlisted."""
    ALPHA = "abcdefghjkmnpqrstuvwxyz23456789"
    EXPIRY = [("never", None), ("1 hour", 3600), ("1 day", 86400), ("1 week", 7 * 86400)]

    def paste_items(self):
        items = self.bbs.pastes["items"]
        now = time.time()
        items[:] = [p for p in items if not p.get("expires") or p["expires"] > now]
        del items[:-500]
        return items

    async def pastebin(self):
        self.where = "Pastebin"
        bbs = self.bbs
        while True:
            await self.header("Pastebin")
            shown = [p for p in reversed(self.paste_items()) if p["listed"]][:10]
            for i, p in enumerate(shown, 1):
                await self.send(" %s %s  %-14s %s\n" % (self.c("byellow", "%2d" % i), self.c("bcyan", p["id"]), p["author"][:14], p["title"][:44]))
            if not shown:
                await self.send("  (nothing listed yet)\n")
            cmds = "[N]ew paste  [V]iew by code  [M]y pastes  [Q]uit   or a number to open"
            a = (await self.readline("\n%s\n> " % cmds)).strip()
            low = a.lower()
            if not a or low == "q":
                return
            if a.isdigit() and 1 <= int(a) <= len(shown):
                await self.paste_view(shown[int(a) - 1])
            elif low == "n":
                await self.paste_new()
            elif low == "v":
                code = (await self.readline("Code: ")).strip().lower()
                p = next((p for p in self.paste_items() if p["id"] == code), None)
                await (self.paste_view(p) if p else self.send(self.c("red", "No paste with that code (it may have expired).\n")))
            elif low == "m":
                await self.paste_mine()

    async def paste_new(self):
        bbs, lim = self.bbs, self.cfg.get("paste") or {}
        if self.guest:
            await self.send(self.c("red", "Guests can read pastes but not write them. Register an account!\n"))
            return
        if bbs.is_muted(self.name):
            await self.send(self.c("red", "You are muted.\n"))
            return
        mine = [p for p in self.paste_items() if p["author"].lower() == self.name.lower()]
        if len(mine) >= int(lim.get("per_user", 50)):
            await self.send(self.c("red", "You have %d pastes already; delete some first.\n" % len(mine)))
            return
        title = (await self.readline("Title: ", maxlen=60)).strip()
        if not title:
            return
        await self.send(self.c("gray", "Paste the text now.\n"))
        body = await self.read_body(int(lim.get("max_lines", 300)))
        if not body:
            return
        await self.send("Expires: " + "  ".join("%d=%s" % (i + 1, n) for i, (n, _) in enumerate(self.EXPIRY)) + "\n")
        ex = (await self.readline("Choice [1]: ")).strip()
        secs = self.EXPIRY[int(ex) - 1][1] if ex.isdigit() and 1 <= int(ex) <= len(self.EXPIRY) else None
        listed = await self.ask_yn("List it on the pastebin? (No = only people with the code can open it)", True)
        used = {p["id"] for p in bbs.pastes["items"]}
        code = "".join(secrets.choice(self.ALPHA) for _ in range(6))
        while code in used:
            code = "".join(secrets.choice(self.ALPHA) for _ in range(6))
        bbs.pastes["items"].append({"id": code, "author": self.name, "ts": time.time(), "title": title, "body": body,
                                    "listed": listed, "expires": time.time() + secs if secs else None, "views": 0})
        bbs.save("pastes", bbs.pastes)
        self.award("paste")
        await self.send(self.c("bgreen", "Saved. Its code is: ") + self.c("bwhite", code) + "\n")

    async def paste_view(self, p):
        p["views"] = p.get("views", 0) + 1
        await self.header(p["title"])
        await self.send(self.c("gray", " %s by %s, %s%s, %d view%s   code %s\n\n" % (
            "listed" if p["listed"] else "unlisted", p["author"], fdate(p["ts"]),
            ", expires " + fdate(p["expires"]) if p.get("expires") else "", p["views"], "" if p["views"] == 1 else "s", p["id"])))
        page = max(8, self.rows - 6)
        w = max(30, self.cols - 8)
        n = 0
        for i, ln in enumerate(p["body"], 1):
            for part in (textwrap.wrap(self.tidy(ln), w) or [""]):
                await self.send(" %s %s\n" % (self.c("gray", "%3d" % i), part))
                n += 1
                if n % page == 0 and (await self.readline(self.c("gray", "-- more (Enter, Q stops) --"))).strip().lower().startswith("q"):
                    self.bbs.save("pastes", self.bbs.pastes)
                    return
        self.bbs.save("pastes", self.bbs.pastes)
        if p["author"].lower() == self.name.lower() or self.mod:
            if (await self.readline(self.c("gray", "\n[D]elete this paste, or Enter: "))).strip().lower() == "d" and await self.ask_yn("Really delete?", False):
                self.bbs.pastes["items"].remove(p)
                self.bbs.save("pastes", self.bbs.pastes)
                await self.send("Deleted.\n")
        else:
            await self.readline(self.c("gray", "\n[Enter to continue]"))

    async def paste_mine(self):
        mine = [p for p in self.paste_items() if p["author"].lower() == self.name.lower()]
        if not mine:
            await self.send("  You have no pastes.\n")
            return
        for i, p in enumerate(mine, 1):
            await self.send(" %s %s %-8s %s\n" % (self.c("byellow", "%2d" % i), self.c("bcyan", p["id"]), "listed" if p["listed"] else "unlisted", p["title"][:44]))
        a = (await self.readline("Number to open (Enter = back): ")).strip()
        if a.isdigit() and 1 <= int(a) <= len(mine):
            await self.paste_view(mine[int(a) - 1])


class NewsMixin:
    """RSS/Atom channels: the sysop's, and each caller's own."""

    def news_channels(self):
        out = [dict(c, mine=False) for c in self.cfg.get("news_channels") or []]
        u = self.user_rec()
        if u:
            out += [dict(c, mine=True) for c in u.get("feeds", [])]
        return out

    async def news_load(self, ch):
        news = self.cfg.get("news") or {}
        cache = self.bbs.__dict__.setdefault("news_cache", {})
        hit = cache.get(ch["url"])
        if hit and time.time() - hit[0] < 60 * int(news.get("cache_minutes", 15)):
            return hit[1], hit[2]
        title, items = await offload(fetch_feed, ch["url"], bool(news.get("allow_private")) and not ch["mine"])
        cache[ch["url"]] = (time.time(), title, items)
        return title, items

    async def news_menu(self):
        self.where = "News"
        news = self.cfg.get("news") or {}
        while True:
            chans = self.news_channels()
            await self.header("News")
            for i, c in enumerate(chans, 1):
                await self.send(" %s %-22s %s\n" % (self.c("byellow", "%2d" % i), c["name"][:22], self.c("gray", "(yours)" if c["mine"] else "")))
            if not chans:
                await self.send("  (no channels yet)\n")
            can = news.get("custom", True) and not self.guest
            a = (await self.readline("\nChannel # to read%s (Enter = back): " % ("   [A]dd your own  [D]elete one" if can else ""))).strip()
            low = a.lower()
            if not a or low == "q":
                return
            if a.isdigit() and 1 <= int(a) <= len(chans):
                await self.news_channel(chans[int(a) - 1])
            elif low == "a" and can:
                await self.news_add()
            elif low == "d" and can:
                await self.news_delete()

    async def news_add(self):
        u = self.user_rec()
        feeds = u.setdefault("feeds", [])
        news = self.cfg.get("news") or {}
        if len(feeds) >= int(news.get("per_user", 8)):
            await self.send(self.c("red", "You have %d feeds already; delete one first.\n" % len(feeds)))
            return
        url = (await self.readline("Feed address (RSS or Atom, https://...): ", maxlen=300)).strip()
        if not url:
            return
        if "://" not in url:
            url = "https://" + url
        await self.send(self.c("gray", "Checking it...\n"))
        try:
            title, items = await offload(fetch_feed, url, False)
        except NewsError as e:
            await self.send(self.c("red", "Not added: %s.\n" % e))
            return
        name = (await self.readline("Name for it [%s]: " % (title or "my feed"), maxlen=22)).strip() or title or "my feed"
        feeds.append({"name": name[:22], "url": url})
        self.bbs.save("users", self.bbs.users)
        await self.send(self.c("bgreen", "Added %s (%d items).\n" % (name, len(items))))

    async def news_delete(self):
        feeds = (self.user_rec() or {}).get("feeds", [])
        if not feeds:
            await self.send("  You have no feeds of your own.\n")
            return
        for i, c in enumerate(feeds, 1):
            await self.send(" %s %s\n" % (self.c("byellow", "%2d" % i), c["name"]))
        a = (await self.readline("Delete which? (Enter = none): ")).strip()
        if a.isdigit() and 1 <= int(a) <= len(feeds):
            gone = feeds.pop(int(a) - 1)
            self.bbs.save("users", self.bbs.users)
            await self.send("Deleted %s.\n" % gone["name"])

    async def news_channel(self, ch):
        await self.send(self.c("gray", "\nFetching %s...\n" % ch["name"]))
        try:
            title, items = await self.news_load(ch)
        except NewsError as e:
            await self.send(self.c("red", "Could not read it: %s.\n" % e))
            return
        self.award("newsy")
        per = max(5, self.rows - 9)
        page, u = 0, self.user_rec()
        seen_key = ch["url"]
        last_seen = (u or {}).get("news_seen", {}).get(seen_key, 0)
        newest = max([i["ts"] for i in items] + [0])
        while True:
            await self.header("%s%s" % (ch["name"], (" - " + title) if title and title != ch["name"] else ""))
            chunk = items[page * per:(page + 1) * per]
            for i, it in enumerate(chunk, page * per + 1):
                fresh = self.c("bgreen", "*") if it["ts"] > last_seen else " "
                when = time.strftime("%m-%d %H:%M", time.localtime(it["ts"])) if it["ts"] else "     ?    "
                await self.send(" %s%s %s  %s\n" % (fresh, self.c("byellow", "%2d" % i), self.c("gray", when), it["title"][:max(20, self.cols - 24)]))
            if not items:
                await self.send("  (the feed is empty)\n")
            more = len(items) > (page + 1) * per
            a = (await self.readline("\n# to read%s%s  [Q]uit\n> " % ("  [N]ext page" if more else "", "  [P]revious" if page else ""))).strip().lower()
            if not a or a == "q":
                break
            if a == "n" and more:
                page += 1
            elif a == "p" and page:
                page -= 1
            elif a.isdigit() and 1 <= int(a) <= len(items):
                await self.news_read(items[int(a) - 1])
        if u is not None and newest:
            u.setdefault("news_seen", {})[seen_key] = newest
            self.bbs.save("users", self.bbs.users)

    async def news_read(self, it):
        await self.header(it["title"][:70])
        if it["ts"]:
            await self.send(self.c("gray", " %s\n" % fdate(it["ts"])))
        await self.send("\n" + "\n".join(" " + ln for ln in it["text"]) + ("\n" if it["text"] else self.c("gray", " (no summary in the feed)\n")))
        if it["link"]:
            await self.send("\n " + self.c("cyan", it["link"]) + "\n")
        await self.readline(self.c("gray", "\n[Enter to continue]"))


class Session(ExtrasMixin, SocialMixin, QuizMixin, RetroMixin, ConfigMixin, PasteMixin, NewsMixin, MoreGamesMixin, GamesMixin):
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
        self.deputy = False
        self.baud, self.music = 0, False
        self.ip = (getattr(writer, "get_extra_info", lambda *_: None)("peername") or ("?",))[0]
        self.toasts, self.alert = [], None
        self.ignored, self.afk, self.after_chat, self.seen_rooms = set(), "", None, {}
        self.logged_in = False
        self.age = None  # (Kids mode: how old the caller is)
        self.telnet = False
        self._where = self._logged = "Logging in"
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
                # (Private mail and pages to the sysop stay out of the log, and leave no gap in it.)
                if place not in ("Reading mail", "Paging the sysop") and not place.startswith("Chat #page-") \
                        and place != self._logged:
                    self._logged = place
                    self.bbs.log("%s went into %s" % (self.name, place))

    # ---- output ----------------------------------------------------------
    def c(self, color, text):
        return paint(text, color, self.color)

    # ---- kids mode -------------------------------------------------------
    def kids(self):
        return bool(self.cfg["kids"]["enabled"])

    def may(self, what):
        """Old enough for this feature (Kids mode; the sysops always are)?"""
        if not self.kids() or self.sysop:
            return True
        return (self.age if self.age is not None else ADULT) >= self.cfg["kids"]["min_age"].get(what, 0)

    def fits(self, ages):
        return not self.kids() or self.sysop or age_fits(self.age, ages)

    def tidy(self, text):
        """Text others wrote, with rude words hidden from younger callers."""
        if not self.kids() or self.sysop or (self.age if self.age is not None else ADULT) >= self.cfg["kids"]["filter_under"]:
            return text
        return self.bbs.rude_re().sub(lambda m: m.group(0)[0] + "*" * (len(m.group(0)) - 1), text)

    def sees(self, name, age):
        """Kids under 13 are not shown to other adults: only to their family, other young
        callers and the sysops."""
        if not self.kids() or self.sysop or age is None or age >= KID:
            return True
        if self.age is not None and self.age < ADULT:
            return True
        return self.bbs.family(self.name, name)

    async def ask_age(self):
        for _ in range(3):
            a = (await self.readline("How old are you? ")).strip()
            if a.isdigit() and 3 <= int(a) <= 120:
                return int(a)
            await self.send(self.c("red", "Please type your age as a number.\n"))
        raise Quit

    async def too_young(self, age):
        need = self.cfg["kids"]["join_age"]
        if age is not None and age < need:
            await self.send(self.c("byellow", "Sorry, %s is for callers aged %d and up. Ask a grown-up "
                                              "about a board for you!\n" % (self.cfg["name"], need)))
            return True
        return False

    def _encode(self, text):
        return text.encode("cp437", "replace") if self.cp437 else text.encode("utf-8")

    def _write(self, text):
        self.w.write(self._encode(text.replace("\r\n", "\n").replace("\n", "\r\n")))

    async def send(self, text, fast=False):
        """Write text; at a set modem speed, a few characters every 50 ms (fast=True skips that)."""
        try:
            if self.baud and not fast and len(text) > 8:
                data = self._encode(text.replace("\r\n", "\n").replace("\n", "\r\n"))
                step = max(1, self.baud // 200)
                for i in range(0, len(data), step):
                    self.w.write(data[i:i + step])
                    await self.w.drain()
                    await asyncio.sleep(0.05)
            else:
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
            await self.modem_connect()
            await self.music_ask()
            if self.music:
                await self.send(self.music_seq("connect"), fast=True)
            art = self.art_choose(self.art_files("connect"), "connect")
            if art:
                await self.text_file(art)
            else:
                await self.send(make_banner(self.cfg, self.color))
            if self.cfg.get("hosted"):
                await self.send(self.c("gray", "  Hosted on Kilobyte, the text-mode desktop: %s\n" % KILOBYTE))
            for line in self.cfg["motd"]:
                await self.send("  " + self.c("byellow", line) + "\n")
            event = self.art_event()
            if event:
                await self.text_file(event)
            await self.text_file(self.cfg.get("greeting"))
            await self.send("\n  Caller #%d. Press Ctrl-C to disconnect any time.\n"
                            % (bbs.meta.get("calls", 0) + 1))
            if self.cfg.get("log", True):
                await self.send(self.c("gray", "  What you do in public here is logged (private mail "
                                               "and private messages are not).\n"))
            await self.login()
            self.timeout = self.cfg["idle_timeout"]
            self.logged_in = True
            bbs.sessions.add(self)
            bbs.write_online()
            bbs.meta["calls"] = bbs.meta.get("calls", 0) + 1
            bbs.count_call()
            bbs.save("meta", bbs.meta)
            bbs.log("login %s from %s%s" % (self.name, self.ip, " (guest)" if self.guest else ""))
            if not self.guest:
                bbs.track(self.name, "calls")
                bbs.cotm_settle()
                if any(v and v["name"].lower() == self.name.lower() for v in bbs.meta["cotm"].values()):
                    self.award("cotm")
            if self.feat.get("daily", True):
                await self.today(brief=True)
            if self.feat.get("oneliners", True):
                await self.show_oneliners()
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
            if self.logged_in:
                bbs.log("logout %s after %s" % (self.name, duration(time.time() - self.joined)))
                try:
                    bbs.save("users", bbs.users)
                except OSError:
                    pass
            if self.logged_in and self.feat.get("lastcallers", True):
                try:
                    bbs.record_caller(self.name, self.joined)
                except OSError:
                    pass
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
                if bbs.bans.get("locked"):
                    await self.send(self.c("red", "Logins are closed right now.\n"))
                    continue
                if self.kids():
                    self.age = await self.ask_age()
                    if await self.too_young(self.age):
                        raise Quit
                self.name, self.guest = bbs.guest_name(), True
                await self.send("Welcome, %s. Guests are read-only for boards and mail.\n" % self.name)
                return
            reason = bbs.is_banned(name=low, ip=self.ip)
            if reason:
                await self.send(self.c("red", "You are banned: %s\n" % reason))
                raise Quit
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
            is_sysop = bool(user.get("sysop"))
            if bbs.bans.get("locked") and not is_sysop:
                await self.send(self.c("red", "Logins are closed right now.\n"))
                raise Quit
            self.name = user["name"]
            self.sysop = is_sysop
            self.deputy = bool(user.get("deputy")) and not is_sysop
            if self.kids() and not self.sysop:
                if user.get("born") is None:  # (made before Kids mode: asked once)
                    user["born"] = time.localtime().tm_year - await self.ask_age()
                    bbs.save("users", bbs.users)
                self.age = bbs.age_of(self.name)
                if await self.too_young(self.age):
                    raise Quit
            self.ignored = set(user.get("ignore", []))
            if user["calls"]:
                await self.send("\nWelcome back, %s. Last call: %s. Calls: %d.\n"
                                % (self.name, fdate(user["last"]), user["calls"]))
            else:
                await self.send("\nWelcome to %s, %s!\n" % (self.cfg["name"], self.name))
            user["last"], user["calls"], user["ip"] = time.time(), user["calls"] + 1, self.ip
            bbs.save("users", bbs.users)
            self.award("hello")
            if user["calls"] >= 10:
                self.award("regular")
            if user["calls"] >= 50:
                self.award("veteran")
            if time.localtime().tm_hour < 5:
                self.award("night")
            if self.feat.get("daily", True):
                self.update_streak()
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
        age = None
        if self.kids():
            age = await self.ask_age()
            if await self.too_young(age):
                raise Quit
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
            if age is not None:
                user["born"] = time.localtime().tm_year - age
                self.bbs.save("users", self.bbs.users)
            return user
        return None

    # ---- main menu ---------------------------------------------------------
    async def menu(self):
        bbs, f = self.bbs, self.feat
        actions = {
            "B": ("Message boards", f["boards"] and self.may("boards") and bool(self.my_boards()), self.boards),
            "M": ("Private mail", f["mail"] and not self.guest and (self.may("mail") or self.has_family()), self.mailbox),
            "C": ("Chat rooms", f["chat"] and self.may("chat") and bool(self.my_rooms()), self.chat),
            "F": ("Files", f.get("files") and self.may("files") and bool(self.areas()), self.files),
            "D": ("Games", f.get("games") and self.may("games") and bool(self.games()), self.games_menu),
            "A": ("Apps", f.get("apps") and self.may("apps") and bool(self.apps()), self.apps_menu),
            "P": ("Multiplayer games", f.get("multiplayer", True) and self.may("multiplayer"), self.multiplayer),
            "E": ("Family", self.kids() and self.cfg["kids"].get("parents") and not self.guest
                  and (self.has_family() or (self.age if self.age is not None else ADULT) >= ADULT), self.family_menu),
            "V": ("Voting booth", f.get("polls", True) or f.get("elections") or bool(bbs.elect["current"]),
                  self.voting_booth),
            "Y": ("Today", f.get("daily", True), self.today),
            "X": ("Page the sysop", f.get("page", True) and f.get("chat") and bool(bbs.rooms), self.page_sysop),
            "K": ("Pastebin", f.get("pastebin", True) and self.may("pastebin"), self.pastebin),
            "N": ("News", f.get("news", True) and self.may("news"), self.news_menu),
            "O": ("Oneliner wall", f.get("oneliners", True) and self.may("oneliners"), self.oneliner_wall),
            "R": ("Profiles", f.get("profiles", True) and self.may("profiles"), self.profiles),
            "Q": ("Trivia & quiz", f.get("trivia", True), self.trivia_menu),
            "J": ("Statistics", f.get("stats", True), self.stats_menu),
            "L": ("Last callers", f.get("lastcallers", True), self.last_callers),
            "H": ("Hall of achievements", f.get("achievements", True) and not self.guest, self.hall),
            "W": ("Who's online", True, self.who),
            "U": ("User list", True, self.userlist),
            "I": ("System info", True, self.info),
            "T": ("Toggle color", self.cfg["color"] is not False, self.toggle_color),
            "S": ("Sysop tools" if self.sysop else "Deputy tools", self.mod, self.sysop_tools),
            "G": ("Goodbye", True, None),
        }
        while True:
            self.where = "Main menu"
            await self.flush_toasts()
            actions["S"] = ("Sysop tools" if self.sysop else "Deputy tools", self.mod, self.sysop_tools)
            await self.header(self.cfg["name"] + " - main menu")
            rows = []
            for k, (label, on, _) in actions.items():
                if on:
                    extra = ""
                    if k == "M" and not self.guest and bbs.unread(self.name):
                        extra = self.c("bgreen", "  (%d new)" % bbs.unread(self.name))
                    rows.append("[%s] %s%s" % (self.c("byellow", k), label, extra))
            if len(rows) > 11 and self.cols >= 64:      # two columns, so it fits a 24-row screen
                half = (len(rows) + 1) // 2
                for i in range(half):
                    left = rows[i]
                    right = rows[i + half] if i + half < len(rows) else ""
                    pad = " " * max(2, 36 - len(strip_ansi(left)))
                    await self.send("  " + left + (pad + right if right else "") + "\n")
            else:
                for r in rows:
                    await self.send("  " + r + "\n")
            line = (await self.readline("\n%s> " % self.c("bwhite", self.name))).strip()
            if self.sysop and line.lower().split()[:1] == ["op"]:  # op restart, op update, op help...
                await self.op_line(line[2:].strip())
                continue
            key = line.upper()[:1]
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
            if not self.color:
                data = re.sub(rb"\x1b\[[0-9;?]*[ -/]*[@-~]", b"", data)
            text = data.decode("cp437") if not self.cp437 else None
            if text is None:  # CP437 callers get the bytes as they are
                self.w.write(data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n") + (b"\x1b[0m" if self.color else b"") + b"\r\n")
                await self.w.drain()
                return
            await self.send(text + ("\x1b[0m" if self.color else "") + "\n")
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
                if self.stories() and shutil.which("frotz"):
                    out.append(g)
            else:
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
            await self.send(" %s %s\n" % (self.c("byellow", " H"), "High scores"))
            k = (await self.readline("\nGame # (Enter = back): ")).strip()
            if not k:
                return
            if k.lower() == "h":
                await self.high_scores()
                continue
            if not k.isdigit() or not 1 <= int(k) <= len(games):
                continue
            g = games[int(k) - 1]
            self.where = "Playing " + GAMES[g][0]
            if g == "stories":
                await self.play_story()
            else:
                await getattr(self, "game_" + g)()

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
        await self.door([shutil.which("frotz") or "frotz", "-R", saves, os.path.join(self.cfg["stories_dir"], st[int(k) - 1])], cwd=saves)

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
            text = await offload(fetch)
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
        await self.send(self.c("gray", "Type a sum such as 2*(3+4) or sqrt(2)**3; Enter alone ends.\n"))
        while True:
            expr = (await self.readline("calc> ", maxlen=120)).strip()
            if not expr or expr.lower() in ("q", "quit", "exit"):
                return
            try:
                await self.send("= %s\n" % calc_eval(expr))
            except (ValueError, SyntaxError, ZeroDivisionError, OverflowError, TypeError):
                await self.send(self.c("red", "That is not a sum I can do.\n"))

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
                    flag, i, m["from"], fdate(m["ts"])[:10], self.tidy(m["subject"])[:34]))
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
                    self.c("bwhite", self.tidy(m["subject"])), m["from"], fdate(m["ts"]),
                    "\n".join(textwrap.fill(self.tidy(ln), 76) if ln else "" for ln in m["body"])))
                await self.readline(self.c("gray", "\n[Enter to continue]"))
            elif cmd == "d":
                box.pop(idx)
                bbs.save("mail", bbs.mail)
            elif cmd == "s":
                await self.send_mail()

    async def send_mail(self, to=None):
        bbs = self.bbs
        if bbs.is_muted(self.name):
            await self.send(self.c("red", "You are muted.\n"))
            return
        to = to or (await self.readline("To: ")).strip()
        rec = bbs.users.get(to.lower())
        if not rec:
            await self.send(self.c("red", "No such user.\n"))
            return
        # (Why not is not told: nobody learns someone else's age.)
        if not bbs.may_contact(self.name, self.age, rec["name"], bbs.age_of(rec["name"]), "mail"):
            await self.send(self.c("red", "You can't send mail to %s.\n" % rec["name"]))
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
            online.push(online.c("bgreen", "[mail] New message from %s: %s" % (self.name, online.tidy(subject))))
        await self.send(self.c("bgreen", "Sent.\n"))
        self.award("writer")
        bbs.track(self.name, "mails")

    # ---- chat ------------------------------------------------------------------
    def fmt_chat(self, e):
        if e["kind"] in ("msg", "emo") and e["who"] != self.name and self.logged_in and \
                re.search(r"\b%s\b" % re.escape(self.name), e["text"], re.I):
            e = dict(e, text=self.c("byellow", e["text"]) + "\a")   # (someone said our name)
        stamp = self.c("gray", time.strftime("%H:%M", time.localtime(e["ts"])))
        who = self.c(self.bbs.who_color(e["who"]), e["who"])
        if e["kind"] == "sys":
            return "%s %s" % (stamp, self.c("gray", "* " + e["text"]))
        if e["kind"] == "emo":
            return "%s %s %s %s" % (stamp, self.c("magenta", "*"), who, self.tidy(e["text"]))
        if e["kind"] == "pm":
            return "%s %s %s: %s" % (stamp, self.c("bmagenta", "[pm]"), who, self.tidy(e["text"]))
        return "%s <%s> %s" % (stamp, who, self.tidy(e["text"]))

    def room_list(self):
        out = []
        for r in self.my_rooms().values():
            lock = " (locked)" if r.password else ""
            guest = " (members only)" if not r.guests and self.guest else ""
            unread = r.count - self.seen_rooms.get(r.name, r.count)
            news = self.c("bgreen", "  (%d new)" % unread) if unread > 0 and self not in r.members else ""
            out.append("  %s %-12s %d here  %s%s%s%s" % (
                self.c("byellow", "#"), r.name, len(r.members), self.c("gray", r.topic), lock, guest, news))
        return "\n".join(out)

    async def chat(self):
        self.where = "Chat"
        rooms = self.my_rooms()
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
            if self.after_chat:
                table, self.after_chat = self.after_chat, None
                await self.mp_play(table)

    async def enter_ok(self, room, given_pw=""):
        if room is None or room.name not in self.my_rooms():
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
        await self.show_art("rooms", room.name, room.name, room.topic)
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
                await self.flush_toasts()
                if not line:
                    continue
                if self.afk and not line.lower().startswith("/afk"):
                    self.afk = ""
                    room.say("sys", self.name, "%s is back" % self.name)
                if not line.startswith("/"):
                    if self.bbs.is_muted(self.name):
                        await self.send(self.c("red", "You are muted.\n"))
                        continue
                    room.say("msg", self.name, line)
                    if not room.name.startswith("page-"):  # (a page is private)
                        self.bbs.log("%s [#%s] %s" % (self.name, room.name, line))
                    self.award("chatter")
                    self.bbs.track(self.name, "chats", save=False)
                    continue
                cmd, _, arg = line[1:].partition(" ")
                arg = arg.strip()
                cmd = cmd.lower()
                if cmd in ("me", "roll", "8ball", "fortune", "shrug", "tableflip", "msg", "pm", "w", "afk") \
                        and self.bbs.is_muted(self.name):
                    await self.send(self.c("red", "You are muted.\n"))
                    continue
                if cmd in ("quit", "leave", "q", "exit"):
                    return None
                if cmd == "join":
                    name, _, pw = arg.partition(" ")
                    target = await self.enter_ok(self.bbs.rooms.get(name.lower()), pw.strip())
                    if target and target is not room:
                        return target
                elif cmd == "me" and arg:
                    room.say("emo", self.name, arg)
                    if not room.name.startswith("page-"):
                        self.bbs.log("%s [#%s] * %s %s" % (self.name, room.name, self.name, arg))
                elif cmd == "who":
                    await self.send("In #%s: %s\n" % (room.name, ", ".join(sorted(
                        m.name for m in room.members if self.sees(m.name, getattr(m, "age", None))))))
                elif cmd == "rooms":
                    await self.send(self.room_list() + "\n")
                elif cmd in ("msg", "pm", "w"):
                    to, _, text = arg.partition(" ")
                    target = self.bbs.find_session(to)
                    if not target or not text.strip():
                        await self.send(self.c("red", "Usage: /msg <online user> <text>\n"))
                    elif self.kids() and (target.guest or self.guest or not self.bbs.may_contact(
                            self.name, self.age, target.name, target.age, "pm")):
                        await self.send(self.c("red", "You can't send private messages to %s.\n" % target.name))
                    else:
                        e = {"ts": time.time(), "kind": "pm", "who": self.name, "text": text.strip()}
                        if self.name.lower() not in target.ignored:
                            target.push(target.fmt_chat(e))
                        await self.send(self.c("bmagenta", "[pm to %s] " % target.name) + text.strip() + "\n")
                        if target.afk:
                            await self.send(self.c("gray", "%s is away: %s\n" % (target.name, target.afk)))
                elif cmd == "op" and self.sysop:
                    await self.op_line(arg)
                elif cmd == "topic" and self.mod:
                    room.topic = arg
                    self.bbs.log("%s [#%s] set the topic: %s" % (self.name, room.name, arg))
                    room.say("sys", self.name, "%s set the topic: %s" % (self.name, arg))
                elif cmd == "help":
                    await self.send(
                        "  /who  /rooms  /join <room> [pw]  /me <action>  /msg <user> <text>  /quit\n"
                        "  /roll 2d6  /8ball  /fortune  /shrug  /tableflip  /color <name>  /ignore <user>\n"
                        "  /afk [why]  /seen <user>  /history [n]  /time  /challenge <user> <ttt|hangman>"
                        + ("\n  /topic <text>  /kick <user>" if self.mod else "") + "\n")
                else:
                    res = await self.chat_extra(room, cmd, arg)
                    if res == "leave":
                        return None
                    if res is False:
                        await self.send(self.c("red", "Unknown command. Try /help.\n"))
        finally:
            self.seen_rooms[room.name] = room.count
            room.members.discard(self)
            if room.name.startswith("page-") and not room.members:
                self.bbs.rooms.pop(room.name, None)
            self.room = None
            room.say("sys", self.name, "%s has left" % self.name)

    # ---- info screens ------------------------------------------------------------
    async def who(self):
        await self.header("Who's online")
        for s in sorted(self.bbs.sessions, key=lambda s: s.joined):
            if not self.sees(s.name, s.age):
                continue
            await self.send(" %-16s %-22s on for %s\n" % (
                s.name + ("*" if s.sysop else "+" if s.deputy else ""), s.where, duration(time.time() - s.joined)))
        await self.readline(self.c("gray", "\n[Enter to continue]"))

    async def userlist(self):
        await self.header("Users")
        users = sorted(self.bbs.users.values(), key=lambda u: -u["last"])[:40]
        for u in users:
            age = self.bbs.age_of(u["name"])
            if not self.sees(u["name"], age):
                continue
            extra = ("   age %s" % (age if age is not None else "?")) if self.sysop and self.kids() else ""
            await self.send(" %-16s %4d calls   last on %s%s\n" % (u["name"], u["calls"], fdate(u["last"]), extra))
        await self.readline(self.c("gray", "\n[Enter to continue]"))

    async def op_line(self, line):
        """A sysop's op command typed at the main menu ("op restart") or in a chat room ("/op ...")."""
        try:
            words = shlex.split(line)
        except ValueError:
            words = []
        ok, out = Ops(self.bbs, True).run(words)
        await self.send(self.c("byellow" if ok else "red", out) + "\n")

    # ---- families (Parent mode) -------------------------------------------
    def has_family(self):
        u = self.bbs.users.get(self.name.lower(), {})
        return bool(self.kids() and self.cfg["kids"].get("parents") and
                    (u.get("parents") or self.bbs.children(self.name)))

    async def family_menu(self):
        """Parents: their children's accounts, and who else may write to them."""
        bbs = self.bbs
        self.where = "Family"
        while True:
            me = bbs.users.get(self.name.lower(), {})
            kids = bbs.children(self.name)
            await self.header("Family")
            if me.get("parents"):
                await self.send("  Your parents here: %s\n" % ", ".join(me["parents"]))
                if me.get("approved"):
                    await self.send("  Also allowed to write to you: %s\n" % ", ".join(me["approved"]))
            for i, k in enumerate(kids, 1):
                u = bbs.users.get(k.lower(), {})
                await self.send(" %s %-16s age %-3s %s%s\n" % (
                    self.c("byellow", "%2d" % i), k, bbs.age_of(k) if bbs.age_of(k) is not None else "?",
                    "approved: " + (", ".join(u.get("approved") or []) or "nobody else"),
                    self.c("bmagenta", "  (family only)") if u.get("family_only") else ""))
            grown = (self.age if self.age is not None else ADULT) >= ADULT
            if not grown:
                await self.readline(self.c("gray", "\n[Enter to continue]"))
                return
            if not kids:
                await self.send("  You have no children's accounts here yet.\n")
            k = (await self.readline("\n[N]ew child account  [A]pprove someone  [R]emove approval\n"
                                     "[O]nly family for a child (on/off)  [Q]uit\n> ")).strip().lower()[:1]
            if k in ("", "q"):
                return
            if k == "n":
                await self.new_child()
                continue
            if not kids:
                continue
            pick = (await self.readline("Which child # (1-%d): " % len(kids))).strip()
            if not pick.isdigit() or not 1 <= int(pick) <= len(kids):
                continue
            child = bbs.users[kids[int(pick) - 1].lower()]
            if k == "o":
                child["family_only"] = not child.get("family_only")
                await self.send("%s: %s.\n" % (child["name"], "only family and approved people may write"
                                                if child["family_only"] else "anyone their age allows may write"))
            elif k == "a":
                who = bbs.users.get((await self.readline("Handle of the person to approve: ")).strip().lower())
                if not who or who["name"].lower() in (child["name"].lower(), self.name.lower()):
                    await self.send(self.c("red", "No such user.\n"))
                    continue
                child.setdefault("approved", [])
                if who["name"] not in child["approved"]:
                    child["approved"].append(who["name"])
                await self.send(self.c("bgreen", "%s may write to %s now, and %s to them.\n" % (
                    who["name"], child["name"], child["name"])))
            elif k == "r":
                name = (await self.readline("Handle to remove: ")).strip().lower()
                child["approved"] = [a for a in child.get("approved") or [] if a.lower() != name]
            bbs.save("users", bbs.users)

    async def new_child(self):
        """A parent makes their child's account: it is theirs from the start."""
        bbs = self.bbs
        name = (await self.readline("Your child's handle: ")).strip()
        if not NAME_RE.match(name) or name.lower().startswith("guest") or name.lower() in bbs.users:
            await self.send(self.c("red", "That handle can't be used (2-16 letters, digits, _ or -, not taken).\n"))
            return
        age = (await self.readline("Their age: ")).strip()
        if not age.isdigit() or not 3 <= int(age) < ADULT:
            await self.send(self.c("red", "Children's accounts are for ages 3 to 17.\n"))
            return
        if int(age) < self.cfg["kids"]["join_age"]:
            await self.send(self.c("red", "This BBS is for callers aged %d and up.\n" % self.cfg["kids"]["join_age"]))
            return
        pw = await self.readline("Their password (4+ chars): ", echo=False)
        if len(pw) < 4 or pw != await self.readline("Again: ", echo=False):
            await self.send(self.c("red", "Too short, or not the same twice.\n"))
            return
        user = await bbs.make_user(name, pw)
        user.update(calls=0, born=time.localtime().tm_year - int(age), parents=[self.name], approved=[])
        bbs.save("users", bbs.users)
        bbs.log("%s made a child account: %s" % (self.name, name))
        await self.send(self.c("bgreen", "%s's account is made. They log in with that handle and password.\n" % name))

    async def sysop_family(self, cmd):
        bbs = self.bbs
        name = (await self.readline("Handle: ")).strip().lower()
        u = bbs.users.get(name)
        if not u:
            await self.send(self.c("red", "No such user.\n"))
            return
        if cmd == "a":
            a = (await self.readline("Their age (Enter: not known): ")).strip()
            if a.isdigit() and 3 <= int(a) <= 120:
                u["born"] = time.localtime().tm_year - int(a)
            elif not a:
                u.pop("born", None)
            else:
                return
        elif cmd == "l":
            p = bbs.users.get((await self.readline("Their parent's handle: ")).strip().lower())
            if not p or p is u:
                await self.send(self.c("red", "No such user.\n"))
                return
            u.setdefault("parents", [])
            if p["name"] not in u["parents"]:
                u["parents"].append(p["name"])
        elif cmd == "u":
            u["parents"], u["approved"] = [], []
        bbs.save("users", bbs.users)
        s = bbs.find_session(u["name"])
        if s and cmd == "a":
            s.age = bbs.age_of(u["name"])
        bbs.log("%s set %s: age %s, parents %s" % (self.name, u["name"], bbs.age_of(u["name"]), ", ".join(u.get("parents") or []) or "none"))
        await self.send("Done: %s, age %s, parents: %s.\n" % (
            u["name"], bbs.age_of(u["name"]), ", ".join(u.get("parents") or []) or "none"))

    async def info(self):
        bbs, f = self.bbs, self.feat
        await self.header("About " + self.cfg["name"])
        on = lambda b: self.c("bgreen", "on") if b else self.c("red", "off")
        await self.send(
            " hostbbs v%s   up %s   %d online   %d calls   %d users\n"
            " chat: %s   boards: %s   mail: %s   guests: %s   registration: %s\n" % (
                VERSION, duration(time.time() - bbs.started), len(bbs.sessions),
                bbs.meta.get("calls", 0), len(bbs.users),
                on(f["chat"]), on(f["boards"]), on(f["mail"]), on(f["guests"]), on(f["register"])) +
            (" kids mode: on (features go by age)%s\n" % (", parent mode: on" if self.cfg["kids"].get("parents") else "")
             if self.kids() else ""))
        await self.readline(self.c("gray", "\n[Enter to continue]"))

    async def sysop_tools(self):
        self.where = "Sysop tools"
        bbs = self.bbs
        while True:
            await self.header("Sysop tools" if self.sysop else "Deputy tools")
            opts = "[K]ick user  " + ("[B]roadcast  [F]orce a message  [C]onfigure the BBS  [S]ysops  [O]p command (type help)  " if self.sysop else "") + \
                ("\n[A]ge of a user  [L]ink a child to a parent  [U]nlink  " if self.sysop and self.kids() else "") + "[Q]uit"
            cmd = (await self.readline(opts + "\n> ")).strip().lower()[:1]
            if cmd == "q" or not cmd:
                return
            if cmd in ("a", "l", "u") and self.sysop and self.kids():
                await self.sysop_family(cmd)
                continue
            if cmd == "b" and self.sysop:
                text = (await self.readline("Message: ", maxlen=200)).strip()
                if text:
                    bbs.broadcast_sysop(text)
            elif cmd == "f" and self.sysop:
                text = (await self.readline("Urgent message for everyone's screen: ", maxlen=300)).strip()
                if text:
                    ok, out = Ops(bbs, True).run(["force", text])
                    await self.send(out + "\n")
            elif cmd == "c" and self.sysop:
                await self.sysop_config()
            elif cmd == "s" and self.sysop:
                await self.sysop_manage()
            elif cmd == "o" and self.sysop:
                line = (await self.readline("op> ", maxlen=300)).strip()
                try:
                    words = shlex.split(line)
                except ValueError:
                    words = []
                ok, out = Ops(bbs, True).run(words)
                await self.send(out + "\n")
            elif cmd == "k":
                target = bbs.find_session((await self.readline("Kick who: ")).strip())
                if target and target is not self and not target.sysop:
                    target.force("You have been disconnected by %s." % ("the sysop" if self.sysop else self.name), kick=True)
                    await self.send("Kicked %s.\n" % target.name)
                else:
                    await self.send(self.c("red", "Not online.\n"))


# --------------------------------------------------------------------------
# Setup dialog (curses, raspi-config style)
# --------------------------------------------------------------------------

try:
    import curses  # noqa: E402  (only used by the setup dialog)
except ImportError:
    curses = None

BTN_KEYS = (10, 13, getattr(curses, "KEY_ENTER", 343))


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
             ("password", "Password (blank = open)", "str", None), ("guests", "Guests allowed", "bool", None),
             ("ages", "For (Kids mode)", "pick", AGES)]
SPEC_BOARD = [("name", "Name", "str", None), ("desc", "Description", "str", None),
              ("ages", "For (Kids mode)", "pick", AGES)]
SPEC_KIDS = [("enabled", "Kids mode (callers say their age)", "bool", None),
             ("parents", "Parent mode (families)", "bool", None),
             ("join_age", "Youngest who may call", "int", None),
             ("filter_under", "Hide rude words under age", "int", None),
             ("words", "More words to hide", "motd", None)]
SPEC_AGES = [("boards", "Read the message boards", "int", None), ("post", "Write on the boards", "int", None),
             ("mail", "Private mail", "int", None), ("pm", "Private chat messages", "int", None),
             ("chat", "Chat rooms", "int", None), ("files", "Files", "int", None),
             ("games", "Games", "int", None), ("apps", "Apps", "int", None),
             ("multiplayer", "Multiplayer games", "int", None), ("pastebin", "Pastebin", "int", None),
             ("news", "News", "int", None), ("oneliners", "Oneliner wall", "int", None),
             ("profiles", "Profiles", "int", None)]
KIDS_HELP = ("Callers say their age when they join, and get the features their age allows; rooms and boards "
             "can be for some ages only. Adults and under-18s can't write to each other privately or sit at "
             "the same table, and kids under 13 are not shown to other adults. Parent mode: parents make their "
             "children's accounts (Family in the main menu), may always write to them, and approve who else may. "
             "Ages are what callers say: they are not checked.")
FEATURES = [("chat", "Chat rooms"), ("boards", "Message boards"), ("mail", "Private mail"),
            ("files", "File areas (downloads)"), ("games", "Games"), ("apps", "Apps"),
            ("multiplayer", "Multiplayer games (Tic-Tac-Toe, Hangman)"), ("polls", "Voting booth (polls)"),
            ("elections", "Sysop elections (deputies)"), ("achievements", "Achievements"),
            ("daily", "Today screen (fortune, tip, history)"), ("lastcallers", "Last callers"),
            ("oneliners", "Oneliner wall"), ("profiles", "Profiles (calling cards)"), ("trivia", "Trivia & quiz"),
            ("stats", "Statistics & caller of the month"), ("page", "Page the sysop"),
            ("pastebin", "Pastebin"), ("news", "News reader (RSS/Atom)"),
            ("guests", "Guest logins"), ("register", "New user registration")]
PICK_BAUD = [(0, "Full speed"), (300, "300 baud"), (1200, "1200 baud"), (2400, "2400 baud"), (9600, "9600 baud"),
             (14400, "14400 baud"), (28800, "28800 baud")]
SPEC_MODEM = [("baud", "Connect speed", "pick", PICK_BAUD), ("ask", "Let callers pick their speed", "bool", None),
              ("handshake", "Act out the dial-up handshake", "bool", None)]
SPEC_MUSIC = [("enabled", "ANSI music", "bool", None), ("ask", "Ask each caller first", "bool", None),
              ("connect", "Jingle at connect (PLAY string)", "str", None),
              ("achievement", "Jingle for an achievement", "str", None)]
SPEC_WEB = [("enabled", "Web terminal port (WebSocket)", "bool", None), ("host", "Listen address", "str", None),
            ("port", "Port", "int", None), ("origins", "Allowed pages (separate with |; blank = any)", "motd", None),
            ("cert", "TLS certificate file (for wss://)", "str", None), ("key", "TLS key file", "str", None)]
SPEC_FEED = [("name", "Channel name", "str", None), ("url", "Feed address (RSS or Atom)", "str", None)]
SPEC_NEWS = [("custom", "Callers may add their own feeds", "bool", None), ("per_user", "Feeds per caller", "int", None),
             ("cache_minutes", "Keep a feed for (minutes)", "int", None),
             ("allow_private", "Allow private-network feeds (sysop channels only)", "bool", None)]
SPEC_PASTE = [("per_user", "Pastes per caller", "int", None), ("max_lines", "Longest paste (lines)", "int", None)]
PICK_SCHEDMODE = [("broadcast", "A line at each caller's prompt"), ("force", "A forced message on every screen")]
SPEC_SCHED = [("at", "Time (HH:MM)", "str", None),
              ("days", "Days: daily weekdays weekends mon,fri MM-DD", "str", None),
              ("mode", "How it is shown", "pick", PICK_SCHEDMODE), ("message", "Message", "str", None)]
SPEC_EVENTS = [("sysop_hours", "Sysop hours for pages (18:00-23:00)", "str", None),
               ("birthday", "BBS birthday (MM-DD)", "str", None),
               ("trivia_file", "Extra trivia questions (JSON file)", "str", None)]
PICK_ROT = [("random", "A random file each time"), ("sequential", "One after another"),
            ("daily", "A different file each day")]
PICK_FORCESTYLE = [("block", "Block: filled with color"), ("box", "Box: framed with asterisks"),
                   ("line", "Line: one colored line")]
SPEC_FORCE = [("title", "Title (blank = none)", "str", None), ("style", "Style", "pick", PICK_FORCESTYLE),
              ("color", "Color (block fill, frame, line)", "pick", PICK_COLOR),
              ("text_color", "Text color on a block", "pick", PICK_COLOR), ("center", "Center the text", "bool", None),
              ("bell", "Ring the bell", "bool", None), ("seconds", "Seconds kept on games (they redraw)", "int", None)]
SPEC_ELECT = [("days", "Days an election runs", "int", None), ("seats", "Deputy seats", "int", None),
              ("min_calls", "Calls needed to stand or vote", "int", None)]


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
                if ui.yesno("Delete", "Really delete '%s'?" % (item.get("name") or str(item.get("message", "this one"))[:30])):
                    items_.remove(item)
                    return True
            ui.form(title, "", item, specs, [("D", "Delete this one", delete)])
            if key == "schedule" and item in items_:
                item["at"] = (item.get("at") or "").strip()
            if key == "rooms" and item in items_:
                item["name"] = re.sub(r"[^a-z0-9_-]", "", item["name"].lower()) or "room"

    def modem_music(self):
        ui, c = self.ui, self.cfg
        sel = None
        while True:
            sel = ui.menu("Modem & music", "Slow output to a real modem speed, and a jingle for terminals that play ANSI music.", [
                ("1", "Modem: %s%s" % (ui.show(c["modem"]["baud"], "pick", PICK_BAUD), ", callers choose" if c["modem"]["ask"] else "")),
                ("2", "ANSI music: %s" % ("on" if c["music"]["enabled"] else "off")),
                ("3", "Phone number in the handshake: %s" % c["phone"])], sel)
            if sel is None:
                return
            if sel == "1":
                ui.form("Modem", "Games and full-screen programs always run at full speed.", c["modem"], SPEC_MODEM)
            elif sel == "2":
                ui.form("ANSI music", "Only some terminals (SyncTERM and the web terminal) play it; others print junk.",
                        c["music"], SPEC_MUSIC)
            else:
                ui.edit(c, ("phone", "Phone number", "str", None))

    def web_reload(self):
        ui, c = self.ui, self.cfg
        sel = None
        while True:
            sel = ui.menu("Web terminal & reload", "", [
                ("1", "Reload: config file %s, log %s" % ("autoreloads" if c.get("autoreload", True) else "needs a signal",
                                                           "on" if c.get("log", True) else "off")),
                ("2", "Web terminal (WebSocket): %s" % ("port %s" % c["websocket"]["port"] if c["websocket"]["enabled"] else "off"))], sel)
            if sel is None:
                return
            if sel == "1":
                ui.form("Reload & log", "The running BBS applies a saved config file by itself (or on kill -HUP, hostbbs op reload).",
                        c, [("autoreload", "Apply the config file when it is saved", "bool", None),
                            ("log", "Write data/hostbbs.log", "bool", None)])
            else:
                ui.form("Web terminal", "The page jgm240.github.io/rbbs can connect here. Browsers need wss:// (TLS) "
                        "from an https page, except for localhost.", c["websocket"], SPEC_WEB)

    def events_hours(self):
        ui, c = self.ui, self.cfg

        def how():
            ui.msgbox("Event screens", "Put files in the art folder under events/ named MM-DD_name.ans (one day) "
                      "or MM-DD_MM-DD_name.ans (a range, may cross New Year), e.g. 12-23_12-26_xmas.ans. "
                      "The one for today is shown after the banner. birthday*.ans shows on the BBS birthday.")
            return False
        ui.form("Events & hours", "", c, SPEC_EVENTS, [("H", "How event screens are named", how)])

    def art_rotation(self):
        ui, c = self.ui, self.cfg

        def make_pack():
            cfg = finalize(c, self.path.parent)
            dest = cfg["art_dir"] or str(self.path.parent / "art")
            n = save_art_pack(cfg, dest)
            if not c["art_dir"]:
                c["art_dir"] = "art"
            ui.msgbox("Art pack", "Wrote %d banners into %s. Add your own .ans or .txt files next "
                      "to them: one is picked per connect, room visit or board visit." % (n, dest))
            return False

        def toggle_small():
            c["art"]["small"] = not c["art"].get("small")
            return False
        ui.form("Art rotation", "Folder with connect/, rooms/<room>/ and boards/<board>/ art.", c,
                [("art_dir", "Art folder", "str", None), ("art_rotation", "Rotation", "pick", PICK_ROT)],
                [("G", "Generate a sample art pack into the folder", make_pack),
                 ("S", "Small generated banners for rooms/boards without art (toggle)", toggle_small)])

    def forced_messages(self):
        ui, c = self.ui, self.cfg

        def preview():
            curses.def_prog_mode()
            curses.endwin()
            print("\n" + force_block(c["force"], "Server restarts in 5 minutes. Please save your game.", 80, True) + "\n")
            input("  Preview of `hostbbs op force` - press Enter to return to setup...")
            curses.reset_prog_mode()
            ui.scr.refresh()
            return False
        ui.form("Forced messages", "How `hostbbs op force` and Sysop tools > Force look on a caller's screen.",
                c["force"], SPEC_FORCE, [("P", "Preview", preview)])

    def voting_extras(self):
        ui, c = self.ui, self.cfg
        ui.form("Voting & daily", "Elections make the winners deputy sysops (they can delete posts, kick "
                "and set topics). Turn elections on under Features.", c["election"], SPEC_ELECT,
                [("T", "Tips for the Today screen", lambda: ui.edit(c, ("tips", "Tips (separate with |)", "motd", None)) and False)])

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
            ("A", "Art rotation", (c.get("art_dir") or "off") + (", " + c.get("art_rotation", "random") if c.get("art_dir") else "")),
            ("F", "Forced messages", "%s, %s" % (c["force"]["style"], c["force"]["color"])),
            ("M", "Modem & music", "%s, music %s" % ("full speed" if not c["modem"]["baud"] else "%d baud" % c["modem"]["baud"],
                                                      "on" if c["music"]["enabled"] else "off")),
            ("R", "Web & reload", "web %s, autoreload %s" % ("on" if c["websocket"]["enabled"] else "off", "on" if c.get("autoreload", True) else "off")),
            ("T", "Timed messages", "%d scheduled" % len(c.get("schedule") or [])),
            ("N", "News channels", "%d channels" % len(c.get("news_channels") or [])),
            ("K", "Kids mode", ("on" + (", parent mode" if c["kids"].get("parents") else "")) if c["kids"]["enabled"] else "off"),
            ("E", "Events & hours", "sysop hours %s" % (c.get("sysop_hours") or "any time")),
            ("V", "Voting & daily", "elections %s, %d seat%s" % ("on" if c["features"].get("elections") else "off",
                                                              c["election"]["seats"], "" if c["election"]["seats"] == 1 else "s")),
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
            elif sel == "A":
                self.art_rotation()
            elif sel == "F":
                self.forced_messages()
            elif sel == "M":
                self.modem_music()
            elif sel == "R":
                self.web_reload()
            elif sel == "T":
                self.list_editor("Timed messages", "schedule", SPEC_SCHED,
                                 lambda i: "%s %-9s %-9s %s" % (i.get("at", ""), i.get("days", "daily"), i.get("mode", ""), str(i.get("message", ""))[:36]),
                                 {"at": "22:00", "days": "daily", "mode": "broadcast", "message": ""})   # (no message: it never fires)
            elif sel == "E":
                self.events_hours()
            elif sel == "K":
                ui.form("Kids mode", KIDS_HELP, c["kids"], SPEC_KIDS,
                        [("A", "Youngest age for each feature", lambda: ui.form(
                            "Ages", "The youngest age for each feature (0: any age).", c["kids"]["min_age"],
                            SPEC_AGES) and False)])
            elif sel == "N":
                self.list_editor("News channels", "news_channels", SPEC_FEED,
                                 lambda i: "%-16s %s" % (i.get("name", ""), i.get("url", "")[:50]),
                                 {"name": "New channel", "url": "https://"})
            elif sel == "V":
                self.voting_extras()
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
    art.add_argument("--save", metavar="DIR", help="write generated banners for connect, rooms and boards "
                     "into DIR (set it as the art folder to rotate them)")
    sub.add_parser("update", help="get the newest hostbbs (from rBBS on GitHub)")
    op = sub.add_parser("op", help="operator commands: kick, ban, force, polls... (hostbbs op help)")
    op.add_argument("-c", "--config", help="config file (default: ~/hostbbs/hostbbs.json)")
    op.add_argument("--data-dir", help="where the BBS keeps its data")
    op.add_argument("words", nargs=argparse.REMAINDER, help="the command, e.g. kick bob")
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
    for key in ("data_dir", "art_dir"):
        if not cfg[key]:
            continue
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


# ---- WebSocket: the web client talks to the BBS as a telnet stream inside binary frames -----------

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def ws_frame(data, opcode=0x2):
    n = len(data)
    head = bytes([0x80 | opcode])
    if n < 126:
        head += bytes([n])
    elif n < 65536:
        head += bytes([126]) + struct.pack(">H", n)
    else:
        head += bytes([127]) + struct.pack(">Q", n)
    return head + data


class WSWriter:
    """Looks like a StreamWriter to a Session; sends everything as WebSocket binary frames."""

    def __init__(self, writer):
        self._w = writer

    def write(self, data):
        if not self._w.is_closing():
            self._w.write(ws_frame(bytes(data)))

    async def drain(self):
        await self._w.drain()

    def close(self):
        try:
            if not self._w.is_closing():
                self._w.write(ws_frame(struct.pack(">H", 1000), 0x8))
            self._w.close()
        except OSError:
            pass

    def is_closing(self):
        return self._w.is_closing()

    def get_extra_info(self, *a):
        return self._w.get_extra_info(*a)


async def ws_handshake(reader, writer, origins):
    """Answer a WebSocket upgrade request. True when the connection is now a WebSocket."""
    try:
        raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
    except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
        return False
    lines = raw.decode("latin-1").split("\r\n")
    hdr = {}
    for ln in lines[1:]:
        if ":" in ln:
            k, _, v = ln.partition(":")
            hdr[k.strip().lower()] = v.strip()
    ok = lines[0].startswith("GET ") and "websocket" in hdr.get("upgrade", "").lower() and hdr.get("sec-websocket-key")
    if not ok:
        body = b"This is a hostbbs WebSocket port. Use the web terminal, or telnet to the other port.\r\n"
        writer.write(b"HTTP/1.1 426 Upgrade Required\r\nContent-Type: text/plain\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(body) + body)
        await writer.drain()
        writer.close()
        return False
    if origins and hdr.get("origin", "") not in origins:
        writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        await writer.drain()
        writer.close()
        return False
    accept = base64.b64encode(hashlib.sha1((hdr["sec-websocket-key"] + WS_GUID).encode()).digest()).decode()
    writer.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                  "Sec-WebSocket-Accept: %s\r\n\r\n" % accept).encode())
    await writer.drain()
    return True


async def ws_pump(raw_reader, raw_writer, out):
    """Read WebSocket frames from the socket and feed their payload to the StreamReader out."""
    frag = b""
    try:
        while True:
            b0, b1 = await raw_reader.readexactly(2)
            op, masked, n = b0 & 0x0F, b1 & 0x80, b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", await raw_reader.readexactly(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", await raw_reader.readexactly(8))[0]
            if n > 1 << 16:
                break
            mask = await raw_reader.readexactly(4) if masked else b""
            data = await raw_reader.readexactly(n)
            if masked:
                data = bytes(c ^ mask[i % 4] for i, c in enumerate(data))
            if op == 0x8:
                break
            if op == 0x9:
                raw_writer.write(ws_frame(data, 0xA))
            elif op in (0x0, 0x1, 0x2):
                frag += data
                if b0 & 0x80:
                    out.feed_data(frag)
                    frag = b""
    except (asyncio.IncompleteReadError, ConnectionError, OSError):
        pass
    finally:
        out.feed_eof()


async def serve(cfg, loader=None, watch=None):
    sys.stdout.reconfigure(line_buffering=True)
    bbs = BBS(cfg)
    bbs.loader = loader
    bbs.config_path = Path(watch) if watch else None
    sysop_pw = await bbs.ensure_sysop()
    bbs.log("hostbbs %s started" % VERSION)

    async def refuse(reader, writer, text):
        try:
            writer.write(text)
            await writer.drain()
            # (What the caller sent first must be read: closing on unread
            # data would throw the message away.)
            await asyncio.wait_for(reader.read(1024), 0.5)
        except (asyncio.TimeoutError, ConnectionError, OSError):
            pass
        writer.close()

    async def accept(reader, writer, peer):
        """A connection, telnet or WebSocket: apply the limits and run a Session on it."""
        if peer in bbs.bans["ips"]:
            return await refuse(reader, writer, b"You are banned from this BBS.\r\n")
        # Every connection counts, logged in or not: no one can hold more
        # lines than the BBS has by connecting and saying nothing.
        if bbs.connections >= cfg["max_users"]:
            return await refuse(reader, writer, b"System full, try again later.\r\n")
        bbs.connections += 1
        try:
            await Session(bbs, reader, writer).run()
        finally:
            bbs.connections -= 1

    async def handle(reader, writer):
        await accept(reader, writer, (writer.get_extra_info("peername") or ("?",))[0])

    async def handle_ws(reader, writer):
        peer = (writer.get_extra_info("peername") or ("?",))[0]
        if not await ws_handshake(reader, writer, cfg["websocket"].get("origins") or []):
            return
        inner = asyncio.StreamReader()
        pump = asyncio.ensure_future(ws_pump(reader, writer, inner))
        try:
            await accept(inner, WSWriter(writer), peer)
        finally:
            pump.cancel()
            try:
                writer.close()
            except OSError:
                pass

    async def handle_op(reader, writer):
        """One `hostbbs op` request: a JSON line in, a JSON line out."""
        try:
            req = json.loads(await asyncio.wait_for(reader.readline(), 5))
            ok, text = Ops(bbs, True).run([str(w) for w in req.get("words", [])])
        except Exception as e:  # (never let a bad request stop the BBS)
            ok, text = False, "error: %s" % e
        try:
            writer.write((json.dumps({"ok": ok, "text": text}) + "\n").encode())
            await writer.drain()
        except (ConnectionError, OSError):
            pass
        writer.close()

    async def ticker():
        n = 0
        while True:
            await asyncio.sleep(5)
            n += 1
            try:
                if n % 4 == 0:
                    bbs.run_schedule()
                if n % 12 == 0:
                    bbs.elect_check()
            except Exception as e:
                bbs.log("ticker error: %r" % (e,))

    last_mtime = [None]

    async def watcher():
        while True:
            await asyncio.sleep(3)
            if not watch or not cfg.get("autoreload", True):
                continue
            try:
                m = os.stat(watch).st_mtime
            except OSError:
                continue
            if last_mtime[0] is None:
                last_mtime[0] = m
            elif m != last_mtime[0]:
                last_mtime[0] = m
                ok, msg = bbs.reload()
                print("hostbbs: %s" % msg)

    servers, tasks = [], []
    server = await asyncio.start_server(handle, cfg["host"], cfg["port"])
    servers.append(server)
    ws = cfg.get("websocket") or {}
    if ws.get("enabled"):
        ctx = None
        if ws.get("cert") and ws.get("key"):
            import ssl
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(ws["cert"], ws["key"])
        servers.append(await asyncio.start_server(handle_ws, ws.get("host", "127.0.0.1"), int(ws.get("port", 8080)), ssl=ctx))
    op_path, op_server = op_socket_path(cfg), None
    try:
        os.unlink(op_path)
    except OSError:
        pass
    try:
        op_server = await asyncio.start_unix_server(handle_op, path=op_path)
        os.chmod(op_path, 0o600)
    except (OSError, NotImplementedError, AttributeError) as e:
        print("  (no operator socket: %s)" % e)
    if watch:
        try:
            last_mtime[0] = os.stat(watch).st_mtime
        except OSError:
            pass
    tasks += [asyncio.ensure_future(ticker()), asyncio.ensure_future(watcher())]
    try:
        asyncio.get_running_loop().add_signal_handler(signal.SIGHUP, lambda: print("hostbbs: " + bbs.reload()[1]))
    except (NotImplementedError, AttributeError, ValueError, RuntimeError):
        pass
    f = cfg["features"]
    print("hostbbs %s: \"%s\" listening on %s:%d" % (VERSION, cfg["name"], cfg["host"], cfg["port"]))
    print("  connect with: telnet localhost %d   (use a UTF-8 terminal)" % cfg["port"])
    if ws.get("enabled"):
        print("  web terminal: %s://%s:%s (WebSocket%s)" % ("wss" if ws.get("cert") else "ws", ws.get("host", "127.0.0.1"),
                                                           ws.get("port", 8080), ", origins: " + ", ".join(ws["origins"]) if ws.get("origins") else ", any origin"))
    print("  color: %s | %s" % (cfg["color"], " ".join(
        "%s=%s" % (k, "on" if v else "off") for k, v in f.items())))
    if f["chat"]:
        print("  rooms: " + ", ".join("#" + r for r in bbs.rooms))
    if op_server:
        print("  operator: hostbbs op help   (socket %s)" % op_path)
    if loader:
        print("  reload: kill -HUP %d%s, or hostbbs op reload" % (os.getpid(), ", or just save the config file" if watch and cfg.get("autoreload", True) else ""))
    if sysop_pw:
        print("  sysop account created: %s / %s   (shown once; change it in setup > Sysop & storage)"
              % (cfg["sysop"], sysop_pw))
    try:
        await asyncio.gather(*[s.serve_forever() for s in servers])
    finally:
        for t in tasks:
            t.cancel()
        for s in servers:
            s.close()
        if op_server:
            op_server.close()
            try:
                os.unlink(op_path)
            except OSError:
                pass
        bbs.log("hostbbs stopped")


# ---- art packs: generated banners to rotate through -------------------------------------------
ART_VARIANTS = [("block", "rainbow", "double", "horizontal"), ("shade", "fire", "single", "vertical"),
                ("hash", "ocean", "ascii", "diagonal"), ("block", "matrix", "double", "horizontal"),
                ("shade", "sunset", "stars", "diagonal")]


def save_art_pack(cfg, dest):
    """Write several generated banners per connect/room/board into dest, as
    CP437 .ans files, ready for art_dir. Returns the number of files."""
    dest, n = Path(dest), 0

    def write(sub, name, tagline, count):
        nonlocal n
        d = dest / sub
        d.mkdir(parents=True, exist_ok=True)
        for i, (style, pal, frame, grad) in enumerate(ART_VARIANTS[:count], 1):
            c = copy.deepcopy(cfg)
            c["name"], c["tagline"] = name, tagline
            c["art"].update(file="", enabled=True, style=style, colors=PALETTES[pal], gradient=grad,
                            frame=frame, frame_color=PALETTES[pal][0])
            (d / ("%02d.ans" % i)).write_bytes(make_banner(c, True).encode("cp437", "replace"))
            n += 1
    write("connect", cfg["name"], cfg["tagline"], 5)
    for r in cfg["rooms"]:
        write("rooms/" + r["name"], r["name"], r.get("topic", ""), 3)
    for b in cfg["board_list"]:
        write("boards/" + b["name"], b["name"], b.get("desc", ""), 3)
    return n


# ---- `hostbbs op` --------------------------------------------------------------------------------
def run_op(args):
    path = Path(args.config).expanduser() if args.config else DEFAULT_CONFIG
    cfg = load_file(path, bool(args.config))
    if args.data_dir:
        cfg["data_dir"] = args.data_dir
    cfg = finalize(cfg, path.parent)
    words = list(args.words)
    if not words or words[0] in ("help", "-h", "--help"):
        print(Ops.HELP)
        return 0
    hint = "hostbbs op: the BBS belongs to another user; run it as that user (for Kilobyte: sudo -u kbbs hostbbs op ...)"
    try:
        sk = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sk.settimeout(10)
        sk.connect(op_socket_path(cfg))
        sk.sendall((json.dumps({"words": words}) + "\n").encode())
        data = b""
        while not data.endswith(b"\n"):
            chunk = sk.recv(65536)
            if not chunk:
                break
            data += chunk
        reply = json.loads(data)
        ok, text = reply["ok"], reply["text"]
    except (FileNotFoundError, ConnectionRefusedError):
        try:  # not running: the commands that only touch files still work
            ok, text = Ops(BBS(cfg), False).run(words)
        except PermissionError:
            sys.exit(hint)
    except PermissionError:
        sys.exit(hint)
    except (OSError, ValueError) as e:
        sys.exit("hostbbs op: %s" % e)
    print(text)
    return 0 if ok else 1


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

    if args.cmd == "op":
        return run_op(args)
    if args.cmd == "update":
        try:
            print(self_update())
        except PermissionError as e:
            sys.exit("hostbbs: %s (in Kilobyte: Internet > Host a BBS > Update)" % e)
        except (OSError, ValueError, SyntaxError, UnicodeDecodeError) as e:
            sys.exit("hostbbs: the update did not work: %s" % e)
        return 0

    if args.cmd == "setup":
        path = Path(args.config).expanduser() if args.config else DEFAULT_CONFIG
        raw = run_setup(path)
        if raw is None:
            return 0
        if SERVICE:
            return 10
        cfg = finalize(raw, path.parent)
        loader, watch = (lambda: finalize(load_file(path), path.parent)), str(path)
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
        loader, watch = (lambda: finalize(*build_config(args))), str(Path(args.config).expanduser() if args.config else DEFAULT_CONFIG)

    if args.cmd == "art":
        if args.text:
            cfg["name"] = args.text
        if args.save:
            print("wrote %d banners into %s" % (save_art_pack(cfg, args.save), args.save))
            return 0
        print(make_banner(cfg, cfg["color"] is not False and sys.stdout.isatty() or cfg["color"] is True))
        return 0

    try:
        asyncio.run(serve(cfg, loader, watch))
    except KeyboardInterrupt:
        print("\nhostbbs: shutting down")
    except OSError as e:
        sys.exit("hostbbs: cannot listen on %s:%s: %s" % (cfg["host"], cfg["port"], e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
