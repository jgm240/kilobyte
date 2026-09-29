#!/usr/bin/env python3
"""Draw the Kilobyte boot logo for every stage of the boot:

  rootfs/usr/share/kilobyte/grub/   GRUB theme (logo.png, frame pieces, theme.txt)
  rootfs/usr/lib/kilobyte/bootlogo  the same logo in block characters, pinned
                                    to the top of the console while the kernel
                                    and systemd messages scroll below it

    python3 tools/make-bootlogo.py
"""
import os
import struct
import zlib

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rootfs")

LETTERS = {
    "K": ["#..#", "#.#.", "##..", "#.#.", "#..#"],
    "I": ["###", ".#.", ".#.", ".#.", "###"],
    "L": ["#...", "#...", "#...", "#...", "####"],
    "O": [".##.", "#..#", "#..#", "#..#", ".##."],
    "B": ["###.", "#..#", "###.", "#..#", "###."],
    "Y": ["#...#", ".#.#.", "..#..", "..#..", "..#.."],
    "T": ["#####", "..#..", "..#..", "..#..", "..#.."],
    "E": ["####", "#...", "###.", "#...", "####"],
}
WORD = "KILOBYTE"
BLUE, CYAN, WHITE, GREY, DARK = (0, 0, 0xAA), (0x55, 0xFF, 0xFF), (0xFF, 0xFF, 0xFF), (0xAA, 0xAA, 0xAA), (0, 0, 0x55)


def bitmap():
    rows = [""] * 5
    for i, ch in enumerate(WORD):
        for r in range(5):
            rows[r] += ("." if i else "") + LETTERS[ch][r]
    return rows


def png(path, pixels):
    h, w = len(pixels), len(pixels[0])
    raw = b"".join(b"\x00" + bytes(v for px in row for v in px) for row in pixels)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def grub_theme():
    out = os.path.join(ROOT, "usr/share/kilobyte/grub")
    os.makedirs(out, exist_ok=True)
    bits, S = bitmap(), 16                    # one logo pixel = 16x16 screen pixels
    w, h = len(bits[0]) * S + S // 2, len(bits) * S + S // 2
    img = [[BLUE] * w for _ in range(h)]
    for y, row in enumerate(bits):            # dark shadow first, then the letters
        for x, c in enumerate(row):
            if c == "#":
                for dy in range(S):
                    for dx in range(S):
                        img[y * S + dy + S // 2][x * S + dx + S // 2] = DARK
    for y, row in enumerate(bits):
        for x, c in enumerate(row):
            if c == "#":
                for dy in range(S):
                    for dx in range(S):
                        img[y * S + dy][x * S + dx] = CYAN
    png(os.path.join(out, "logo.png"), img)
    # Frame pieces: a white double line around the menu, a grey bar for the choice.
    for style, edge, fill in (("menu", WHITE, BLUE), ("sel", GREY, GREY)):
        for part, size in (("nw", (6, 6)), ("n", (1, 6)), ("ne", (6, 6)), ("w", (6, 1)), ("c", (1, 1)),
                           ("e", (6, 1)), ("sw", (6, 6)), ("s", (1, 6)), ("se", (6, 6))):
            pw, ph = size
            pix = []
            for y in range(ph):
                row = []
                for x in range(pw):
                    on = False
                    if style == "menu" and part != "c":
                        # two lines: pixels 0-1 and 4-5 counted from the outside
                        dx = x if "w" in part else pw - 1 - x if "e" in part else None
                        dy = y if "n" in part else ph - 1 - y if "s" in part else None
                        on = any(d is not None and d in (0, 1, 4, 5) for d in (dx, dy))
                        if dx is not None and dy is not None:       # corners
                            on = min(dx, dy) in (0, 1, 4, 5)
                    row.append(edge if on else fill)
                pix.append(row)
            png(os.path.join(out, "%s_%s.png" % (style, part)), pix)
    lw = w
    with open(os.path.join(out, "theme.txt"), "w") as f:
        f.write('''# Kilobyte boot menu (made by tools/make-bootlogo.py)
title-text: ""
desktop-color: "#0000aa"
terminal-font: "Unifont Regular 16"
terminal-box: "menu_*.png"

+ image {
    left = 50%%-%d
    top = 8%%
    file = "logo.png"
}
+ label {
    left = 0
    top = 8%%+%d
    width = 100%%
    align = "center"
    color = "#aaaaaa"
    font = "Unifont Regular 16"
    text = "The text-mode desktop - Debian GNU/Linux"
}
+ boot_menu {
    left = 50%%-300
    top = 8%%+%d
    width = 600
    height = 176
    item_font = "Unifont Regular 16"
    item_color = "#ffffff"
    selected_item_font = "Unifont Regular 16"
    selected_item_color = "#0000aa"
    selected_item_pixmap_style = "sel_*.png"
    menu_pixmap_style = "menu_*.png"
    item_height = 24
    item_padding = 8
    item_spacing = 4
    icon_width = 0
    icon_height = 0
    item_icon_space = 0
    scrollbar = false
}
+ label {
    id = "__timeout__"
    left = 0
    top = 8%%+%d
    width = 100%%
    align = "center"
    color = "#55ffff"
    font = "Unifont Regular 16"
    text = "Starting in %%d seconds. Arrow keys choose, Enter starts, E edits."
}
''' % (lw // 2, h + 16, h + 56, h + 250))


def console_logo():
    """Half blocks: two logo rows per text line."""
    bits = bitmap() + ["." * len(bitmap()[0])]
    lines = []
    for r in range(0, len(bits), 2):
        top, bot = bits[r], bits[r + 1]
        lines.append("".join({("#", "#"): "█", ("#", "."): "▀", (".", "#"): "▄"}.get((a, b), " ")
                             for a, b in zip(top, bot)).rstrip())
    body = "\n".join("printf '\\033[44m\\033[K   \\033[1;36m%s\\033[0;44m\\n'" % l for l in lines)
    script = '''#!/bin/sh
# The Kilobyte logo at the top of the console during start-up (made by
# tools/make-bootlogo.py). The kernel's and systemd's messages scroll in the
# lines below it (a scroll region), so the whole start is visible.
# Runs in the initramfs (scripts/*/kilobyte-logo) and again after the
# console font is loaded (kilobyte-bootlogo.service).
v=""
read -r v 2>/dev/null < /usr/lib/kilobyte/version || v=$(sed -n 's/^KB_VERSION="\\(.*\\)"/\\1/p' /usr/lib/kilobyte/lib.sh 2>/dev/null)
# "bootlogo again" draws it over whatever is on the screen (after the console
# changed size or font) and carries on at the bottom.
[ "$1" = again ] || printf '\\033[0m\\033[2J'
printf '\\033[0m\\033[r\\033[H\\033[44m\\033[K\\n'
%s
printf '\\033[44m\\033[K   \\033[0;37;44mKilobyte %%s - starting up\\033[0;44m\\n' "$v"
printf '\\033[44m\\033[K\\033[0m\\n\\033[K'
# Everything from line 8 down scrolls; the logo stays.
if [ "$1" = again ]; then printf '\\033[8r\\033[999;1H'; else printf '\\033[8r\\033[8;1H'; fi
''' % body
    path = os.path.join(ROOT, "usr/lib/kilobyte/bootlogo")
    with open(path, "w") as f:
        f.write(script)
    os.chmod(path, 0o755)


if __name__ == "__main__":
    grub_theme()
    console_logo()
    print("\n".join(bitmap()))
