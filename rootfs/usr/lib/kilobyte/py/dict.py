#!/usr/bin/python3
"""Kilobyte's dictionary and translator.

    dict.py define WORD [WIDTH]     meanings of an English word: from the
                                    dictionaries in /usr/share/dictd (WordNet,
                                    without the Internet), else from dict.org
    dict.py translate FROM TO TEXT  TEXT in another language (on-line, MyMemory);
                                    FROM may be "auto"

define fails with status 2 and prints words that look alike when there is
no such word.
"""
import difflib
import glob
import json
import os
import socket
import struct
import sys
import textwrap
import urllib.parse
import urllib.request
import zlib

DICTD = "/usr/share/dictd"
B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
NAMES = {"wn": "WordNet", "gcide": "Collaborative International Dictionary of English"}


def b64num(s):
    n = 0
    for c in s:
        n = n * 64 + B64.index(c)
    return n


class DictZip:
    """Reads a piece of a .dict.dz file without unpacking all of it: dictzip
    files are gzip files made of chunks that can be unpacked one by one."""

    def __init__(self, path):
        self.f = open(path, "rb")
        h = self.f.read(10)
        if h[:2] != b"\x1f\x8b":
            raise ValueError("not gzip")
        flags = h[3]
        self.chunks = None
        if flags & 4:
            xlen = struct.unpack("<H", self.f.read(2))[0]
            extra = self.f.read(xlen)
            i = 0
            while i + 4 <= len(extra):
                sid, slen = extra[i:i + 2], struct.unpack("<H", extra[i + 2:i + 4])[0]
                if sid == b"RA":
                    _, self.chlen, count = struct.unpack("<HHH", extra[i + 4:i + 10])
                    self.chunks = struct.unpack("<%dH" % count, extra[i + 10:i + 10 + 2 * count])
                i += 4 + slen
        for bit in (8, 16):                         # file name, comment
            if flags & bit:
                while self.f.read(1) not in (b"\0", b""):
                    pass
        if flags & 2:
            self.f.read(2)
        self.start = self.f.tell()
        if self.chunks:
            self.where = [self.start]
            for c in self.chunks:
                self.where.append(self.where[-1] + c)

    def read(self, off, length):
        if not self.chunks:                         # a plain gzip file: unpack from the start
            import gzip
            with gzip.open(self.f.name) as g:
                g.seek(off)
                return g.read(length)
        first, last = off // self.chlen, (off + length - 1) // self.chlen
        out = b""
        for n in range(first, min(last, len(self.chunks) - 1) + 1):
            self.f.seek(self.where[n])
            out += zlib.decompressobj(-15).decompress(self.f.read(self.chunks[n]))
        skip = off - first * self.chlen
        return out[skip:skip + length]


def local_dicts():
    out = []
    for idx in sorted(glob.glob(os.path.join(DICTD, "*.index"))):
        base = idx[:-6]
        data = base + ".dict.dz" if os.path.exists(base + ".dict.dz") else base + ".dict"
        if os.path.exists(data):
            out.append((os.path.basename(base), idx, data))
    # WordNet first: short, clear meanings.
    out.sort(key=lambda d: (d[0] != "wn", d[0]))
    return out


def lookup_local(word):
    """[(dictionary, text)] and words that look alike."""
    found, alike = [], set()
    w = word.lower().encode()
    for name, idx, data in local_dicts():
        raw = open(idx, "rb").read()
        low = raw.lower()
        hits, pos = [], 0
        while True:
            pos = low.find(b"\n" + w + b"\t", pos)
            if pos < 0:
                break
            line = raw[pos + 1:raw.index(b"\n", pos + 1)].decode("utf-8", "replace").split("\t")
            hits.append(line)
            pos += 1
        if low.startswith(w + b"\t"):
            hits.insert(0, raw[:raw.index(b"\n")].decode("utf-8", "replace").split("\t"))
        if hits:
            dz = DictZip(data) if data.endswith(".dz") else None
            for h in hits:
                off, length = b64num(h[1]), b64num(h[2])
                if dz:
                    text = dz.read(off, length)
                else:
                    with open(data, "rb") as f:
                        f.seek(off)
                        text = f.read(length)
                found.append((NAMES.get(name, name), text.decode("utf-8", "replace")))
        elif len(w) >= 2:
            # Headwords with the same first two letters, the closest few.
            cands, pos = [], 0
            key = b"\n" + w[:2]
            while len(cands) < 20000:
                pos = low.find(key, pos)
                if pos < 0:
                    break
                end = low.index(b"\t", pos + 1)
                cands.append(raw[pos + 1:end].decode("utf-8", "replace"))
                pos = end
            alike.update(difflib.get_close_matches(word.lower(), [c.lower() for c in cands], 8, 0.75))
    return found, sorted(alike)


