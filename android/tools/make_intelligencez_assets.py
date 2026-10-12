#!/usr/bin/env python3
"""Generate the IntelligenceZ Android art from the sign members already see.

IntelligenceZ ships as its own Android app (the `intelligencez` flavor in
android/), and its icon is the supplied IntelligenceZ sign — the neon brain, the
name, the media panels — not a redrawn mark. It is the same artwork the
IntelligenceZ tab shows (frontend `public/icons/intelligencez.png`), so a launcher
icon and the in-app icon are one identity.

The source is vendored here as intelligencez-source-1024.png (the 2000px original,
scaled once), so this runs without the frontend checkout and every output below is
a DOWNSCALE or a same-size placement of it, never an upscale.

    python android/tools/make_intelligencez_assets.py [--play-out DIR]

Outputs
  android/app/src/intelligencez/res/drawable-nodpi/ic_intelligencez_foreground.png   432x432
  android/app/src/intelligencez/res/drawable-nodpi/ic_intelligencez_monochrome.png   432x432
  android/app/src/intelligencez/res/drawable-nodpi/ic_intelligencez_splash.png       352x352
  <play-out>/icon-512.png                    Play listing icon (required), RGBA
  <play-out>/feature-graphic-1024x500.png    Play listing graphic (required)
  (play-out defaults to android/tools/play-out; the frontend repo keeps its copy in
   play/intelligencez/graphics/)

Why the art is not full-bleed in the adaptive layer. The sign's NAME sits in a
band near the top. An adaptive icon is a 108dp layer of which the launcher shows
a mask — a circle of 72dp at most, 66dp guaranteed — so art that fills the layer
loses the ends of "IntelligenceZ" to a circular mask. ART_SIDE is the largest
square whose title row still clears a 66dp circle (worked out in `title_clears`);
it was checked through circle and squircle masks (`--preview`) before being
chosen. Only the frame's corners ever touch a mask.

The feature graphic does NOT reuse the sign whole. The sign carries panels
labelled IMAGE / PHOTO, VIDEO / CLIP, MEDIA FILES and 3D / VISUALS, and the app has
none of those: Video ConnectZ and Image ConnectZ are not in it. A listing graphic
that shows a video panel promises one. So it is built from the brain alone, with
the four things the app actually does written beside it.
"""
import argparse
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))        # android/
SOURCE = os.path.join(ROOT, "tools", "intelligencez-source-1024.png")
RES = os.path.join(ROOT, "app", "src", "intelligencez", "res", "drawable-nodpi")

# The art's own near-black edge. The adaptive background layer, the splash and
# the Play graphic use the same value so no seam shows where they meet.
INK = (2, 2, 12)

# Largest art square (px, of the 432px layer) whose title band clears a 66dp
# (264px) circle. See title_clears().
ART_SIDE = 222

FONT_BOLD = "/usr/share/fonts/opentype/inter/Inter-Bold.otf"
FONT_FALLBACK = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _art():
    from PIL import Image
    return Image.open(SOURCE).convert("RGB")


def title_clears(side, circle_px=264, title_top=0.085, title_half=0.42):
    """Does the sign's title band (measured off the source: its top edge at 8.5% of
    the art's height, spanning 42% of its width either side of centre) sit inside
    a circle of `circle_px` — 264 is Android's guaranteed 66dp at xxxhdpi — when
    the art is `side` px wide and centred?"""
    r = circle_px / 2
    dx = side * title_half
    dy = side * (0.5 - title_top)
    return math.hypot(dx, dy) <= r


def _fit(img, width):
    from PIL import Image, ImageFilter
    h = round(img.height * width / img.width)
    out = img.resize((width, h), Image.LANCZOS)
    return out.filter(ImageFilter.UnsharpMask(radius=0.8, percent=35, threshold=2))


