#!/usr/bin/python3
"""Chess: you play white against GNU Chess.

Arrows move, Space or Enter picks a piece up and puts it down (or click
both squares), or type a move such as e2e4. U takes your last move back,
T turns the board, N new game, 1/2/3 computer strength, Q quits.
Games are kept: the next start carries on where you left off.
"""
import os
import queue
import shutil
import subprocess
import sys
import threading
import time

sys.path.insert(0, "/usr/lib/kilobyte/py")
import kbui  # noqa: E402
from kbui import BLACK, BLUE, BROWN, CYAN, DARKGREY, LIGHTGREY, RED, WHITE, YELLOW  # noqa: E402
import curses  # noqa: E402

CONF = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "kilobyte")
SAVE = os.path.join(CONF, "chess-game")
START = "rnbqkbnrpppppppp" + "." * 32 + "PPPPPPPPRNBQKBNR"   # a8 ... h1
NAMES = {"p": "pawn", "n": "knight", "b": "bishop", "r": "rook", "q": "queen", "k": "king"}
KNIGHT = (-17, -15, -10, -6, 6, 10, 15, 17)
STEPS = {"n": KNIGHT, "b": (-9, -7, 7, 9), "r": (-8, -1, 1, 8), "q": (-9, -8, -7, -1, 1, 7, 8, 9),
         "k": (-9, -8, -7, -1, 1, 7, 8, 9)}


def sq(name):
    return (8 - int(name[1])) * 8 + "abcdefgh".index(name[0])