def lookup_online(word):
    """[(dictionary, text)] from dict.org (the DICT protocol)."""
    out = []
    s = socket.create_connection(("dict.org", 2628), timeout=15)
    f = s.makefile("rwb")
    f.readline()
    for db in ("wn", "gcide"):
        f.write(b'DEFINE %s "%s"\r\n' % (db.encode(), word.replace('"', "").encode()))
        f.flush()
        status = f.readline()
        if not status.startswith(b"150"):
            continue
        while True:
            line = f.readline()
            if line.startswith(b"151"):
                text = []
                while True:
                    t = f.readline()
                    if t in (b".\r\n", b""):
                        break
                    text.append(t.decode("utf-8", "replace").rstrip("\r\n").removeprefix(".."))
                out.append((NAMES.get(db, db) + " (dict.org)", "\n".join(text)))
            else:
                break                               # 250 ok
    f.write(b"QUIT\r\n")
    f.flush()
    s.close()
    return out


def define(word, width):
    found, alike = lookup_local(word)
    if not found:
        try:
            found = lookup_online(word)
        except OSError:
            if not local_dicts():
                sys.exit("There is no dictionary on this computer and no Internet connection.")
    if not found:
        for a in alike:
            print(a)
        sys.exit(2)
    for name, text in found:
        print("── %s " % name + "─" * max(0, width - len(name) - 4))
        for line in text.strip("\n").split("\n"):
            ind = len(line) - len(line.lstrip())
            print(textwrap.fill(line.strip(), width, initial_indent=" " * ind,
                                subsequent_indent=" " * (ind + 2)) if line.strip() else "")
        print()


def translate(src, dst, text):
    out = []
    # MyMemory takes up to 500 bytes at a time: sentence by sentence.
    parts, cur = [], ""
    for piece in text.replace("\n", " ").split(". "):
        if len((cur + piece).encode()) > 450 and cur:
            parts.append(cur)
            cur = ""
        cur += piece + ". "
    parts.append(cur.rstrip(". ") + ("." if text.rstrip().endswith(".") else ""))
    for p in parts:
        if not p.strip():
            continue
        q = urllib.parse.urlencode({"q": p.strip(), "langpair": "%s|%s" % ("Autodetect" if src == "auto" else src, dst)})
        req = urllib.request.Request("https://api.mymemory.translated.net/get?" + q,
                                     headers={"User-Agent": "Kilobyte"})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.load(r)
        if str(d.get("responseStatus")) not in ("200", "None"):
            sys.exit(d.get("responseDetails") or "The translation service did not answer.")
        out.append(d["responseData"]["translatedText"])
    import html
    print(html.unescape(" ".join(out)))


if __name__ == "__main__":
    a = sys.argv[1:]
    try:
        if len(a) >= 2 and a[0] == "define":
            define(a[1], int(a[2]) if len(a) > 2 else 72)
        elif len(a) >= 4 and a[0] == "translate":
            translate(a[1], a[2], " ".join(a[3:]))
        else:
            sys.exit(__doc__)
    except OSError as e:
        sys.exit("No answer (is the computer on-line?): %s" % e)
    except (ValueError, KeyError) as e:
        sys.exit("Something went wrong: %s" % e)
