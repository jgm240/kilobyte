#!/usr/bin/python3
"""Programs installed with APT (apt install, Settings > Add or remove
programs...), for More programs: those with a menu entry of their own
(/usr/share/applications/*.desktop) from packages that are not part of
Kilobyte itself or its Store.

    aptapps.py table        lines of the Program Manager's table (see
                            apps_table in /usr/bin/kilobyte): Apt:ID|more|...
    aptapps.py graphical    every graphical program with a menu entry (also
                            Kilobyte's own): ID<TAB>NAME<TAB>WHAT IT IS
    aptapps.py exec ID      how to start one: "terminal" or "graphical" on
                            the first line, its name on the second, then the
                            command, a word a line

Graphical programs open in X in a Kilobyte window (kb-xwin); terminal
programs run as they are.
"""
import glob
import os
import re
import shlex
import shutil
import subprocess
import sys

APPS = "/usr/share/applications"
BASE = "/usr/share/kilobyte/packages.txt"          # the image's own packages (kb-update keeps it)
STORE = "/usr/share/kilobyte/store.tsv"
LANG = (os.environ.get("LANG") or "").split(".")[0]


def entry(path):
    """The [Desktop Entry] of a .desktop file, as a dict (in this language
    where it has one)."""
    d, section = {}, None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith("["):
                    section = line
                    continue
                if section != "[Desktop Entry]" or "=" not in line or line.startswith("#"):
                    continue
                k, v = (x.strip() for x in line.split("=", 1))
                if k.endswith("[%s]" % LANG) or k.endswith("[%s]" % LANG.split("_")[0]):
                    d[k.split("[")[0] + "@"] = v
                elif "[" not in k:
                    d[k] = v
    except OSError:
        return {}
    for k in ("Name", "Comment", "GenericName"):
        if k + "@" in d:
            d[k] = d.pop(k + "@")
    return d


def command(d):
    """The command of an entry, without its %f-style codes; None if it is
    not there."""
    try:
        words = shlex.split(d.get("Exec", ""))
    except ValueError:
        return None
    words = [w for w in words if not re.fullmatch(r"%[a-zA-Z]", w)]
    words = [w.replace("%%", "%") for w in words]
    if not words:
        return None
    try_exec = d.get("TryExec")
    if try_exec and not shutil.which(try_exec):
        return None
    if not shutil.which(words[0]):
        return None
    return words


def shown(d):
    return (d.get("Type", "Application") == "Application" and d.get("NoDisplay", "").lower() != "true" and
            d.get("Hidden", "").lower() != "true" and not d.get("OnlyShowIn") and d.get("Name"))


def all_entries():
    """(ID, entry, command) of every program with a menu entry."""
    out = []
    for path in sorted(glob.glob(os.path.join(APPS, "*.desktop"))):
        d = entry(path)
        if not shown(d):
            continue
        cmd = command(d)
        if cmd:
            out.append((os.path.basename(path)[:-8], d, cmd))
    return out


def owners(paths):
    """{path: package} for the files given (dpkg's own lists)."""
    if not paths:
        return {}
    try:
        res = subprocess.run(["dpkg-query", "-S"] + paths, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return {}
    found = {}
    for line in res.stdout.splitlines():
        pkgs, _, path = line.partition(": ")
        if path:
            found[path.strip()] = pkgs.split(",")[0].split(":")[0].strip()
    return found


def kilobytes_own():
    """The packages Kilobyte brings and the Store's."""
    own = set()
    try:
        with open(BASE) as f:
            own.update(f.read().split())
    except OSError:
        pass
    try:
        with open(STORE, encoding="utf-8") as f:
            for line in f:
                fields = line.split("|")
                if len(fields) > 2 and not line.startswith("#"):
                    own.update(fields[1].split())
    except OSError:
        pass
    return own


def graphical_ok():
    """Whether graphical programs can be shown (not on a Kindle)."""
    try:
        with open("/etc/kilobyte/variant") as f:
            return f.read().strip() != "kindle"
    except OSError:
        return True


def table():
    entries = all_entries()
    pkgs = owners([os.path.join(APPS, i + ".desktop") for i, _, _ in entries])
    own = kilobytes_own()
    gui_ok = graphical_ok()
    for i, d, _ in entries:
        pkg = pkgs.get(os.path.join(APPS, i + ".desktop"))
        if not pkg or pkg in own or pkg.startswith("kilobyte"):
            continue                               # (made by hand, or Kilobyte's own)
        terminal = d.get("Terminal", "").lower() == "true"
        if not terminal and not gui_ok:
            continue
        name = d["Name"].replace("|", "/")[:40]
        what = (d.get("Comment") or d.get("GenericName") or "Installed with APT").replace("|", "/")
        what = what[:70] + ("" if terminal else " (a graphical program: opens in X)")
        icon = (re.sub(r"[^A-Za-z0-9]", "", name)[:2] or "▣ ").ljust(2)
        print("Apt:%s|more|%s|%s|%s|%s" % (i.replace("|", ""), name, what, icon, "M" if terminal else "L"))


def graphical():
    for i, d, _ in all_entries():
        if d.get("Terminal", "").lower() != "true":
            what = d.get("Comment") or d.get("GenericName") or ""
            print("%s\t%s\t%s" % (i, d["Name"][:40], what[:70]))


def exec_(ident):
    path = os.path.join(APPS, os.path.basename(ident) + ".desktop")
    d = entry(path)
    cmd = command(d) if d else None
    if not cmd:
        return 1
    print("terminal" if d.get("Terminal", "").lower() == "true" else "graphical")
    print(d.get("Name", ident))
    for w in cmd:
        print(w)
    return 0


def main(argv):
    if argv[:1] == ["table"]:
        table()
    elif argv[:1] == ["graphical"]:
        graphical()
    elif argv[:1] == ["exec"] and len(argv) == 2:
        return exec_(argv[1])
    else:
        sys.exit(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
