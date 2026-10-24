#!/usr/bin/python3
"""Kilobyte's BBS terminal: telnet to a bulletin board system, the way BBS
programs do it.

    bbsterm.py HOST [PORT] [--utf8 | --cp437]

Most boards send the IBM PC's characters (CP437), newer ones (such as hostbbs)
UTF-8: which it is, is told from the first letters beyond plain ASCII, and
shown as it was meant to look (--utf8 or --cp437 decide it beforehand). The window's size is sent to the
board. A file the board sends with ZMODEM is received by itself, into
~/Downloads (with lrzsz's rz). Ctrl+] then Q hangs up (in Kilobyte, Ctrl+C
does too).
"""
import codecs
import os
import select
import signal
import socket
import struct
import subprocess
import sys
import termios
import time
import tty

IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240
BINARY, ECHO, SGA, TTYPE, NAWS = 0, 1, 3, 24, 31
ZRQINIT = b"**\x18B00"                       # a ZMODEM sender's first words
DOWNLOADS = os.path.expanduser("~/Downloads")


class Term:
    def __init__(self, host, port, charset=None):
        self.sock = socket.create_connection((host, port), timeout=20)
        self.sock.settimeout(None)
        self.charset = charset               # "utf-8", "cp437", or None: not known yet
        self.utf8 = codecs.getincrementaldecoder("utf-8")("replace")
        self.raw = b""
        self.naws = False
        self.tail = b""                      # the last bytes shown, to spot ZMODEM across reads
        self.resized = False
        signal.signal(signal.SIGWINCH, lambda *a: setattr(self, "resized", True))

    def send(self, data):
        self.sock.sendall(data)

    def size(self):
        try:
            rows, cols = struct.unpack("HH", fcntl_ioctl())
        except OSError:
            rows, cols = 24, 80
        return cols or 80, rows or 24

    def send_size(self):
        if self.naws:
            cols, rows = self.size()
            sub = struct.pack(">HH", cols, rows).replace(b"\xff", b"\xff\xff")
            self.send(bytes([IAC, SB, NAWS]) + sub + bytes([IAC, SE]))

    def negotiate(self, cmd, opt):
        if cmd == DO:
            if opt == NAWS:
                self.naws = True
                self.send(bytes([IAC, WILL, NAWS]))
                self.send_size()
            elif opt in (TTYPE, BINARY, SGA):
                self.send(bytes([IAC, WILL, opt]))
            else:
                self.send(bytes([IAC, WONT, opt]))
        elif cmd == WILL:
            self.send(bytes([IAC, DO if opt in (ECHO, SGA, BINARY) else DONT, opt]))

    def data(self, chunk):
        """Telnet codes answered, the board's data returned."""
        r = self.raw + chunk
        out = bytearray()
        i = 0
        while i < len(r):
            b = r[i]
            if b != IAC:
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
                self.negotiate(cmd, r[i + 2])
                i += 3
            elif cmd == SB:
                end = r.find(bytes([IAC, SE]), i)
                if end < 0:
                    break
                if r[i + 2:i + 4] == bytes([TTYPE, 1]):      # SEND: we are an ANSI terminal
                    self.send(bytes([IAC, SB, TTYPE, 0]) + b"ANSI" + bytes([IAC, SE]))
                i = end + 2
            else:
                i += 2
        self.raw = r[i:]
        return bytes(out)

    def show(self, data):
        if self.charset is None and any(b >= 0x80 for b in data):
            try:                             # valid UTF-8 (perhaps cut off at the end)?
                codecs.getincrementaldecoder("utf-8")().decode(data, False)
                self.charset = "utf-8"
            except UnicodeDecodeError:
                self.charset = "cp437"
        text = self.utf8.decode(data) if self.charset == "utf-8" else data.decode("cp437")
        os.write(1, text.encode("utf-8", "replace"))

    def zmodem(self, first):
        """Receive files with rz, from the bytes that began it on."""
        os.makedirs(DOWNLOADS, exist_ok=True)
        os.write(1, b"\r\n\x1b[1m[ZMODEM: receiving into ~/Downloads]\x1b[0m\r\n")
        try:
            rz = subprocess.Popen(["rz", "-b", "-E", "-q"], cwd=DOWNLOADS, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            os.write(1, b"[rz is not installed: kbutils dl bbs]\r\n")
            self.send(b"\x18" * 10 + b"\x08" * 10)          # cancel
            return
        before = set(os.listdir(DOWNLOADS))
        rz.stdin.write(first)
        rz.stdin.flush()
        out = rz.stdout.fileno()
        while rz.poll() is None:
            r, _, _ = select.select([self.sock, out], [], [], 30)
            if not r:
                break
            if self.sock in r:
                chunk = self.sock.recv(65536)
                if not chunk:
                    break
                try:
                    rz.stdin.write(self.data(chunk))
                    rz.stdin.flush()
                except BrokenPipeError:
                    break
            if out in r:
                d = os.read(out, 65536)
                if d:
                    self.send(d.replace(b"\xff", b"\xff\xff"))
        if rz.poll() is None:
            rz.kill()
        rz.wait()
        got = sorted(set(os.listdir(DOWNLOADS)) - before)
        msg = f"[received: {', '.join(got)}]" if got else "[nothing was received]"
        os.write(1, f"\r\n\x1b[1m{msg}\x1b[0m\r\n".encode())

    def run(self):
        old = termios.tcgetattr(0)
        tty.setraw(0)
        menu = False
        try:
            while True:
                if self.resized:
                    self.resized = False
                    self.send_size()
                try:
                    r, _, _ = select.select([self.sock, 0], [], [], 1)
                except InterruptedError:
                    continue
                if self.sock in r:
                    chunk = self.sock.recv(65536)
                    if not chunk:
                        break
                    data = self.data(chunk)
                    look = self.tail + data
                    at = look.find(ZRQINIT)
                    if at >= 0:
                        start = at - len(self.tail)
                        self.show(data[:max(0, start)])
                        self.zmodem(look[at:])
                        self.tail = b""
                        continue
                    self.show(data)
                    self.tail = data[-8:]
                if 0 in r:
                    keys = os.read(0, 1024)
                    if not keys:
                        break
                    if menu:
                        menu = False
                        if keys[:1] in (b"q", b"Q"):
                            break
                        os.write(1, b"\r\n")
                        continue
                    if b"\x1d" in keys:                      # Ctrl+]
                        keys, _, _ = keys.partition(b"\x1d")
                        menu = True
                        os.write(1, b"\r\n\x1b[7m Q hangs up, any other key goes back \x1b[0m")
                    # Enter is CR NUL in telnet.
                    keys = keys.replace(b"\xff", b"\xff\xff").replace(b"\r", b"\r\x00")
                    if keys:
                        self.send(keys)
        finally:
            termios.tcsetattr(0, termios.TCSADRAIN, old)
            os.write(1, b"\x1b[0m\r\nNO CARRIER\r\n")
            self.sock.close()


def fcntl_ioctl():
    import fcntl
    return fcntl.ioctl(1, termios.TIOCGWINSZ, b"\0" * 8)[:4]


def main(args):
    charset = "utf-8" if "--utf8" in args else "cp437" if "--cp437" in args else None
    args = [a for a in args if a not in ("--utf8", "--cp437")]
    if not args:
        sys.exit(__doc__)
    host = args[0]
    port = int(args[1]) if len(args) > 1 else 23
    try:
        t = Term(host, port, charset)
    except OSError as e:
        sys.exit(f"{host} did not answer: {e}")
    t.run()


if __name__ == "__main__":
    main(sys.argv[1:])
