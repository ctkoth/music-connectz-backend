"""FunnelZ offers — one list of every promotion this platform will ever spring.

FunnelZ has only ever MEASURED. `FunnelEvent` counts landing → try → register
for a visitor with no account, owner-only, and nothing has ever acted on it.
This is the other half: the funnels that reach a member who is already here,
and the promotions that arrive without being asked for.

`crosspost.py` is the shape being copied deliberately — one module holding
every destination a post can go to, each row saying what it needs and what it
costs before it is spent. This is that, for offers: one module, every offer,
each row saying who it is true for and what it gives.

# Springing a sale on somebody is fine. Springing a FAKE one is not.

That distinction is the whole design, and it is the substance rule with a
price tag on it. The test that rule gives — *could a member get a good number
without getting good?* — reads here as **could a member get a good deal
without the deal being good?** A countdown that resets on reload, a "was $50"
against a price nobody ever paid, a "last 3 seats" that is last-3 forever:
each is decoration wearing a discount's clothes, and each is found out by the
first person who looks twice. On a platform selling subscriptions to
musicians who have been sold to their whole careers, being caught once is the
end of it.

So five rules, and every offer below answers to all five:

1. **It states the cost and the gain up front**, in the resource emoji, on the
   control. The existing rule, unchanged — a promotion is the one place it is
   most tempting to lead with the gain and put the cost in the small print.
2. **A deadline that does not end is a lie.** `ends_at` is real: `offers_for`
   drops an expired offer, and the endpoint that redeems it REFUSES after the
   deadline rather than quietly honouring it. Both directions are tested,
   because an offer that still works after it "ended" teaches members that
   every deadline here is theatre.
3. **Scarcity is counted, never claimed.** "3 left" comes from
   `founding_status()["remaining"]` — a real row count — or it is not said.
4. **It is TRUE when it is shown.** Every offer is computed from the member's
   own state at request time (`when`), never blasted at a list. An offer to
   top up PromptZ shown to somebody with 400 of them is not a promotion, it is
   noise, and noise is what teaches people to stop reading.
5. **Dismissible, and it stays dismissed.** `OfferDismissal` is per member per
   offer. An offer that comes back after being closed is not a promotion, it
   is an obstruction, and the member's answer to it is to leave.

# The CTA lands on the control, never the tab

Every row carries `tab` + `target`, and `goToSpot` puts the member on the
exact button. "Go to MembershipZ" is where a funnel dies: the member arrives
at the top of a screen they have never seen, hunts, and leaves. That is the
cross-pollination rule — *a read-only surface is usually an unfinished one* —
applied to marketing, and it is the difference between a funnel and a poster.

# What is NOT here, and why

**No blast, no schedule, no "everyone gets this on Tuesday".** Every offer in
this file is triggered by something the member did or is; none is triggered by
the calendar. A time-triggered promotion cannot answer rule 4, because the
thing that made it true was the date rather than the member.
"""
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import SPINAZ_PER_PROMPTZ
from .models import (
    daily_prompt_state,
    founding_status,
    membership_for,
    profile_for,
    prompt_walls_week,
    wallet_for,
)

# Every offer's gain, in the format the cost/gain rule asks for. Kept as
# structured pairs rather than a sentence so the client renders them the same
# way it renders every other price on the platform — a promotion that styles
# its own numbers is a promotion that will drift from the app around it.
#
# `resource` is one of energy | spinaz | promptz | money | xp, and the client
# maps it to the emoji through `resources.js`. Never the character here: the
# working notes say import it, never retype it, and that applies on this side
# of the wire too.


def _line(resource, amount, sign="+"):
    return {"resource": resource, "amount": amount, "sign": sign}


