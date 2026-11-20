"""ImageZ scores a picture's CRAFT: what works, why, and how to make it better.

Corey asked for ImageZ pictures to be scored in detail. Every dimension is something the picture itself shows and
the maker can change — composition, light, colour, sharpness, editing, impact — each 1-10 with WHY (what in this
picture earned the number) and HOW (the one change that would move it). The overall is the server's arithmetic
(the mean of what was scored), never the model's, so it cannot drift from the numbers under it.

What it will not score, said in the prompt and on the screen: **how attractive anybody in the picture is**, their
face, body, age or weight. Rating looks is LookZMaxZ's, for verified adults scoring their own photo, and never a
minor. Corey asked for attractiveness at every age; that one is refused, because a number on a kid's looks on a
platform with strangers on it is harm whatever the disclaimer says, and the Play listing commits to the Families
policy. Everything else he asked for is here.

Priced like any one-picture AI reading (stated on GET before the button), billed only when a readable score comes
back. The picture rides inside the one request and is not kept.
"""
import base64
import logging

import requests
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .attractivenessz import _parse
from .catalog import ai_cost
from .gemini import _bill, _key, generate_content
from .imagez_cutout import _decode
from .models import ai_energy_cost, can_afford_ai, daily_prompt_covers, daily_prompt_state

logger = logging.getLogger(__name__)

MAX_MB = 8
DIMENSIONS = {
    "composition": {"label": "Composition 📐", "what": "Where things sit in the frame, and where the eye goes first."},
    "light": {"label": "Light 💡", "what": "Exposure and the quality and direction of the light."},
    "color": {"label": "Colour 🎨", "what": "How the colours work together, and whether they carry a mood."},
    "sharpness": {"label": "Sharpness 🔍", "what": "Focus where it matters, and noise or blur where it doesn't belong."},
    "editing": {"label": "Editing ✂️", "what": "Crops, retouching, text and layers: clean, or showing the seams."},
    "impact": {"label": "Impact 🔥", "what": "Whether it stops a scroll and says something."},
}
# A PROFILE PHOTO is judged as a photo, for the things its maker can change in a minute: how it is framed, the light,
# what is behind them, whether it is sharp, and whether it reads at the size it is shown. Nothing here is about the
# person in it — not their face, body, age, expression or looks — and there is NO overall number, because one number
# beside a face reads as a score on the face. Any age may use it for that reason.
PROFILE_DIMENSIONS = {
    "framing": {"label": "Framing & crop 📐", "what": "Is the subject well placed and cropped so it reads at thumbnail size, with room around it and nothing cut off awkwardly?"},
    "light": {"label": "Lighting 💡", "what": "Is the exposure right and the light even, without harsh shadows or a blown-out window behind?"},
    "background": {"label": "Background 🖼️", "what": "Is what is behind the subject tidy and uncluttered, and does it help rather than distract?"},
    "sharpness": {"label": "Sharpness 🔍", "what": "Is the photo in focus where it matters, free of blur and noise?"},
    "color": {"label": "Colour & contrast 🎨", "what": "Do the colours and contrast look natural and clear, with nothing muddy or over-filtered?"},
}
PROFILE_CAVEAT = ("This is feedback on the PHOTO — framing, light, background, focus and colour — and nothing about you. It never "
                  "judges a face, body, age, expression or looks, and there is deliberately no overall score.")
CAVEAT = ("A score of the picture's craft, from one look at it — not of anybody in it. It never rates how a person "
          "looks; that is LookZMaxZ's, for adults rating their own photo.")


def prompt(purpose=""):
    if purpose == "profile":
        dims = "\n".join(f"- {k}: {d['what']}" for k, d in PROFILE_DIMENSIONS.items())
        return (
            "You are a photo editor advising on a PROFILE PHOTO as a photograph. Score each dimension 1-10 on this scale: "
            "1-4 is getting in the way, 5-7 is solid, 8-9 is strong, 10 is exceptional. A dimension the photo does not let "
            "you judge is null, never guessed.\n" + dims + "\n"
            "For each give `why` (what in THIS photo earned the number, one sentence) and `how` (the one change the maker can "
            "make in a minute — move, crop, window, background, a setting — to raise it, one sentence). You are judging the "
            "photograph, never the person: NEVER comment on or score anybody's face, body, weight, age, expression, "
            "attractiveness or appearance, and never suggest changing how a person looks. Then one sentence `verdict` about "
            "the photo and the single best `next` step.\n"
            'Return JSON only: {"scores": {key: {"score": n|null, "why": s, "how": s}}, "verdict": s, "next": s}'
        )
    dims = "\n".join(f"- {k}: {d['what']}" for k, d in DIMENSIONS.items())
    return (
        "You are an art director scoring one picture for its maker. Score each dimension 1-10 on this scale: "
        "1-4 is getting in the way, 5-7 is solid, 8-9 is strong, 10 is exceptional. A dimension the picture does not "
        "let you judge is null, never guessed.\n" + dims + "\n"
        "For each give `why` (what in THIS picture earned the number, one sentence) and `how` (the one change that "
        "would raise it, one sentence). NEVER comment on or score how attractive any person is, their face, body, "
        "weight, age or appearance; judge only the picture's craft. Then one sentence `verdict` and the single best "
        "`next` step.\n"
        'Return JSON only: {"scores": {key: {"score": n|null, "why": s, "how": s}}, "verdict": s, "next": s}'
    )


