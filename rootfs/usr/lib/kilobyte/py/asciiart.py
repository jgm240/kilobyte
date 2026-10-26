#!/usr/bin/python3
"""ASCII Art Generator: a heading in big letters, a subheading, and art (big
letters, a picture made of characters, or your own text) in a border of any
characters; as text, and printed portrait or landscape to fill the page.

    asciiart.py get KEY | set KEY VALUE | reset    the work, in its settings file
    asciiart.py render [OUT]                       the art (on standard output)
    asciiart.py fonts                              the big-letter fonts
    asciiart.py printopts OUT portrait|landscape   lp options that fit it on a page

The work is kept in ~/.config/kilobyte/asciiart.json. Big letters come from
figlet (its fonts), else from a built-in block font.
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys
import unicodedata

CONF = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "kilobyte", "asciiart.json")
FIGLET_DIR = "/usr/share/figlet"

DEFAULT = {
    "heading": "", "heading_font": "standard",    # a figlet font, "plain" or "blocks" (built in)
    "subheading": "",
    "body": "big",                                  # big | picture | text | none
    "body_text": "Kilobyte",                        # for big letters, or your own text
    "body_font": "slant",
    "picture": "", "width": 70,                     # picture: its width in characters
    "ramp": "classic",                              # classic | blocks | dense | letters | your own characters
    "invert": False,
    "border": "double",                             # see BORDERS, "none", or "custom"
    "border_chars": "*",
    "padding": 1,
    "divider": True,                                # a line between the headings and the art
    "align": "center",                              # center | left
}

BORDERS = {  # top-left, top-right, bottom-left, bottom-right, horizontal, vertical
    "single": "┌┐└┘─│", "double": "╔╗╚╝═║", "heavy": "┏┓┗┛━┃", "rounded": "╭╮╰╯─│",
    "ascii": "++++-|", "stars": "******", "hash": "######", "dots": "......", "blocks": "████▀█",
}
RAMPS = {"classic": " .:-=+*#%@", "blocks": " ░▒▓█", "dense": " .'`^\",:;Il!i><~+_-?][}{1)(|/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$",
         "letters": " .oO0@"}

# A built-in 5-row block font (when figlet is not there): '#' is a lit cell.
FONT = {
    "A": [" ### ", "#   #", "#####", "#   #", "#   #"], "B": ["#### ", "#   #", "#### ", "#   #", "#### "],
    "C": [" ####", "#    ", "#    ", "#    ", " ####"], "D": ["#### ", "#   #", "#   #", "#   #", "#### "],
    "E": ["#####", "#    ", "#### ", "#    ", "#####"], "F": ["#####", "#    ", "#### ", "#    ", "#    "],
    "G": [" ####", "#    ", "# ###", "#   #", " ####"], "H": ["#   #", "#   #", "#####", "#   #", "#   #"],
    "I": ["###", " # ", " # ", " # ", "###"], "J": ["  ###", "    #", "    #", "#   #", " ### "],
    "K": ["#   #", "#  # ", "###  ", "#  # ", "#   #"], "L": ["#    ", "#    ", "#    ", "#    ", "#####"],
    "M": ["#   #", "## ##", "# # #", "#   #", "#   #"], "N": ["#   #", "##  #", "# # #", "#  ##", "#   #"],
    "O": [" ### ", "#   #", "#   #", "#   #", " ### "], "P": ["#### ", "#   #", "#### ", "#    ", "#    "],
    "Q": [" ### ", "#   #", "# # #", "#  # ", " ## #"], "R": ["#### ", "#   #", "#### ", "#  # ", "#   #"],
    "S": [" ####", "#    ", " ### ", "    #", "#### "], "T": ["#####", "  #  ", "  #  ", "  #  ", "  #  "],
    "U": ["#   #", "#   #", "#   #", "#   #", " ### "], "V": ["#   #", "#   #", "#   #", " # # ", "  #  "],
    "W": ["#   #", "#   #", "# # #", "## ##", "#   #"], "X": ["#   #", " # # ", "  #  ", " # # ", "#   #"],
    "Y": ["#   #", " # # ", "  #  ", "  #  ", "  #  "], "Z": ["#####", "   # ", "  #  ", " #   ", "#####"],
    "0": [" ### ", "#  ##", "# # #", "##  #", " ### "], "1": ["  #  ", " ##  ", "  #  ", "  #  ", " ### "],
    "2": [" ### ", "#   #", "  ## ", " #   ", "#####"], "3": ["#### ", "    #", " ### ", "    #", "#### "],
    "4": ["#  # ", "#  # ", "#####", "   # ", "   # "], "5": ["#####", "#    ", "#### ", "    #", "#### "],
    "6": [" ### ", "#    ", "#### ", "#   #", " ### "], "7": ["#####", "    #", "   # ", "  #  ", "  #  "],
    "8": [" ### ", "#   #", " ### ", "#   #", " ### "], "9": [" ### ", "#   #", " ####", "    #", " ### "],
    " ": ["   ", "   ", "   ", "   ", "   "], "-": ["     ", "     ", " ### ", "     ", "     "],
    "!": ["#", "#", "#", " ", "#"], ".": [" ", " ", " ", " ", "#"], "?": [" ### ", "#   #", "  ## ", "     ", "  #  "],
    "'": ["#", "#", " ", " ", " "], ":": [" ", "#", " ", "#", " "],
}


def load():
    w = dict(DEFAULT)
    try:
        with open(CONF, encoding="utf-8") as f:
            w.update({k: v for k, v in json.load(f).items() if k in DEFAULT})
    except (OSError, ValueError):
        pass
    return w


def save(w):
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    with open(CONF + ".new", "w", encoding="utf-8") as f:
        json.dump(w, f, indent=1, ensure_ascii=False)
    os.replace(CONF + ".new", CONF)


def width(text):
    """Columns a line takes (wide characters count twice)."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def fonts():
    out = ["plain", "blocks"]
    if shutil.which("figlet") and os.path.isdir(FIGLET_DIR):
        out += sorted(f[:-4] for f in os.listdir(FIGLET_DIR) if f.endswith(".flf"))
    return out


