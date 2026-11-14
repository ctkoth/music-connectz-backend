"""SoundZ — what the app sounds like, and who may change it.

The sounds themselves are synthesised in `src/sound.js`: a few oscillators and
a gain envelope each, so the whole vocabulary adds no audio files to the bundle
and works offline. That file is also where the PACKS live, because a pack is a
set of waveform settings and those belong where somebody can hear them while
they edit them.

**This module stores a choice, never a waveform.** It knows that a pack key is
a short slug and that changing it is a Premium perk. It does not know what
"arcade" sounds like and must not learn — a copy of the synthesis parameters
here would be a second source of truth for something Python cannot play, and
the client would drift from it the first time a sound was tuned.

So validation splits along that line:

* the SERVER checks shape — a plausible slug, a bounded override map, and the
  tier that is allowed to set either;
* the CLIENT checks meaning — a pack it does not recognise falls back to the
  house sound rather than failing, which is what makes it safe for this file to
  accept a name it cannot verify.

Why it is stored on the account at all, when the on/off toggle is happily in
localStorage: on/off is a per-device courtesy, and this is sold. A perk that
evaporates when you open the app on your phone is not a perk, it is a browser
setting somebody paid for.
"""
import re

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import TIER_DEBUG, TIER_FREE, TIER_PREMIUM, TIER_STATZ, membership_for, profile_for

# Premium AND StatZ. Written as a set rather than a `!= TIER_FREE` so that a
# tier added later is a deliberate decision here instead of a silent grant.
SOUND_CUSTOM_TIERS = {TIER_PREMIUM, TIER_STATZ}

# Packs that are StatZ's. Names only: this is who may CHOOSE a slug, never what it
# sounds like, so the module still stores no waveform. Premium chooses every other
# pack; these are the top of the ladder, and the reason is the usual one for a
# decoration: nobody loses a capability without it (the house set is free at every
# tier and says the same things), so it may be sold. A pack named here that the
# client has never heard of is harmless: it would fall back to the house sound.
STATZ_PACKS = frozenset({"highroller"})
STATZ_PACK_TIERS = {TIER_STATZ, TIER_DEBUG}
STATZ_PACK_REFUSAL = ("That sound pack is a StatZ perk. Every other pack is yours on Premium, "
                      "and the house set is free at every tier.")

# Shape only. Lowercase slug, because that is what a pack key is; the client
# owns which slugs mean anything.
PACK_KEY = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

# A ceiling on the override map so a preference cannot become a payload. There
# are fewer than 40 sounds; 64 is room to grow and still bounded.
MAX_OVERRIDES = 64


def may_customize(user):
    return membership_for(user).tier in SOUND_CUSTOM_TIERS


def may_use_pack(user, pack):
    """Whether this member may choose `pack` (a cleaned slug). StatZ packs need StatZ."""
    return pack not in STATZ_PACKS or membership_for(user).tier in STATZ_PACK_TIERS


def clean_pack(value):
    """A pack key, or "" for the house sound. Anything unparseable is "" —
    silently falling back to the default is right here, where the worst case is
    hearing the standard set."""
    value = str(value or "").strip().lower()
    return value if PACK_KEY.match(value) else ""


def clean_overrides(value):
    """{sound_key: pack_key}, cleaned. Entries that fail the shape are dropped
    rather than failing the whole save — one bad key should not cost somebody
    the other sixty they set."""
    if not isinstance(value, dict):
        return {}
    out = {}
    for k, v in list(value.items())[:MAX_OVERRIDES]:
        key, pack = clean_pack(k), clean_pack(v)
        if key and pack:
            out[key] = pack
    return out


def sound_state(user):
    p = profile_for(user)
    tier = membership_for(user).tier
    # A lapse serves the house sound, and keeps the choice for when they are back:
    # the row is not rewritten on a read.
    ok = (lambda x: x not in STATZ_PACKS or tier in STATZ_PACK_TIERS)
    return {
        "pack": (p.sound_pack or "") if ok(p.sound_pack or "") else "",
        "overrides": {k: v for k, v in (p.sound_overrides or {}).items() if ok(v)},
        "can_customize": tier in SOUND_CUSTOM_TIERS,
        "tier": tier,
        # Named, not hardcoded in the client's copy — the same rule that keeps
        # tier numbers out of UI strings.
        "tier_required": TIER_PREMIUM,
        "max_overrides": MAX_OVERRIDES,
        # Which packs sit a tier higher, and whether this member has them: the screen
        # locks those and says who gets them, without typing a tier into its copy.
        "statz_packs": sorted(STATZ_PACKS),
        "has_statz_packs": tier in STATZ_PACK_TIERS,
        "statz_pack_tier": TIER_STATZ,
    }


class SoundZView(APIView):
    """GET your sound settings; PATCH them (Premium and above)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(sound_state(request.user))

    def patch(self, request):
        if not may_customize(request.user):
            return Response(
                {**sound_state(request.user),
                 "detail": "Choosing a sound pack is a Premium perk. The house "
                           "set, and turning sound on or off, are free at every tier."},
                status=status.HTTP_403_FORBIDDEN)
        d = request.data or {}
        p = profile_for(request.user)
        changed = []
        # Judged before anything is written, so a refusal never half-saves.
        want_pack = clean_pack(d["pack"]) if "pack" in d else None
        want_over = clean_overrides(d["overrides"]) if "overrides" in d else None
        asked = ([want_pack] if want_pack else []) + list((want_over or {}).values())
        if any(not may_use_pack(request.user, x) for x in asked):
            return Response({**sound_state(request.user), "detail": STATZ_PACK_REFUSAL},
                            status=status.HTTP_403_FORBIDDEN)
        if want_pack is not None:
            p.sound_pack = want_pack
            changed.append("sound_pack")
        if want_over is not None:
            p.sound_overrides = want_over
            changed.append("sound_overrides")
        if changed:
            p.save(update_fields=changed + ["updated_at"])
        return Response(sound_state(request.user))
