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
from .instruments import DIFFICULTIES, profile_for_app, prompt_for
from .gemini import BASE, _bill, _key
from .models import (
    TIER_DEBUG,
    TIER_STATZ,
    can_afford_ai,
    daily_prompt_state,
    membership_for,
    wallet_for,
)

logger = logging.getLogger(__name__)

MAX_MB = 25

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
    """The Boss Take coach for any InstrumentZ app.

    GET  → what a take costs this member, plus the dimensions THIS instrument
           is scored on so the client renders from the server rather than
           keeping its own copy that can drift.
    POST → multipart {take, genre, range, difficulty} → score + coaching.

    `app_key` is bound per-route in urls.py; it defaults to singz so the
    original /api/singz/coach/ keeps behaving exactly as it did.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    app_key = "singz"

    def get(self, request):
        """The price, before anyone commits to paying it.

        A cost that only appears in the response is a bill, not a price. This
        answers what THIS member pays for THIS take right now — whether a free
        daily prompt covers it, how many they have left, and what it falls back
        to if not.
        """
        profile = profile_for_app(self.app_key)
        tier = membership_for(request.user).tier
        allowed = tier in (TIER_STATZ, TIER_DEBUG)
        _, _, daily_left = daily_prompt_state(request.user)
        w = wallet_for(request.user)
        cost = ai_cost("standard")
        return Response({
            "allowed": allowed,
            "required_tier": TIER_STATZ,
            "configured": bool(_key()),
            "cost_cents": cost,
            # A free daily prompt covers the whole run before any paid balance.
            "free_today": daily_left > 0,
            "daily_remaining": daily_left,
            "promptz": w.promptz or 0,
            "money_cents": w.money_cents or 0,
            # A take the coach can't read is never billed — _bill runs only
            # after a usable result parses. Worth saying, not just doing.
            "charged_on_failure": False,
            "max_mb": MAX_MB,
            # The client renders its score chips, range picker and honest-scope
            # footnote from these, so they cannot disagree with what the model
            # was actually asked to score.
            "app_key": self.app_key,
            "label": profile["label"],
            "scores": profile["scores"],
            "range_label": profile["range_label"],
            "ranges": [{"key": k, "label": l} for k, l in profile["ranges"]],
            "difficulties": DIFFICULTIES,
            "caveat": profile["caveat"],
        })

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

        # A free daily prompt covers the whole run, so it has to count here
        # too. Billing spends the allowance first (count_daily below), and this
        # gate did not know that — a StatZ member with prompts left but an
        # empty balance was refused a take that would have cost them nothing.
        cost = ai_cost("standard")
        _, _, daily_left = daily_prompt_state(request.user)
        if cost and not daily_left and not can_afford_ai(request.user, cost):
            return Response({"detail": "Not enough PromptZ / balance for a coached take.", "cost_cents": cost},
                            status=status.HTTP_402_PAYMENT_REQUIRED)

        data = request.data
        difficulty = str(data.get("difficulty", "")).lower()
        prompt = prompt_for(
            self.app_key,
            genre=str(data.get("genre", "") or "unspecified")[:60],
            target=str(data.get("range", "") or "unspecified")[:60],
            difficulty=difficulty if difficulty in DIFFICULTIES else "builder",
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
        # count_daily: a coached take is a flat text-model run, so the tier's
        # free daily prompts cover it first. Without it the coach silently
        # skipped the allowance a StatZ member is told they get and went
        # straight to their PromptZ and cash.
        charged = _bill(request.user, note=f"{profile_for_app(self.app_key)['label']} Boss Take — AI Coach", count_daily=True)

        listy = lambda v: [str(x)[:300] for x in v][:6] if isinstance(v, list) else []
        return Response({
            "score": _clamp(parsed.get("score")),
            "scores": {k: _clamp((parsed.get("scores") or {}).get(k))
                       for k in profile_for_app(self.app_key)["scores"]},
            "verdict": str(parsed.get("verdict", ""))[:400],
            "strengths": listy(parsed.get("strengths")),
            "fixes": listy(parsed.get("fixes")),
            "next_drill": str(parsed.get("next_drill", ""))[:300],
            "cost_cents": charged,
        })
