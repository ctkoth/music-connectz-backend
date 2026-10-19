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

# ---------------------------------------------------------------------------
# The OTHER zodiac — twelve animals, twelve more doors.
#
# Same engine, same two numbers, same four rules. What makes it worth adding
# rather than doubling the western list is that the two zodiacs disagree about
# WHO YOU ARE, and disagree on a different axis: a star sign is a month and an
# animal is a year, so the pairing is 144 combinations rather than 12. Two
# members born five weeks apart share a sign and rarely an animal; two born
# eleven months apart share an animal and never a sign. Nobody is nudged at
# the same pair as the person beside them, which is the whole point of a nudge
# — a push everybody gets is a push nobody notices.
#
# The animal actions are deliberately somewhere ELSE in the app. The western
# twelve cluster around posting, battling and being scored, because that is
# what a star sign's character is about — how you show up. These twelve sit on
# the parts of the platform a member can go a month without finding: escrow,
# journalling, the bug queue, curation, translation, the wallet's own
# conversion. A second zodiac aimed at the same twelve buttons would be a
# louder version of the first; aimed at twelve different ones it is a map of
# the app.
#
# `chinese_zodiac_for` can answer `approximate` for a birthday outside the
# lunar-new-year table (`CHINESE_NEW_YEAR` covers 1940–2030). The bonus is
# paid on it anyway, for the same reason the profile already RENDERS it with a
# "?": refusing to pay would mean the members the boundary is hardest on are
# the ones who get nothing, which is the failure the first line of this file
# is about.
ANIMALS = {
    "Rat": {
        "tab": "promptz",
        "name": "Small Change",
        "action": "promptz_swap",
        "does": "Turn earned 🍥 into 🏷️",
        "stretch": "Swap enough in one go for five 🏷️",
        "why": "The rat hoards, and knows exactly what a scrap is worth. This "
               "is the one door in the app from the money you EARN to the AI "
               "you'd otherwise buy — and the rat is the sign that finds it.",
    },
    "Ox": {
        "tab": "collabz",
        "name": "Ploughed It Through",
        "action": "collab_deliver",
        "does": "Hand over finished work on a funded collab",
        "stretch": "Deliver on a deal you did not start",
        "why": "The ox finishes. Starting is the exciting half and this is the "
               "other one; the stretch is doing it on somebody else's project, "
               "which is work with none of the glory attached.",
    },
    "Tiger": {
        "tab": "battlez",
        "name": "Skin In The Game",
        "action": "wager",
        "does": "Stake 🍥 on somebody else's battle",
        "stretch": "Stake 100 🍥 or more",
        "why": "The tiger commits. Watching a battle costs nothing and means "
               "nothing; a wager is having an opinion you can be wrong about.",
    },
    "Rabbit": {
        "tab": "journalz",
        "name": "Kept The Record",
        "action": "journal",
        "does": "Write a JournalZ entry",
        "stretch": "Seven entries",
        "why": "The rabbit tends its burrow. This is the one thing here nobody "
               "else sees, scores or rates — which is exactly why it needs a "
               "reason to start and none of the others do.",
    },
    "Dragon": {
        "tab": "profilez",
        "name": "Proved The Wingspan",
        "action": "verified_link",
        "does": "Get an external account verified",
        "stretch": "Three of them verified",
        "why": "The dragon is stature you can see. And this is the one that "
               "pays a member back for a real fact: an unverified link is a "
               "claim, a verified one is reach, and reach is what ⚡ "
               "regenerates on. It is the most substantial thing on this list.",
    },
    "Snake": {
        "tab": "occ",
        "name": "Worked It Out",
        "action": "occ_run",
        "does": "Set OCC on a problem and let it run",
        "stretch": "Run one that produces code",
        "why": "The snake is patient and does its thinking before it moves. "
               "OCC is the app people bounce off hardest, and it rewards "
               "exactly that temperament.",
    },
    "Horse": {
        "tab": "keyconnectz",
        "name": "Crossed The Border",
        "action": "translate",
        "does": "Translate something in KeyConnectZ",
        "stretch": "Translate 200 characters or more",
        "why": "The horse covers ground. Translate is free at every tier on "
               "purpose — being understood is not a luxury — and this is the "
               "nudge that gets somebody to find out it is there.",
    },
    "Goat": {
        "tab": "playlistz",
        "name": "Arranged It",
        "action": "playlist",
        "does": "Build a playlist",
        "stretch": "One with ten or more tracks on it",
        "why": "The goat has taste. Curating is the one creative act here that "
               "makes nothing of your own and still makes something — and it "
               "is other people's work that gets heard for it.",
    },
    "Monkey": {
        "tab": "coachz",
        "name": "Turned Its Hand",
        "action": "second_app",
        "does": "Train in a second SkillZ app",
        "stretch": "Four apps",
        "why": "The monkey tries everything. Every coach here shares one "
               "engine and scores on the instrument's OWN dimensions, so a "
               "second app is a genuinely different skill — not the same "
               "drill wearing a hat.",
    },
    "Rooster": {
        "tab": "messagez",
        "name": "Spoke First",
        "action": "first_message",
        "does": "Message a member you have not messaged before",
        "stretch": "Three different people",
        "why": "The rooster starts the day. Everything else on this platform "
               "is downstream of somebody sending the first message, and it "
               "is the single hardest button in the app to press.",
    },
    "Dog": {
        "tab": "bugz",
        "name": "Barked At It",
        "action": "bug_report",
        "does": "File a BugZ report",
        "stretch": "One with a screenshot or a recording attached",
        "why": "The dog guards the house and tells you when something is "
               "wrong. The stretch is not padding: an attached repro is the "
               "difference between a report that gets fixed and one that gets "
               "a reply asking what you were doing.",
    },
    "Pig": {
        "tab": "collabz",
        "name": "Paid The Table",
        "action": "collab_fund",
        "does": "Put your own stake into a collab's escrow",
        "stretch": "Fund one where somebody else is owed more than you",
        "why": "The pig shares what it has. Funding is where a collab stops "
               "being a conversation, and the stretch is doing it on a deal "
               "where the money is mostly going to somebody else.",
    },
}

