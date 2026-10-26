#!/usr/bin/env python3
"""The theme gallery: add the theme in an approved issue (label theme-approved).

    add-theme.py EVENT.json SITE-THEMES-DIR OUT-DIR

Reads the issue from the event, as data: "kbtheme: CODE" and "by: NAME" in its
body. The code is checked by Kilobyte's own themes.py (only colours, a name
and a few switches can be in it). Writes themes/gallery.json and
themes/files/NAME.kbtheme in SITE-THEMES-DIR, and for the workflow in OUT-DIR:
ok (yes/no), message.txt (the commit), comment.txt (for the issue).
"""
import datetime
import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "rootfs", "usr", "lib", "kilobyte", "py"))
import themes  # noqa: E402

event_path, site, out = sys.argv[1:4]
issue = json.load(open(event_path)).get("issue") or {}
body = issue.get("body") or ""
number = issue.get("number")


def finish(ok, comment, message=""):
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, "ok"), "w").write("yes" if ok else "no")
    open(os.path.join(out, "comment.txt"), "w").write(comment)
    open(os.path.join(out, "message.txt"), "w").write(message)
    sys.exit(0)


m = re.search(r"kbtheme:\s*([A-Za-z0-9_-]{20,200})\b", body)
if not m:
    finish(False, "There is no theme code (`kbtheme: ...`) in this issue, so nothing was added to the gallery.")
code = m.group(1)
try:
    t = themes.from_code(code)
except (ValueError, UnicodeDecodeError) as e:
    finish(False, "The theme code could not be read (%s), so nothing was added." % e)
by = ""
b = re.search(r"^by:[ \t]*([^\n]*)$", body, re.M)
if b:
    by = re.sub(r"[^\w .-]", "", b.group(1))[:30].strip()

path = os.path.join(site, "gallery.json")
try:
    gallery = json.load(open(path))
except (OSError, ValueError):
    gallery = []
if any(g.get("code") == code for g in gallery):
    finish(False, "This theme is in the gallery already.")
slug = re.sub(r"[^a-z0-9]+", "-", t["name"].lower()).strip("-")[:30] or "theme"
n, base = 2, slug
while any(g.get("file") == "files/%s.kbtheme" % slug for g in gallery):
    slug, n = "%s-%d" % (base, n), n + 1
os.makedirs(os.path.join(site, "files"), exist_ok=True)
with open(os.path.join(site, "files", slug + ".kbtheme"), "w") as f:
    f.write(themes.conf_text(t))
gallery.append({"name": t["name"], "by": by, "code": code, "file": "files/%s.kbtheme" % slug,
                "added": datetime.date.today().isoformat(), "issue": number})
with open(path, "w") as f:
    json.dump(gallery, f, indent=1, ensure_ascii=False)
finish(True, "Thank you! **%s** is in the gallery now: https://jgm240.github.io/kilobyte/themes.html "
             "(and in Kilobyte: Settings > Colour theme > Theme editor > Gallery)." % t["name"],
       "Theme gallery: %s%s (#%s)" % (t["name"], " by " + by if by else "", number))