def name_of(i):
    return "abcdefgh"[i % 8] + str(8 - i // 8)


class Position:
    """A position: board (64 characters, a8 first), side to move, castling
    rights, en passant square. Moves are UCI strings such as e2e4, e7e8q."""

    def __init__(self):
        self.b = list(START)
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
            for d in STEPS[kind]:
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
                        out.append(name_of(i) + name_of(j + d))
                for dc in (-1, 1):
                    j = i + d + dc
                    if 0 <= j < 64 and abs(j % 8 - c) == 1:
                        if (b[j] != "." and not self.mine(b[j], w)) or j == self.ep:
                            out += self.promos(i, j, last)
            elif k in ("n", "k"):
                for d in STEPS[k]:
                    j = i + d
                    if 0 <= j < 64 and abs(j % 8 - c) <= 2 and not self.mine(b[j], w):
                        out.append(name_of(i) + name_of(j))
                if k == "k":
                    out += self.castles()
            else:
                for d in STEPS[k]:
                    j = i
                    while True:
                        pc = j % 8
                        j += d
                        if not 0 <= j < 64 or abs(j % 8 - pc) > 1 or self.mine(b[j], w):
                            break
                        out.append(name_of(i) + name_of(j))
                        if b[j] != ".":
                            break
        return out

    def promos(self, i, j, last):
        m = name_of(i) + name_of(j)
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
                out.append(name_of(e) + name_of(row * 8 + through[-1]))
        return out

    def play(self, m, check=True):
        """Make move m (UCI). Returns False if it is not legal."""
        if check and m not in self.legal():
            return False
        self.history.append((self.b[:], self.white, set(self.castle), self.ep, self.halfmoves))
        self.moves.append(m)
        b = self.b
        i, j = sq(m[:2]), sq(m[2:4])
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
        i, j = sq(m[:2]), sq(m[2:4])
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
                same = [o for o in self.legal() if o[2:4] == m[2:4] and o != m and self.b[sq(o[:2])].lower() == p]
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


class Engine:
    """GNU Chess, spoken to in UCI."""

    def __init__(self):
        exe = shutil.which("gnuchess") or "/usr/games/gnuchess"
        self.p = subprocess.Popen([exe, "--uci"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, bufsize=1)
        # Its answers are read in a thread of their own (select() cannot see
        # lines already waiting in the pipe's buffer).
        self.lines = queue.Queue()
        threading.Thread(target=self.read, daemon=True).start()
        self.send("uci")
        self.wait("uciok", 20)
        self.send("isready")
        self.wait("readyok", 20)

    def send(self, line):
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()

    def wait(self, word, timeout):
        end = time.time() + timeout
        while True:
            try:
                line = self.lines.get(timeout=max(0.01, end - time.time()))
            except queue.Empty:
                return None
            if line is None:                       # GNU Chess ended
                return None
            if line.startswith(word):
                return line.split()

    def read(self):
        for line in self.p.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def best(self, moves, level):
        self.send("position startpos" + (" moves " + " ".join(moves) if moves else ""))
        self.send({1: "go depth 1", 2: "go movetime 700", 3: "go movetime 3000"}[level])
        r = self.wait("bestmove", 120)
        return r[1] if r and len(r) > 1 else None

    def close(self):
        try:
            self.send("quit")
            self.p.wait(2)
        except Exception:
            self.p.kill()


def load():
    pos, level = Position(), 2
    try:
        with open(SAVE) as f:
            words = f.read().split()
        if words and words[0] in "123":
            level = int(words.pop(0))
        for m in words:
            if not pos.play(m):
                break
    except OSError:
        pass
    return pos, level


def save(pos, level):
    try:
        os.makedirs(CONF, exist_ok=True)
        with open(SAVE, "w") as f:
            f.write(" ".join([str(level)] + pos.moves) + "\n")
    except OSError:
        pass


SANS = []      # (move, notation) of the game shown, worked out once each


def notation(moves):
    """The moves in the usual notation; only new ones are worked out (on a
    slow computer replaying a long game for every key would take seconds)."""
    keep = 0
    while keep < len(SANS) and keep < len(moves) and SANS[keep][0] == moves[keep]:
        keep += 1
    del SANS[keep:]
    if keep < len(moves):
        replay = Position()
        for m in moves[:keep]:
            replay.play(m, check=False)
        for m in moves[keep:]:
            SANS.append((m, replay.san(m)))
            replay.play(m, check=False)
    return [t for _, t in SANS]


def draw(s, pos, cur, picked, flipped, msg, level, typed, last):
    H, W = s.size()
    s.fill(LIGHTGREY, BLUE)
    cw, ch = (7, 3) if H >= 30 and W >= 70 else (5, 2) if H >= 20 else (3, 1)
    bw, bh = 8 * cw, 8 * ch
    side = 26 if W >= bw + 4 + 28 else 0
    ox = max(2, (W - bw - side) // 2)
    oy = max(1, (H - bh - 3) // 2)
    legal = pos.legal() if picked is not None else []
    targets = {sq(m[2:4]) for m in legal if sq(m[:2]) == picked}
    lastsq = {sq(last[:2]), sq(last[2:4])} if last else set()
    for r in range(8):
        for c in range(8):
            i = (7 - r) * 8 + (7 - c) if flipped else r * 8 + c
            px, py = ox + c * cw, oy + r * ch
            bg = BROWN if (r + c) % 2 else LIGHTGREY
            if i in lastsq:
                bg = CYAN
            if i == picked:
                bg = YELLOW & 7
            if i == cur:
                bg = BLUE
            for k in range(ch):
                s.put(py + k, px, " " * cw, BLACK, bg)
            p = pos.b[i]
            mid = py + ch // 2
            if p != ".":
                fg = WHITE if p.isupper() else BLACK
                if bg == BLACK & 7:
                    fg = DARKGREY
                # White (K), black [k]: told apart without colours too (e-ink).
                t = "(%s)" % p if p.isupper() else "[%s]" % p
                s.put(mid, px + cw // 2 - 1 if cw >= 3 else px, t if cw >= 3 else p, fg, bg)
            elif i in targets:
                s.put(mid, px + cw // 2, "·", RED, bg)
        rank = str(r + 1) if flipped else str(8 - r)
        s.put(oy + r * ch + ch // 2, ox - 2, rank, WHITE, BLUE)
    files = "hgfedcba" if flipped else "abcdefgh"
    s.put(oy + bh, ox, "".join(f.center(cw) for f in files), WHITE, BLUE)
    if side:
        x = ox + bw + 3
        s.put(oy, x, "You: white", WHITE, BLUE)
        s.put(oy + 1, x, f"GNU Chess: black, strength {level}", LIGHTGREY, BLUE)
        # The moves so far, in pairs, as many as fit.
        lines = []
        for n, t in enumerate(notation(pos.moves)):
            if n % 2 == 0:
                lines.append(f"{n // 2 + 1:3d}. {t:8s}")
            else:
                lines[-1] += t
        room = bh - 3
        for k, line in enumerate(lines[-room:]):
            s.put(oy + 3 + k, x, line, LIGHTGREY, BLUE)
    status = msg
    if typed:
        status = f" Move: {typed}_ "
    if status:
        s.put(oy - 1 if oy > 0 else 0, ox, status[:W - ox], BLACK, YELLOW)
    s.put(H - 1, 0, " Arrows+Space or type e2e4  U take back  T turn board  N new  1/2/3 strength  Q quit "[:W].ljust(W),
          BLACK, CYAN)
    return ox, oy, cw, ch


def main(s):
    try:
        engine = Engine()
    except OSError:
        s.fill(LIGHTGREY, BLUE)
        s.put(2, 2, "GNU Chess is not installed (Settings > Add or remove programs: gnuchess).", WHITE, BLUE)
        s.put(4, 2, "Press any key.", LIGHTGREY, BLUE)
        s.scr.getch()
        return
    pos, level = load()
    cur, picked, flipped, typed = sq("e2"), None, False, ""
    msg = " Your move " if pos.white else ""
    try:
        while True:
            last = pos.moves[-1] if pos.moves else None
            if not pos.white and not pos.outcome():
                draw(s, pos, cur, None, flipped, " GNU Chess is thinking... ", level, "", last)
                s.scr.refresh()
                m = engine.best(pos.moves, level)
                if m and pos.play(m):
                    msg = " GNU Chess: " + Position_san(pos, m) + " "
                else:
                    msg = " GNU Chess gave up "
                save(pos, level)
                continue
            over = pos.outcome()
            if over:
                msg = f" {over}. N plays again. "
            elif pos.in_check():
                msg = msg.rstrip() + " - check! "
            bx, by, cw, ch = draw(s, pos, cur, picked, flipped, msg, level, typed, pos.moves[-1] if pos.moves else None)
            s.scr.refresh()
            k = s.scr.getch()
            r, c = divmod(cur, 8)
            dr = -1 if not flipped else 1
            target = None
            key = chr(k) if 0 < k < 256 else ""
            if k == 27 or (key in ("q", "Q") and not typed):
                return
            # Typed moves: a file letter starts one (e2e4, e7e8q).
            if typed or key in "abcdefgh" and key:
                if k in (curses.KEY_BACKSPACE, 127, 8):
                    typed = typed[:-1]
                    continue
                if key and key in "abcdefgh12345678qrbn" and len(typed) < 5:
                    typed += key
                done = key in ("\n", "\r", " ")
                cand = [x for x in pos.legal() if x.startswith(typed)]
                if len(typed) == 4 and not done and any(len(x) == 5 for x in cand):
                    continue                       # a pawn reaching the end: which piece?
                if len(typed) >= 4 or done:
                    if len(typed) == 4 and len(cand) > 1:
                        cand = [typed + "q"]
                    if typed in cand or (len(typed) == 4 and len(cand) == 1):
                        mv = typed if typed in cand else cand[0]
                        msg = " You: " + pos.san(mv) + " "
                        pos.play(mv)
                        picked = None
                        save(pos, level)
                    else:
                        curses.beep()
                        msg = f" {typed} is not a move here "
                    typed = ""
                continue
            if k in (ord("n"), ord("N")):
                pos, picked, msg = Position(), None, " New game: your move "
                save(pos, level)
            elif k in (ord("u"), ord("U")):
                pos.undo()
                if not pos.white:
                    pos.undo()
                picked, msg = None, " Taken back "
                save(pos, level)
            elif k in (ord("t"), ord("T")):
                flipped = not flipped
            elif k in (ord("1"), ord("2"), ord("3")):
                level = k - ord("0")
                msg = f" Strength {level} "
                save(pos, level)
            elif k == curses.KEY_LEFT:
                c = (c - (1 if not flipped else -1)) % 8
            elif k == curses.KEY_RIGHT:
                c = (c + (1 if not flipped else -1)) % 8
            elif k == curses.KEY_UP:
                r = (r + dr) % 8
            elif k == curses.KEY_DOWN:
                r = (r - dr) % 8
            elif k in (ord(" "), 10, 13):
                target = cur
            elif k == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, _ = curses.getmouse()
                except curses.error:
                    continue
                x, y = (mx - bx) // cw, (my - by) // ch
                if 0 <= x < 8 and 0 <= y < 8:
                    target = (7 - y) * 8 + (7 - x) if flipped else y * 8 + x
                    r, c = divmod(target, 8)
            cur = r * 8 + c
            if target is None or pos.outcome():
                continue
            if picked is None:
                if pos.mine(pos.b[target], True):
                    picked = target
                    msg = " Where to? (Space again puts it back) "
                else:
                    curses.beep()
                continue
            if target == picked:
                picked, msg = None, " Your move "
                continue
            if pos.mine(pos.b[target], True):
                picked = target
                continue
            cand = [m for m in pos.legal() if sq(m[:2]) == picked and sq(m[2:4]) == target]
            if not cand:
                curses.beep()
                msg = " That piece cannot go there "
                continue
            mv = cand[0]
            if len(cand) > 1:                      # a pawn reaching the end
                mv = choose_promotion(s, cand)
                if not mv:
                    continue
            msg = " You: " + pos.san(mv) + " "
            pos.play(mv)
            picked = None
            save(pos, level)
    finally:
        engine.close()


def Position_san(pos, m):
    """The notation of a move that was just made."""
    pos.undo()
    t = pos.san(m)
    pos.play(m, check=False)
    return t


def choose_promotion(s, cand):
    H, W = s.size()
    s.put(H - 2, 0, " Your pawn becomes: Q queen, R rook, B bishop, N knight ".ljust(W), BLACK, YELLOW)
    s.scr.refresh()
    while True:
        k = s.scr.getch()
        if k == 27:
            return None
        for m in cand:
            if 0 < k < 256 and chr(k).lower() == m[4]:
                return m


if __name__ == "__main__":
    kbui.run(main)
