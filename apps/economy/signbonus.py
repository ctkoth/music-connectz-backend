"""ZodiacZ bonuses — one list, twelve doors into the same healthy behaviours.

The obvious version of this is the wrong one. "Leos get free SpinaZ" rewards a
birthday, which nobody earned and nobody can change, and the substance rule
answers it in one line: could a member get a good number without getting good?

Every bonus here rewards an ACTION. The sign only decides WHICH action you are
nudged toward — so a Leo and a Capricorn are pushed at different doors into the
same building, and both still have to walk through one. That is the distinction
CLAUDE.md already draws: *XP and badges may reward effort. Ratings and skill
levels may not.* Effort is exactly what this pays for.

Four rules hold it, and each is here because dropping it would turn the feature
into a problem:

* **Comparable value across all twelve.** 20 🍥 for the base, 50 for the harder
  version of the same thing, everywhere. A birthday is the one attribute a
  member cannot change, so it must never be the reason somebody earns less.
* **It never touches a measurement.** No rating, no median, no skill level, no
  leaderboard position. Sign flavours what you are nudged toward, never what
  you are called.
* **Once each, and capped daily.** Every other earn in this app is bounded and
  this is no different — an unbounded bonus is a mint with a horoscope on it.
* **Only actions that already exist.** Each hook below fires on something the
  platform already does. A bonus for an action nobody can take is decoration,
  and this codebase has enough of those to know how they end up.

The list is published by `GET /api/economy/signbonus/` so a member can see
their own before they do the thing. A bonus discovered by accident afterwards
is not a nudge, it is a surprise — and the cost/gain rule cuts both ways.
"""
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import SignBonusAward, award_spinaz, profile_for

BASE, STRETCH = 20, 50

# sign -> the one bonus that sign gets.
#
# `action` is the key a call site fires. `stretch` is the harder version of the
# SAME action, so nobody has to do a different thing to reach the bigger number.
# `tab` is where the member goes to DO it — the cross-pollination rule applies
# to a bonus as much as to anything else. A screen that tells somebody what
# they could earn and leaves them to find the app is a dead end with a number
# on it, and the destination belongs on the row rather than in a mapping the
# client keeps privately and lets drift.
BONUSES = {
    "Aries": {
        "tab": "battlez",
        "name": "First Blood",
        "action": "battle_first_in",
        "does": "Be the first take up in a battle",
        "stretch": "Be first within an hour of it opening",
        "why": "The ram charges. Aries goes first, and the stretch is going "
               "first FAST — not a second way of saying the same thing.",
    },
    "Taurus": {
        "tab": "coachz",
        "name": "The Long Haul",
        "action": "streak",
        "does": "Practise seven days running",
        "stretch": "Keep it going for thirty",
        "why": "The bull does not sprint and does not stop.",
    },
    "Gemini": {
        "tab": "postz",
        "name": "Two Places At Once",
        "action": "post_album",
        "does": "Put up a post carrying more than one piece of work",
        "stretch": "Four or more in the one post",
        "why": "The twins. One of anything was never going to be enough.",
    },
    "Cancer": {
        "tab": "profilez",
        "name": "Brought Them Home",
        "action": "referral",
        "does": "Someone joins on your invite",
        "stretch": "Three of them",
        "why": "The crab carries its home. Cancer's instinct is to bring people in.",
    },
    "Leo": {
        "tab": "battlez",
        "name": "Never Alone On Stage",
        "action": "battle_joins_others",
        "does": "Enter a battle someone else is already in",
        "stretch": "Enter a 1v1 you were challenged to by name",
        "why": "The lion needs a crowd and a rival. Corey's own, and the one "
               "the rest were built to match.",
    },
    "Virgo": {
        "tab": "postz",
        "name": "Named The Craft",
        "action": "post_with_skills",
        "does": "Post with the skills you used named on it",
        "stretch": "Three or more named",
        "why": "The maiden edits. Virgo is the sign that labels the work "
               "properly, and naming skills is what makes a post findable.",
    },
    "Libra": {
        "tab": "social",
        "name": "Even Hands",
        "action": "rate",
        "does": "Rate somebody else's work",
        "stretch": "Rate five in a day",
        "why": "The scales. Libra keeps the balance, and a rating is the only "
               "thing here that weighs anything.",
    },
    "Scorpio": {
        "tab": "singz",
        "name": "Under The Knife",
        "action": "post_scored",
        "does": "Put a take up to be scored",
        "stretch": "Score eight or better",
        "why": "The scorpion goes deep and does not flinch. Being judged on "
               "purpose is the most Scorpio thing this app offers.",
    },
    "Sagittarius": {
        "tab": "venuez",
        "name": "Long Distance",
        "action": "venue_book",
        "does": "Ask for a seat at a VenuZ room — somewhere real, in person",
        "stretch": "One that runs three hours or more",
        "why": "The archer aims far. Sagittarius is the sign that actually "
               "turns up somewhere rather than sending a link. (We don't "
               "measure how far you came — we don't know where you are, and "
               "a distance nobody can check isn't worth paying for.)",
    },
    "Capricorn": {
        "tab": "coachz",
        "name": "The Climb",
        "action": "level_up",
        "does": "Reach a new SkillZ level",
        "stretch": "Reach level five",
        "why": "The goat climbs. Slowly, and it does not come back down.",
    },
    "Aquarius": {
        "tab": "collabz",
        "name": "The Collective",
        "action": "collab_crowd",
        "does": "Start a collab with two or more other people on it",
        "stretch": "Four or more others",
        "why": "The water bearer serves everybody. Aquarius is the sign that "
               "thinks in groups rather than pairs.",
    },
    "Pisces": {
        "tab": "postz",
        "name": "Out Of Nowhere",
        "action": "freestyle",
        "does": "Post a freestyle",
        "stretch": "Post three",
        "why": "The fish makes it up as it swims. Pisces is imagination "
               "before plan.",
    },
}

