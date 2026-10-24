#!/usr/bin/python3
"""Messenger: talk to the people on Kilobyte computers on the same network,
and send them files. No account and no server: while Messenger is open, it
tells the network who you are (a UDP broadcast every few seconds) and the
others' Messengers answer. Messages and files then go straight from one
computer to the other (TCP).

    messenger.py              (the people here, and the conversation)

Keys: ↑ ↓ choose a person (or Everyone), type and Enter to send, F2 sends a
file, F3 changes your name, PgUp PgDn scroll, Esc or F10 closes.

Only people on this network can reach you, and only while Messenger is open.
A file is only taken when you say yes; it goes to Documents/Received.
"""
import curses
import json
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kbui  # noqa: E402
from kbui import BLACK, BLUE, CYAN, DARKGREY, LIGHTCYAN, LIGHTGREEN, LIGHTGREY, WHITE, YELLOW  # noqa: E402

PORT = 47474                                 # where everyone announces themselves
MAX_TEXT = 4000
MAX_FILE = 4 * 1024 ** 3
CONF = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "kilobyte", "messenger")
RECEIVED = os.path.expanduser("~/Documents/Received")
EVERYONE = "*"


def clean(text, limit=MAX_TEXT):
    """Text from the network, without anything a terminal would act on."""
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f‪-‮⁦-⁩]", "", str(text))[:limit]


def my_id():
    os.makedirs(CONF, exist_ok=True)
    path = os.path.join(CONF, "id")
    try:
        with open(path) as f:
            i = f.read().strip()
            if re.fullmatch(r"[0-9a-f]{32}", i):
                return i
    except OSError:
        pass
    i = uuid.uuid4().hex
    with open(path, "w") as f:
        f.write(i + "\n")
    return i


def my_name():
    try:
        with open(os.path.join(CONF, "name")) as f:
            n = clean(f.read().strip(), 30)
            if n:
                return n
    except OSError:
        pass
    try:
        import pwd
        gecos = pwd.getpwuid(os.getuid()).pw_gecos.split(",")[0].strip()
    except (KeyError, ImportError):
        gecos = ""
    return clean(gecos or os.environ.get("USER", "someone"), 30)


def broadcasts():
    """The broadcast addresses of this computer's networks."""
    out = {"255.255.255.255"}
    try:
        text = subprocess.run(["ip", "-o", "-4", "addr"], capture_output=True, text=True, timeout=3).stdout
        out.update(re.findall(r"\bbrd (\d+\.\d+\.\d+\.\d+)", text))
    except (OSError, subprocess.SubprocessError):
        pass
    return out


