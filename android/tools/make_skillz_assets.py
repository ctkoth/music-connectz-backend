#!/usr/bin/env python3
"""Generate the SkillZ Android art from the sign members already see.

SkillZ ships as its own Android app (the `skillz` flavor in android/), and its
icon is the supplied SkillZ sign — the ring of performers around the wave mark,
and the name — not a redrawn mark.

The source is vendored here as skillz-source-1024.png so this runs without the
frontend checkout. It is the supplied 2000px art, scaled once to 1024px, with one
repair: the original is a rounded square on WHITE, and those four white corners
were filled with the colour beside them so the picture is a plain square. Play and
the launcher apply their own masks; a corner of white inside one would show as a
white notch. Every output below is a DOWNSCALE or a same-size placement of it.

    python android/tools/make_skillz_assets.py [--play-out DIR]

Outputs
  android/app/src/skillz/res/drawable-nodpi/ic_skillz_foreground.png   432x432
  android/app/src/skillz/res/drawable-nodpi/ic_skillz_monochrome.png   432x432
  android/app/src/skillz/res/drawable-nodpi/ic_skillz_splash.png       352x352
  <play-out>/icon-512.png                    Play listing icon (required), RGBA
  <play-out>/feature-graphic-1024x500.png    Play listing graphic (required)

Why the art is not full-bleed in the adaptive layer. The sign's NAME, "SkillZ",
sits in a band at the BOTTOM. An adaptive icon is a 108dp layer of which the
launcher shows a mask — a circle of 72dp at most, 66dp guaranteed — so art that
fills the layer loses the ends of the word to a circular mask. ART_SIDE is the
largest square whose name still clears a 66dp circle (`title_clears`). The ring
beyond the art is the art's own four corner colours, continued, so there is no seam where it meets
and no ink border at the edge of a squircle.

The monochrome layer (Android 13 themed icons) is NOT the whole sign: a launcher
reads only its alpha and tints it, and ten painted portraits become a smudge. It
is the wave mark from the middle of the sign — the one part of the art that is
already a one-colour shape — which stays a shape at 48px.

The feature graphic does NOT reuse the sign whole. The sign shows ten people —
a DJ, a producer, an A&R, an illustrator and a videographer among them — and the
app has coaches for singing, rapping, guitar, bass, keys, drums and violin only.
A listing graphic that shows a DJ promises one. So it is built from the five
portraits of coaches the app really has (singer, rapper, guitarist, drummer,
pianist), with all seven written out beside them.
"""
import argparse
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))        # android/
SOURCE = os.path.join(ROOT, "tools", "skillz-source-1024.png")
RES = os.path.join(ROOT, "app", "src", "skillz", "res", "drawable-nodpi")

# Near-black ink the splash, status bar and Play graphic share, so no seam shows.
INK = (7, 6, 13)

# Largest art square (px, of the 432px layer) whose name clears a 66dp circle.
ART_SIDE = 268

FONT_BOLD = "/usr/share/fonts/opentype/inter/Inter-Bold.otf"
FONT_BLACK = "/usr/share/fonts/opentype/inter/Inter-Black.otf"
FONT_FALLBACK = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# The performers a built coach has, as (cx, cy, r) in the 2000px original, fitted
# to each portrait's black rim, with a per-portrait shrink so a neighbour's rim
# that overlaps it does not come along. Source scale: 1024/2000.
SCALE = 1024 / 2000
PORTRAITS = {
    "singer": (1001, 336, 246, 0.965, 0, 0),
    "rapper": (1652, 995, 250, 0.965, 0, 0),
    "guitarist": (1681 + 42, 1646 + 44, 218, 0.72, 0, 0),
    "drummer": (268 - 8, 1691 + 14, 213, 0.88, 0, 0),
    "pianist": (554, 1429, 225, 0.965, 0, 0),
}
# Where the wave mark sits in the middle of the sign (fractions of the side).
MARK_BOX = (0.335, 0.37, 0.625, 0.58)


def _art():
    from PIL import Image
    return Image.open(SOURCE).convert("RGB")


def title_clears(side, circle_px=264, title_bottom=0.965, title_half=0.15):
    """Does the sign's name — its bottom edge at 96.5% of the art's height,
    spanning 15% of its width either side of centre (measured off the source) —
    sit inside a circle of `circle_px` (264 is Android's guaranteed 66dp at
    xxxhdpi) when the art is `side` px wide and centred?"""
    r = circle_px / 2
    dx = side * title_half
    dy = side * (title_bottom - 0.5)
    return math.hypot(dx, dy) <= r


