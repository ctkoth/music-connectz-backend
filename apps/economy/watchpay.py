"""What an hour of somebody's work costs to read or watch — and what it pays.

Corey's proposal, in his words: *ViewZ pays creators — 10% of their skill-used
price per hour, or buy it to read whenever for 10% of the skill price and not
pay the hourly.*

The idea is sound and the platform is already most of the way to it. Two things
about the numbers had to change first, and both are written down here rather
than in a commit nobody re-reads.

## Why this is possible at all: it is two systems that already exist, joined

- **ViewZ already measures attention honestly.** Heartbeats, `document.hidden`,
  a session that stops counting when the tab is not being looked at. Billing by
  the hour needs exactly that and nothing else — a wall clock would charge
  somebody for a tab they left open in a drawer.
- **CallZ already meters money by the minute.** Rate published before it rings,
  running cost on screen, receipt matching the quote, rate snapshotted so it
  cannot move mid-call. Reading a manga by the hour is CallZ with a page
  instead of a voice, and it answers to the same rule: **a price discovered by
  paying it is not a price, it's a bill.**

So the new thing is small: a rate, a ceiling, and a quote.

## The flaw in the proposal as stated, and the fix

**Rent and buy cannot both be 10%.** If an hour costs 10% of the skill rate and
buying costs 10% of the skill rate, then buying costs exactly one hour of
renting — so nobody ever rents, and the hourly path is dead the day it ships.

The fix is that the two prices come off different things:

- **Renting is priced by TIME** — `READER_SHARE` of the creator's hourly rate,
  per hour, prorated per second like a call.
- **Buying is priced by the WORK'S LENGTH** — what a full read-through would
  cost at that hourly rate, times `KEEP_MULTIPLIER`. A ninety-minute MovieZ
  costs more to keep than a forty-second ReelZ, which is the sentence anybody
  would expect to be true and the flat 10% makes false.

That keeps both doors open: rent to find out, buy when you know you will come
back. And `credit_toward_buy` means the renting you already did comes off the
purchase, so "am I wasting money by not buying" — the hesitation that kills
metered media — has an answer on screen.

## The real risk, named: this prices off a number the creator types

`profile_skill_rate` is self-declared. Deriving what a READER pays from it
fails the test this codebase holds every number to — *could a member get a good
one without getting good?* — because they can simply type a bigger rate.

Three guards, and the third is the one still owed:

1. **It uses the CHEAPEST priced skill** (`profile_skill_rate` picks `min` on
   purpose), so padding one expensive skill moves nothing.
2. **`MAX_READ_CENTS_PER_HOUR` caps it.** A ladder with no ceiling is whatever
   the most expensive person on the platform typed. This is the same reason
   `DAILY_PROMPT_MAX_CENTS` exists.
3. **Not yet built: price off a rate somebody has actually been PAID.** A
   completed CollabZ or LessonZ deal is evidence; a profile field is an
   aspiration. Until that lands, the cap is doing the work alone and this
   comment is the record of it.

Self-dealing needs no guard beyond the ones already here: a creator watching
their own work is never counted by ViewZ, and routing money to yourself through
the platform loses the developer tax on every pass.
"""
import math

from .models import (DEV_TAX, TIER_FREE, membership_for, profile_for,
                     split_cents)
from .social import profile_skill_rate

# What a reader pays, as a share of the creator's own hourly rate. Corey's
# number. An hour of your attention is worth a tenth of an hour of their
# labour, which is a sentence a reader can weigh without being taught anything.
READER_SHARE = 0.10

# The ceiling on that, per hour. Nothing may cost more than this to read or
# watch, whatever the creator's rate says — a limit that has no ceiling is
# whatever the dearest person on the platform typed into a form.
MAX_READ_CENTS_PER_HOUR = 1500          # $15.00/hr

# What a work costs when its creator has priced no skill at all. Zero, not a
# default price: a member who has not asked for money is not asking for money,
# and inventing a rate on their behalf would put a paywall on their work
# without them ever choosing one.
UNPRICED_CENTS_PER_HOUR = 0

