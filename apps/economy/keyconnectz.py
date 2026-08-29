"""KeyConnectZ — the keyboard.

Two halves, gated differently on purpose:

* **The wallpaper is Premium.** It's decoration — nobody loses a capability by
  not having it — which is exactly what makes it fair to sell.
* **Translate is free for every member, in any direction.** Being understood is
  not a luxury. A Free member typing to somebody in another language is the
  most useful thing this keyboard does, and putting a price on it would shut
  the app out of the rooms it exists to open.

Free is not uncapped. It runs a real model, and an unmetered LLM call behind a
login is a bill anyone can run up. The daily character allowance is published
by GET before a member types a word, per the cost/gain rule — a limit you find
out about by hitting it is not a limit, it's an ambush.

`auto` source detection is the default because asking somebody to declare the
language they're already typing in is asking them to do the computer's job.
"""
import base64
import json
import logging
import struct

import requests
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .gemini import _key as gemini_key, generate_content
from .catalog import (
    KEY_VOICE_CLIP_MAX_MB,
    KEY_VOICE_CLIP_MAX_SECONDS,
    key_voice_ladder,
    key_voice_limits,
)
from .models import (
    KEY_TRANSLATE_DAILY_CHARS,
    KEY_TRANSLATE_MAX_CHARS,
    KEY_WALLPAPER_MAX_MB,
    TIER_DEBUG,
    TIER_FREE,
    TIER_PREMIUM,
    TIER_STATZ,
    KeyboardSkin,
    KeyTranslation,
    KeyVoiceUse,
    key_translate_state,
    key_voice_state,
    keyboard_skin_for,
    membership_for,
)

logger = logging.getLogger(__name__)

WALLPAPER_TIERS = (TIER_PREMIUM, TIER_STATZ, TIER_DEBUG)


def _text_of(resp):
    """The text parts of a generateContent reply, joined. Never raises."""
    try:
        parts = resp.json()["candidates"][0]["content"]["parts"]
    except Exception:
        return ""
    return "".join(str(p.get("text", "")) for p in parts if isinstance(p, dict)).strip()


def _first_json(raw):
    """The JSON object in `raw`, or None.

    Models wrap answers in prose and code fences however firmly they are asked
    not to. One definition, because the salvage was written twice and the two
    copies had already started to differ.
    """
    raw = str(raw or "").strip()
    if not raw:
        return None
    try:
        out = json.loads(raw)
    except ValueError:
        a, b = raw.find("{"), raw.rfind("}")
        if a == -1 or b <= a:
            return None
        try:
            out = json.loads(raw[a:b + 1])
        except ValueError:
            return None
    return out if isinstance(out, dict) else None

# Haiku, not Opus, and the reason is the same one that keeps translate free.
#
# The keyboard is the only AI surface in this app that charges nothing, so it is
# the only one whose bill has no ceiling but the daily character allowance. On
# Opus that allowance is worth about 19c a day per member who spends all of it;
# on Haiku it is about 4c. Five times cheaper is the difference between "we can
# afford to give this away" and "we have to start charging for it" — and
# translation is the classic task where the small model is indistinguishable,
# because it is transformation, not reasoning.
#
# TranslateZ (translate.py) stays on Opus deliberately: it transcreates UI and
# content in batches, it is a paid action, and it has brand rules to get right.
# That is a different job than turning one message into another language.
TRANSLATE_MODEL = "claude-haiku-4-5"

# Enough to cover the rooms this app is actually in, with `auto` on the source
# side so nobody has to name the language they're already typing.
LANGUAGES = [
    ("auto", "Detect"), ("en", "English"), ("es", "Español"), ("pt", "Português"),
    ("fr", "Français"), ("de", "Deutsch"), ("it", "Italiano"), ("nl", "Nederlands"),
    ("pl", "Polski"), ("ru", "Русский"), ("uk", "Українська"), ("tr", "Türkçe"),
    ("ar", "العربية"), ("he", "עברית"), ("fa", "فارسی"), ("hi", "हिन्दी"),
    ("bn", "বাংলা"), ("ur", "اردو"), ("zh", "中文"), ("ja", "日本語"),
    ("ko", "한국어"), ("vi", "Tiếng Việt"), ("th", "ไทย"), ("id", "Bahasa Indonesia"),
    ("tl", "Tagalog"), ("sw", "Kiswahili"), ("yo", "Yorùbá"), ("ig", "Igbo"),
    ("ha", "Hausa"), ("am", "አማርኛ"), ("zu", "isiZulu"), ("el", "Ελληνικά"),
    ("sv", "Svenska"), ("no", "Norsk"), ("da", "Dansk"), ("fi", "Suomi"),
    ("cs", "Čeština"), ("ro", "Română"), ("hu", "Magyar"), ("ms", "Bahasa Melayu"),
]
LANG_NAME = dict(LANGUAGES)


