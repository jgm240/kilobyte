#!/usr/bin/env python3
"""The website's icon: a grey Kilobyte dialog box with its black shadow on the
blue desk, drawn on 16x16 pixels and scaled up without smoothing.
Output: site/favicon.ico (16, 32, 48), favicon-32.png, apple-touch-icon.png
(180). site/favicon.svg is the same drawing.  Needs Pillow."""
import os
from PIL import Image

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "site")
BLUE, BLACK, GREY, WHITE = (0, 0, 170), (0, 0, 0), (170, 170, 170), (255, 255, 255)


def icon16():
    im = Image.new("RGB", (16, 16), BLUE)
    px = im.load()

    def rect(x, y, w, h, c):
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                px[xx, yy] = c
    rect(5, 5, 9, 9, BLACK)           # shadow
    rect(2, 2, 10, 10, GREY)          # the box
    rect(2, 2, 10, 1, WHITE)          # lit edges
    rect(2, 2, 1, 10, WHITE)
    for y, w in ((5, 6), (7, 6), (9, 4)):
        rect(4, y, w, 1, BLACK)       # lines of text
    return im


base = icon16()
scaled = lambda n: base.resize((n, n), Image.NEAREST)
base.save(os.path.join(OUT, "favicon.ico"), sizes=[(16, 16), (32, 32), (48, 48)],
          append_images=[scaled(32), scaled(48)])
scaled(32).save(os.path.join(OUT, "favicon-32.png"))
# Apple's icon: the drawing on a blue margin, 180 pixels (11.25 per pixel, so 160 + margin)
touch = Image.new("RGB", (180, 180), BLUE)
touch.paste(base.resize((160, 160), Image.NEAREST), (10, 10))
touch.save(os.path.join(OUT, "apple-touch-icon.png"))
print("icons written")