# Buying is a full read-through at the hourly rate, times this. Two, because
# owning a thing you would otherwise rent twice is the point at which buying
# stops being a gamble — the ratio physical rental markets settled on long
# before any of this.
KEEP_MULTIPLIER = 2.0

# Nothing shorter than this is billed as a read-through when a work does not
# declare its length. Twenty minutes is a chapter or a short film; it is a
# floor for the BUY price only, never for the meter.
ASSUMED_MINUTES = 20

# You cannot judge a manga from its cover or a film from its poster. The
# opening is free at every tier, for the same reason /try scores one take with
# no account: the trial IS the pitch, and a paywall in front of the first page
# sells nothing to somebody who has never read you.
FREE_MINUTES = 10

# Formats this prices. A work kind not in here has no meter and no buy
# button — deliberately, so a surface cannot start charging by being added to
# a URL. MangaZ is absent because MangaZ does not exist yet; the day it does,
# it is one line.
PRICED_KINDS = {
    "reelz": "ReelZ",
    "episodez": "EpisodeZ",
    "moviez": "MovieZ",
}


def hourly_cents_for(user):
    """What one hour of this creator's work costs a reader, in cents.

    Rounded UP so a rate can never round away to nothing, then capped. Zero
    when they have priced no skill — see UNPRICED_CENTS_PER_HOUR.
    """
    per_hour = profile_skill_rate(profile_for(user))
    if not per_hour:
        return UNPRICED_CENTS_PER_HOUR
    return min(MAX_READ_CENTS_PER_HOUR, max(1, math.ceil(per_hour * READER_SHARE)))


def cost_for_seconds(hourly_cents, seconds):
    """Prorated per second, rounded up to the cent — same shape as CallZ.

    Per-second rather than per-started-hour so ten minutes costs ten minutes.
    Rounding up means the platform never owes a fraction it cannot pay, and
    the most that rounding can ever cost somebody is one cent.
    """
    seconds = max(0, int(seconds or 0))
    if hourly_cents <= 0 or seconds <= 0:
        return 0
    return max(1, math.ceil(hourly_cents * seconds / 3600))


def billable_seconds(watched_seconds, free_seconds=None):
    """Seconds that cost money — the free opening comes off the top, once.

    A free window that is charged after the fact is not free, so it is
    subtracted here rather than refunded anywhere.
    """
    free = FREE_MINUTES * 60 if free_seconds is None else max(0, int(free_seconds))
    return max(0, int(watched_seconds or 0) - free)


def buy_cents_for(user, duration_sec=0):
    """What it costs to keep this work: a full read-through, times the keep
    multiplier.

    Priced by the WORK'S LENGTH rather than as a flat share, because the flat
    share makes buying cost exactly one hour of renting and kills the hourly
    path outright. A ninety-minute film costing more to own than a forty-second
    clip is the sentence anybody expects to be true.
    """
    hourly = hourly_cents_for(user)
    if hourly <= 0:
        return 0
    minutes = max(ASSUMED_MINUTES, int((duration_sec or 0) / 60))
    full_run = cost_for_seconds(hourly, minutes * 60)
    return max(1, math.ceil(full_run * KEEP_MULTIPLIER))


def credit_toward_buy(spent_cents, buy_cents):
    """What renting has already paid toward owning it.

    The whole of it, capped at the price. "Am I wasting money by not buying
    yet" is the hesitation that kills metered media, and the answer being
    "no, it all counts" is worth more than the few cents it costs.
    """
    return max(0, min(int(spent_cents or 0), int(buy_cents or 0)))


def creator_take(amount_cents, tier=TIER_FREE):
    """(to the creator, platform cut) — both halves, because both belong on
    screen. A reader sees what they pay; a creator sees what lands."""
    dev, rest = split_cents(amount_cents, DEV_TAX.get(tier, DEV_TAX[TIER_FREE]))
    return rest, dev