def big(text, font, maxw=200):
    """Text in big letters, as lines."""
    if not text.strip():
        return []
    if font == "plain":
        return [text]
    if font != "blocks" and shutil.which("figlet") and os.path.exists(os.path.join(FIGLET_DIR, font + ".flf")):
        out = subprocess.run(["figlet", "-d", FIGLET_DIR, "-f", font, "-w", str(maxw), "--", text],
                             capture_output=True, text=True).stdout.rstrip("\n").split("\n")
        while out and not out[-1].strip():
            out.pop()
        return [ln.rstrip() for ln in out]
    rows = [""] * 5
    for ch in text.upper():
        g = FONT.get(ch, FONT["?"])
        for r in range(5):
            rows[r] += g[r].replace("#", "█") + " "
    return [r.rstrip() for r in rows]


def picture(path, cols, ramp, invert):
    """A picture as characters: darker is denser (or lighter, inverted)."""
    chars = RAMPS.get(ramp, ramp) or RAMPS["classic"]
    if len(chars) < 2:
        chars = " " + chars
    cols = max(10, min(int(cols), 300))
    # Characters are about twice as tall as wide: half the rows.
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-nostdin", "-i", path, "-frames:v", "1",
                          "-vf", "scale=%d:-2,scale=%d:ih/2,format=gray" % (cols, cols),
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True)
    if raw.returncode or not raw.stdout:
        raise ValueError("That picture could not be read.")
    data = raw.stdout
    rows = len(data) // cols
    lines = []
    for y in range(rows):
        line = ""
        for x in range(cols):
            v = data[y * cols + x] / 255
            if not invert:
                v = 1 - v                                 # (dark on paper: dense characters)
            line += chars[min(len(chars) - 1, int(v * len(chars)))]
        lines.append(line.rstrip())
    while lines and not lines[-1].strip():
        lines.pop()
    while lines and not lines[0].strip():
        lines.pop(0)
    return lines


def border_chars(w):
    style = w["border"]
    if style == "custom":
        c = "".join(ch for ch in w.get("border_chars", "*") if ch.isprintable()) or "*"
        if len(c) == 6:
            return c[0], c[1], c[2], c[3], c, c[5]      # corners and sides
        return c[0], c[0], c[0], c[0], c, c[0]           # a pattern along the top and bottom
    b = BORDERS.get(style)
    return (b[0], b[1], b[2], b[3], b[4], b[5]) if b else None


def run_of(pattern, n):
    """n columns of a pattern repeated (for a border's top and bottom)."""
    if len(pattern) == 6:
        pattern = pattern[4]
    out = ""
    while width(out) < n:
        out += pattern
    while width(out) > n:
        out = out[:-1]
    return out