def _fit(img, width):
    from PIL import ImageFilter
    h = round(img.height * width / img.width)
    out = img.resize((width, h), __import__("PIL.Image", fromlist=["x"]).LANCZOS)
    return out.filter(ImageFilter.UnsharpMask(radius=0.8, percent=30, threshold=2))


def _layer(art, side, art_width):
    """A `side`-px square: the art centred at `art_width`, on a backdrop of the art's
    own four corner colours. The sign is four colour quadrants with a seam on each
    centre line, so a flat 2x2 field continues it past the art's edge with the seam
    where the seam already was — a blur of the whole picture would drag the portraits
    out into a purple halo."""
    from PIL import Image, ImageDraw
    n = art.width
    blk = round(n * 0.04)

    def patch(fx, fy):
        x, y = round(fx * n), round(fy * n)
        px = art.crop((x, y, x + blk, y + blk)).resize((1, 1), Image.BOX)
        return px.getpixel((0, 0))

    # Sampled where the art is plain colour: the top edge clear of the singer's
    # portrait, and the bottom edge in the gaps between portraits and the name.
    quad = Image.new("RGB", (2, 2))
    quad.putpixel((0, 0), patch(0.20, 0.02))
    quad.putpixel((1, 0), patch(0.76, 0.02))
    quad.putpixel((0, 1), patch(0.22, 0.945))
    quad.putpixel((1, 1), patch(0.74, 0.945))
    backdrop = quad.resize((side, side), Image.NEAREST)
    fitted = _fit(art, art_width)
    # Feathered by a few pixels so the art's edge dissolves into the field.
    feather = 8
    mask = Image.new("L", fitted.size, 0)
    ImageDraw.Draw(mask).rectangle((feather, feather, fitted.width - feather - 1, fitted.height - feather - 1), fill=255)
    mask = mask.filter(__import__("PIL.ImageFilter", fromlist=["x"]).GaussianBlur(feather / 2))
    backdrop.paste(fitted, ((side - fitted.width) // 2, (side - fitted.height) // 2), mask)
    return backdrop


def play_icon(path):
    # Full-bleed square: Play applies its own corner mask, and one drawn in here
    # would be masked twice.
    _fit(_art(), 512).convert("RGBA").save(path, "PNG", optimize=True)


def adaptive_foreground(path, size=432):
    _layer(_art(), size, ART_SIDE).convert("RGBA").save(path, "PNG", optimize=True)


def _mark(art):
    w, h = art.size
    x0, y0, x1, y1 = MARK_BOX
    return art.crop((round(x0 * w), round(y0 * h), round(x1 * w), round(y1 * h)))


def monochrome(path, size=432):
    """Android 13 themed icons: only alpha is read, the launcher tints it. The
    mark's bars are dark on a light field, so darkness becomes opacity."""
    from PIL import Image, ImageOps
    mark = _mark(_art()).convert("L")
    dark = ImageOps.invert(ImageOps.autocontrast(mark, cutoff=3))
    dark = dark.point(lambda v: 0 if v < 70 else min(255, int((v - 70) * 255 / 185)))
    # Fit inside the 66dp-safe 264px centre, with a little room.
    side = 232
    scale = min(side / dark.width, side / dark.height)
    dark = dark.resize((round(dark.width * scale), round(dark.height * scale)), Image.LANCZOS)
    out = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    alpha = Image.new("L", (size, size), 0)
    alpha.paste(dark, ((size - dark.width) // 2, (size - dark.height) // 2))
    out.putalpha(alpha)
    out.save(path, "PNG", optimize=True)


def splash(path, size=352):
    # The TWA splash image: the whole sign, which carries the name; the splash
    # layer-list supplies the background colour.
    from PIL import Image
    canvas = Image.new("RGB", (size, size), INK)
    fitted = _fit(_art(), size - 12)
    canvas.paste(fitted, ((size - fitted.width) // 2, (size - fitted.height) // 2))
    canvas.convert("RGBA").save(path, "PNG", optimize=True)


def _disc(art2000, spec, diameter):
    from PIL import Image, ImageDraw
    cx, cy, r, shrink, dx, dy = spec
    cx, cy, r = cx + dx, cy + dy, int(r * shrink) + 2
    tile = art2000.crop((cx - r, cy - r, cx + r, cy + r)).resize((diameter, diameter), Image.LANCZOS)
    mask = Image.new("L", (diameter * 4, diameter * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, diameter * 4 - 1, diameter * 4 - 1), fill=255)
    return tile, mask.resize((diameter, diameter), Image.LANCZOS)


def feature_graphic(path, w=1024, h=500):
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

    # The portraits are cut from the 1024px source, so their coordinates are scaled
    # and the discs are downscales (about 190px of a 450px source disc).
    art = _art()
    art2000 = art.resize((2000, 2000), Image.LANCZOS)  # coordinates only; discs are then reduced

    img = Image.new("RGB", (w, h), INK)
    glow = Image.new("RGB", (w, h), INK)
    gd = ImageDraw.Draw(glow)
    gd.ellipse((-120, 10, 560, 500), fill=(70, 30, 130))
    gd.ellipse((660, 220, 1140, 620), fill=(20, 70, 120))
    glow = glow.filter(ImageFilter.GaussianBlur(110))
    img = Image.blend(img, glow, 0.85)
    d = ImageDraw.Draw(img)

    # Five performers on a ring, the wave mark in the middle.
    cx0, cy0, ring, disc = 248, 250, 156, 164
    order = ["singer", "rapper", "guitarist", "drummer", "pianist"]
    for i, name in enumerate(order):
        ang = math.radians(-90 + i * 72)
        x = round(cx0 + ring * math.cos(ang) - disc / 2)
        y = round(cy0 + ring * math.sin(ang) - disc / 2)
        d.ellipse((x - 4, y - 4, x + disc + 3, y + disc + 3), fill=(244, 242, 255))
        tile, mask = _disc(art2000, PORTRAITS[name], disc)
        img.paste(tile, (x, y), mask)
    mark = ImageOps.invert(_mark(art).convert("L")).point(lambda v: 0 if v < 60 else v)
    mw = 118
    mark = mark.resize((mw, round(mark.height * mw / mark.width)), Image.LANCZOS)
    img.paste(Image.new("RGB", mark.size, (244, 242, 255)), (cx0 - mark.width // 2, cy0 - mark.height // 2), mark)

    try:
        f_title = ImageFont.truetype(FONT_BLACK, 104)
        f_line = ImageFont.truetype(FONT_BOLD, 38)
        f_sub = ImageFont.truetype(FONT_BOLD, 24)
    except OSError:
        f_title = ImageFont.truetype(FONT_FALLBACK, 96)
        f_line = ImageFont.truetype(FONT_FALLBACK, 34)
        f_sub = ImageFont.truetype(FONT_FALLBACK, 22)

    d = ImageDraw.Draw(img)
    x, margin = 520, 36
    d.text((x, 62), "Skill", font=f_title, fill=(244, 242, 255))
    z_x = x + d.textlength("Skill", font=f_title)
    d.text((z_x, 62), "Z", font=f_title, fill=(255, 150, 40))
    assert z_x + d.textlength("Z", font=f_title) <= w - margin

    lines = [
        ((x + 4, 196), "Record a take.", f_line, (244, 242, 255)),
        ((x + 4, 242), "Get it scored.", f_line, (255, 150, 40)),
        ((x + 4, 326), "SingZ · RapZ · GuitarZ · BassZ", f_sub, (190, 185, 225)),
        ((x + 4, 360), "KeyZ · DrumZ · ViolinZ", f_sub, (190, 185, 225)),
        ((x + 4, 410), "Free takes every day.", f_sub, (190, 185, 225)),
    ]
    for xy, text, font, fill in lines:
        d.text(xy, text, font=font, fill=fill)
        assert xy[0] + d.textlength(text, font=font) <= w - margin, text
    img.save(path, "PNG", optimize=True)


def preview(path, size=432):
    """A contact sheet of the adaptive foreground through circle, squircle and
    rounded-square masks, for looking at — not shipped."""
    from PIL import Image, ImageDraw
    fg = Image.open(os.path.join(RES, "ic_skillz_foreground.png")).convert("RGB")
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
    assert title_clears(ART_SIDE), "ART_SIDE is too large: the name would clip on a circular mask"
    os.makedirs(RES, exist_ok=True)
    os.makedirs(args.play_out, exist_ok=True)
    adaptive_foreground(os.path.join(RES, "ic_skillz_foreground.png"))
    monochrome(os.path.join(RES, "ic_skillz_monochrome.png"))
    splash(os.path.join(RES, "ic_skillz_splash.png"))
    play_icon(os.path.join(args.play_out, "icon-512.png"))
    feature_graphic(os.path.join(args.play_out, "feature-graphic-1024x500.png"))
    if args.preview:
        preview(args.preview)
    print("SkillZ assets written to android/app/src/skillz/res and", args.play_out)


if __name__ == "__main__":
    main()