def quote(owner, viewer=None, *, kind="reelz", duration_sec=0, spent_cents=0,
          balance_cents=None):
    """Everything a reader needs BEFORE they open it, in one dict.

    This is the whole point of the module. Corey's rule is that a price is
    stated before the thing that spends it, never in the result — so the rate,
    the free window, the purchase price, what the reader can afford and what
    the creator actually receives are all computed here and published together.
    Nothing downstream should be doing this arithmetic a second time.
    """
    hourly = hourly_cents_for(owner)
    buy = buy_cents_for(owner, duration_sec)
    tier = membership_for(owner).tier
    take_hour, cut_hour = creator_take(hourly, tier)
    take_buy, cut_buy = creator_take(buy, tier)
    credit = credit_toward_buy(spent_cents, buy)
    free_paid = hourly <= 0

    minutes_affordable = None
    if balance_cents is not None and hourly > 0:
        minutes_affordable = int((max(0, balance_cents) * 60) // hourly)

    return {
        "kind": kind,
        "kind_label": PRICED_KINDS.get(kind, kind),
        "priced": not free_paid,
        # Renting, by time.
        "hourly_cents": hourly,
        "free_minutes": FREE_MINUTES,
        "minutes_affordable": minutes_affordable,
        # Owning, by length.
        "buy_cents": buy,
        "buy_credit_cents": credit,
        "buy_now_cents": max(0, buy - credit),
        "runtime_minutes": max(ASSUMED_MINUTES, int((duration_sec or 0) / 60)),
        # Both sides of the money, always. A referral states +300 🍥 and
        # +100 🍥; this is the same rule with a bigger number.
        "creator_hourly_cents": take_hour,
        "platform_hourly_cents": cut_hour,
        "creator_buy_cents": take_buy,
        "platform_buy_cents": cut_buy,
        # The derivation, said out loud. A price whose reason is on screen is
        # one a reader can judge; a bare number is one they can only accept.
        "why": (
            f"{int(READER_SHARE * 100)}% of the creator's own hourly skill rate, "
            f"capped at ${MAX_READ_CENTS_PER_HOUR / 100:.2f}/hour. "
            f"Owning it is a full {max(ASSUMED_MINUTES, int((duration_sec or 0) / 60))}-minute "
            f"read-through × {KEEP_MULTIPLIER:g}, and what you've already spent comes off it."
            if not free_paid else
            "This creator hasn't priced a skill, so reading it is free. "
            "We don't invent a rate on somebody's behalf."
        ),
        "free_note": (
            f"The first {FREE_MINUTES} minutes are free at every tier — "
            "you can't judge a work from its cover."
        ),
    }


# ---------------------------------------------------------------- the endpoint
from rest_framework.permissions import IsAuthenticated          # noqa: E402
from rest_framework.response import Response                    # noqa: E402
from rest_framework.views import APIView                        # noqa: E402
from rest_framework import status                               # noqa: E402


class WatchPriceView(APIView):
    """GET ?target=directz:12 — what this costs to read, before opening it.

    A quote and nothing else: it moves no money and creates no session. That
    is deliberate — the price has to be publishable without committing anybody
    to it, or the only way to learn a price is to start paying one.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        raw = str(request.query_params.get("target") or "").strip()[:64]
        kind, _, key = raw.partition(":")
        if kind != "directz" or not key.isdigit():
            return Response(
                {"detail": "target must be directz:<id> — the only priced kind so far.",
                 "priced_kinds": list(PRICED_KINDS)},
                status=status.HTTP_400_BAD_REQUEST)

        from .models import DirectZWork
        work = DirectZWork.objects.filter(pk=int(key)).select_related("owner").first()
        if not work:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)

        from .models import wallet_for
        mine = work.owner_id == request.user.id
        balance = wallet_for(request.user).money
        q = quote(work.owner, request.user, kind=work.fmt,
                  duration_sec=work.duration_sec, balance_cents=balance)
        return Response({
            "target": raw,
            "title": work.title,
            "owner": work.owner.username,
            # Your own work is never billed to you, and saying so here means
            # the client never has to work it out for itself.
            "mine": mine,
            "your_balance_cents": balance,
            "open_in": "directz",
            **({"priced": False, "why": "It's yours — your own work is never billed to you."}
               if mine else {}),
            **{k: v for k, v in q.items() if not (mine and k in ("priced", "why"))},
        })