# ---------------------------------------------------------------------------
# The offers.
#
# `when(ctx)` decides whether this member sees it, off a context built ONCE per
# request (see `_context`) rather than each row re-reading the wallet. Twelve
# offers each calling `wallet_for` would be twelve queries on a screen that
# renders in one.
#
# `body` may be a callable so a figure inside the copy comes from the same
# state the offer was decided on — a sentence that says "you have 2 left" must
# never be able to disagree with the check that showed it.
OFFERS = {

    # -- Acquisition -------------------------------------------------------
    "invite_pays_both": {
        "step": "acquisition",
        "title": "Every invite pays twice",
        "body": "They land with a balance, you get the bigger half. There's no "
                "cap and no cooling-off — it pays on the account, every time.",
        "gain": [_line("spinaz", 300), _line("spinaz", 100)],
        "gain_note": "you / them",
        "cta": "Get your invite link",
        "tab": "profilez", "target": "referral-code",
        # Shown while they have not yet brought anyone. After the first, the
        # thing itself is the argument and a promotion is redundant.
        "when": lambda c: c["referrals"] == 0,
        "why": "The one number on this platform that is genuinely two-sided, "
               "and the only funnel where the member is the channel.",
    },

    # -- Activation --------------------------------------------------------
    "finish_onboarding": {
        "step": "activation",
        "title": "You're four steps from the welcome payout",
        "body": "OnboardZ is the only thing here that pays for setting up "
                "rather than for turning up, and it pays once.",
        "gain": [_line("spinaz", 150), _line("energy", 50)],
        "cta": "Finish OnboardZ",
        "tab": "onboardz", "target": "onboardz-steps",
        "when": lambda c: not c["profile"].onboarded,
        "why": "The single highest-value action a new member can take, and the "
               "one nobody finds on their own.",
    },
    "first_take": {
        "step": "activation",
        "title": "Nobody's heard you yet",
        "body": "One take, scored on pitch, timing and tone by something that "
                "actually listens. The first one's on the house.",
        "gain": [_line("spinaz", 20)],
        "gain_note": "if it's your sign's action",
        "cta": "Record a take",
        "tab": "singz", "target": "singz-record",
        "when": lambda c: c["posts"] == 0 and c["profile"].onboarded,
        "why": "Activation is one action, not a checklist, and this is the one "
               "that makes the rest of the app mean anything.",
    },
    "set_your_birthday": {
        "step": "activation",
        "title": "Two bonuses are sitting unclaimed",
        "body": "Your star sign and your animal year each carry their own — "
                "worth the same for everybody, and both need a birthday first.",
        "gain": [_line("spinaz", 140)],
        "gain_note": "across both, in total",
        "cta": "Set your birthday",
        "tab": "profilez", "target": "birthday",
        "when": lambda c: not (c["profile"].birthday or "").strip(),
        "why": "The ZodiacZ bonuses are twenty-four doors into the app and a "
               "member without a birthday can open none of them.",
    },

    # -- Monetisation ------------------------------------------------------
    "out_of_prompts": {
        "step": "monetisation",
        "title": "You're out of free AI for today",
        "body": lambda c: (
            f"Your tier gets {c['prompt_allowance']} a day and they're spent. "
            f"{SPINAZ_PER_PROMPTZ} 🍥 buys one more — no card, and you've got "
            f"{c['wallet'].spinaz or 0}."
        ),
        "gain": [_line("promptz", 1)],
        "cost": [_line("spinaz", SPINAZ_PER_PROMPTZ, "−")],
        "cta": "Swap 🍥 for 🏷️",
        "tab": "promptz", "target": "promptz-convert",
        # The moment it is true, and only then. This is the one offer on the
        # list that arrives at exactly the second it is useful, which is why
        # it does not need a discount attached to work.
        "when": lambda c: (c["prompt_remaining"] == 0
                           and (c["wallet"].spinaz or 0) >= SPINAZ_PER_PROMPTZ),
        "why": "A wall a member hits with the means to climb it already in "
               "their pocket, and no screen has ever told them so.",
    },
    "prompts_wall_no_spinaz": {
        "step": "monetisation",
        "title": "Out of AI, and out of 🍥 to swap",
        "body": "Rating other people's work pays, and so does watching an AdZ. "
                "Both are free and neither needs a card.",
        "gain": [_line("energy", 1), _line("spinaz", 0)],
        "gain_note": "per rating, plus AdZ",
        "cta": "Go and earn some",
        "tab": "social", "target": "social-feed",
        "when": lambda c: (c["prompt_remaining"] == 0
                           and (c["wallet"].spinaz or 0) < SPINAZ_PER_PROMPTZ),
        # The ladder rule, as an offer: a member who cannot do a thing at all
        # does not upgrade, they leave. This one exists so the free tier's
        # wall always has a free door beside it.
        "why": "A limit that stops somebody doing anything is a door out. This "
               "is the door back in, and it is deliberately not a sale.",
    },
    "premium_ladder": {
        "step": "monetisation",
        "title": lambda c: f"You've hit your {c['prompt_allowance']}/day three times this week",
        "body": "Premium widens the allowance and the upload cap. Everything "
                "you can do now, you can still do — there's just more of it.",
        "gain": [_line("promptz", 5)],
        "gain_note": "a day, plus a bigger upload cap",
        "cta": "Compare the tiers",
        "tab": "membershipz", "target": "membershipz-plans",
        "when": lambda c: c["tier"] == "free" and c["prompt_walls_week"] >= 3,
        "why": "Sold at the wall the member actually hit, three times, rather "
               "than at a member who has never met it.",
    },
    "founding_seat": {
        "step": "monetisation",
        "title": lambda c: f"{c['founding']['remaining']} founding seats left",
        "body": "Half price, for life, and it never goes back up. When the "
                "fifty are gone the price is the price.",
        "gain": [_line("money", 0)],
        "gain_note": "half of StatZ, permanently",
        "cta": "Take a seat",
        "tab": "membershipz", "target": "membershipz-founding",
        # Scarcity that is COUNTED. `founding_status()` reads the rows; if the
        # number is not real the offer does not render, rather than falling
        # back to a vague "limited time" that would be the lie this whole
        # module exists to avoid.
        "when": lambda c: (not c["membership"].lifetime
                           and 0 < c["founding"]["remaining"] <= 50),
        "why": "The only honest scarcity on the platform, because there is a "
               "row count behind it and it genuinely runs out.",
    },

    # -- Retention ---------------------------------------------------------
    "streak_at_risk": {
        "step": "retention",
        "title": lambda c: f"Your {c['streak']}-day streak ends tonight",
        "body": "One drill keeps it. It's the only counter here that resets to "
                "one rather than counting down.",
        "gain": [_line("xp", 0)],
        "gain_note": "and the streak stays alive",
        "cta": "Do one drill",
        "tab": "coachz", "target": "skillz-drills",
        "when": lambda c: c["streak"] >= 3 and not c["trained_today"],
        "why": "The one retention message that is doing the member a favour "
               "rather than asking one — it is their number, not ours.",
    },
    "unfinished_collab": {
        "step": "retention",
        "title": "A collab is waiting on you",
        "body": "It's funded and undelivered. The clock on it releases the "
                "money whether or not the work arrives.",
        "gain": [_line("spinaz", 20)],
        "gain_note": "if it's your animal's action",
        "cta": "Open the deal",
        "tab": "collabz", "target": "collabz-deals",
        "when": lambda c: c["deals_owed"] > 0,
        "why": "Money already in escrow is the strongest reason anybody has to "
               "come back, and nothing was telling them.",
    },
    "unread_messages": {
        "step": "retention",
        "title": lambda c: f"{c['unread']} message{'s' if c['unread'] != 1 else ''} you haven't opened",
        "body": "Somebody here started a conversation. That's the whole "
                "platform working, and it's sitting unread.",
        "gain": [],
        "cta": "Read them",
        "tab": "messagez", "target": "messagez-threads",
        "when": lambda c: c["unread"] > 0,
        "why": "Not a promotion at all, and it belongs on this list precisely "
               "because a funnel that only ever sells is one people stop "
               "reading before the thing worth reading arrives.",
    },
}