def _square(art, side, art_width, bg=INK):
    from PIL import Image
    fitted = _fit(art, art_width)
    canvas = Image.new("RGB", (side, side), bg)
    canvas.paste(fitted, ((side - fitted.width) // 2, (side - fitted.height) // 2))
    return canvas


def play_icon(path):
    # Full-bleed square: Play applies its own corner mask, and one drawn in here
    # would be masked twice.
    _fit(_art(), 512).convert("RGBA").save(path, "PNG", optimize=True)


def adaptive_foreground(path, size=432):
    _square(_art(), size, ART_SIDE).convert("RGBA").save(path, "PNG", optimize=True)


def monochrome(path, size=432):
    """Android 13 themed icons: only the alpha channel is read, the launcher tints
    it. Brightness becomes opacity, so the neon lines stay lines."""
    from PIL import Image, ImageOps
    lum = ImageOps.autocontrast(_square(_art(), size, ART_SIDE).convert("L"), cutoff=2)
    lum = lum.point(lambda v: min(255, int(255 * (v / 255) ** 0.6)))
    out = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    out.putalpha(lum)
    out.save(path, "PNG", optimize=True)


def splash(path, size=352):
    # The TWA splash image: the whole sign, which carries the name; the splash
    # layer-list supplies the background colour.
    _square(_art(), size, 340).convert("RGBA").save(path, "PNG", optimize=True)


def feature_graphic(path, w=1024, h=500):
    from PIL import Image, ImageDraw, ImageFont, ImageFilter

    art = _art()
    # The brain, between the sign's side panels (x 560-1440 of 2000), so no panel
    # edge is in the crop. Coordinates are for the 1024px source.
    s = 1024 / 2000
    brain = art.crop((round(560 * s), round(450 * s), round(1440 * s), round(1290 * s)))

    img = Image.new("RGB", (w, h), INK)
    glow = Image.new("RGB", (w, h), INK)
    gd = ImageDraw.Draw(glow)
    gd.ellipse((-140, 10, 560, 560), fill=(20, 24, 120))
    glow = glow.filter(ImageFilter.GaussianBlur(100))
    img = Image.blend(img, glow, 0.9)

    bh = 452
    bw = round(brain.width * bh / brain.height)
    fitted = brain.resize((bw, bh), Image.LANCZOS)
    # Feathered, so the picture dissolves into the background instead of sitting
    # on it as a rectangle with its own edge.
    fade = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(fade).rectangle((48, 36, bw - 48, bh - 36), fill=255)
    fade = fade.filter(ImageFilter.GaussianBlur(34))
    img.paste(fitted, (24, (h - bh) // 2), fade)

    try:
        f_title = ImageFont.truetype(FONT_BOLD, 72)
        f_line = ImageFont.truetype(FONT_BOLD, 38)
        f_sub = ImageFont.truetype(FONT_BOLD, 25)
    except OSError:
        f_title = ImageFont.truetype(FONT_FALLBACK, 66)
        f_line = ImageFont.truetype(FONT_FALLBACK, 34)
        f_sub = ImageFont.truetype(FONT_FALLBACK, 23)

    d = ImageDraw.Draw(img)
    x = 480
    margin = 36
    d.text((x, 104), "Intelligence", font=f_title, fill=(244, 242, 255))
    z_x = x + d.textlength("Intelligence", font=f_title)
    d.text((z_x, 104), "Z", font=f_title, fill=(34, 230, 255))
    assert z_x + d.textlength("Z", font=f_title) <= w - margin

    lines = [
        ((x + 4, 222), "Write. Chat.", f_line, (244, 242, 255)),
        ((x + 4, 268), "Compose. Master.", f_line, (34, 230, 255)),
        ((x + 4, 350), "Free prompts every day.", f_sub, (170, 175, 215)),
        ((x + 4, 386), "Mastering stays on your device.", f_sub, (170, 175, 215)),
    ]
    for xy, text, font, fill in lines:
        d.text(xy, text, font=font, fill=fill)
        assert xy[0] + d.textlength(text, font=font) <= w - margin, text
    img.save(path, "PNG", optimize=True)


def preview(path, size=432):
    """A contact sheet of the adaptive foreground through circle, squircle and
    rounded-square masks, for looking at — not shipped."""
    from PIL import Image, ImageDraw
    fg = Image.open(os.path.join(RES, "ic_intelligencez_foreground.png")).convert("RGB")
    visible = int(size * 72 / 108)
    off = (size - visible) // 2
    tiles = []
    for shape in ("circle", "squircle", "rounded"):
        m = Image.new("L", (size, size), 0)
        md = ImageDraw.Draw(m)
        box = (off, off, off + visible, off + visible)
        if shape == "circle":
            md.ellipse(box, fill=255)
        elif shape == "squircle":
            md.rounded_rectangle(box, radius=int(visible * 0.38), fill=255)
        else:
            md.rounded_rectangle(box, radius=int(visible * 0.2), fill=255)
        tile = Image.new("RGB", (size, size), (120, 120, 120))
        tile.paste(fg, (0, 0), m)
        tiles.append(tile)
    sheet = Image.new("RGB", (size * 3, size), (120, 120, 120))
    for i, t in enumerate(tiles):
        sheet.paste(t, (i * size, 0))
    sheet.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--play-out", default=os.path.join(ROOT, "tools", "play-out"))
    ap.add_argument("--preview", metavar="PNG", help="also write a mask contact sheet here")
    args = ap.parse_args()
    assert title_clears(ART_SIDE), "ART_SIDE is too large: the title would clip on a circular mask"
    os.makedirs(RES, exist_ok=True)
    os.makedirs(args.play_out, exist_ok=True)
    adaptive_foreground(os.path.join(RES, "ic_intelligencez_foreground.png"))
    monochrome(os.path.join(RES, "ic_intelligencez_monochrome.png"))
    splash(os.path.join(RES, "ic_intelligencez_splash.png"))
    play_icon(os.path.join(args.play_out, "icon-512.png"))
    feature_graphic(os.path.join(args.play_out, "feature-graphic-1024x500.png"))
    if args.preview:
        preview(args.preview)
    print("IntelligenceZ assets written to android/app/src/intelligencez/res and", args.play_out)


if __name__ == "__main__":
    main()
