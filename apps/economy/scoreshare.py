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

from django.db.models import F
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


def _shown(row):
    """The number as the member saw it: one decimal when the coach gave one (6.2),
    the whole number otherwise. A card that said 6 under a screen that said 6.2
    is a small disagreement a member notices in front of their followers."""
    exact = (row.payload or {}).get("score_exact")
    if isinstance(exact, (int, float)) and 1 <= exact <= 10:
        return f"{float(exact):.1f}"
    return str(row.score)


HUMAN_LINE = "Human-made — declared by @{who}. The AI coach scored it."
AI_ONLY_LINE = "Scored by the AI coach."


def _why(payload):
    """Up to two reasons behind the score, in the coach's own words: what worked,
    then what to fix. The robot's number is only as good as the reasons you can
    read next to it, and these are the same sentences the member got."""
    out = []
    for key in ("strengths", "fixes"):
        v = (payload or {}).get(key)
        if isinstance(v, list) and v and str(v[0]).strip():
            out.append({"kind": key, "text": str(v[0]).strip()[:200]})
    return out


def share_dict(row):
    progress = (row.payload or {}).get("progress") or None
    payload = row.payload or {}
    return {
        "shown": _shown(row),
        "progress": progress,
        # Whether the member DECLARED this performance human-made when they shared
        # it. A declaration, not a detection — nothing here can hear whether audio
        # is AI-generated — so the card says "declared by", and a false one is
        # reportable like anything else on the platform.
        "human": bool(payload.get("human")),
        "recap": payload.get("recap") or None,
        "challenge": payload.get("challenge") or "",
        "why": _why(payload),
        "listeners": payload.get("listeners") if isinstance(payload.get("listeners"), dict) else None,
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
        # One atomic add, never read-modify-write: two people opening it at once
        # must both count. Best-effort — a counter must not break the page.
        try:
            ScoreShare.objects.filter(pk=row.pk).update(views=F("views") + 1)
        except Exception:                                   # pragma: no cover
            pass
        return Response(share_dict(row))


class ScoreShareHumanView(APIView):
    """POST /api/economy/scores/<token>/human/ {declared} — the member's own
    declaration that this performance is human-made, shown on the card as such.

    Theirs alone to make (a stranger cannot put "human-made" on somebody else's
    card), reversible, and worded everywhere as a declaration because it is one."""
    from rest_framework.permissions import IsAuthenticated as _Auth
    permission_classes = [_Auth]

    def post(self, request, token):
        row = ScoreShare.objects.filter(token=token, user=request.user).first()
        if not row:
            return Response({"detail": "Not found."}, status=404)
        declared = (request.data or {}).get("declared")
        if not isinstance(declared, bool):
            return Response({"detail": "Say yes or no."}, status=400)
        row.payload = {**(row.payload or {}), "human": declared}
        row.save(update_fields=["payload"])
        return Response({"human": declared})


def _font(size):
    from PIL import ImageFont
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _wrap(draw, text, font, width, max_lines=2):
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
    if len(lines) > max_lines:              # what fits above the footer
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" .,;:”") + "…”"
    return lines


# The two shapes of the same card. 1200x630 is what every social preview
# (Open Graph / X large card) expects; 1080x1920 is what TikTok, Reels and
# Stories are — the places a member actually posts a score to.
CARD_SIZE = (1200, 630)
STORY_SIZE = (1080, 1920)


def wants_story(request):
    return str(request.GET.get("format", "")).lower() == "story"