# action -> (which zodiac, which key). Built once so a call site does not have
# to know which sign OR animal it is firing for — it names the action and this
# decides. Twenty-four entries, and the assertion below is the thing that keeps
# it twenty-four: a duplicated action key would silently make one of the two
# unreachable rather than raising, and the member who lost theirs would have no
# way to tell.
_BY_ACTION = {}
for _key, _b in BONUSES.items():
    _BY_ACTION[_b["action"]] = ("sign", _key)
for _key, _b in ANIMALS.items():
    assert _b["action"] not in _BY_ACTION, f"action {_b['action']} is claimed twice"
    _BY_ACTION[_b["action"]] = ("animal", _key)
del _key, _b

# Bounded like every other earn here. An unbounded bonus is a mint.
#
# Left at 3 on purpose now there are twenty-four rather than twelve. The cap is
# a DAY's ceiling, not a lifetime one — once-each already fixes the lifetime at
# 140 🍥 — and its job is to stop a member sitting down on a single afternoon
# and clearing the board. Raising it because the board got bigger would undo
# the only thing it does.
DAILY_CAP = 3


def animal_of(user):
    """This member's Chinese zodiac animal, or "" when the birthday is unset.

    Derived, never stored: the year turns at lunar new year, so a table decides
    it and `chinese_zodiac_for` owns that table. A column here would be a
    second copy of an answer that already has one place to live.
    """
    from .models import chinese_zodiac_for
    cn = chinese_zodiac_for(profile_for(user).birthday) or {}
    return (cn.get("animal") or "").strip()


def _card(key, spec, got):
    """One bonus as the client reads it — the spec, the amounts, what is spent."""
    return {
        "key": key, **spec,
        "base_spinaz": BASE, "stretch_spinaz": STRETCH,
        "earned_base": "base" in got,
        "earned_stretch": "stretch" in got,
        "daily_cap": DAILY_CAP,
    }


def bonus_for(user):
    """This member's own STAR SIGN bonus, or None when their sign is unknown.

    Served before they do the thing. A bonus found out about afterwards is a
    surprise, not a nudge.

    `sign` is kept on the returned dict alongside `key` because the screen that
    reads this shipped before the animals existed, and the two repos deploy
    independently — a rename here would blank a live panel for however long the
    frontend took to follow.
    """
    sign = (profile_for(user).sign or "").strip()
    b = BONUSES.get(sign)
    if not b:
        return None
    got = set(SignBonusAward.objects.filter(user=user, sign=sign)
              .values_list("tier", flat=True))
    return {"sign": sign, **_card(sign, b, got)}


