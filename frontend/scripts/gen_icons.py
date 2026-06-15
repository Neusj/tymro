"""Generate TYMRO PWA icons (geometric two-tone "T" monogram).

Run from frontend/:  python scripts/gen_icons.py
Outputs PNGs into frontend/public/. Re-run any time to regenerate.
Brand colors: black #09090b, panel #101013, red #dc2626, white #fafafa.
"""
import os
from PIL import Image, ImageDraw

BLACK = (9, 9, 11, 255)      # brand-black #09090b
PANEL = (16, 16, 19, 255)    # brand-panel #101013
RED = (220, 38, 38, 255)     # brand-red #dc2626
WHITE = (250, 250, 250, 255) # brand-white #fafafa

OUT = os.path.join(os.path.dirname(__file__), "..", "public")
os.makedirs(OUT, exist_ok=True)


def draw_t(draw, cx, cy, c):
    """Draw a two-tone 'T' (red top bar, white stem) centered at (cx, cy),
    fitting in a c x c box."""
    x0, y0 = cx - c / 2, cy - c / 2
    bar_h = c * 0.22
    stem_w = c * 0.24
    # white stem (full height), drawn first
    draw.rounded_rectangle(
        [cx - stem_w / 2, y0, cx + stem_w / 2, y0 + c],
        radius=stem_w * 0.18, fill=WHITE,
    )
    # red top bar
    draw.rounded_rectangle(
        [x0, y0, x0 + c, y0 + bar_h],
        radius=bar_h * 0.30, fill=RED,
    )


def make_icon(size, maskable=False, apple=False):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if maskable:
        # Full-bleed dark background; content kept inside the safe zone so
        # OS circle/squircle masks never clip the mark.
        d.rectangle([0, 0, size, size], fill=BLACK)
        c = size * 0.42
    else:
        # Rounded "tile" with a subtle red hairline border (card look).
        r = size * 0.22
        d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=PANEL)
        border = max(2, round(size * 0.012))
        d.rounded_rectangle(
            [border / 2, border / 2, size - 1 - border / 2, size - 1 - border / 2],
            radius=r, outline=RED, width=border,
        )
        c = size * (0.50 if apple else 0.52)
    draw_t(d, size / 2, size / 2, c)
    return img


def save(img, name):
    path = os.path.join(OUT, name)
    img.save(path, "PNG")
    print("wrote", os.path.normpath(path), img.size)


if __name__ == "__main__":
    save(make_icon(192), "pwa-192x192.png")
    save(make_icon(512), "pwa-512x512.png")
    save(make_icon(512, maskable=True), "pwa-maskable-512x512.png")
    save(make_icon(180, apple=True), "apple-touch-icon.png")
    print("done")