class Net:
    """Announcing, finding the others, and sending and receiving."""

    def __init__(self, events):
        self.id, self.name = my_id(), my_name()
        self.host = socket.gethostname()[:30]
        self.events = events                 # (kind, ...) for the screen
        self.people = {}                     # id -> dict(name, host, addr, port, seen)
        self.lock = threading.Lock()
        self.running = True
        self.tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp.bind(("0.0.0.0", 0))
        self.tcp.listen(8)
        self.port = self.tcp.getsockname()[1]
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.udp.bind(("0.0.0.0", PORT))
        for target in (self.listen_udp, self.listen_tcp, self.announce_loop):
            threading.Thread(target=target, daemon=True).start()

    def hello(self, kind="here"):
        return json.dumps({"kb": 1, "kind": kind, "id": self.id, "name": self.name,
                           "host": self.host, "port": self.port}).encode()

    def announce(self, kind="here", to=None):
        for addr in ([to] if to else broadcasts()):
            try:
                self.udp.sendto(self.hello(kind), (addr, PORT))
            except OSError:
                pass

    def announce_loop(self):
        while self.running:
            self.announce()
            with self.lock:
                gone = [i for i, p in self.people.items() if time.time() - p["seen"] > 16]
                for i in gone:
                    self.events.put(("gone", i, self.people.pop(i)["name"]))
            time.sleep(5)

    def listen_udp(self):
        while self.running:
            try:
                data, (addr, _) = self.udp.recvfrom(2048)
                m = json.loads(data.decode("utf-8", "replace"))
                pid = str(m.get("id", ""))
                if m.get("kb") != 1 or pid == self.id or not re.fullmatch(r"[0-9a-f]{32}", pid):
                    continue
                port = int(m.get("port", 0))
                if not 0 < port < 65536:
                    continue
            except (OSError, ValueError, TypeError):
                continue
            with self.lock:
                if m.get("kind") == "bye":
                    if pid in self.people:
                        self.events.put(("gone", pid, self.people.pop(pid)["name"]))
                    continue
                new = pid not in self.people
                self.people[pid] = dict(name=clean(m.get("name", "?"), 30) or "?", host=clean(m.get("host", ""), 30),
                                        addr=addr, port=port, seen=time.time())
            if new:
                self.events.put(("here", pid))
                self.announce(to=addr)           # so they see us at once too

    def listen_tcp(self):
        while self.running:
            try:
                conn, (addr, _) = self.tcp.accept()
            except OSError:
                continue
            threading.Thread(target=self.receive, args=(conn, addr), daemon=True).start()

    def sender(self, pid, addr):
        """A message is only taken from someone who announced themselves from that address."""
        with self.lock:
            p = self.people.get(pid)
            return p if p and p["addr"] == addr else None

    def receive(self, conn, addr):
        conn.settimeout(30)
        try:
            f = conn.makefile("rwb")
            head = json.loads(f.readline(8192).decode("utf-8", "replace"))
            pid = str(head.get("from", ""))
            if not self.sender(pid, addr):
                return
            if head.get("type") == "msg":
                self.events.put(("msg", pid, clean(head.get("text", "")), bool(head.get("all"))))
            elif head.get("type") == "file":
                name = clean(os.path.basename(str(head.get("name", ""))), 120).lstrip(".") or "file"
                size = int(head.get("size", 0))
                if not 0 <= size <= MAX_FILE:
                    return
                answer = queue.Queue()
                self.events.put(("offer", pid, name, size, answer))
                try:
                    ok = answer.get(timeout=120)
                except queue.Empty:
                    ok = False
                f.write(b"yes\n" if ok else b"no\n")
                f.flush()
                if not ok:
                    return
                os.makedirs(RECEIVED, exist_ok=True)
                path = os.path.join(RECEIVED, name)
                base, ext = os.path.splitext(path)
                n = 2
                while os.path.exists(path):
                    path, n = f"{base} ({n}){ext}", n + 1
                got = 0
                conn.settimeout(60)
                with open(path + ".part", "wb") as out:
                    while got < size:
                        chunk = f.read(min(65536, size - got))
                        if not chunk:
                            break
                        out.write(chunk)
                        got += len(chunk)
                if got == size:
                    os.replace(path + ".part", path)
                    self.events.put(("received", pid, os.path.basename(path)))
                else:
                    os.remove(path + ".part")
                    self.events.put(("note", f"{name} did not arrive whole."))
        except (OSError, ValueError, TypeError):
            pass
        finally:
            conn.close()

    def connect(self, pid):
        with self.lock:
            p = self.people.get(pid)
        if not p:
            raise OSError("they left")
        s = socket.create_connection((p["addr"], p["port"]), timeout=10)
        return s

    def send_text(self, pid, text, everyone=False):
        s = self.connect(pid)
        with s:
            s.sendall(json.dumps({"type": "msg", "from": self.id, "text": text[:MAX_TEXT], "all": everyone}).encode() + b"\n")

    def send_file(self, pid, path, progress):
        size = os.path.getsize(path)
        s = self.connect(pid)
        with s, open(path, "rb") as f:
            s.sendall(json.dumps({"type": "file", "from": self.id, "name": os.path.basename(path), "size": size}).encode() + b"\n")
            s.settimeout(130)                    # while they decide
            reply = s.makefile("rb").readline(16)
            if reply.strip() != b"yes":
                return False
            s.settimeout(60)
            sent = 0
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                s.sendall(chunk)
                sent += len(chunk)
                progress(sent * 100 // max(size, 1))
        return True

    def rename(self, name):
        self.name = clean(name, 30) or self.name
        with open(os.path.join(CONF, "name"), "w") as f:
            f.write(self.name + "\n")
        self.announce()

    def close(self):
        self.running = False
        self.announce("bye")


class Chat:
    """The screen: people on the left, the conversation on the right."""

    def __init__(self, s, net, events):
        self.s, self.net, self.events = s, net, events
        self.talk = {}                       # id (or EVERYONE) -> [(time, who, text)]
        self.unread = set()
        self.chosen = EVERYONE
        self.line = ""
        self.scroll = 0
        self.prompt = None                   # (question, callback) while asking something
        self.offers = []                     # file offers waiting for an answer
        self.status = "Looking for other Kilobyte computers on this network..."

    def log_path(self, pid):
        return os.path.join(CONF, "talk-" + ("everyone" if pid == EVERYONE else pid) + ".log")

    def history(self, pid):
        if pid not in self.talk:
            self.talk[pid] = []
            try:
                with open(self.log_path(pid), encoding="utf-8", errors="replace") as f:
                    for line in f.readlines()[-200:]:
                        t, who, text = (line.rstrip("\n").split("\t", 2) + ["", ""])[:3]
                        self.talk[pid].append((t, clean(who, 30), clean(text)))
            except OSError:
                pass
        return self.talk[pid]

    def add(self, pid, who, text):
        t = time.strftime("%H:%M")
        self.history(pid).append((t, who, text))
        try:
            with open(self.log_path(pid), "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d')} {t}\t{who}\t{text}\n")
        except OSError:
            pass
        if pid != self.chosen:
            self.unread.add(pid)

    def people(self):
        with self.net.lock:
            ps = sorted(self.net.people.items(), key=lambda kv: kv[1]["name"].lower())
        return [(EVERYONE, {"name": "Everyone here", "host": ""})] + ps

    def name_of(self, pid):
        with self.net.lock:
            p = self.net.people.get(pid)
        return p["name"] if p else "someone"

    def notify(self, title, text):
        if os.environ.get("KB_DESK_SOCK"):
            subprocess.Popen(["/usr/lib/kilobyte/kb-notify", title, text[:60]],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def handle(self, ev):
        kind = ev[0]
        if kind == "here":
            self.status = f"{self.name_of(ev[1])} is here."
        elif kind == "gone":
            self.status = f"{ev[2]} left."
            if self.chosen == ev[1]:
                self.chosen = EVERYONE
        elif kind == "msg":
            _, pid, text, everyone = ev
            who = self.name_of(pid)
            self.add(EVERYONE if everyone else pid, who, text)
            kbui.play_sound("message.wav")
            self.notify(f"Message from {who}", text)
        elif kind == "offer":
            self.offers.append(ev)
            self.notify("Messenger", f"{self.name_of(ev[1])} wants to send you {ev[2]}")
        elif kind == "received":
            self.add(ev[1], self.name_of(ev[1]), f"[sent you {ev[2]}: it is in Documents/Received]")
        elif kind == "note":
            self.status = ev[1]
        elif kind == "sent":
            self.status = ev[1]

    def draw(self):
        s = self.s
        h, w = s.size()
        s.fill(LIGHTGREY, BLUE)
        left = min(28, max(18, w // 4))
        s.put(0, 0, " " * w, BLACK, CYAN)
        s.put(0, 1, f"Messenger: you are {self.net.name} on {self.net.host}", BLACK, CYAN)
        s.box(1, 0, h - 4, left, WHITE, BLUE, title="People here")
        people = self.people()
        for i, (pid, p) in enumerate(people[: h - 6]):
            mark = "●" if pid in self.unread else " "
            label = f"{mark}{p['name']}"[: left - 3]
            if pid == self.chosen:
                s.put(2 + i, 1, " " + label.ljust(left - 3), BLACK, CYAN)
            else:
                s.put(2 + i, 1, " " + label, YELLOW if pid in self.unread else LIGHTCYAN, BLUE)
        if len(people) == 1:
            s.put(4, 2, "Nobody else yet."[: left - 3], LIGHTGREY, BLUE)
            for j, t in enumerate(("Others appear here", "when they open", "Messenger on this", "network.")):
                s.put(6 + j, 2, t[: left - 3], LIGHTGREY, BLUE)
        title = "Everyone here" if self.chosen == EVERYONE else \
            f"{self.name_of(self.chosen)} ({self.net.people.get(self.chosen, {}).get('host', '')})"
        cw = w - left
        s.box(1, left, h - 4, cw, WHITE, BLUE, title=title[: cw - 4])
        lines = []
        for t, who, text in self.history(self.chosen):
            prefix = f"{t} {who}: "
            body = text
            width = cw - 3
            first = True
            while body or first:
                room = width - (len(prefix) if first else 2)
                part, body = body[:room], body[room:]
                lines.append((prefix if first else "  ", part, who == self.net.name))
                first = False
        rows = h - 6
        end = max(0, len(lines) - self.scroll)
        for i, (prefix, part, mine) in enumerate(lines[max(0, end - rows):end]):
            s.put(2 + i, left + 1, prefix, LIGHTGREEN if mine else YELLOW, BLUE)
            s.put(2 + i, left + 1 + len(prefix), part, WHITE, BLUE)
        # The typing line, or a question.
        if self.offers:
            _, pid, name, size, _ = self.offers[0]
            q = f"{self.name_of(pid)} wants to send you {name} ({size / 1e6:.1f} MB). Take it? Y/N"
            s.put(h - 3, 0, " " + q[: w - 2].ljust(w - 1), BLACK, YELLOW)
        elif self.prompt:
            s.put(h - 3, 0, f" {self.prompt[0]} {self.line}"[: w - 1].ljust(w - 1), BLACK, CYAN)
        else:
            s.put(h - 3, 0, f" > {self.line}"[-(w - 1):].ljust(w - 1), WHITE, BLACK)
        s.put(h - 2, 0, (" " + self.status)[: w - 1].ljust(w - 1), LIGHTGREY, BLUE)
        s.put(h - 1, 0, " ↑↓ person  Enter send  F2 send a file  F3 your name  PgUp/PgDn scroll  Esc close"[: w - 1].ljust(w - 1),
              BLACK, CYAN)
        s.scr.refresh()

    def send(self, text):
        if self.chosen == EVERYONE:
            targets = [pid for pid, _ in self.people()[1:]]
            if not targets:
                self.status = "Nobody is here to read it yet."
                return
        else:
            targets = [self.chosen]
        self.add(self.chosen, self.net.name, text)
        everyone = self.chosen == EVERYONE

        def go():
            failed = []
            for pid in targets:
                try:
                    self.net.send_text(pid, text, everyone)
                except OSError:
                    failed.append(self.name_of(pid))
            if failed:
                self.events.put(("note", "Did not reach: " + ", ".join(failed)))
        threading.Thread(target=go, daemon=True).start()

    def send_file(self, path):
        path = os.path.expanduser(path.strip().strip("'\""))
        if not os.path.isabs(path):
            path = os.path.join(os.path.expanduser("~/Documents"), path)
        if not os.path.isfile(path):
            self.status = f"There is no file {path}"
            return
        pid = self.chosen
        if pid == EVERYONE:
            self.status = "Choose one person to send a file to."
            return
        who = self.name_of(pid)
        self.status = f"Asking {who} to take {os.path.basename(path)}..."

        def go():
            try:
                ok = self.net.send_file(pid, path, lambda p: self.events.put(("sent", f"Sending to {who}: {p}%")))
                if ok:
                    self.events.put(("sent", f"{who} has {os.path.basename(path)} now."))
                    self.add(pid, self.net.name, f"[sent {os.path.basename(path)}]")
                else:
                    self.events.put(("sent", f"{who} did not take it."))
            except OSError as e:
                self.events.put(("sent", f"Sending did not work: {e}"))
        threading.Thread(target=go, daemon=True).start()

    def key(self, k):
        people = [pid for pid, _ in self.people()]
        if self.offers:
            if k in ("y", "Y", "j", "J", "n", "N", "\x1b"):
                offer = self.offers.pop(0)
                offer[4].put(k in ("y", "Y", "j", "J"))
                if k in ("y", "Y", "j", "J"):
                    self.status = f"Receiving {offer[2]}..."
            return True
        if k in ("\x1b", curses.KEY_F10):
            if self.prompt:
                self.prompt, self.line = None, ""
                return True
            return False
        if k == curses.KEY_UP or k == curses.KEY_DOWN:
            i = people.index(self.chosen) if self.chosen in people else 0
            i = (i + (1 if k == curses.KEY_DOWN else -1)) % len(people)
            self.chosen, self.scroll = people[i], 0
            self.unread.discard(self.chosen)
        elif k == curses.KEY_PPAGE:
            self.scroll += 5
        elif k == curses.KEY_NPAGE:
            self.scroll = max(0, self.scroll - 5)
        elif k == curses.KEY_F2:
            self.prompt, self.line = ("File to send (from Documents, or a full path):", self.send_file), ""
        elif k == curses.KEY_F3:
            self.prompt, self.line = ("Your name:", self.net.rename), self.net.name
        elif k in ("\n", "\r", curses.KEY_ENTER):
            text = self.line.strip()
            self.line = ""
            if self.prompt:
                callback = self.prompt[1]
                self.prompt = None
                if text:
                    callback(text)
            elif text:
                self.scroll = 0
                self.send(text)
        elif k in (curses.KEY_BACKSPACE, "\x7f", "\b"):
            self.line = self.line[:-1]
        elif isinstance(k, str) and k.isprintable():
            if len(self.line) < MAX_TEXT:
                self.line += k
        return True


def main(s):
    events = queue.Queue()
    try:
        net = Net(events)
    except OSError as e:
        curses.endwin()
        print(f"Messenger cannot use the network: {e}")
        input("Press Enter.")
        return
    chat = Chat(s, net, events)
    s.scr.timeout(250)
    try:
        while True:
            while not events.empty():
                chat.handle(events.get())
            chat.unread.discard(chat.chosen)
            chat.draw()
            try:
                k = s.scr.get_wch()
            except curses.error:
                continue
            if k == curses.KEY_RESIZE:
                continue
            if not chat.key(k):
                break
    finally:
        net.close()


if __name__ == "__main__":
    kbui.run(main, mouse=False)
