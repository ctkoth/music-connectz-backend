"""The house rules, in one place, served to whoever needs to state them.

A rule that lives in three screens' copy is a rule that will read three
different ways within a year — the same drift the tier numbers had before
`catalog.py`, and worse here, because a rule people are held to has to be one
they were actually told. So a rule is written once, given a key, and every
surface that mentions it reads it from `GET /api/economy/rulez/`.

Each rule carries what it is, why it exists, and — the part that stops this
becoming decoration — **what actually happens**. A rule with no consequence
named is a preference, and members work out the difference fast.

`enforced_by` names the code that does the enforcing, so a rule cannot quietly
become a wish: if the module named there stops doing it, the rule is lying and
somebody grepping for the key will find both ends.
"""
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

RULES = [
    {
        "key": "one_account",
        "emoji": "👤",
        "title": "One person, one account",
        # Stated as the flat rule Corey asked for, and then the reason — in
        # that order, because a rule that opens with its excuse reads as
        # negotiable.
        "rule": "Every member gets one account 👤. Duplicate accounts are not allowed 🚫",
        "why": (
            "Everything here is counted per person 📊: reach, ratings, referral "
            "rewards ✅, the daily AI allowance, one vote 🗳️ in a battle. A second "
            "account is a second helping of all of it, and every one of those "
            "numbers stops meaning anything the moment they can be doubled. "
            "It also costs the member who has one — their work sits split "
            "across two profiles and neither is the one they are building 🏗️."
        ),
        "what_happens": (
            "Tell us and it is sorted ✅: say which account is yours in DupeZ and "
            "the other one goes 🗑️. Accounts kept deliberately to farm rewards 🚜 or "
            "vote twice 🗳️ are removed by the owner, and what they earned 💎 goes "
            "with them."
        ),
        # Signing in with Google in June and SoundCloud in August makes two
        # accounts without anybody meaning to. Saying so in the rule is the
        # difference between a member coming forward and hiding it.
        "note": (
            "Ending up with two by accident is common 🤷 — a different sign-in "
            "button is all it takes. That is not what this rule is about, and "
            "owning up to it ✅ costs you nothing."
        ),
        "enforced_by": "apps/economy/dupez.py",
    },
]

RULES_BY_KEY = {r["key"]: r for r in RULES}


def rule(key):
    """One rule, or None. Callers render the absence rather than inventing copy."""
    return RULES_BY_KEY.get(key)


class RulezView(APIView):
    """GET → the house rules.

    Open to anyone, including logged out, on purpose: the rule about how many
    accounts a person may have is one somebody most needs on the signup screen,
    which is the one screen where nobody is signed in yet.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        key = (request.query_params.get("key") or "").strip()
        if key:
            r = rule(key)
            return Response({"rules": [r] if r else []})
        return Response({"rules": RULES})