def render_card(d, story=False):
    """The score card as PNG bytes, drawn from a plain dict.

    `d` needs `label`, `genre`, `score`, `verdict` and `username` — the shape
    `share_dict` returns. It is a dict, not a ScoreShare row, so the same card
    can be drawn for a coach read that lives on a POST (see coachshare.py) and
    not only for one that has its own share row. The caller decides whether the
    card may be drawn at all; this only draws.
    """
    from PIL import Image, ImageDraw
    W, H = STORY_SIZE if story else CARD_SIZE
    img = Image.new("RGB", (W, H), (7, 6, 13))
    g = ImageDraw.Draw(img)
    # Neon frame, the house look.
    g.rounded_rectangle((24, 24, W - 24, H - 24), radius=36, outline=(255, 85, 0), width=6)
    g.rounded_rectangle((36, 36, W - 36, H - 36), radius=30, outline=(56, 227, 255), width=2)
    who = f"@{d['username']}  ·  " if d["username"] else ""
    coach_line = (f"{d['label']} · glow-up" if d.get("progress")
                  else f"{d['label']} · my month" if d.get("recap")
                  else f"{d['label']} · {d['challenge']} challenge" if d.get("challenge")
                  else f"{d['label']} coach") \
        + (f" · {d['genre']}" if d["genre"] else "")
    quote = f"“{d['verdict']}”" if d["verdict"] else ""
    score = str(d.get("shown") or d["score"])

    if not story:
        g.text((80, 70), "MUSIC CONNECTZ", font=_font(34), fill=(56, 227, 255))
        g.text((80, 120), coach_line, font=_font(40), fill=(255, 255, 255))
        big = _font(220 if len(score) <= 2 else 190)
        g.text((80, 150), score, font=big, fill=(255, 85, 0))
        sw = g.textlength(score, font=big)
        g.text((80 + sw + 16, 310), "/10", font=_font(90), fill=(255, 255, 255))
        y = 420
        for line in _wrap(g, quote, _font(36), W - 160):
            g.text((80, y), line, font=_font(36), fill=(220, 220, 230))
            y += 46
        g.text((80, H - 140), (HUMAN_LINE.format(who=d["username"]) if d.get("human") and d["username"] else AI_ONLY_LINE),
               font=_font(26), fill=(255, 255, 255))
        g.text((80, H - 92), f"{who}Get your take scored free → musicconnectz.net",
               font=_font(30), fill=(52, 211, 153))
    else:
        # The same four things, stacked for a phone held upright. Side margins
        # are wider than the feed card's because Stories overlays its own UI at
        # the top and bottom edges; nothing that matters sits inside them.
        g.text((90, 190), "MUSIC CONNECTZ", font=_font(48), fill=(56, 227, 255))
        for i, line in enumerate(_wrap(g, coach_line, _font(60), W - 180, max_lines=2)):
            g.text((90, 270 + i * 74), line, font=_font(60), fill=(255, 255, 255))
        big = _font(520 if len(score) <= 2 else 400)
        g.text((90, 470), score, font=big, fill=(255, 85, 0))
        sw = g.textlength(score, font=big)
        g.text((90 + sw + 20, 800), "/10", font=_font(150), fill=(255, 255, 255))
        y = 1130
        for line in _wrap(g, quote, _font(58), W - 180, max_lines=6):
            g.text((90, y), line, font=_font(58), fill=(220, 220, 230))
            y += 76
        foot = ([(HUMAN_LINE.format(who=d["username"]) if d.get("human") and d["username"] else AI_ONLY_LINE)]) + \
               ([f"@{d['username']}"] if d["username"] else []) + [
            "Get your take scored free", "musicconnectz.net"]
        y = H - 150 - 66 * len(foot)
        for line in foot:
            g.text((90, y), line, font=_font(46), fill=(52, 211, 153))
            y += 66

    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def score_card_png(request, token):
    """GET /api/economy/scores/<token>/card.png — 1200x630, the size every
    social preview (Open Graph / X large card) expects. `?format=story` is the
    same card at 1080x1920 for TikTok, Reels and Stories."""
    row = get_object_or_404(ScoreShare.objects.select_related("user"), token=token)
    resp = HttpResponse(render_card(share_dict(row), story=wants_story(request)),
                        content_type="image/png")
    # The row never changes, so crawlers and CDNs may keep it.
    resp["Cache-Control"] = "public, max-age=86400"
    return resp
