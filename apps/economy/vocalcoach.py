"""SingZ Boss Take — record a take, get it scored and coached.

The blueprint's Boss Take ("user records one scored final take, exercise pass,
or song section") plus the AI Vocal Coach ("deeper feedback on why notes,
transitions, tone, or breath control are weak").

Open to every tier, priced per take. The blueprint filed the coach under StatZ
Gated Features; that was reconsidered once the no-account trial door shipped,
because gating members harder than strangers put the ladder upside down. A tier
now buys FREQUENCY — 1 / 5 / 10 free takes a day — not permission.

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
from .gemini import _bill, _key, generate_content
from .models import (
    PROMPT_ALLOWANCE,
    TIER_FREE,
    TIER_PREMIUM,
    TIER_STATZ,
    can_afford_ai,
    daily_prompt_state,
    membership_for,
    wallet_for,
)

logger = logging.getLogger(__name__)

# The take rides to Gemini as inline_data — base64 inside the request body —
# and that path caps the WHOLE request at 20MB. Base64 inflates by 4/3, so the
# real ceiling on the file is about 15MB, not 25.
#
# 25 was the stated limit and it could not be honoured: a 22MB take passed our
# own check, blew Gemini's, and came back as "The coach couldn't process that
# take" — a limit the app advertised and then refused, with a message that
# blamed the take. 14 leaves headroom for the prompt and the JSON envelope.
#
# It is enough for what a Boss Take is: ~15 minutes of 128kbps audio, or about
# a minute of video at the bitrate the recorder asks for. Anything longer than
# that is not one take.
MAX_MB = 14

# What Gemini will actually accept as inline media. Anything outside these two
# sets is refused by the API, not by us — and the refusal arrives as a plain
# non-200 that we used to surface as "The coach couldn't process that take",
# which blamed the performance for a container problem.
_GEMINI_AUDIO = {"audio/wav", "audio/mp3", "audio/mpeg", "audio/aiff",
                 "audio/aac", "audio/ogg", "audio/flac"}
_GEMINI_VIDEO = {"video/mp4", "video/mpeg", "video/mov", "video/quicktime",
                 "video/avi", "video/x-flv", "video/mpg", "video/webm",
                 "video/wmv", "video/3gpp"}

# Browsers record into containers Gemini names under `video/` even when the
# recording is audio-only. Same bytes, same container — only the label differs,
# so relabel rather than refuse a take we can obviously send.
_RELABEL = {
    "audio/webm": "video/webm",        # Chrome / Edge / Android default
    "audio/x-matroska": "video/webm",
    "audio/mp4": "video/mp4",          # Safari / iOS default
    "audio/x-m4a": "video/mp4",
    "audio/m4a": "video/mp4",
    "audio/3gpp": "video/3gpp",
    "audio/vorbis": "audio/ogg",
    "audio/opus": "audio/ogg",
    "audio/x-wav": "audio/wav",
    "audio/wave": "audio/wav",
    "audio/x-aiff": "audio/aiff",
}


def gemini_mime(content_type):
    """The mime type to hand Gemini for this upload, or None if it can't take it.

    Two things go wrong between a browser and this call, and both were live:

    1. `MediaRecorder.mimeType` is a FULL media type — Chrome hands back
       `audio/webm;codecs=opus`. The parameter rides through the Blob, the
       multipart upload and Django untouched, and Gemini rejects the whole
       request over it. Strip to the bare type.
    2. `audio/webm` is not on Gemini's audio list at all, though `video/webm`
       is. A browser-recorded take was therefore unscoreable on the two
       biggest browsers — which is exactly the "couldn't process that take"
       people were seeing on a perfectly good performance.
    """
    base = (content_type or "").split(";")[0].strip().lower()
    base = _RELABEL.get(base, base)
    return base if base in _GEMINI_AUDIO or base in _GEMINI_VIDEO else None


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


def score_take(app_key, f, content_type, *, genre, target, difficulty):
    """Send one take to the model. Returns (payload, error) — exactly one is None.

    Shared by the member coach and the no-account trial, deliberately: a trial
    that grades on an easier rubric is a lie about the product, and the first
    real take would contradict it.
    """
    key = _key()
    if not key:
        return None, (
            {"detail": "The vocal coach isn't configured — set GEMINI_API_KEY on the backend."},
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    difficulty = str(difficulty or "").lower()
    prompt = prompt_for(
        app_key,
        genre=str(genre or "unspecified")[:60],
        target=str(target or "unspecified")[:60],
        difficulty=difficulty if difficulty in DIFFICULTIES else "builder",
    )
    # Normalise BEFORE the call. An unsupported container is a refusal we can
    # give instantly and explain, rather than a round trip that comes back as a
    # generic failure the member reads as "my take was bad".
    mime = gemini_mime(content_type)
    if not mime:
        return None, (
            {"detail": f"The coach can't read {content_type or 'that format'}. "
                       "Record in the app, or attach an m4a, mp3, wav, ogg or mp4.",
             "content_type": content_type},
            status.HTTP_400_BAD_REQUEST,
        )

    unreadable = ({"detail": "The coach couldn't process that take."}, status.HTTP_502_BAD_GATEWAY)
    # Read the take ONCE. The chain below may try several models, and a file
    # object read a second time hands the next attempt an empty take — which
    # would come back as "the coach couldn't read that" about a take we never
    # actually sent.
    body = {"contents": [{"parts": [
        {"text": prompt},
        {"inline_data": {"mime_type": mime, "data": base64.b64encode(f.read()).decode()}},
    ]}]}
    try:
        resp, tried = generate_content("text", body, key=key, timeout=90,
                                       env_vars=("GEMINI_AUDIO_MODEL",),
                                       label=f"{app_key} coach")
    except requests.RequestException:
        logger.exception("SingZ coach: could not reach Gemini")
        return None, ({"detail": "Couldn't reach the coach. Try that take again."},
                      status.HTTP_502_BAD_GATEWAY)
    model = ", ".join(tried)

    if resp.status_code != 200:
        # Log what we SENT as well as what came back. Without the mime type and
        # model in the line, a container rejection and a bad API key look
        # identical in the logs, which is how this one stayed hidden.
        logger.error("%s coach: Gemini %s for mime=%s model=%s — %s",
                     app_key, resp.status_code, mime, model, resp.text[:300])
        # And say it on the SCREEN. "The coach couldn't process that take" was
        # true of a bad key, a retired model, a spent quota and an unreadable
        # container alike — one sentence for four different problems, none of
        # them the member's, all of them reading like the take was bad.
        #
        # The upstream body is deliberately NOT forwarded: it is a third party's
        # error text, and it is not ours to put in front of a member. The status
        # plus our own reading of it is the useful part.
        why = {
            400: "that take's format wasn't accepted",
            403: "the coach's API key was refused",
            404: "the coach can't reach a model right now — we're on it",
            429: "the coach has hit its limit for now — try again shortly",
        }.get(resp.status_code,
              "the coach is having a moment" if resp.status_code >= 500
              else "the coach refused that one")
        return None, ({"detail": f"The coach couldn't read that take — {why}.",
                       # Enough for you to diagnose from a screenshot, and
                       # nothing that identifies the key or the account.
                       "upstream_status": resp.status_code,
                       "sent_mime": mime,
                       "model": model},
                      status.HTTP_502_BAD_GATEWAY)
    try:
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, ValueError):
        logger.error("SingZ coach: unexpected Gemini shape")
        return None, unreadable

    parsed = _parse(text)
    if not parsed or _clamp(parsed.get("score")) is None:
        logger.error("SingZ coach: unparseable reply — %s", text[:300])
        return None, ({"detail": "The coach's reply didn't come back readable. Try again."},
                      status.HTTP_502_BAD_GATEWAY)

    listy = lambda v: [str(x)[:300] for x in v][:6] if isinstance(v, list) else []
    return {
        "score": _clamp(parsed.get("score")),
        "scores": {k: _clamp((parsed.get("scores") or {}).get(k))
                   for k in profile_for_app(app_key)["scores"]},
        "verdict": str(parsed.get("verdict", ""))[:400],
        "strengths": listy(parsed.get("strengths")),
        "fixes": listy(parsed.get("fixes")),
        "next_drill": str(parsed.get("next_drill", ""))[:300],
    }, None


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
        allowance, _, daily_left = daily_prompt_state(request.user)
        w = wallet_for(request.user)
        cost = ai_cost("standard")
        # "Allowed" now means CAN YOU TAKE ONE RIGHT NOW — configured, and either
        # a free prompt left or the balance to cover it. It used to mean "are you
        # StatZ", which was a less useful answer to the only question the screen
        # is actually asking.
        allowed = bool(_key()) and (daily_left > 0 or can_afford_ai(request.user, cost))
        return Response({
            "allowed": allowed,
            # Nothing tier-locks a take any more. The tier decides HOW MANY come
            # free per day, not whether you may have one — see the ladder below.
            "gated": False,
            "required_tier": None,
            "configured": bool(_key()),
            "cost_cents": cost,
            # A free daily prompt covers the whole run before any paid balance.
            "free_today": daily_left > 0,
            "daily_remaining": daily_left,
            "daily_allowance": allowance,
            "tier": tier,
            # What more would buy: frequency, not access. Stated so the upsell is
            # present and honest without being a wall in front of the feature.
            "allowance_ladder": [
                {"tier": t, "daily": PROMPT_ALLOWANCE[t]}
                for t in (TIER_FREE, TIER_PREMIUM, TIER_STATZ)
            ],
            "open_in": "membershipz",
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
        # No tier gate. The blueprint filed the AI coach under StatZ Gated
        # Features and that was reconsidered on purpose: the trial door already
        # hands an anonymous visitor a full scored take, one per address per
        # day, so gating members harder than non-members had the ladder upside
        # down — a Premium member paying every month got less than a stranger.
        #
        # A take still costs a prompt, and the tier still decides how many come
        # free each day (PROMPT_ALLOWANCE: 1 / 5 / 10). Frequency is the honest
        # difference between somebody tracking daily and somebody curious once a
        # month; access was charging twice for the same thing.
        f = request.FILES.get("take")
        if not f:
            return Response({"detail": "Record or attach a take first."}, status=status.HTTP_400_BAD_REQUEST)
        content_type = (getattr(f, "content_type", "") or "").lower()
        # Video has always been accepted here — the model watches the take as
        # well as hearing it, which is worth real marks on delivery and breath.
        # The refusal copy said "isn't audio" and contradicted the check, which
        # is how the file picker ended up audio-only for a year.
        if not (content_type.startswith("audio/") or content_type.startswith("video/")):
            return Response({"detail": "That isn't audio or video. Record a take, or attach an "
                                       "audio or video file."},
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
        payload, err = score_take(
            self.app_key, f, content_type,
            genre=data.get("genre"), target=data.get("range"),
            difficulty=data.get("difficulty"),
        )
        if err:
            body, code = err
            return Response(body, status=code)

        # Only bill once a usable result exists — a failed take is not charged.
        # count_daily: a coached take is a flat text-model run, so the tier's
        # free daily prompts cover it first. Without it the coach silently
        # skipped the allowance a StatZ member is told they get and went
        # straight to their PromptZ and cash.
        charged = _bill(request.user, note=f"{profile_for_app(self.app_key)['label']} Boss Take — AI Coach", count_daily=True)
        return Response({**payload, "cost_cents": charged})
