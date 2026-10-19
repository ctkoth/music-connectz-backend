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

from .models import TIER_FREE, TIER_PREMIUM, TIER_STATZ, membership_for, profile_for

# Premium AND StatZ. Written as a set rather than a `!= TIER_FREE` so that a
# tier added later is a deliberate decision here instead of a silent grant.
SOUND_CUSTOM_TIERS = {TIER_PREMIUM, TIER_STATZ}

# Shape only. Lowercase slug, because that is what a pack key is; the client
# owns which slugs mean anything.
PACK_KEY = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

# A ceiling on the override map so a preference cannot become a payload. There
# are fewer than 40 sounds; 64 is room to grow and still bounded.
MAX_OVERRIDES = 64


def may_customize(user):
    return membership_for(user).tier in SOUND_CUSTOM_TIERS


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
    return {
        "pack": p.sound_pack or "",
        "overrides": p.sound_overrides or {},
        "can_customize": tier in SOUND_CUSTOM_TIERS,
        "tier": tier,
        # Named, not hardcoded in the client's copy — the same rule that keeps
        # tier numbers out of UI strings.
        "tier_required": TIER_PREMIUM,
        "max_overrides": MAX_OVERRIDES,
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
        if "pack" in d:
            p.sound_pack = clean_pack(d["pack"])
            changed.append("sound_pack")
        if "overrides" in d:
            p.sound_overrides = clean_overrides(d["overrides"])
            changed.append("sound_overrides")
        if changed:
            p.save(update_fields=changed + ["updated_at"])
        return Response(sound_state(request.user))
