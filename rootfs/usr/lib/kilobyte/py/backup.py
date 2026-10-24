#!/usr/bin/python3
"""Help Kilobyte's Backup read restic's lists.

    restic snapshots --json | backup.py snapshots
        ID<TAB>DAY AND TIME, newest first
    backup.py ls LIST DIR        what folder DIR held (LIST: restic ls --json)
        d|f<TAB>NAME<TAB>SIZE<TAB>CHANGED
    backup.py find LIST WORDS    files whose name has WORDS in it
        PATH<TAB>SIZE<TAB>CHANGED
"""
import datetime
import json
import os
import sys


def when(text):
    """restic's time (2026-10-21T14:05:09.123+02:00) as local time."""
    try:
        t = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))   # (Python 3.11 and newer)
        return t.astimezone().strftime("%a %d %b %Y, %H:%M")
    except ValueError:
        return text[:16].replace("T", " ")


def size(n):
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024


def nodes(path):
    with open(path) as f:
        for line in f:
            try:
                n = json.loads(line)
            except ValueError:
                continue
            if n.get("struct_type") == "node" or "path" in n and "type" in n:
                yield n


def main(args):
    if args == ["snapshots"]:
        snaps = json.load(sys.stdin) or []
        snaps.sort(key=lambda s: s.get("time", ""), reverse=True)
        for s in snaps:
            print(f"{s.get('short_id') or s['id'][:8]}\t{when(s.get('time', ''))}")
    elif len(args) == 3 and args[0] == "ls":
        top = args[2].rstrip("/") or "/"
        rows = []
        for n in nodes(args[1]):
            if os.path.dirname(n["path"]) == top and n["path"] != top:
                kind = "d" if n["type"] == "dir" else "f"
                rows.append((kind, os.path.basename(n["path"]), size(n.get("size", 0)) if kind == "f" else "",
                             when(n.get("mtime", ""))))
        for r in sorted(rows, key=lambda r: (r[0] != "d", r[1].lower())):
            print("\t".join(r))
    elif len(args) == 3 and args[0] == "find":
        words = args[2].lower()
        found = 0
        for n in nodes(args[1]):
            if n["type"] == "file" and words in os.path.basename(n["path"]).lower():
                print(f"{n['path']}\t{size(n.get('size', 0))}\t{when(n.get('mtime', ''))}")
                found += 1
                if found >= 150:
                    break
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