# The steps a member moves through, in order. Named here rather than inferred
# from the offers so the funnel has a shape even when a step has nothing to
# show — a stage that vanishes when it is empty cannot be measured.
STEPS = ["acquisition", "activation", "monetisation", "retention"]

# At most this many at once. An offer screen showing eleven things is a screen
# nobody reads, and the one that mattered is buried among ten that did not.
MAX_SHOWN = 3


def _resolve(value, ctx):
    """A field may be a callable, so a figure in the copy comes from the same
    state the offer was decided on. A sentence saying "you have 2 left" must
    never be able to disagree with the check that showed it."""
    return value(ctx) if callable(value) else value


def _context(user):
    """Everything every offer needs, read ONCE.

    The point of building this up front is the same point the coach's
    `coach_cap` makes and the feed's query-count test enforces: a screen that
    renders eleven offers must not cost eleven wallet reads. Each field here is
    at most one query, and a `when` that needed a twelfth would be a `when`
    that has to be re-thought rather than a query that gets added.
    """
    from .models import CollabDeal, Message, Post, Referral

    w = wallet_for(user)
    m = membership_for(user)
    allowance, _used, remaining = daily_prompt_state(user)

    streak, trained_today = 0, False
    try:
        from apps.skillz.models import TrainingProfile
        best = (TrainingProfile.objects.filter(user=user)
                .order_by("-current_streak").first())
        if best:
            streak = best.current_streak or 0
            trained_today = best.last_active == timezone.localdate()
    except Exception:                                   # noqa: BLE001
        # SkillZ is a separate app and an offer screen must never 500 because
        # a neighbouring app is mid-migration. A missing streak reads as no
        # streak, which is the safe direction: it shows one fewer offer.
        pass

    return {
        "wallet": w,
        "membership": m,
        "tier": m.tier,
        "profile": profile_for(user),
        "prompt_allowance": allowance,
        "prompt_remaining": remaining,
        # How often they've hit the wall lately. This is the honest version
        # of "they seem to want more" — a member who has met the ceiling three
        # times HAS met it, which is a fact, where "seems engaged" would be a
        # guess with a price attached. Rolling, so it goes back to zero when
        # they stop hitting it.
        "prompt_walls_week": prompt_walls_week(user),
        "founding": founding_status(),
        "referrals": Referral.objects.filter(referrer=user).count(),
        "posts": Post.objects.filter(author=user).count(),
        "unread": Message.objects.filter(recipient=user, read=False).count(),
        "deals_owed": CollabDeal.objects.filter(
            status=CollabDeal.STATUS_FUNDED,
            participants__contains=[{"username": user.username}],
        ).count() if _json_contains_works() else 0,
        "streak": streak,
        "trained_today": trained_today,
    }