def animal_bonus_for(user):
    """The same, for the animal. None when the birthday is unset."""
    animal = animal_of(user)
    b = ANIMALS.get(animal)
    if not b:
        return None
    got = set(SignBonusAward.objects.filter(user=user, sign=animal)
              .values_list("tier", flat=True))
    return {"animal": animal, **_card(animal, b, got)}


def award(user, action, *, stretch=False):
    """Pay the bonus if this action is the one this member is nudged at.

    Silent and cheap when it is not — every call site fires unconditionally and
    this decides, so no caller has to carry a sign check of its own. A rule
    written in twenty-four places is a rule that reads twenty-four ways within
    a year.

    Returns the amount paid, or 0.
    """
    what = _BY_ACTION.get(action)
    if not what:
        return 0
    kind, key = what

    # Only ONE of these is read per call, and which one is decided by the
    # action rather than by the member — an animal action never touches the
    # star sign and vice versa. `animal_of` costs a derivation off the same
    # profile row `profile_for` already returns, so neither branch is a second
    # query.
    mine = (profile_for(user).sign or "").strip() if kind == "sign" else animal_of(user)
    if not mine or mine != key:
        return 0

    # THE STRETCH IMPLIES THE BASE, and this is not a convenience — it is the
    # rule "the stretch is the SAME action, harder" carried to its conclusion.
    # Every one of the twenty-four is built so that doing the harder version
    # means you also did the easier one: rating five today means you rated one,
    # swapping enough for five 🏷️ means you swapped, being challenged by name
    # to a 1v1 means somebody was already there.
    #
    # Without this, a member whose FIRST attempt clears the stretch is paid 50
    # and left owed 20 until they happen to do a smaller version of the same
    # thing — which reads as being punished for doing well, and is most likely
    # to hit exactly the members who engage hardest.
    tiers = ["base", "stretch"] if stretch else ["base"]

    # `sign` holds a star sign OR an animal — the two name sets do not overlap
    # (no Aries is a Rat), so one column addresses both and
    # `unique_together (user, sign, tier)` keeps meaning what it says.
    already = set(SignBonusAward.objects.filter(user=user, sign=key)
                  .values_list("tier", flat=True))
    owed = [t for t in tiers if t not in already]          # once each, still
    if not owed:
        return 0

    today = timezone.localdate()
    # The cap counts ROWS in a day, so a base+stretch pair spends two of the
    # three. That is the honest reading: it is two payments.
    room = DAILY_CAP - SignBonusAward.objects.filter(user=user, awarded_on=today).count()
    if room <= 0:
        return 0
    owed = owed[:room]

    spec = (BONUSES if kind == "sign" else ANIMALS)[key]
    paid = 0
    for tier in owed:
        amount = STRETCH if tier == "stretch" else BASE
        SignBonusAward.objects.create(user=user, sign=key, tier=tier,
                                      action=action, amount=amount, awarded_on=today)
        award_spinaz(user, amount, f"ZodiacZ · {key} · {spec['name']}",
                     app_key="zodiacz", target="zodiacz")
        paid += amount
    return paid


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
    """`GET /api/economy/signbonus/` — your two bonuses, and all twenty-four.

    Both halves matter. `mine` / `mine_animal` are the ones the cost/gain rule
    is about: a member has to be able to read what they get BEFORE they go and
    do it, or the bonus is a surprise rather than a nudge. `all` / `all_animals`
    are there because the fairness of this feature is only checkable by seeing
    the whole list — every one of the twenty-four is worth the same 20 / 50,
    and a member who cannot see the other twenty-three has to take that on
    trust.

    Both are null when the birthday is unset. That is honest and it is also the
    door: the client can send them to set one.

    **The animal keys are additions, never replacements.** `mine` and `all`
    keep the shape and the names they shipped with, because the screen reading
    them is in the other repo and the two deploy independently — renaming
    `mine` to `mine_sign` would blank a live panel for however long the
    frontend took to catch up. An endpoint may grow keys ahead of its client;
    it may never lose one.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            "mine": bonus_for(request.user),
            "mine_animal": animal_bonus_for(request.user),
            "base_spinaz": BASE,
            "stretch_spinaz": STRETCH,
            "daily_cap": DAILY_CAP,
            "all": [{"sign": s, **b} for s, b in BONUSES.items()],
            "all_animals": [{"animal": a, **b} for a, b in ANIMALS.items()],
            "open_in": {"app_key": "zodiacz", "target": "zodiacz"},
        })
