"""PhilosophieZ — a declared philosophy and a declared political outlook.

Two fields, one app, and both are DECLARATIONS exactly as ReligionZ's tradition
and PersonalitieZ's letters are: there is no good one, so the substance rule's
test ("could a member get a good one without getting good?") has nothing to ask.
Three lines hold it, and none may be crossed later for convenience:

- **It never touches a measurement.** No rating, median, skill level, price or
  leaderboard position moves because somebody picked a word. It changes who you
  SEE and nothing about what anyone is CALLED.
- **Nothing is inferred.** Never read off posts, comments, takes, likes, who
  somebody follows or what they listen to. "We detected you lean liberal" would
  be `directz_ai_rating` wearing a ballot. `test_philosophiez` asserts no third
  writer of either column exists.
- **Undeclared is a third state.** `""` is "hasn't said" — never a default, never
  "centrist", and never counted into any word's total.

**Why one app and two fields, and why not inside ReligionZ.** A religion is a
tradition you belong to; a philosophy and a political outlook are views you hold.
They combine freely (a Catholic Stoic who votes green), so they are independent
columns — and they get independent privacy, which is the real reason they are not
one field. ReligionZ already carries "Spiritual, not religious", agnostic, atheist,
pagan and indigenous traditions, so the spiritual side needed no new list.

**Politics is private until the member opens it** (`visibility.DEFAULTS`). It is
the most contested thing on a profile and the one a stranger can do most with, and
`Profile.visibility` stores only deviations — so the default is the member's whole
exposure. Philosophy is open to members, like religion.

**The words are broad outlooks, never parties.** A party is a country, a year and
somebody's trademark; an outlook ("Libertarian", "Green / environmentalist") travels.
Listed alphabetically on purpose: a left-to-right order would be a claim about the
spectrum, and the order here is read by nothing but the picker. **The two lists are
an editorial judgement, Corey's to change** — one place, `PHILOSOPHIES` / `POLITICS`;
keys are what is stored and matched, so a label can be reworded without moving anyone.

Served from here (`GET /api/economy/philosophiez/`) and never retyped into a screen.
"""
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

# Alphabetical by label, "Other" last. Keys are <= 32 chars (the column width).
PHILOSOPHIES = (
    ("absurdism", "Absurdism"),
    ("deontology", "Deontology (duty-based ethics)"),
    ("empiricism", "Empiricism"),
    ("epicureanism", "Epicureanism"),
    ("existentialism", "Existentialism"),
    ("hedonism", "Hedonism"),
    ("humanism", "Humanism"),
    ("idealism", "Idealism"),
    ("nihilism", "Nihilism"),
    ("objectivism", "Objectivism"),
    ("pragmatism", "Pragmatism"),
    ("rationalism", "Rationalism"),
    ("skepticism", "Skepticism"),
    ("stoicism", "Stoicism"),
    ("transcendentalism", "Transcendentalism"),
    ("utilitarianism", "Utilitarianism"),
    ("virtue_ethics", "Virtue ethics"),
    ("other", "Other"),
)

POLITICS = (
    ("anarchist", "Anarchist"),
    ("apolitical", "Apolitical — not into politics"),
    ("centrist", "Centrist / moderate"),
    ("communist", "Communist"),
    ("conservative", "Conservative"),
    ("environmentalist", "Green / environmentalist"),
    ("liberal", "Liberal"),
    ("libertarian", "Libertarian"),
    ("progressive", "Progressive"),
    ("social_democrat", "Social democrat"),
    ("socialist", "Socialist"),
    ("other", "Other"),
)

_PHIL = {k for k, _ in PHILOSOPHIES}
_POL = {k for k, _ in POLITICS}
# Asserted on import, like religionz and personalityz: a repeated key would make two
# rows answer to one filter, and an over-long one would be a 500 on Postgres only.
assert len(_PHIL) == len(PHILOSOPHIES) and len(_POL) == len(POLITICS), "a duplicated key"
assert all(len(k) <= 32 for k in _PHIL | _POL), "a key wider than the column"


def clean_philosophy(value):
    """A valid key, or "" for nothing said. Junk never refuses a save."""
    v = str(value or "").strip().lower()
    return v if v in _PHIL else ""


def clean_politics(value):
    v = str(value or "").strip().lower()
    return v if v in _POL else ""


class PhilosophieView(APIView):
    """GET /api/economy/philosophiez/ — both closed lists. Open logged-out, like
    religionz: a list of words is not anybody's declaration."""
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({
            "philosophies": [{"key": k, "label": l} for k, l in PHILOSOPHIES],
            "politics": [{"key": k, "label": l} for k, l in POLITICS],
            "note": ("A declaration, not a score. Neither list is ranked, nothing is guessed from "
                     "what you do here, and picking a word never moves a rating or a skill level."),
            "politics_note": "Only you see this until you open it — it is private by default.",
        })