def _json_contains_works():
    """`participants__contains` on a JSONField is Postgres-only.

    The suite runs on SQLite and production is Postgres — the working notes
    are explicit that this gap is the one to respect — so rather than have an
    offer that works in production and raises in every test, the query is
    skipped where the backend cannot answer it. A skipped offer shows nothing;
    a raising one takes the whole screen down.
    """
    from django.db import connection
    return connection.vendor == "postgresql"


def offers_for(user, *, limit=MAX_SHOWN):
    """Every offer that is TRUE for this member right now, best step first.

    Rule 4 in one function: nothing here is scheduled, blasted or targeted at
    a segment. Each row asks the member's own state whether it is true, and an
    offer that is not true is not shown — which is what stops this becoming
    the noise that teaches people to close the panel without reading it.
    """
    from .models import OfferDismissal

    ctx = _context(user)
    dismissed = set(OfferDismissal.objects.filter(user=user)
                    .values_list("offer_key", flat=True))
    now = timezone.now()

    out = []
    for key, spec in OFFERS.items():
        if key in dismissed:
            continue
        # Rule 2. An expired offer is gone from the list AND refused on
        # redemption — see `redeemable`. One of the two on its own is the bug.
        ends = spec.get("ends_at")
        if ends and now >= ends:
            continue
        try:
            if not spec["when"](ctx):
                continue
        except Exception:                               # noqa: BLE001
            # A `when` that raises hides ONE offer, never the screen. An offer
            # panel that 500s because a single predicate met an edge case is a
            # worse outcome than a member not seeing one promotion.
            import logging
            logging.getLogger(__name__).exception("offer %s failed its check", key)
            continue
        out.append({
            "key": key,
            "step": spec["step"],
            "title": _resolve(spec["title"], ctx),
            "body": _resolve(spec["body"], ctx),
            "gain": spec.get("gain") or [],
            "gain_note": spec.get("gain_note", ""),
            "cost": spec.get("cost") or [],
            "cta": spec["cta"],
            # The CTA lands on the CONTROL, not the tab. "Go to MembershipZ" is
            # where a funnel dies.
            "tab": spec["tab"],
            "target": spec["target"],
            "ends_at": ends.isoformat() if ends else None,
        })

    out.sort(key=lambda o: STEPS.index(o["step"]) if o["step"] in STEPS else 99)
    return out[:limit]