def can_set_wallpaper(user):
    return membership_for(user).tier in WALLPAPER_TIERS


def skin_dict(skin, request):
    url = ""
    if skin.wallpaper:
        try:
            url = request.build_absolute_uri(skin.wallpaper.url)
        except ValueError:
            url = ""
    return {
        "wallpaper_url": url,
        "accent": skin.accent,
        "key_opacity": skin.key_opacity,
        "dark_keys": skin.dark_keys,
        "source_lang": skin.source_lang or "auto",
        "target_lang": skin.target_lang or "",
    }


class KeyboardView(APIView):
    """GET the keyboard's whole state; PATCH the look; POST a wallpaper.

    One GET answers everything the keyboard needs to render honestly: the skin,
    whether this member may change the wallpaper and what it costs them if not,
    the language list, and exactly how much translating they have left today.
    """

    permission_classes = [IsAuthenticated]
    # Multipart for the wallpaper, JSON for the settings — one view serves
    # both halves of the keyboard, so it has to accept both.
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        skin = keyboard_skin_for(request.user)
        used, cap, left = key_translate_state(request.user)
        tier = membership_for(request.user).tier
        return Response({
            "skin": skin_dict(skin, request),
            # Stated before anyone reaches for the button, not after.
            "wallpaper_allowed": can_set_wallpaper(request.user),
            "wallpaper_required_tier": TIER_PREMIUM,
            "wallpaper_max_mb": KEY_WALLPAPER_MAX_MB,
            "tier": tier,
            # Translate is free at EVERY tier — say so plainly, because every
            # other AI surface in this app costs PromptZ and a member has good
            # reason to assume this one does too.
            "translate_free": True,
            "translate_cost_cents": 0,
            "translate_used_today": used,
            # None on both when the Polyglot badge has lifted the cap. The
            # client shows "no daily limit" rather than a number, because a
            # made-up large number is a limit pretending to be real.
            "translate_daily_chars": cap,
            "translate_remaining": left,
            "translate_uncapped": cap is None,
            "translate_max_chars": KEY_TRANSLATE_MAX_CHARS,
            "languages": [{"key": k, "label": v} for k, v in LANGUAGES],
            # ---- Voice, stated before either button is pressed ----
            #
            # Both are available at EVERY tier. What a tier buys is how often,
            # which is the same answer BossTake's ladder gives and the same one
            # that keeps translate free — see catalog.key_voice_limits for why
            # neither of these is sold as an ability.
            "voice": self._voice_state(request.user, tier),
        })

    @staticmethod
    def _voice_state(user, tier):
        """Everything the voice buttons need to render honestly, in one place.

        The ladder travels with it, so a member who has spent today's clips is
        told what a tier up would buy instead of being shown a wall with
        nothing behind it.
        """
        heard, _clip_cap, clips_left = key_voice_state(user, KeyVoiceUse.KIND_TRANSCRIBE)
        spoken, _char_cap, chars_left = key_voice_state(user, KeyVoiceUse.KIND_SPEAK)
        limits = key_voice_limits(tier)
        return {
            # Nothing here is gated by tier. Said explicitly, because every
            # other capability list in this app has a tier on it and a member
            # has good reason to assume this one does too.
            "transcribe_allowed": True,
            "speak_allowed": True,
            "cost_cents": 0,
            # The device's own voice: unlimited, offline, and costing us
            # nothing, so there is no bill to justify a gate. The client tries
            # it first and only asks the server for a language the phone has
            # no voice for.
            "device_voice_free": True,
            "clips_daily": limits["clips"],
            "clips_used_today": heard,
            "clips_remaining": clips_left,
            "clip_max_seconds": KEY_VOICE_CLIP_MAX_SECONDS,
            "clip_max_mb": KEY_VOICE_CLIP_MAX_MB,
            "speak_daily_chars": limits["chars"],
            "speak_used_today": spoken,
            "speak_remaining": chars_left,
            "ladder": key_voice_ladder(),
        }

    def patch(self, request):
        """Colours, opacity and the remembered language pair — free at any tier.

        Only the wallpaper is Premium. Charging Free members for a colour would
        be pricing the paint and giving away the wall.
        """
        skin = keyboard_skin_for(request.user)
        d = request.data or {}
        changed = []
        accent = str(d.get("accent", "") or "").strip()
        if accent:
            if not (accent.startswith("#") and len(accent) in (4, 7)):
                return Response({"detail": "accent must be a hex colour like #7c3aed."},
                                status=status.HTTP_400_BAD_REQUEST)
            skin.accent = accent
            changed.append("accent")
        if "key_opacity" in d:
            try:
                skin.key_opacity = max(0, min(100, int(d["key_opacity"])))
                changed.append("key_opacity")
            except (TypeError, ValueError):
                return Response({"detail": "key_opacity must be 0-100."},
                                status=status.HTTP_400_BAD_REQUEST)
        if "dark_keys" in d:
            skin.dark_keys = bool(d["dark_keys"])
            changed.append("dark_keys")
        for field in ("source_lang", "target_lang"):
            if field in d:
                value = str(d[field] or "").strip()[:12]
                if value and value not in LANG_NAME:
                    return Response({"detail": f"Unknown language '{value}'."},
                                    status=status.HTTP_400_BAD_REQUEST)
                setattr(skin, field, value)
                changed.append(field)
        if changed:
            skin.save(update_fields=changed + ["updated_at"])
        return Response(skin_dict(skin, request))

    def post(self, request):
        """Upload the wallpaper. Premium and above."""
        if not can_set_wallpaper(request.user):
            return Response(
                {"detail": "A custom keyboard wallpaper is a Premium feature — upgrade in MembershipZ. "
                           "Translate stays free on every tier.",
                 "required_tier": TIER_PREMIUM},
                status=status.HTTP_403_FORBIDDEN,
            )
        f = request.FILES.get("wallpaper") or request.FILES.get("file")
        if not f:
            return Response({"detail": "Pick an image for your keyboard."},
                            status=status.HTTP_400_BAD_REQUEST)
        if not (getattr(f, "content_type", "") or "").lower().startswith("image/"):
            return Response({"detail": "That isn't an image."},
                            status=status.HTTP_400_BAD_REQUEST)
        if f.size > KEY_WALLPAPER_MAX_MB * 1024 * 1024:
            return Response({"detail": f"Keep the wallpaper under {KEY_WALLPAPER_MAX_MB}MB."},
                            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        skin = keyboard_skin_for(request.user)
        # Replace rather than accumulate — a keyboard has one wallpaper, and
        # keeping the old file would silently eat the member's storage quota.
        if skin.wallpaper:
            skin.wallpaper.delete(save=False)
        skin.wallpaper = f
        skin.save(update_fields=["wallpaper", "updated_at"])
        return Response(skin_dict(skin, request), status=status.HTTP_201_CREATED)

    def delete(self, request):
        """Clear the wallpaper. Never gated — a member who lapses from Premium
        must still be able to take their own picture back off."""
        skin = keyboard_skin_for(request.user)
        if skin.wallpaper:
            skin.wallpaper.delete(save=False)
            skin.wallpaper = None
            skin.save(update_fields=["wallpaper", "updated_at"])
        return Response(skin_dict(skin, request))


def _system(source_name, target_name):
    return (
        f"You are a translator inside a keyboard. Translate the user's message "
        f"{'from ' + source_name + ' ' if source_name else ''}into {target_name}.\n"
        "Rules: (1) Translate naturally, the way a native speaker would say it — "
        "not a literal word-for-word swap. (2) Preserve every emoji exactly, in "
        "the same places. (3) Preserve @mentions, #tags, URLs, numbers and "
        "currency symbols verbatim. (4) Keep the register — if they wrote casually, "
        "stay casual; if they swore, don't sanitise it. (5) Return ONLY a JSON "
        'object: {"text": "...", "detected": "<iso code of the source language>"}. '
        "No prose, no explanation, no code fences."
    )


class KeyTranslateView(APIView):
    """POST { text, target_lang, source_lang? } → the translation.

    Free at every tier. Metered by characters per day, and the allowance is
    reported on every response so the client can show what's left without
    asking again.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        d = request.data or {}
        text = str(d.get("text", "") or "")
        target = str(d.get("target_lang", "") or "").strip().lower()[:12]
        source = str(d.get("source_lang", "auto") or "auto").strip().lower()[:12]

        if not text.strip():
            return Response({"detail": "Type something first."}, status=status.HTTP_400_BAD_REQUEST)
        if target not in LANG_NAME or target == "auto":
            return Response({"detail": "Pick a language to translate into."},
                            status=status.HTTP_400_BAD_REQUEST)
        if source not in LANG_NAME:
            source = "auto"
        if len(text) > KEY_TRANSLATE_MAX_CHARS:
            return Response(
                {"detail": f"That's longer than {KEY_TRANSLATE_MAX_CHARS:,} characters — send it in pieces.",
                 "max_chars": KEY_TRANSLATE_MAX_CHARS},
                status=status.HTTP_400_BAD_REQUEST,
            )

        used, cap, left = key_translate_state(request.user)
        # `left is None` is Polyglot: no allowance to run out of.
        if left is not None and len(text) > left:
            return Response(
                {"detail": f"You've used your {cap:,} free characters for today — {left:,} left. "
                           "It resets on a rolling 24 hours.",
                 "translate_used_today": used, "translate_daily_chars": cap,
                 "translate_remaining": left},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        # Same source-to-same-target is a no-op, and charging the allowance for
        # it would be taking something for nothing.
        if source == target:
            return Response({"text": text, "detected": source, "translated": False,
                             "translate_remaining": left, "cost_cents": 0})

        try:
            import anthropic
        except ImportError:
            return Response({"detail": "Translation isn't switched on — the backend is missing its client."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        try:
            client = anthropic.Anthropic()
            resp = client.messages.create(
                model=TRANSLATE_MODEL,
                max_tokens=2048,
                system=_system("" if source == "auto" else LANG_NAME.get(source, source),
                               LANG_NAME.get(target, target)),
                messages=[{"role": "user", "content": text}],
            )
            raw = "".join(b.text for b in resp.content
                          if getattr(b, "type", "") == "text").strip()
        except Exception as exc:
            return Response({"detail": f"Couldn't reach the translator: {exc}"[:200]},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        out = _first_json(raw)
        if not out or not str(out.get("text", "")).strip():
            return Response({"detail": "The translation came back unreadable. Try again."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        # Meter only a run that produced something usable — a failed call must
        # not eat the member's day, exactly as a failed Boss Take isn't billed.
        KeyTranslation.objects.create(
            user=request.user, source_lang=source, target_lang=target, chars=len(text))
        used, cap, left = key_translate_state(request.user)

        # Remember the pair so the keyboard opens where it was left.
        skin = keyboard_skin_for(request.user)
        if skin.source_lang != source or skin.target_lang != target:
            skin.source_lang, skin.target_lang = source, target
            skin.save(update_fields=["source_lang", "target_lang", "updated_at"])

        return Response({
            "text": str(out["text"]),
            "detected": str(out.get("detected", "") or source)[:12],
            "translated": True,
            "cost_cents": 0,
            "translate_used_today": used,
            "translate_daily_chars": cap,
            "translate_remaining": left,
            "translate_uncapped": cap is None,
        })


# ---------------------------------------------------------------------------
# Voice: speaking to the keyboard, and the keyboard speaking back.
#
# Both live at every tier. The reasoning is in catalog.key_voice_limits and it
# is the same reasoning that made translate free: the wallpaper is decoration
# and fair to sell; being understood is not.
# ---------------------------------------------------------------------------

# What a clip may arrive as. Checked before the upload leaves the browser too,
# but this is the wall — a container the model can't read is a refusal we can
# give instantly and explain, rather than a round trip that comes back as a
# generic failure the member reads as "my voice was the problem".
TRANSCRIBE_MIME = {
    "audio/webm": "audio/webm", "audio/ogg": "audio/ogg", "audio/mp4": "audio/mp4",
    "audio/mpeg": "audio/mp3", "audio/mp3": "audio/mp3", "audio/wav": "audio/wav",
    "audio/x-wav": "audio/wav", "audio/aac": "audio/aac", "audio/flac": "audio/flac",
    "audio/m4a": "audio/mp4", "audio/x-m4a": "audio/mp4",
}


def _clip_mime(content_type):
    """Gemini's name for this container, or "" when it has none.

    Chrome records `audio/webm;codecs=opus`; the parameters are ours to strip,
    because the model rejects the whole string rather than ignoring the part it
    doesn't need — which is the same trap the coach fell into.
    """
    base = str(content_type or "").split(";")[0].strip().lower()
    return TRANSCRIBE_MIME.get(base, "")


def _transcribe_prompt(hint):
    return (
        "Transcribe this audio EXACTLY as spoken, and return only the words.\n"
        "Rules: (1) Write what was actually said — do not summarise, translate, "
        "answer, or continue it. (2) Keep the speaker's own language; if they "
        "switched languages mid-sentence, keep both. (3) Punctuate and "
        "capitalise normally so the text is usable in a message. (4) Do not "
        "invent words to fill a gap — if a stretch is unintelligible, leave it "
        "out rather than guessing. (5) No speaker labels, no timestamps, no "
        "commentary, no quotation marks around the whole thing.\n"
        + (f"The speaker is most likely speaking {hint}.\n" if hint else "")
        + 'Return ONLY a JSON object: {"text": "...", "detected": "<iso code>"}. '
          "No prose, no code fences."
    )


class KeyTranscribeView(APIView):
    """POST a clip (multipart `clip`) → the words in it.

    Free at every tier and metered in clips a day, published by GET before the
    mic is ever pressed. Speech input is how you type when typing is the hard
    part, so it is not sold as an ability — only as a frequency.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        f = request.FILES.get("clip") or request.FILES.get("file")
        if not f:
            return Response({"detail": "Hold the mic and say something first."},
                            status=status.HTTP_400_BAD_REQUEST)

        used, cap, left = key_voice_state(request.user, KeyVoiceUse.KIND_TRANSCRIBE)
        if left <= 0:
            return Response(
                {"detail": f"You've used today's {cap} voice clips. It resets on a "
                           "rolling 24 hours, and a tier up raises it — typing and "
                           "translating stay free either way.",
                 "clips_used_today": used, "clips_daily": cap, "clips_remaining": 0,
                 "ladder": key_voice_ladder()},
                status=status.HTTP_429_TOO_MANY_REQUESTS)

        if f.size > KEY_VOICE_CLIP_MAX_MB * 1024 * 1024:
            return Response(
                {"detail": f"That clip is {f.size / (1024 * 1024):.1f}MB — one clip is "
                           f"one thing said, up to {KEY_VOICE_CLIP_MAX_SECONDS} seconds. "
                           "Say it in pieces and each piece still counts as one.",
                 "clip_max_mb": KEY_VOICE_CLIP_MAX_MB},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

        mime = _clip_mime(getattr(f, "content_type", ""))
        if not mime:
            return Response(
                {"detail": f"The keyboard can't read {getattr(f, 'content_type', '') or 'that format'}. "
                           "Record with the mic button, or send an m4a, mp3, wav, ogg or webm.",
                 "content_type": getattr(f, "content_type", "")},
                status=status.HTTP_400_BAD_REQUEST)

        key = gemini_key()
        if not key:
            return Response({"detail": "Voice isn't switched on — the backend is missing GEMINI_API_KEY."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        hint = LANG_NAME.get(str((request.data or {}).get("lang", "") or "").strip().lower(), "")
        if hint in ("Detect", "auto"):
            hint = ""
        body = {"contents": [{"parts": [
            {"text": _transcribe_prompt(hint)},
            {"inline_data": {"mime_type": mime,
                             "data": base64.b64encode(f.read()).decode("ascii")}},
        ]}]}
        try:
            resp, tried = generate_content("text", body, key=key, timeout=90,
                                           env_vars=("GEMINI_AUDIO_MODEL",),
                                           label="KeyConnectZ transcribe")
        except requests.RequestException:
            logger.exception("KeyConnectZ transcribe: could not reach Gemini")
            return Response({"detail": "Couldn't reach the transcriber. Try that clip again."},
                            status=status.HTTP_502_BAD_GATEWAY)

        if resp is None or resp.status_code != 200:
            code = getattr(resp, "status_code", 0)
            # One sentence for four different problems is not an error message
            # — the coach learned that the hard way and this is the same shape.
            # The upstream body is a third party's error text and is never put
            # in front of a member.
            logger.error("KeyConnectZ transcribe: Gemini %s mime=%s model=%s — %s",
                         code, mime, ", ".join(tried), getattr(resp, "text", "")[:300])
            why = {
                400: "that clip's format wasn't accepted",
                403: "the transcriber's API key was refused",
                404: "the transcriber can't reach a model right now — we're on it",
                429: "the transcriber has hit its limit for now — try again shortly",
            }.get(code, "the transcriber is having a moment" if code >= 500
                  else "the transcriber refused that one")
            return Response({"detail": f"Couldn't read that clip — {why}.",
                             "upstream_status": code, "sent_mime": mime},
                            status=status.HTTP_502_BAD_GATEWAY)

        out = _first_json(_text_of(resp))
        text = str((out or {}).get("text", "") or "").strip()
        if not text:
            # Nothing usable came back, so nothing is spent. A silent clip and
            # a broken model look the same from here; either way the member
            # keeps the allowance they did not get anything for.
            return Response({"detail": "Nothing came back from that clip — try again, "
                                       "closer to the mic. It hasn't cost you one.",
                             "clips_remaining": left},
                            status=status.HTTP_502_BAD_GATEWAY)

        # Metered only once something usable exists, exactly as translate meters
        # only a run that produced a translation and the coach bills only after
        # a score parses.
        KeyVoiceUse.objects.create(user=request.user, kind=KeyVoiceUse.KIND_TRANSCRIBE,
                                   lang=str((out or {}).get("detected", ""))[:12], units=1)
        used, cap, left = key_voice_state(request.user, KeyVoiceUse.KIND_TRANSCRIBE)
        return Response({
            "text": text,
            "detected": str((out or {}).get("detected", "") or "")[:12],
            "cost_cents": 0,
            "clips_used_today": used, "clips_daily": cap, "clips_remaining": left,
        })


# Gemini's TTS models answer with raw PCM, not a file — `audio/L16;codec=pcm;
# rate=24000`. A browser will not play that, so the header goes on here rather
# than in three clients that would each get it slightly wrong.
TTS_MODELS = ("gemini-2.5-flash-preview-tts", "gemini-2.5-pro-preview-tts")
TTS_VOICE = "Kore"


def _wav(pcm, rate=24000, channels=1, bits=16):
    """A 44-byte RIFF header in front of raw PCM. Nothing else changes."""
    block = channels * bits // 8
    return (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
            + struct.pack("<IHHIIHH", 16, 1, channels, rate, rate * block, block, bits)
            + b"data" + struct.pack("<I", len(pcm)) + pcm)


def _pcm_rate(mime):
    """The sample rate the model says it used. Defaults to 24k, which is what
    every Gemini TTS reply has carried — but reading it beats assuming it, and
    a wrong rate is not an error, it is a chipmunk."""
    for bit in str(mime or "").split(";"):
        if bit.strip().startswith("rate="):
            try:
                return int(bit.strip()[5:])
            except ValueError:
                return 24000
    return 24000


class KeySpeakView(APIView):
    """POST { text, lang } → the same words as audio, in the server's voice.

    THE DEVICE VOICE IS THE DEFAULT AND IT NEVER TOUCHES THIS ENDPOINT.
    `speechSynthesis` is on every phone, costs us nothing, works offline and is
    unlimited at every tier — so the client speaks locally and only asks here
    for a language the device has no voice for. In practice that is Yorùbá,
    Igbo, Hausa and Amharic before it is anything else, which is exactly why
    this is not sold by tier: gating it would mean English speakers hear their
    translation read back free while Yorùbá speakers pay for it.

    Metered in characters a day, like translate, and published by GET first.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        d = request.data or {}
        text = str(d.get("text", "") or "").strip()
        lang = str(d.get("lang", "") or "").strip().lower()[:12]

        if not text:
            return Response({"detail": "Nothing to read out."},
                            status=status.HTTP_400_BAD_REQUEST)
        if len(text) > KEY_TRANSLATE_MAX_CHARS:
            return Response(
                {"detail": f"That's longer than {KEY_TRANSLATE_MAX_CHARS:,} characters — "
                           "read it in pieces.",
                 "max_chars": KEY_TRANSLATE_MAX_CHARS},
                status=status.HTTP_400_BAD_REQUEST)

        used, cap, left = key_voice_state(request.user, KeyVoiceUse.KIND_SPEAK)
        if len(text) > left:
            return Response(
                {"detail": f"You've used today's {cap:,} characters of the server voice — "
                           f"{left:,} left. Your phone's own voice is unlimited and free, "
                           "and this resets on a rolling 24 hours.",
                 "speak_used_today": used, "speak_daily_chars": cap,
                 "speak_remaining": left, "ladder": key_voice_ladder()},
                status=status.HTTP_429_TOO_MANY_REQUESTS)

        key = gemini_key()
        if not key:
            return Response({"detail": "The server voice isn't switched on — the backend is "
                                       "missing GEMINI_API_KEY. Your phone's own voice still works."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        name = LANG_NAME.get(lang, "")
        body = {
            # Read it, do not answer it. A TTS model handed a question will
            # sometimes reply to it, and a keyboard that argues with the member
            # instead of reading their sentence out is worse than silence.
            "contents": [{"parts": [{"text": (
                f"Read the following aloud in {name}, naturally, as a native speaker "
                f"would say it. Read ONLY these words and add nothing:\n\n{text}"
                if name else
                f"Read the following aloud, naturally, reading ONLY these words "
                f"and adding nothing:\n\n{text}")}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": TTS_VOICE}}},
            },
        }
        try:
            resp, tried = generate_content("tts", body, key=key, timeout=90,
                                           env_vars=("GEMINI_TTS_MODEL",),
                                           label="KeyConnectZ speak")
        except requests.RequestException:
            logger.exception("KeyConnectZ speak: could not reach Gemini")
            return Response({"detail": "Couldn't reach the server voice. Your phone's own "
                                       "voice still works — try the speaker again."},
                            status=status.HTTP_502_BAD_GATEWAY)

        if resp is None or resp.status_code != 200:
            code = getattr(resp, "status_code", 0)
            logger.error("KeyConnectZ speak: Gemini %s lang=%s model=%s — %s",
                         code, lang, ", ".join(tried), getattr(resp, "text", "")[:300])
            why = {
                400: "that text wasn't accepted",
                403: "the voice's API key was refused",
                404: "the voice can't reach a model right now — we're on it",
                429: "the voice has hit its limit for now — try again shortly",
            }.get(code, "the voice is having a moment" if code >= 500
                  else "the voice refused that one")
            return Response({"detail": f"Couldn't read that out — {why}. Your phone's own "
                                       f"voice still works.",
                             "upstream_status": code},
                            status=status.HTTP_502_BAD_GATEWAY)

        try:
            part = resp.json()["candidates"][0]["content"]["parts"][0]["inline_data"]
            pcm = base64.b64decode(part["data"])
        except Exception:
            logger.exception("KeyConnectZ speak: no audio in the reply")
            pcm = b""
        if not pcm:
            # Nothing playable came back, so nothing is spent.
            return Response({"detail": "The voice came back empty. Nothing was counted — "
                                       "try again, or use your phone's own voice.",
                             "speak_remaining": left},
                            status=status.HTTP_502_BAD_GATEWAY)

        wav = _wav(pcm, rate=_pcm_rate(part.get("mime_type", "")))
        KeyVoiceUse.objects.create(user=request.user, kind=KeyVoiceUse.KIND_SPEAK,
                                   lang=lang, units=len(text))
        used, cap, left = key_voice_state(request.user, KeyVoiceUse.KIND_SPEAK)
        return Response({
            # Inline, not stored. A sentence read aloud is heard once and
            # thrown away — writing it into the member's FileZ would spend
            # their storage quota on something nobody asked to keep.
            "audio_b64": base64.b64encode(wav).decode("ascii"),
            "mime": "audio/wav",
            "voice": "server",
            "cost_cents": 0,
            "speak_used_today": used, "speak_daily_chars": cap, "speak_remaining": left,
        })
