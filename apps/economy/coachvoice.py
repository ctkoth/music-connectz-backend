"""CoachVoiceZ — which voice reads a Boss Take's feedback aloud, and who may
choose it.

**Not a voice clone.** Gemini TTS ships a handful of prebuilt voices — no
cloning, no real voice sample. An actual clone of one specific real person's
voice needs a dedicated voice-cloning service and an explicit consent-and-
sample workflow, which is a different, bigger project than this one. "corey"
here is a LABEL on one of Gemini's stock voices — the house voice — never a
claim that it sounds like a specific person.

Three levels of access, the same shape `soundz.py` already uses for CHOOSE,
plus one more for LISTEN:

* **Everyone** can hear the coach read feedback aloud, in the house voice.
  The substance of "being understood is not a luxury" applies to coaching
  too — a member should not need a subscription to have their own feedback
  read back to them.
* **Premium** can SAMPLE any voice in the catalog — hear it once, without
  saving it. A taste of the StatZ feature, not the feature itself.
* **StatZ** can CHOOSE — save a voice as a standing preference, same as
  `sound_pack`.

The server stores a CHOICE (a catalog key) and never a waveform; the catalog
itself — which Gemini voice each key maps to, and its label — lives here
rather than the client, because "which voices exist" is exactly the kind of
thing that drifted into nine places when it lived in copy instead of code.
"""
import base64
import logging
import struct

import requests
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .gemini import _key as gemini_key, generate_content
from .models import (TIER_FREE, TIER_PREMIUM, TIER_STATZ, CoachVoiceUse,
                     coach_voice_state, membership_for, profile_for)

logger = logging.getLogger(__name__)

# Real Gemini prebuilt voice names. Nothing here is a clone of anybody's real
# voice — these are the model's own stock set, and "corey" is a label on one
# of them, chosen as the house default.
COACH_VOICES = {
    "corey":  {"label": "Coach Corey (default)", "gemini_voice": "Charon",
               "description": "The house voice — direct and warm, no flattery.",
               "tier": TIER_FREE},
    "kore":   {"label": "Kore", "gemini_voice": "Kore",
               "description": "Clear and even.", "tier": TIER_PREMIUM},
    "puck":   {"label": "Puck", "gemini_voice": "Puck",
               "description": "Upbeat and energetic.", "tier": TIER_PREMIUM},
    "fenrir": {"label": "Fenrir", "gemini_voice": "Fenrir",
               "description": "Deep and blunt.", "tier": TIER_STATZ},
    "aoede":  {"label": "Aoede", "gemini_voice": "Aoede",
               "description": "Bright and quick.", "tier": TIER_STATZ},
}
DEFAULT_VOICE = "corey"

MAX_SPEAK_CHARS = 2000  # one Boss Take's worth of prose, not a novel


def may_sample(user):
    """Premium or StatZ — hear any catalog voice once, without saving it."""
    return membership_for(user).tier in (TIER_PREMIUM, TIER_STATZ)


def may_choose(user):
    """StatZ only — save a voice as the standing preference."""
    return membership_for(user).tier == TIER_STATZ


def clean_voice_id(value):
    """A catalog key, or "" for anything unrecognised — falling back to the
    house voice is the correct degrade, the same rule `soundz.clean_pack`
    follows for a sound pack it cannot verify."""
    value = str(value or "").strip().lower()
    return value if value in COACH_VOICES else ""


def voice_state(user):
    p = profile_for(user)
    tier = membership_for(user).tier
    used, cap, left = coach_voice_state(user)
    stored = clean_voice_id(p.coach_voice) or DEFAULT_VOICE
    return {
        "voice": stored,
        "voices": [{"id": k, **v} for k, v in COACH_VOICES.items()],
        "can_sample": may_sample(user),
        "can_choose": may_choose(user),
        "tier": tier,
        "sample_tier_required": TIER_PREMIUM,
        "choose_tier_required": TIER_STATZ,
        "speak_used_today": used, "speak_daily_chars": cap, "speak_remaining": left,
    }


class CoachVoiceView(APIView):
    """GET the voice catalog and current choice; PATCH to save one (StatZ)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(voice_state(request.user))

    def patch(self, request):
        if not may_choose(request.user):
            return Response(
                {**voice_state(request.user),
                 "detail": "Choosing your coach's voice is a StatZ perk. Premium "
                           "can sample any voice; the house voice is free at every tier."},
                status=status.HTTP_403_FORBIDDEN)
        voice_id = clean_voice_id((request.data or {}).get("voice"))
        if not voice_id:
            return Response({**voice_state(request.user),
                              "detail": "That's not a voice this coach has."},
                             status=status.HTTP_400_BAD_REQUEST)
        p = profile_for(request.user)
        p.coach_voice = voice_id
        p.save(update_fields=["coach_voice", "updated_at"])
        return Response(voice_state(request.user))


def _wav(pcm, rate=24000, channels=1, bits=16):
    """A 44-byte RIFF header in front of raw PCM. Same shape as
    keyconnectz._wav — Gemini's TTS reply is raw PCM either way."""
    block = channels * bits // 8
    return (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
            + struct.pack("<IHHIIHH", 16, 1, channels, rate, rate * block, block, bits)
            + b"data" + struct.pack("<I", len(pcm)) + pcm)