def redeemable(key):
    """Whether this offer may still be acted on, checked SERVER-side.

    Separate from `offers_for` on purpose. A client holding a panel it
    rendered before the deadline will happily post after it, and an offer that
    still works once it has "ended" teaches members that every deadline here
    is theatre — which costs more than the sale was worth.
    """
    spec = OFFERS.get(key)
    if not spec:
        return False, "That offer doesn't exist."
    ends = spec.get("ends_at")
    if ends and timezone.now() >= ends:
        return False, "That one's finished — it ended when it said it would."
    return True, ""


class FunnelOffersView(APIView):
    """`GET /api/economy/offerz/funnel/` — the offers true for me right now.
    `POST {key, action: "dismiss"}` — close one, for good.

    GET is what every screen reads to decide whether to show a promotion, and
    it answers with at most `MAX_SHOWN`. The cap is the feature: a panel with
    eleven things on it is a panel nobody reads, and the one that mattered is
    buried under ten that did not.

    The client renders what it is given and decides NOTHING about who sees
    what. That is the same line `DupeZ.jsx` holds about who is an owner, and
    for the same reason: a targeting rule that lives in a screen is a
    targeting rule that will disagree with the one in the next screen.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            "offers": offers_for(request.user),
            "steps": STEPS,
            "max_shown": MAX_SHOWN,
        })

    def post(self, request):
        from .models import OfferDismissal

        key = str((request.data or {}).get("key", ""))[:48]
        if key not in OFFERS:
            return Response({"detail": "No such offer."},
                            status=status.HTTP_400_BAD_REQUEST)
        OfferDismissal.objects.get_or_create(user=request.user, offer_key=key)
        # Answer with what is left rather than an empty ack, so closing one
        # does not cost the screen a second round trip to find out what now
        # sits in its place.
        return Response({"dismissed": key, "offers": offers_for(request.user)})


class FunnelOfferRedeemView(APIView):
    """`POST /api/economy/offerz/funnel/redeem/ {key}` — act on one.

    This exists ONLY to enforce rule 2, and it is worth its own endpoint for
    that alone. A client holding a panel it rendered before a deadline will
    happily post after it, and an offer that still works once it has "ended"
    teaches members that every deadline here is theatre — which costs more,
    permanently, than the sale was ever worth.

    It does not move any resource itself. The offers are doors, and the thing
    behind each door has its own endpoint with its own price and its own
    checks; a redeem that granted things would be a second place every one of
    those prices lives.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        key = str((request.data or {}).get("key", ""))[:48]
        ok, why = redeemable(key)
        if not ok:
            return Response({"detail": why}, status=status.HTTP_409_CONFLICT)
        spec = OFFERS[key]
        return Response({"key": key, "tab": spec["tab"], "target": spec["target"]})
