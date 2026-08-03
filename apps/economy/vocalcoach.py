"""SingZ Boss Take — record a take, get it scored and coached.

The blueprint's Boss Take ("user records one scored final take, exercise pass,
or song section") plus the StatZ-gated AI Vocal Coach ("deeper feedback on why
notes, transitions, tone, or breath control are weak").

A take is sent to Gemini as inline audio along with the member's genre, target
range and difficulty, and comes back as a score out of 10 plus advice in the
Music ConnectZ voice — direct, specific, no hedging.

Only the sub-scores a single take can honestly support are returned. The
blueprint's Consistency, Voice Health and Goal Match scores need history or
self-reported condition, so they are deliberately absent rather than invented
from one clip.
"""
import base64
import json
import logging
import os
import re

import requests
from django.conf import settings
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import ai_cost
from .gemini import BASE, _bill, _key
from .models import TIER_DEBUG, TIER_STATZ, can_afford_ai, membership_for

logger = logging.getLogger(__name__)

MAX_MB = 25
# Difficulty and the scored dimensions come straight from the blueprint.
DIFFICULTIES = ["starter", "builder", "performer", "stageboss"]
SCORES = ["pitch", "tone", "breath", "range", "agility"]

PROMPT = """You are the Music ConnectZ vocal coach. You are listening to one \
recorded take from a member training in SingZ.

Their context:
- Genre: {genre}
- Target vocal range: {range}
- Difficulty: {difficulty}

Score the take and coach it. Write the way a good engineer talks to an artist \
in the room: direct, specific, second person, no hedging and no flattery. Name \
the actual moment something goes wrong rather than describing the category. \
Never invent detail you cannot hear.

Return ONLY valid JSON, no markdown fence, in exactly this shape:
{{
  "score": <overall 1-10 integer>,
  "scores": {{"pitch": <1-10>, "tone": <1-10>, "breath": <1-10>, "range": <1-10>, "agility": <1-10>}},
  "verdict": "<one sentence, what this take is>",
  "strengths": ["<what genuinely worked>", "..."],
  "fixes": ["<the specific thing to change, and how>", "..."],
  "next_drill": "<one drill to run before the next take>"
}}"""


def _parse(text):
    """Pull the JSON object out of a model reply that may be fenced."""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def _clamp(v, lo=1, hi=10):
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except (TypeError, ValueError):
        return None


class SingZCoachView(APIView):
    """POST multipart {take, genre, range, difficulty} → score + coaching."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        # The blueprint lists AI Vocal Coach under StatZ Gated Features.
        tier = membership_for(request.user).tier
        if tier not in (TIER_STATZ, TIER_DEBUG):
            return Response(
                {"detail": "The AI Vocal Coach is a StatZ feature. Upgrade in MembershipZ to have your takes scored.",
                 "required_tier": TIER_STATZ},
                status=status.HTTP_403_FORBIDDEN,
            )

        f = request.FILES.get("take")
        if not f:
            return Response({"detail": "Record or attach a take first."}, status=status.HTTP_400_BAD_REQUEST)
        content_type = (getattr(f, "content_type", "") or "").lower()
        if not (content_type.startswith("audio/") or content_type.startswith("video/")):
            return Response({"detail": "That file isn't audio. Record a take or attach an audio file."},
                            status=status.HTTP_400_BAD_REQUEST)
        if f.size > MAX_MB * 1024 * 1024:
            return Response({"detail": f"That take is too big — keep it under {MAX_MB}MB."},
                            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

        key = _key()
        if not key:
            return Response({"detail": "The vocal coach isn't configured — set GEMINI_API_KEY on the backend."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        cost = ai_cost("standard")
        if cost and not can_afford_ai(request.user, cost):
            return Response({"detail": "Not enough PromptZ / balance for a coached take.", "cost_cents": cost},
                            status=status.HTTP_402_PAYMENT_REQUIRED)

        data = request.data
        prompt = PROMPT.format(
            genre=str(data.get("genre", "") or "unspecified")[:60],
            range=str(data.get("range", "") or "unspecified")[:60],
            difficulty=(str(data.get("difficulty", "")).lower() if str(data.get("difficulty", "")).lower() in DIFFICULTIES else "builder"),
        )

        model = os.environ.get("GEMINI_AUDIO_MODEL", "gemini-2.5-flash")
        try:
            resp = requests.post(
                f"{BASE}/models/{model}:generateContent?key={key}",
                json={"contents": [{"parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": content_type,
                                     "data": base64.b64encode(f.read()).decode()}},
                ]}]},
                timeout=90,
            )
        except requests.RequestException:
            logger.exception("SingZ coach: could not reach Gemini")
            return Response({"detail": "Couldn't reach the coach. Try that take again."},
                            status=status.HTTP_502_BAD_GATEWAY)

        if resp.status_code != 200:
            logger.error("SingZ coach: Gemini returned %s — %s", resp.status_code, resp.text[:300])
            return Response({"detail": "The coach couldn't process that take."},
                            status=status.HTTP_502_BAD_GATEWAY)

        try:
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, ValueError):
            logger.error("SingZ coach: unexpected Gemini shape")
            return Response({"detail": "The coach couldn't process that take."},
                            status=status.HTTP_502_BAD_GATEWAY)

        parsed = _parse(text)
        if not parsed or _clamp(parsed.get("score")) is None:
            logger.error("SingZ coach: unparseable reply — %s", text[:300])
            return Response({"detail": "The coach's reply didn't come back readable. Try again."},
                            status=status.HTTP_502_BAD_GATEWAY)

        # Only bill once a usable result exists — a failed take is not charged.
        charged = _bill(request.user, note="SingZ Boss Take — AI Vocal Coach")

        listy = lambda v: [str(x)[:300] for x in v][:6] if isinstance(v, list) else []
        return Response({
            "score": _clamp(parsed.get("score")),
            "scores": {k: _clamp((parsed.get("scores") or {}).get(k)) for k in SCORES},
            "verdict": str(parsed.get("verdict", ""))[:400],
            "strengths": listy(parsed.get("strengths")),
            "fixes": listy(parsed.get("fixes")),
            "next_drill": str(parsed.get("next_drill", ""))[:300],
            "cost_cents": charged,
        })
