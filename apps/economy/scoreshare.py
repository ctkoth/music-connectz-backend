"""Shareable score cards — the growth loop's last inch.

A member (or a trial visitor) gets a take scored; the coach's answer comes
back with `share_url` = /s/<token>. That page, and the image every social
crawler pulls for it, show the score and the coach's own verdict, and the
"get yours scored" link carries the sharer's handle as the referral code.

Everything here is READ off a ScoreShare row minted server-side when the
coach answered (models.mint_score_share). Nothing a client sends can put a
number on a card.
"""
import io
import re

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .instruments import profile_for_app
from .models import ScoreShare


def _label(app_key):
    try:
        return profile_for_app(app_key)["label"]
    except Exception:
        return app_key


def short_verdict(text, n=160):
    """The coach's first sentence, cut on a word — what fits on a card."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    first = re.split(r"(?<=[.!?])\s", t, maxsplit=1)[0]
    if len(first) <= n:
        return first
    cut = first[: n - 1]
    return (cut[: cut.rfind(" ")] if " " in cut else cut).rstrip(",;: ") + "…"


def share_dict(row):
    return {
        "token": row.token,
        "app_key": row.app_key,
        "label": _label(row.app_key),
        "score": row.score,
        "verdict": short_verdict(row.verdict),
        "genre": row.genre,
        # The referral code is the member's handle; a trial take has none.
        "username": row.user.username if row.user_id else "",
        "created_at": row.created_at,
        "image": f"/api/economy/scores/{row.token}/card.png",
    }


class ScoreShareView(APIView):
    """GET /api/economy/scores/<token>/ — public, like the profile card."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, token):
        row = get_object_or_404(ScoreShare.objects.select_related("user"), token=token)
        return Response(share_dict(row))


def _font(size):
    from PIL import ImageFont
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _wrap(draw, text, font, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > 2:                      # two lines fit above the footer
        lines = lines[:2]
        lines[1] = lines[1].rstrip(" .,;:”") + "…”"
    return lines


def score_card_png(request, token):
    """GET /api/economy/scores/<token>/card.png — 1200x630, the size every
    social preview (Open Graph / X large card) expects."""
    from PIL import Image, ImageDraw
    row = get_object_or_404(ScoreShare.objects.select_related("user"), token=token)
    d = share_dict(row)
    W, H = 1200, 630
    img = Image.new("RGB", (W, H), (7, 6, 13))
    g = ImageDraw.Draw(img)
    # Neon frame, the house look.
    g.rounded_rectangle((24, 24, W - 24, H - 24), radius=36, outline=(255, 85, 0), width=6)
    g.rounded_rectangle((36, 36, W - 36, H - 36), radius=30, outline=(56, 227, 255), width=2)

    g.text((80, 70), "MUSIC CONNECTZ", font=_font(34), fill=(56, 227, 255))
    g.text((80, 120), f"{d['label']} coach" + (f" · {d['genre']}" if d["genre"] else ""),
           font=_font(40), fill=(255, 255, 255))

    big = _font(220)
    score = f"{d['score']}"
    g.text((80, 150), score, font=big, fill=(255, 85, 0))
    sw = g.textlength(score, font=big)
    g.text((80 + sw + 16, 310), "/10", font=_font(90), fill=(255, 255, 255))

    y = 420
    for line in _wrap(g, f"“{d['verdict']}”" if d["verdict"] else "", _font(36), W - 160):
        g.text((80, y), line, font=_font(36), fill=(220, 220, 230))
        y += 46
    who = f"@{d['username']}  ·  " if d["username"] else ""
    g.text((80, H - 92), f"{who}Get your take scored free → musicconnectz.net",
           font=_font(30), fill=(52, 211, 153))

    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    resp = HttpResponse(buf.getvalue(), content_type="image/png")
    # The row never changes, so crawlers and CDNs may keep it.
    resp["Cache-Control"] = "public, max-age=86400"
    return resp
