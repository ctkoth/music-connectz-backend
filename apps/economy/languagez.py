"""LanguageZ — declared languages spoken AND how well, grouped by region,
one filter, every search.

Same shape as ReligionZ, with the differences the field itself demands. A
member is one religion (or none) but commonly SEVERAL languages, and for
each one, "I speak it" is not one fact but three very different ones —
so `Profile.languages` is `{lang_key: level}`, the same shape SubstanceZ
already uses for "what, and how often": a bare list of keys could not say
frequency there and cannot say fluency here.

- **It never touches a measurement.** No rating, median, skill level or
  leaderboard position moves because somebody speaks four languages instead
  of one. It filters WHO you see, same as regions and religion already do
  in `MembersView` — knowing whether you can actually talk to somebody
  before you message them is the whole value of the field.
- **Nothing is inferred.** Never guessed from a name, a region, or a post's
  language — a declared field stays declared.
- **An empty dict is "hasn't said"**, not "speaks nothing" and not a
  default — the same third state `religion` and `personality` already keep.
  A level is never guessed for a language that IS declared, either: no key
  reaches storage without one of the three named levels attached.

The list is closed, grouped by region for a picker that would otherwise be
fifty flat rows, and served from here — never typed into a screen a second
time, the same reason a tier number lives in `catalog.py` and nowhere else.

Grouped by REGION rather than by linguistic family on purpose: a "family"
label invites a claim about language history this module has no business
making (and would get some of it wrong), while "where this is widely
spoken" is a claim a picker can make safely and a member can navigate by.
"""

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

# Top 50 by number of speakers worldwide, grouped by the region each is most
# associated with. Order groups related languages for a picker that scrolls
# — it is NOT a ranking, and `key` (an ISO 639-1 code, or the closest common
# one) is the only thing anything else may read.
LANGUAGE_GROUPS = (
    ("western_europe", "Western Europe", (
        ("en", "English"),
        ("es", "Spanish"),
        ("fr", "French"),
        ("pt", "Portuguese"),
        ("de", "German"),
        ("it", "Italian"),
        ("nl", "Dutch"),
    )),
    ("northern_europe", "Northern Europe", (
        ("sv", "Swedish"),
        ("no", "Norwegian"),
        ("da", "Danish"),
        ("fi", "Finnish"),
    )),
    ("eastern_europe", "Eastern & Southeastern Europe", (
        ("ru", "Russian"),
        ("pl", "Polish"),
        ("uk", "Ukrainian"),
        ("ro", "Romanian"),
        ("hu", "Hungarian"),
        ("el", "Greek"),
        ("tr", "Turkish"),
    )),
    ("middle_east", "Middle East", (
        ("ar", "Arabic"),
        ("he", "Hebrew"),
        ("fa", "Persian / Farsi"),
        ("ur", "Urdu"),
    )),
    ("south_asia", "South Asia", (
        ("hi", "Hindi"),
        ("bn", "Bengali"),
        ("pa", "Punjabi"),
        ("gu", "Gujarati"),
        ("mr", "Marathi"),
        ("ta", "Tamil"),
        ("te", "Telugu"),
        ("kn", "Kannada"),
        ("ml", "Malayalam"),
        ("si", "Sinhala"),
        ("ne", "Nepali"),
    )),
    ("east_asia", "East Asia", (
        ("zh", "Chinese (Mandarin)"),
        ("yue", "Cantonese"),
        ("ja", "Japanese"),
        ("ko", "Korean"),
    )),
    ("southeast_asia", "Southeast Asia", (
        ("vi", "Vietnamese"),
        ("th", "Thai"),
        ("id", "Indonesian"),
        ("ms", "Malay"),
        ("tl", "Tagalog / Filipino"),
    )),
    ("africa", "Africa", (
        ("sw", "Swahili"),
        ("am", "Amharic"),
        ("ha", "Hausa"),
        ("yo", "Yoruba"),
        ("ig", "Igbo"),
        ("zu", "Zulu"),
        ("xh", "Xhosa"),
        ("af", "Afrikaans"),
    )),
)

# The flat top-50, derived rather than typed a second time — the exact trap
# the module docstring warns about, one level down.
LANGUAGES = tuple(leaf for _, _, leaves in LANGUAGE_GROUPS for leaf in leaves)

# Asserted on import rather than trusted, same as religionz's check.
assert len(LANGUAGES) == 50, "the picker promises the top 50 — keep the count honest"
_KEYS = {k for k, _ in LANGUAGES}
assert len(_KEYS) == len(LANGUAGES), "a duplicated leaf key would make two rows the same filter"
_GROUP_KEYS = {g for g, _, _ in LANGUAGE_GROUPS}
assert len(_GROUP_KEYS) == len(LANGUAGE_GROUPS), "a duplicated group key"

# How many a member may declare. Not a real person's ceiling — it exists so
# a profile row cannot be made arbitrarily large, the same reasoning
# `personas`/`links` are capped at 50 for; ten is generous for a member
# count and cheap for a card that serializes this on every search result.
MAX_LANGUAGES = 10

# Three, because that is the question the toggle actually asks — "can you
# work in this, get by in it, or just started" — not a CEFR scale nobody
# outside language teaching uses day to day. No "native": fluency is what
# matters for whether two people can actually talk, and a native/fluent
# split would be a distinction this app has no way to verify and no reason
# to ask a member to prove.
LEVELS = ("beginner", "intermediate", "fluent")


def clean_languages(value):
    """Normalize whatever arrived to {lang_key: level}, or {} for nothing
    said.

    An unrecognised language key OR an unrecognised level drops that ONE
    entry rather than refusing the whole save — the same rule
    `religionz.clean_religion` and `personalityz.clean_code` follow. There is
    no default level to fall back to the way `clean_substances` falls back
    to a legacy stance: every key here is new, so a level that cannot be
    read is dropped rather than guessed, which would risk overstating
    somebody's fluency.
    """
    if not isinstance(value, dict):
        return {}
    out = {}
    for k, v in list(value.items())[:MAX_LANGUAGES]:
        key = str(k).strip().lower()
        level = str(v or "").strip().lower()
        if key in _KEYS and level in LEVELS:
            out[key] = level
    return out


class LanguagesView(APIView):
    """GET /api/economy/languagez/ — the closed list, grouped by region,
    never typed into a screen a second time.

    Open logged-out, same reason `religionz` and `personalityz` are: the
    screen that renders this picker is ProfileZ, and a stranger reads the
    join page before deciding whether to make an account at all.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({
            "groups": [
                {"key": g, "label": label,
                 "options": [{"key": k, "label": l} for k, l in leaves]}
                for g, label, leaves in LANGUAGE_GROUPS
            ],
            "levels": list(LEVELS),
            "max": MAX_LANGUAGES,
            "note": ("A declaration, never a score — languages are listed, with how well "
                     "you speak each one, so people who can actually talk to you can find "
                     "you. Picking one never moves a rating or a skill level. Leave it "
                     "blank and it stays \"hasn't said\", not a default."),
        })