def render(w):
    # Lines go in blocks: big letters move as one (figlet's lines belong
    # together), each other line by itself.
    blocks = []
    head = big(w["heading"], w["heading_font"])
    if head:
        blocks.append(head)
    if w["subheading"].strip():
        if head:
            blocks.append([""])
        blocks.append([w["subheading"]])
    art = []
    if w["body"] == "big":
        art = big(w["body_text"], w["body_font"])
    elif w["body"] == "text":
        art = w["body_text"].split("\n")          # (your own art: kept as one block)
    elif w["body"] == "picture" and w["picture"]:
        art = picture(w["picture"], w["width"], w["ramp"], w["invert"])
    inner = max([width(ln) for blk in blocks for ln in blk] + [width(ln) for ln in art] + [1])
    if blocks and art:
        blocks.append([""])
        if w["divider"]:
            b = border_chars(w)
            blocks.append([run_of(b[4] if b else "-", inner)])
            blocks.append([""])
    if art:
        blocks.append(art)
    pad = max(0, min(int(w["padding"]), 10))
    body = []
    for blk in blocks:
        bw = max(width(ln) for ln in blk)
        left = 0 if w["align"] == "left" else (inner - bw) // 2
        body += [" " * left + ln + " " * (inner - left - width(ln)) for ln in blk]
    b = border_chars(w)
    if not b:
        return "\n".join(ln.rstrip() for ln in body) + "\n"
    tl, tr, bl, br, h, v = b
    full = inner + 2 * pad
    out = [tl + run_of(h, full) + tr]
    out += [v + " " * full + v] * min(pad, 3) if pad else []
    out += [v + " " * pad + ln + " " * pad + v for ln in body]
    out += [v + " " * full + v] * min(pad, 3) if pad else []
    out.append(bl + run_of(h, full) + br)
    return "\n".join(out) + "\n"


def printopts(path, orientation):
    """cpi and lpi so that the art fills the page (what fits on both A4 and
    Letter, with 1.25 cm margins), keeping its shape: a character is 0.6 times
    as wide as tall. CUPS's text filter sets characters a little wider than
    1/cpi: there is room to spare, and long lines are never wrapped."""
    with open(path, encoding="utf-8") as f:
        lines = f.read().rstrip("\n").split("\n")
    cols = max([width(ln) for ln in lines] + [1])
    rows = max(len(lines), 1)
    W, H = (7.2, 10.0) if orientation == "portrait" else (10.0, 7.2)    # inches, inside the margins
    cpi = max(cols / (W * 0.88), rows / (H * 0.6 * 0.94), 2.0)
    cpi = min(cpi, 40.0)
    lpi = cpi * 0.6
    opts = ["-o", "cpi=%.2f" % cpi, "-o", "lpi=%.2f" % lpi, "-o", "page-left=36", "-o", "page-right=36",
            "-o", "page-top=36", "-o", "page-bottom=36", "-o", "prettyprint=false", "-o", "wrap=false"]
    opts += ["-o", "landscape"] if orientation == "landscape" else ["-o", "portrait"]
    return opts, cols, rows, cpi


def main(args):
    cmd = args[0] if args else ""
    if cmd == "get" and len(args) == 2:
        v = load().get(args[1], "")
        print(json.dumps(v) if isinstance(v, bool) else v)
    elif cmd == "set" and len(args) == 3:
        w = load()
        key, v = args[1], args[2]
        if key not in DEFAULT:
            sys.exit("no such setting: " + key)
        if isinstance(DEFAULT[key], bool):
            v = v in ("1", "true", "on", "yes")
        elif isinstance(DEFAULT[key], int):
            if not re.fullmatch(r"\d{1,3}", v):
                sys.exit("a number, please")
            v = int(v)
        else:
            v = v.replace("\\n", "\n")[:4000]
        w[key] = v
        save(w)
    elif cmd == "reset":
        save(dict(DEFAULT))
    elif cmd == "fonts":
        print("\n".join(fonts()))
    elif cmd == "render":
        try:
            text = render(load())
        except ValueError as e:
            sys.exit(str(e))
        if len(args) > 1:
            with open(args[1], "w", encoding="utf-8") as f:
                f.write(text)
        else:
            sys.stdout.write(text)
    elif cmd == "printopts" and len(args) == 3:
        opts, cols, rows, cpi = printopts(args[1], args[2])
        print(" ".join(opts))
        print("%d x %d characters, %.0f to the inch" % (cols, rows, cpi), file=sys.stderr)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
