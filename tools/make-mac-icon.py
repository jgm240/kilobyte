#!/usr/bin/env python3
"""Kilobyte.app's icon: the website's pixel icon (a grey Kilobyte dialog box
with its shadow on the blue desk), scaled up without smoothing on a rounded
blue square, as an iconset for iconutil.
  python3 tools/make-mac-icon.py OUT.iconset && iconutil -c icns OUT.iconset
Needs Pillow."""
import os
import sys
from PIL import Image, ImageDraw

BLUE, BLACK, GREY, WHITE = (0, 0, 170), (0, 0, 0), (170, 170, 170), (255, 255, 255)


def drawing():
    im = Image.new("RGBA", (16, 16), BLUE + (255,))
    d = ImageDraw.Draw(im)
    d.rectangle([5, 5, 13, 13], fill=BLACK)
    d.rectangle([2, 2, 11, 11], fill=GREY)
    d.line([2, 2, 11, 2], fill=WHITE)
    d.line([2, 2, 2, 11], fill=WHITE)
    for y, w in ((5, 6), (7, 6), (9, 4)):
        d.line([4, y, 4 + w - 1, y], fill=BLACK)
    return im


def icon(size):
    # macOS icons: a rounded square with a margin (824 of 1024).
    art = drawing().resize((size * 13 // 16, size * 13 // 16), Image.NEAREST)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    m = (size - art.width) // 2
    mask = Image.new("L", art.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, art.width - 1, art.height - 1], radius=art.width // 5, fill=255)
    out.paste(art, (m, m), mask)
    return out


dest = sys.argv[1]
os.makedirs(dest, exist_ok=True)
for s in (16, 32, 128, 256, 512):
    icon(s).save(os.path.join(dest, "icon_%dx%d.png" % (s, s)))
    icon(s * 2).save(os.path.join(dest, "icon_%dx%d@2x.png" % (s, s)))
print("iconset written:", dest)
