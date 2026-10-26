#!/usr/bin/env python3
"""Kilobyte's own themes for the website's theme gallery: site/themes/builtin.json
(name and code of each) and site/themes/files/NAME.kbtheme (to download).
The gallery's other themes come from people (Settings > Colour theme > Theme
editor > Upload), approved by .github/workflows/theme-gallery.yml.

    python3 tools/make-theme-gallery.py
"""
import json
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "rootfs", "usr", "lib", "kilobyte", "py"))
import themes  # noqa: E402

SRC = os.path.join(ROOT, "rootfs", "usr", "share", "kilobyte", "themes")
OUT = os.path.join(ROOT, "site", "themes")
ORDER = ["classic", "panels", "cyan", "lightblue", "orange", "mono", "green", "amber", "mustard", "eink"]

os.makedirs(os.path.join(OUT, "files"), exist_ok=True)
out = []
for key in ORDER + sorted(set(os.listdir(SRC)) - set(ORDER)):
    d = os.path.join(SRC, key)
    if not os.path.isfile(os.path.join(d, "dialogrc")):
        continue
    t = themes.from_dir(d)
    code = themes.to_code(t)
    out.append({"name": t["name"], "by": "Kilobyte", "code": code, "file": "files/%s.kbtheme" % key})
    with open(os.path.join(OUT, "files", key + ".kbtheme"), "w") as f:
        f.write(themes.conf_text(t))
with open(os.path.join(OUT, "builtin.json"), "w") as f:
    json.dump(out, f, indent=1, ensure_ascii=False)
print("%d themes -> %s" % (len(out), OUT))