# action -> the sign that owns it, built once so a call site does not have to
# know which sign it is firing for.
_BY_ACTION = {b["action"]: sign for sign, b in BONUSES.items()}

# Bounded like every other earn here. An unbounded bonus is a mint.
DAILY_CAP = 3


def bonus_for(user):
    """This member's own bonus, or None when their sign is unknown.

    Served before they do the thing. A bonus found out about afterwards is a
    surprise, not a nudge.
    """
    sign = (profile_for(user).sign or "").strip()
    b = BONUSES.get(sign)
    if not b:
        return None
    got = set(SignBonusAward.objects.filter(user=user, sign=sign)
              .values_list("tier", flat=True))
    return {
        "sign": sign, **b,
        "base_spinaz": BASE, "stretch_spinaz": STRETCH,
        "earned_base": "base" in got,
        "earned_stretch": "stretch" in got,
        "daily_cap": DAILY_CAP,
    }


def award(user, action, *, stretch=False):
    """Pay the bonus if this action is the one this member's sign is nudged at.

    Silent and cheap when it is not — every call site fires unconditionally and
    this decides, so no caller has to carry a sign check of its own. A rule
    written in twelve places is a rule that reads twelve ways within a year.

    Returns the amount paid, or 0.
    """
    sign = (profile_for(user).sign or "").strip()
    if not sign or _BY_ACTION.get(action) != sign:
        return 0

    tier = "stretch" if stretch else "base"
    # Once each. The stretch is a second, larger payment for the harder version
    # of the same action, not a replacement for the first.
    if SignBonusAward.objects.filter(user=user, sign=sign, tier=tier).exists():
        return 0

    today = timezone.localdate()
    if SignBonusAward.objects.filter(user=user, awarded_on=today).count() >= DAILY_CAP:
        return 0

    amount = STRETCH if stretch else BASE
    b = BONUSES[sign]
    SignBonusAward.objects.create(user=user, sign=sign, tier=tier,
                                  action=action, amount=amount, awarded_on=today)
    award_spinaz(user, amount, f"ZodiacZ · {sign} · {b['name']}",
                 app_key="zodiacz", target="zodiacz")
    return amount


def try_award(user, action, *, stretch=False):
    """`award`, wrapped, for call sites where the bonus is a side effect.

    A battle entry, a post and a rating all have to succeed whether or not a
    bonus does. Nothing here is worth failing the thing the member actually
    came to do.
    """
    try:
        return award(user, action, stretch=stretch)
    except Exception:                       # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("sign bonus failed for %s", action)
        return 0


class SignBonusView(APIView):
    """`GET /api/economy/signbonus/` — your own bonus, and all twelve.

    Both halves matter. `mine` is the one the cost/gain rule is about: a
    member has to be able to read what they get BEFORE they go and do it,
    or the bonus is a surprise rather than a nudge. `all` is there because
    the fairness of this feature is only checkable by seeing the whole
    list — every sign is worth the same 20 / 50, and a member who cannot
    see the other eleven has to take that on trust.

    `mine` is null when the birthday is unset. That is honest and it is
    also the door: the client can send them to set one.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            "mine": bonus_for(request.user),
            "base_spinaz": BASE,
            "stretch_spinaz": STRETCH,
            "daily_cap": DAILY_CAP,
            "all": [{"sign": s, **b} for s, b in BONUSES.items()],
            "open_in": {"app_key": "zodiacz", "target": "zodiacz"},
        })
