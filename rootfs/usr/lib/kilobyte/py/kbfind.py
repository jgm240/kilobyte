#!/usr/bin/python3
"""KBFind: find anything, as you type: programs, Settings pages, files (by
name, and inside notes, index cards and text documents), the agenda and the
help. Enter opens it; Esc closes.

    kbfind.py ACTION-FILE [WORDS]

What was chosen is written to ACTION-FILE, one line, for apps/kbfind to do:
    app<TAB>ID<TAB>NAME<TAB>SIZE    a program of the Program Manager
    settings<TAB>PAGE               a page of Settings
    open<TAB>PATH                   a file or folder, with the program for it
    help<TAB>LINE                   the help, from that line on
    agenda                          the agenda
"""
import curses
import os
import re
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kbui  # noqa: E402
from kbui import BLACK, BLUE, CYAN, DARKGREY, LIGHTCYAN, LIGHTGREY, WHITE, YELLOW  # noqa: E402

HOME = os.path.expanduser("~")
HELP = "/usr/share/kilobyte/help.txt"
TEXT = (".txt", ".md", ".note", ".csv", ".log", ".conf", ".ini", ".sh", ".py", ".html", ".htm", ".kbtheme")
SKIP = {".cache", ".local", ".config", ".mozilla", ".wine", "node_modules", ".git", "__pycache__", "DOS"}
LIMIT = 30000                                     # files looked at, at most (a small computer stays quick)


class Item:
    __slots__ = ("kind", "title", "detail", "action", "words")

    def __init__(self, kind, title, detail, action, extra=""):
        self.kind, self.title, self.detail, self.action = kind, title, detail, action
        w = (title + " " + detail + " " + extra).lower()
        self.words = w + " " + w.replace("-", "")         # (wifi finds Wi-Fi)


