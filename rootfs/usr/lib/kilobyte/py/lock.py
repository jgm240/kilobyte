#!/usr/bin/python3
"""Lock the screen: everything is hidden until the password of the user who
locked it is typed.

The password is checked by unix_chkpwd, the helper PAM itself uses, which
may check the caller's own password without being root. Ctrl+C, Ctrl+Z and
Ctrl+\\ do nothing here. (Other consoles, Alt+F2..., ask for a login of
their own.)
"""
import curses
import getpass
import os
import signal
import socket
import subprocess
import sys
import time

sys.path.insert(0, "/usr/lib/kilobyte/py")
import kbui  # noqa: E402
from kbui import BLACK, BLUE, LIGHTCYAN, LIGHTGREY, WHITE, YELLOW  # noqa: E402

CHKPWD = next((p for p in ("/usr/sbin/unix_chkpwd", "/sbin/unix_chkpwd") if os.path.exists(p)), None)

DIGITS = {
    "0": ["███", "█ █", "█ █", "█ █", "███"], "1": ["  █", "  █", "  █", "  █", "  █"],
    "2": ["███", "  █", "███", "█  ", "███"], "3": ["███", "  █", "███", "  █", "███"],
    "4": ["█ █", "█ █", "███", "  █", "  █"], "5": ["███", "█  ", "███", "  █", "███"],
    "6": ["███", "█  ", "███", "█ █", "███"], "7": ["███", "  █", "  █", "  █", "  █"],
    "8": ["███", "█ █", "███", "█ █", "███"], "9": ["███", "█ █", "███", "  █", "███"],
    ":": [" ", "█", " ", "█", " "],
}


def right_password(user, password):
    if not CHKPWD:
        return True                        # nothing to check with: do not lock anyone out
    try:
        p = subprocess.run([CHKPWD, user, "nullok"], input=password.encode("utf-8") + b"\0",
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        return p.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def main(s):
    for sig in (signal.SIGINT, signal.SIGQUIT, signal.SIGTSTP, signal.SIGHUP):
        signal.signal(sig, signal.SIG_IGN)
    curses.raw()
    s.scr.keypad(True)
    s.scr.timeout(1000)
    user = getpass.getuser()
    host = socket.gethostname()
    typed, message, since = "", "", time.time()
    while True:
        h, w = s.size()
        s.fill(LIGHTGREY, BLUE)
        now = time.strftime("%H:%M")
        rows = ["  ".join(DIGITS[c][r] for c in now) for r in range(5)]
        cy = max(1, h // 2 - 7)
        for r, row in enumerate(rows):
            s.put(cy + r, (w - len(row)) // 2, row, LIGHTCYAN, BLUE)
        day = time.strftime("%A, %d %B %Y")
        s.put(cy + 6, (w - len(day)) // 2, day, LIGHTGREY, BLUE)
        line = "■ Kilobyte is locked by %s on %s" % (user, host)
        s.put(cy + 9, (w - len(line)) // 2, line, WHITE, BLUE)
        prompt = "Password: " + "*" * len(typed)
        bw = max(40, len(prompt) + 6)
        bx = (w - bw) // 2
        s.put(cy + 11, bx, " " * bw, BLACK, LIGHTGREY)
        s.put(cy + 11, bx + 2, prompt[:bw - 4], BLACK, LIGHTGREY)
        hint = message or "Type your password and press Enter."
        s.put(cy + 13, (w - len(hint)) // 2, hint, YELLOW if message else LIGHTGREY, BLUE)
        try:
            curses.curs_set(1)
            s.scr.move(cy + 11, min(w - 2, bx + 2 + len(prompt)))
        except curses.error:
            pass
        s.scr.refresh()
        try:
            k = s.scr.get_wch()
        except curses.error:
            if message and time.time() - since > 4:
                message = ""
            continue
        if k in ("\n", "\r", curses.KEY_ENTER):
            s.put(cy + 13, 0, " " * (w - 1), LIGHTGREY, BLUE)
            s.put(cy + 13, (w - 12) // 2, "Checking ...", LIGHTGREY, BLUE)
            s.scr.refresh()
            if right_password(user, typed):
                return
            typed, message, since = "", "That is not the password.", time.time()
            time.sleep(1.5)                 # slow down guessing
            curses.flushinp()
        elif k in ("\x7f", "\b", curses.KEY_BACKSPACE):
            typed = typed[:-1]
        elif k == "\x15":                   # Ctrl+U: start again
            typed = ""
        elif isinstance(k, str) and k.isprintable():
            typed += k


if __name__ == "__main__":
    kbui.run(main, mouse=False)