def _pcm_rate(mime):
    for bit in str(mime or "").split(";"):
        if bit.strip().startswith("rate="):
            try:
                return int(bit.strip()[5:])
            except ValueError:
                return 24000
    return 24000


class CoachSpeakView(APIView):
    """POST { text, voice? } → the coach's own feedback, read aloud.

    `voice` defaults to the member's saved choice (or the house voice).
    Asking for a DIFFERENT voice than that requires `may_sample` — refused
    rather than silently substituted, so a member learns why from the
    response instead of hearing a voice they did not ask for.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        d = request.data or {}
        text = str(d.get("text", "") or "").strip()
        if not text:
            return Response({"detail": "Nothing to read out."}, status=status.HTTP_400_BAD_REQUEST)
        if len(text) > MAX_SPEAK_CHARS:
            return Response(
                {"detail": f"That's longer than {MAX_SPEAK_CHARS:,} characters."},
                status=status.HTTP_400_BAD_REQUEST)

        p = profile_for(request.user)
        saved = clean_voice_id(p.coach_voice) or DEFAULT_VOICE
        requested = clean_voice_id(d.get("voice")) or saved
        if requested != saved and not may_sample(request.user):
            return Response(
                {**voice_state(request.user),
                 "detail": "Sampling another voice is a Premium perk. The house "
                           "voice is free — leave voice unset to hear it."},
                status=status.HTTP_403_FORBIDDEN)

        used, cap, left = coach_voice_state(request.user)
        if len(text) > left:
            return Response(
                {**voice_state(request.user),
                 "detail": f"You've used today's {cap:,} characters of coach "
                           f"playback — {left:,} left. Resets on a rolling 24 hours."},
                status=status.HTTP_429_TOO_MANY_REQUESTS)

        key = gemini_key()
        if not key:
            return Response({"detail": "The coach's voice isn't switched on — "
                                       "the backend is missing GEMINI_API_KEY."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        gemini_voice = COACH_VOICES[requested]["gemini_voice"]
        body = {
            "contents": [{"parts": [{"text": (
                "Read the following coaching feedback aloud, naturally, as a "
                "real coach talking to the person who just performed. Read "
                f"ONLY these words and add nothing:\n\n{text}")}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": gemini_voice}}},
            },
        }
        try:
            resp, tried = generate_content("tts", body, key=key, timeout=90,
                                           env_vars=("GEMINI_TTS_MODEL",),
                                           label="CoachVoiceZ speak")
        except requests.RequestException:
            logger.exception("CoachVoiceZ speak: could not reach Gemini")
            return Response({"detail": "Couldn't reach the coach's voice. Try again."},
                            status=status.HTTP_502_BAD_GATEWAY)

        if resp is None or resp.status_code != 200:
            code = getattr(resp, "status_code", 0)
            logger.error("CoachVoiceZ speak: Gemini %s voice=%s model=%s — %s",
                         code, requested, ", ".join(tried), getattr(resp, "text", "")[:300])
            why = {
                400: "that text wasn't accepted",
                403: "the voice's API key was refused",
                404: "the voice can't reach a model right now — we're on it",
                429: "the voice has hit its limit for now — try again shortly",
            }.get(code, "the voice is having a moment" if code >= 500
                  else "the voice refused that one")
            return Response({"detail": f"Couldn't read that out — {why}.",
                             "upstream_status": code},
                            status=status.HTTP_502_BAD_GATEWAY)

        try:
            part = resp.json()["candidates"][0]["content"]["parts"][0]["inline_data"]
            pcm = base64.b64decode(part["data"])
            rate = _pcm_rate(part.get("mime_type", ""))
        except Exception:
            logger.exception("CoachVoiceZ speak: no audio in the reply")
            pcm, rate = b"", 24000

        if not pcm:
            # Nothing playable came back, so nothing is spent — the same rule
            # a failed Boss Take or a failed translation already follows.
            return Response({"detail": "The coach's voice came back empty. "
                                       "Nothing was counted — try again."},
                            status=status.HTTP_502_BAD_GATEWAY)

        wav = _wav(pcm, rate=rate)
        CoachVoiceUse.objects.create(user=request.user, chars=len(text))
        used, cap, left = coach_voice_state(request.user)
        return Response({
            # Inline, not stored — heard once and thrown away, same as
            # KeyConnectZ's read-aloud.
            "audio_b64": base64.b64encode(wav).decode("ascii"),
            "mime": "audio/wav",
            "voice": requested,
            "speak_used_today": used, "speak_daily_chars": cap, "speak_remaining": left,
        })
