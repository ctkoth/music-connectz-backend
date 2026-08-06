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
import json

from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

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
    key_translate_state,
    keyboard_skin_for,
    membership_for,
)

WALLPAPER_TIERS = (TIER_PREMIUM, TIER_STATZ, TIER_DEBUG)

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
            "translate_daily_chars": cap,
            "translate_remaining": left,
            "translate_max_chars": KEY_TRANSLATE_MAX_CHARS,
            "languages": [{"key": k, "label": v} for k, v in LANGUAGES],
        })

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
        if len(text) > left:
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
                model="claude-opus-4-8",
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

        out = None
        try:
            out = json.loads(raw)
        except ValueError:
            a, b = raw.find("{"), raw.rfind("}")
            if a != -1 and b > a:
                try:
                    out = json.loads(raw[a:b + 1])
                except ValueError:
                    out = None
        if not isinstance(out, dict) or not str(out.get("text", "")).strip():
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
        })