def clean(raw, purpose=""):
    """Only declared dimensions, scores 1-10 or None, text bounded; the overall is ours. None if nothing scored.
    A profile photo has no overall at all (see PROFILE_DIMENSIONS)."""
    if not isinstance(raw, dict):
        return None
    profile = purpose == "profile"
    out = {}
    for k, d in (PROFILE_DIMENSIONS if profile else DIMENSIONS).items():
        r = (raw.get("scores") or {}).get(k) if isinstance(raw.get("scores"), dict) else None
        if not isinstance(r, dict):
            continue
        try:
            n = int(round(float(r.get("score"))))
        except (TypeError, ValueError):
            n = None
        if n is not None and not 1 <= n <= 10:
            n = max(1, min(10, n))
        why = " ".join(str(r.get("why") or "").split())[:240]
        how = " ".join(str(r.get("how") or "").split())[:240]
        if n is None and not why:
            continue
        out[k] = {"label": d["label"], "score": n, "why": why, "how": how}
    scored = [v["score"] for v in out.values() if v["score"] is not None]
    if not scored:
        return None
    return {"scores": out, "overall": None if profile else round(sum(scored) / len(scored), 1),
            "verdict": " ".join(str(raw.get("verdict") or "").split())[:300],
            "next": " ".join(str(raw.get("next") or "").split())[:240],
            "caveat": PROFILE_CAVEAT if profile else CAVEAT, **({"purpose": "profile"} if profile else {})}


def _price(user):
    cost = ai_cost("standard")
    _, _, left = daily_prompt_state(user)
    free = left > 0 and daily_prompt_covers(cost)
    return {"cost_cents": cost, "free_today": free, "energy": ai_energy_cost(user),
            "can_run": bool(_key()) and (free or can_afford_ai(user, cost))}


class ImageZRateView(APIView):
    """GET: price and what is scored. POST {image: data URL}: the picture's craft, scored with why and how."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"price": _price(request.user), "configured": bool(_key()), "max_mb": MAX_MB, "caveat": CAVEAT,
                         "dimensions": [{"key": k, **d} for k, d in DIMENSIONS.items()],
                         "profile": {"caveat": PROFILE_CAVEAT, "dimensions": [{"key": k, **d} for k, d in PROFILE_DIMENSIONS.items()]}})

    def post(self, request):
        purpose = "profile" if str((request.data or {}).get("purpose") or "") == "profile" else ""
        mime, raw = _decode(str((request.data or {}).get("image") or ""))
        if not raw:
            return Response({"detail": "Send the picture as a PNG, JPEG or WebP. Nothing was charged."}, status=status.HTTP_400_BAD_REQUEST)
        if len(raw) > MAX_MB * 1024 * 1024:
            return Response({"detail": f"That picture is over {MAX_MB} MB — make it smaller first. Nothing was charged."},
                            status=status.HTTP_400_BAD_REQUEST)
        if not _key():
            return Response({"detail": "The AI isn't switched on yet. Nothing was charged."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        price = _price(request.user)
        if not price["free_today"] and not can_afford_ai(request.user, price["cost_cents"]):
            return Response({"detail": "Not enough PromptZ or balance for a score. Nothing was charged.", **price},
                            status=status.HTTP_402_PAYMENT_REQUIRED)
        body = {"contents": [{"parts": [{"text": prompt(purpose)}, {"inline_data": {"mime_type": mime, "data": base64.b64encode(raw).decode()}}]}],
                "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json"}}
        try:
            resp, _tried = generate_content("text", body, key=_key(), timeout=90, label="ImageZ score")
        except requests.RequestException:
            logger.exception("ImageZ score: could not reach Gemini")
            return Response({"detail": "Couldn't reach the AI — nothing was charged."}, status=status.HTTP_502_BAD_GATEWAY)
        if resp is None or resp.status_code != 200:
            return Response({"detail": "The AI couldn't read that picture right now — nothing was charged."}, status=status.HTTP_502_BAD_GATEWAY)
        try:
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (ValueError, KeyError, IndexError, TypeError):
            text = ""
        got = clean(_parse(text), purpose)
        if not got:
            return Response({"detail": "The AI's answer couldn't be read — nothing was charged. Try again."}, status=status.HTTP_502_BAD_GATEWAY)
        charged = _bill(request.user, "ImageZ score", count_daily=True)
        if charged is None:
            return Response({"detail": "Not enough PromptZ or balance for a score."}, status=status.HTTP_402_PAYMENT_REQUIRED)
        return Response({**got, "charged_cents": charged})
