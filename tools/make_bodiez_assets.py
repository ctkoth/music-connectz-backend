#!/usr/bin/env python3
"""Generate the BodieZ Play assets from the art members already see in the app.

BodieZ ships as its own Android app (the `bodiez` flavor in android/), and its
icon is the neon athletes illustration from the frontend's `public/icons/
bodiez.png` — the one on the BodieZ tab — not a redrawn mark. A launcher icon
that differs from the in-app one would be two identities for one app.

The source is vendored at brand/bodiez/source-384.png so this runs without the
frontend checkout. It is 384px, so every output is an UPSCALE of it (Play wants
512, an adaptive icon wants 432). Lanczos plus a light unsharp mask keeps the
neon lines clean at that ratio; if a sharper master ever exists, drop it in as
`source-*.png` and change SOURCE — nothing else moves.

    python tools/make_bodiez_assets.py

Outputs
  brand/play/bodiez/icon-512.png                   Play listing icon (required)
  brand/play/bodiez/feature-graphic-1024x500.png   Play listing graphic (required)
  android/app/src/bodiez/res/drawable-nodpi/ic_bodiez_foreground.png
  android/app/src/bodiez/res/drawable-nodpi/ic_bodiez_monochrome.png
  android/app/src/bodiez/res/drawable-nodpi/ic_bodiez_splash.png

Why a crop, and why this one: the source has a margin and a frame that a
launcher mask would clip unevenly. CROP trims to the artwork's own content box,
which lets the figures and the wordmark fill the 66dp safe zone instead of
sitting small in the middle of it. It was checked through circle and squircle
masks before being chosen (the athletes only, cropped tighter, lost the name).
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "brand", "bodiez", "source-384.png")
PLAY = os.path.join(ROOT, "brand", "play", "bodiez")
RES = os.path.join(ROOT, "android", "app", "src", "bodiez", "res", "drawable-nodpi")

# (left, top, right, bottom) in source pixels: the artwork's content box.
CROP = (28, 20, 356, 336)
# The art's own background is near-black; the adaptive icon's background layer
# and the splash use the same value so no seam shows where they meet.
INK = (3, 3, 6)

FONT_BOLD = "/usr/share/fonts/opentype/inter/Inter-Bold.otf"
FONT_FALLBACK = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _art():
    from PIL import Image
    return Image.open(SOURCE).convert("RGB").crop(CROP)


def _fit(img, width):
    """Scale to `width`, keeping proportions, with a light sharpen for upscales."""
    from PIL import Image, ImageFilter
    h = round(img.height * width / img.width)
    out = img.resize((width, h), Image.LANCZOS)
    return out.filter(ImageFilter.UnsharpMask(radius=1.2, percent=55, threshold=2))


def _square(art, side, art_width, bg=INK):
    """`art` centred on a `side`-px square of `bg`."""
    from PIL import Image
    fitted = _fit(art, art_width)
    canvas = Image.new("RGB", (side, side), bg)
    canvas.paste(fitted, ((side - fitted.width) // 2, (side - fitted.height) // 2))
    return canvas


def play_icon(path):
    # Full-bleed square: Play applies its own corner mask, and one drawn in
    # here would be masked twice. 440 of 512 keeps the frame off the corners
    # that mask removes.
    img = _square(_art(), 512, 440).convert("RGBA")
    img.save(path, "PNG", optimize=True)


def adaptive_foreground(path, size=432):
    # Adaptive icons are authored at 108dp (432px at xxxhdpi). The launcher
    # shows at most the central 72dp and only 66dp is guaranteed, so the art is
    # 288px wide — the whole of it inside the visible area on a squircle, and
    # only ornaments, never the figures or the name, touching a circle's edge.
    _square(_art(), size, 288).convert("RGBA").save(path, "PNG", optimize=True)


def monochrome(path, size=432):
    """Android 13 themed icons: only the alpha channel is read, the launcher
    tints it. Brightness becomes opacity, so the neon lines stay lines."""
    from PIL import Image, ImageOps
    lum = ImageOps.autocontrast(_square(_art(), size, 288).convert("L"), cutoff=2)
    # A gamma lift so thin, dim strokes survive the tint rather than vanishing.
    lum = lum.point(lambda v: min(255, int(255 * (v / 255) ** 0.6)))
    out = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    out.putalpha(lum)
    out.save(path, "PNG", optimize=True)


def splash(path, size=352):
    # The TWA splash image: the art alone; the splash layer-list supplies the
    # background colour.
    _square(_art(), size, 336).convert("RGBA").save(path, "PNG", optimize=True)


def feature_graphic(path, w=1024, h=500):
    from PIL import Image, ImageDraw, ImageFont, ImageFilter

    img = Image.new("RGB", (w, h), INK)
    # A faint violet bloom behind the art so the graphic is not a flat black
    # rectangle with a picture on it.
    glow = Image.new("RGB", (w, h), INK)
    gd = ImageDraw.Draw(glow)
    gd.ellipse((-120, 20, 560, 560), fill=(34, 16, 70))
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    img = Image.blend(img, glow, 0.9)

    art = _fit(_art(), 470)
    img.paste(art, (30, (h - art.height) // 2))

    try:
        f_title = ImageFont.truetype(FONT_BOLD, 104)
        f_line = ImageFont.truetype(FONT_BOLD, 34)
        f_sub = ImageFont.truetype(FONT_BOLD, 26)
    except OSError:
        f_title = ImageFont.truetype(FONT_FALLBACK, 96)
        f_line = ImageFont.truetype(FONT_FALLBACK, 30)
        f_sub = ImageFont.truetype(FONT_FALLBACK, 24)

    d = ImageDraw.Draw(img)
    # Everything right of the art must clear the edge by the same margin the art
    # has on the left; the asserts below fail the build rather than ship a cut-off
    # line, which is what the first version of this did.
    x = 524
    margin = 36
    lines = [
        ((x, 104), "Bodie", f_title, (244, 242, 255)),
        ((x + 4, 236), "Plan it. Log it.", f_line, (34, 230, 255)),
        ((x + 4, 280), "See what actually moved.", f_line, (244, 242, 255)),
        ((x + 4, 352), "Weight, then reps.", f_sub, (170, 160, 205)),
        ((x + 4, 388), "The coach shows its math.", f_sub, (170, 160, 205)),
    ]
    for xy, text, font, fill in lines:
        d.text(xy, text, font=font, fill=fill)
        assert xy[0] + d.textlength(text, font=font) <= w - margin, text
    z_x = x + d.textlength("Bodie", font=f_title)
    d.text((z_x, 104), "Z", font=f_title, fill=(0, 255, 136))
    assert z_x + d.textlength("Z", font=f_title) <= w - margin
    img.save(path, "PNG", optimize=True)


def main():
    os.makedirs(PLAY, exist_ok=True)
    os.makedirs(RES, exist_ok=True)
    play_icon(os.path.join(PLAY, "icon-512.png"))
    feature_graphic(os.path.join(PLAY, "feature-graphic-1024x500.png"))
    adaptive_foreground(os.path.join(RES, "ic_bodiez_foreground.png"))
    monochrome(os.path.join(RES, "ic_bodiez_monochrome.png"))
    splash(os.path.join(RES, "ic_bodiez_splash.png"))
    print("BodieZ assets written to brand/play/bodiez and android/app/src/bodiez/res")


if __name__ == "__main__":
    main()