def programs():
    try:
        out = subprocess.run(["/usr/bin/kilobyte", "--list-apps"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    seen, items = set(), []
    for line in out.splitlines():
        f = line.split("|")
        if len(f) < 6 or f[0] in seen:
            continue
        seen.add(f[0])
        items.append(Item("Program", f[2], f[3], "app\t%s\t%s\t%s" % (f[0], f[2], f[5] or "M"), f[0]))
    return items


def settings():
    try:
        out = subprocess.run(["/usr/lib/kilobyte/apps/settings", "--list"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    items = []
    for line in out.splitlines():
        f = line.split("\t")
        if len(f) == 3:
            items.append(Item("Setting", re.sub(r":.*", "", f[1]), f[2], "settings\t" + f[0], f[0]))
    return items


def files():
    """Every file and folder in the home folder (not the hidden ones)."""
    items, n = [], 0
    for root, dirs, names in os.walk(HOME):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIP)
        rel = os.path.relpath(root, HOME)
        for d in dirs:
            items.append(Item("Folder", d, "~/" + os.path.join(rel, d).lstrip("./"), "open\t" + os.path.join(root, d)))
        for f in sorted(names):
            if f.startswith("."):
                continue
            items.append(Item("File", f, "~/" + (rel + "/" if rel != "." else ""), "open\t" + os.path.join(root, f)))
            n += 1
        if n > LIMIT or root.count(os.sep) - HOME.count(os.sep) > 8:
            dirs[:] = []
    return items


def agenda():
    items = []
    path = os.path.join(os.environ.get("XDG_DATA_HOME", os.path.join(HOME, ".local/share")), "calcurse", "apts")
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r"(\d\d)/(\d\d)/(\d{4})\s.*?\|(.*)", line.strip())
                if m:
                    items.append(Item("Agenda", m.group(4)[:60], "%s-%s-%s" % (m.group(3), m.group(1), m.group(2)), "agenda"))
    except OSError:
        pass
    try:
        with open(os.path.join(os.path.dirname(path), "todo"), encoding="utf-8", errors="replace") as f:
            for line in f:
                t = re.sub(r"^\[-?\d+\]\s*", "", line.strip())
                if t:
                    items.append(Item("To-do", t[:60], "Agenda", "agenda"))
    except OSError:
        pass
    return items


def help_lines():
    items = []
    try:
        with open(HELP, encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                t = line.strip()
                if len(t) > 3:
                    items.append(Item("Help", t[:70], "", "help\t%d" % i))
    except OSError:
        pass
    return items


def inside(words, stop):
    """Text files whose contents have the words: (path, the line)."""
    found = []
    roots = [os.path.join(HOME, d) for d in ("Documents", "Cardfile", "Desktop")]
    for top in roots:
        for root, dirs, names in os.walk(top):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in names:
                if stop() or len(found) >= 60:
                    return found
                if not f.lower().endswith(TEXT) and "Cardfile" not in root and "Notes" not in root:
                    continue
                p = os.path.join(root, f)
                try:
                    if os.path.getsize(p) > 300_000:
                        continue
                    with open(p, encoding="utf-8", errors="replace") as fh:
                        for line in fh:
                            if words in line.lower():
                                found.append((p, line.strip()[:70]))
                                break
                except OSError:
                    continue
    return found


def score(item, q):
    """Lower is better: a name that starts with the words, a word that does,
    then anywhere; programs and settings before files."""
    t = item.title.lower()
    if t.startswith(q):
        s = 0
    elif re.search(r"\b" + re.escape(q), t):
        s = 1
    elif q in t:
        s = 2
    else:
        s = 3 if item.kind not in ("Program", "Setting") else 2   # (found in what it is, or its ID)
    if item.kind == "Help":
        s += 4                                                       # (the help comes last)
    return s * 10 + {"Program": 0, "Setting": 1, "Folder": 2, "File": 3, "Agenda": 4, "To-do": 4, "Text": 5, "Help": 6}.get(item.kind, 7)


class Find:
    def __init__(self, s, out, query):
        self.s, self.out, self.q = s, out, query
        self.items = []
        self.ready = False
        self.sel = 0
        self.top = 0
        self.content = []                      # (path, line) of the last content search
        self.content_q = None
        self.content_thread = None
        self.typed_at = 0
        threading.Thread(target=self.load, daemon=True).start()

    def load(self):
        items = programs() + settings()
        self.items = items[:]
        items += agenda() + files() + help_lines()
        self.items = items
        self.ready = True

    def results(self):
        q = self.q.strip().lower()
        if not q:
            return [i for i in self.items if i.kind in ("Program",)][:200]
        words = q.replace("-", "").split()
        hits = [i for i in self.items if all(w in i.words for w in words)]
        if self.content_q == q:
            names = {i.action for i in hits}
            for p, line in self.content:
                a = "open\t" + p
                if a not in names:
                    hits.append(Item("Text", os.path.basename(p), line, a))
        hits.sort(key=lambda i: score(i, q))
        return hits[:300]

    def search_inside(self):
        q = self.q.strip().lower()
        if len(q) < 3 or q == self.content_q or (self.content_thread and self.content_thread.is_alive()):
            return
        if time.time() - self.typed_at < 0.4:
            return

        def run():
            found = inside(q, lambda: self.q.strip().lower() != q)
            if self.q.strip().lower() == q:
                self.content, self.content_q = found, q
        self.content_thread = threading.Thread(target=run, daemon=True)
        self.content_thread.start()

    def draw(self, res):
        s = self.s
        h, w = s.size()
        s.fill(LIGHTGREY, BLUE)
        s.put(0, 0, " KBFind: programs, settings, files, notes, agenda, help".ljust(w), BLACK, CYAN)
        s.box(1, 0, 3, w, WHITE, BLUE)
        s.put(2, 2, "Find: ", YELLOW, BLUE)
        s.put(2, 8, (self.q + "_")[-(w - 10):], WHITE, BLUE)
        rows = h - 6
        if self.sel < self.top:
            self.top = self.sel
        if self.sel >= self.top + rows:
            self.top = self.sel - rows + 1
        for i, it in enumerate(res[self.top:self.top + rows]):
            y = 4 + i
            on = self.top + i == self.sel
            fg, bg = (BLACK, CYAN) if on else (LIGHTGREY, BLUE)
            s.put(y, 0, " " * w, fg, bg)
            s.put(y, 1, "%-8s" % it.kind, (BLACK if on else DARKGREY), bg)
            s.put(y, 10, it.title[: w // 2 - 10], WHITE if not on else BLACK, bg)
            s.put(y, max(w // 2 + 1, 10 + len(it.title[: w // 2 - 10]) + 2), it.detail[: w // 2 - 3], LIGHTCYAN if not on else BLACK, bg)
        if not res:
            s.put(5, 2, "Looking..." if not self.ready else "Nothing found.", LIGHTGREY, BLUE)
        status = "↑↓ choose   Enter opens   Esc closes" + ("" if self.ready else "   (still looking through your files...)")
        s.put(h - 1, 0, (" " + status)[: w - 1].ljust(w - 1), BLACK, CYAN)
        s.scr.refresh()

    def run(self):
        s = self.s
        s.scr.timeout(150)
        curses.curs_set(0)
        while True:
            res = self.results()
            self.sel = max(0, min(self.sel, len(res) - 1))
            self.draw(res)
            self.search_inside()
            try:
                k = s.scr.get_wch()
            except curses.error:
                continue
            if k in ("\x1b", "\x00", curses.KEY_F10):     # (Ctrl-Space again closes it too)
                return
            if k in ("\n", "\r", curses.KEY_ENTER):
                if res:
                    with open(self.out, "w", encoding="utf-8") as f:
                        f.write(res[self.sel].action + "\n")
                return
            if k == curses.KEY_UP:
                self.sel -= 1
            elif k == curses.KEY_DOWN:
                self.sel += 1
            elif k == curses.KEY_PPAGE:
                self.sel -= 10
            elif k == curses.KEY_NPAGE:
                self.sel += 10
            elif k in (curses.KEY_BACKSPACE, "\x7f", "\b"):
                self.q, self.sel, self.typed_at = self.q[:-1], 0, time.time()
            elif k == "\x15":                              # Ctrl-U: clear
                self.q, self.sel = "", 0
            elif isinstance(k, str) and k.isprintable():
                self.q, self.sel, self.typed_at = self.q + k, 0, time.time()


def main(args):
    if not args:
        sys.exit(__doc__)
    out, query = args[0], " ".join(args[1:])
    kbui.run(lambda s: Find(s, out, query).run(), mouse=False)


if __name__ == "__main__":
    main(sys.argv[1:])
