"""QuestZ — the Energy on-ramp, and the reason a new member can use anything.

WHY THIS EXISTS, which is not "engagement"
------------------------------------------
`energy_rate_per_hour` is `reach_median(user) // divisor`. A member with no
reach earns **zero** Energy an hour — not slowly, zero — and Energy is what pays
for an OCC run, a GameZ build, and posting once your skills carry a price. So
the app hands a newcomer a set of tools and no way to afford them until they
already have an audience, which is the wrong way round.

Quests are the income that exists before reach does. The milestone that
verifies a reach source is deliberately the biggest one-off in the list: the
quest that switches on passive income is the quest that graduates you off
quests.

THE RULES THESE FOLLOW
----------------------
* **Effort may pay Energy and XP. It may never pay a rating or a skill level.**
  That is the substance rule, and Energy is a resource rather than a claim
  about how good somebody is, so paying it for turning up is honest.
* **A quest states its reward before it is started**, like every other button
  in this app. `board()` returns the number with the quest, not after it.
* **A quest a spammer can finish alone is a mint with extra steps.** "Post 5
  tracks" pays for garbage, because posting is free when no priced skills are
  attached. The weekly version asks for three posts *that somebody else rated*
  — identical work for an honest member, impossible for one account.
* **Every quest is a doorway.** Each carries the app and the `data-tour` anchor
  that completes it, so the board hands you the control rather than the tab.

MINTING
-------
Every claim is new Energy. The sinks (posting, OCC seconds, GameZ builds) are
real, so moderate minting is fine — but it IS minting, so there is a per-member
daily ceiling below, every award goes through `award_energy` and therefore
lands in LogZ with its reason, and the numbers sit in one table where they can
be argued with.
"""
from datetime import timedelta

from django.utils import timezone
from .personaz import personas_of

DAILY = "daily"
WEEKLY = "weekly"
ONCE = "once"

# The ceiling on what one member can mint in a day, streak bonus included.
# Sized just under the hourly regen of a Free member with ~1,500 reach: quests
# are a floor for people who have no audience yet, never a better deal than
# actually being listened to.
DAILY_ENERGY_CAP = 150

# A streak is consecutive days with at least one daily claim. It multiplies the
# DAILY rewards only — a weekly or a milestone pays what it says.
STREAK_STEPS = [(30, 2.0), (7, 1.5)]        # checked longest-first


def _own_post_items(user):
    """`post:<id>` keys for this member's own posts — used to make "give
    feedback" quests mean feedback to somebody else."""
    from .models import Post
    return [f"post:{pid}" for pid in
            Post.objects.filter(author=user).values_list("id", flat=True)]


# ---- how each quest is actually measured, against real rows -------------

def _rated(user, since):
    from .models import ItemRating
    q = ItemRating.objects.filter(user=user)
    if since:
        q = q.filter(created_at__gte=since)
    return q.count()


def _commented_on_others(user, since):
    from .models import SocialComment
    q = SocialComment.objects.filter(user=user).exclude(item_id__in=_own_post_items(user))
    if since:
        q = q.filter(created_at__gte=since)
    return q.count()


def _carried_a_post(user, since):
    """A post taken somewhere else — the cross-pollination habit, measured by
    the deal it produced rather than by a tab change nobody records."""
    from .models import CollabDeal
    q = CollabDeal.objects.filter(initiator=user, source_post__isnull=False)
    if since:
        q = q.filter(created_at__gte=since)
    return q.count()


def _practised(user, since):
    from apps.skillz.models import TrainingEvent
    q = TrainingEvent.objects.filter(profile__user=user)
    if since:
        q = q.filter(created_at__gte=since)
    return q.count()


def _posts_others_rated(user, since):
    """Posts of theirs that somebody ELSE rated.

    This is the anti-spam heart of the set. An honest member posts and people
    rate it; a farmer posting five empty tracks scores zero here, because the
    thing being counted is not something they can do to themselves.
    """
    from .models import ItemRating, Post
    q = Post.objects.filter(author=user)
    if since:
        q = q.filter(created_at__gte=since)
    keys = [f"post:{pid}" for pid in q.values_list("id", flat=True)]
    if not keys:
        return 0
    return (ItemRating.objects.filter(item_id__in=keys)
            .exclude(user=user).values("item_id").distinct().count())


def _takes_coached(user, since):
    """Counted off the LEDGER rather than off Post.score.

    `_bill` writes "… Boss Take — AI Coach" on every coached run, which is one
    portable string query instead of digging through a JSON column differently
    on SQLite and Postgres.
    """
    from .models import Transaction
    q = Transaction.objects.filter(user=user, note__icontains="Boss Take")
    if since:
        q = q.filter(created_at__gte=since)
    return q.count()


FUNDED = ("funded", "delivered", "released")


def _collabs_funded(user, since):
    from .models import CollabDeal
    q = CollabDeal.objects.filter(initiator=user, status__in=FUNDED)
    if since:
        q = q.filter(created_at__gte=since)
    return q.count()


def _referrals_who_posted(user, since):
    """A referral that produced a MEMBER, not a signup. Paying for the signup
    is how you buy a list of people who never come back."""
    from .models import Post, Referral
    q = Referral.objects.filter(referrer=user)
    if since:
        q = q.filter(created_at__gte=since)
    joinees = list(q.values_list("joinee_id", flat=True))
    if not joinees:
        return 0
    return (Post.objects.filter(author_id__in=joinees)
            .values("author_id").distinct().count())


def _journaled(user, since):
    """Days with a journal entry — DAYS, not entries.

    Counting entries would pay a member for pressing save five times on the
    same afternoon. The quest is "keep the day", so the thing counted is the
    day, and the `day` column is the one the member chose rather than the clock
    the row was written on.
    """
    from .models import JournalEntry
    q = JournalEntry.objects.filter(author=user)
    if since:
        q = q.filter(created_at__gte=since)
    return q.values("day").distinct().count()


def _priced_a_skill(user, _since):
    from .models import profile_for
    for persona in personas_of(profile_for(user)):
        for s in (persona.get("skills") or []):
            if isinstance(s, dict) and int(s.get("rate_cents") or 0) > 0:
                return 1
    return 0


def _reach_verified(user, _since):
    from .models import reach_median
    return 1 if reach_median(user) > 0 else 0


# ---- the list -----------------------------------------------------------
#
# `energy` is what the quest pays. `target` is how many of the measured thing
# it takes. `app`/`anchor` are where the member is sent to do it.

QUESTS = [
    # --- daily: small, habitual, and mostly about giving rather than posting.
    dict(id="rate-5", scope=DAILY, target=5, energy=25, count=_rated,
         title="Rate 5 tracks", app="postz", anchor="feed",
         what="Rate five tracks you didn't make. You keep the +1 ⚡ each rating "
              "already pays — this is on top.",
         why="Curation is the scarcest volunteer work in the app."),
    dict(id="comment-2", scope=DAILY, target=2, energy=20, count=_commented_on_others,
         title="Leave 2 comments", app="postz", anchor="feed",
         what="Two comments on somebody else's post. Your own don't count.",
         why="A rating is a number. A comment is the bit people actually keep."),
    dict(id="carry-1", scope=DAILY, target=1, energy=15, count=_carried_a_post,
         title="Take a post somewhere else", app="postz", anchor="postz-open-in",
         what="Open one post in another app and start something with it.",
         why="Nothing you make is a dead end — this is the habit that proves it."),
    dict(id="journal-1", scope=DAILY, target=1, energy=15, count=_journaled,
         title="Keep the day", app="journalz", anchor="journalz-composer",
         what="Write one JournalZ entry for today. It stays private — nothing is "
              "published and nobody you tag is told unless you share it.",
         why="The only daily here you can do on a day nothing happened, which is "
             "what makes it the one that holds a streak together."),
    dict(id="practise-1", scope=DAILY, target=1, energy=15, count=_practised,
         title="Practise once", app="mimez", anchor="skillz-panel",
         what="Log one drill in MimeZ or any SkillZ app.",
         why="The training loop only works if it's a loop."),

    # --- weekly: real work, and the two best ones need other people.
    dict(id="posts-rated-3", scope=WEEKLY, target=3, energy=150, count=_posts_others_rated,
         title="3 posts somebody rated", app="postz", anchor="composer",
         what="Post three tracks this week that each get at least one rating "
              "from another member.",
         why="Posting alone is free and easy to fake. Being listened to isn't."),
    dict(id="coached-2", scope=WEEKLY, target=2, energy=200, count=_takes_coached,
         title="Get 2 takes coached", app="singz", anchor="bosstake-mic",
         what="Send two takes to the coach — recorded here, or a track you "
              "already posted.",
         why="The coach is the fastest way this app makes you better."),
    dict(id="collab-1", scope=WEEKLY, target=1, energy=250, count=_collabs_funded,
         title="Fund a collab", app="collabz", anchor="collabz-deals",
         what="Start a CollabZ deal and get it funded.",
         why="The highest-value thing that happens here, so it pays like it."),
    dict(id="referral-active", scope=WEEKLY, target=1, energy=200,
         count=_referrals_who_posted,
         title="Bring somebody who posts", app="profilez", anchor="referral-code",
         what="Refer someone who goes on to post at least once. The +300 🍥 "
              "referral reward is separate and still yours.",
         why="A signup is a number. Somebody who posts is a member."),

    # --- milestones: the on-ramp, once each, ever.
    dict(id="first-post", scope=ONCE, target=1, energy=100, count=lambda u, s: _posts_or_zero(u),
         title="Your first post", app="postz", anchor="composer",
         what="Put one thing up.", why="Everything else here starts from a post."),
    dict(id="first-rating", scope=ONCE, target=1, energy=50, count=_rated,
         title="Your first rating given", app="postz", anchor="feed",
         what="Rate somebody's track.", why="The feed only works if people rate."),
    dict(id="first-price", scope=ONCE, target=1, energy=75, count=_priced_a_skill,
         title="Price a skill", app="profilez", anchor="skills",
         what="Put a rate on one thing you can do.",
         why="It's how you get paid, and how posts get priced."),
    dict(id="first-coached", scope=ONCE, target=1, energy=100, count=_takes_coached,
         title="Your first coached take", app="singz", anchor="bosstake-mic",
         what="Have one take scored.", why="Find out where you actually are."),
    dict(id="first-collab", scope=ONCE, target=1, energy=500, count=_collabs_funded,
         title="Your first funded collab", app="collabz", anchor="collabz-deals",
         what="Get one deal funded.", why="This is the point of the whole thing."),
    dict(id="reach-verified", scope=ONCE, target=1, energy=150, count=_reach_verified,
         title="Switch on passive Energy", app="social", anchor="social-feed",
         what="Get one social source verified. Reach is the median across your "
              "verified accounts, so one is enough to start the clock.",
         why="Reach is what pays Energy every hour. This is the quest that "
             "means you need quests less."),
]

BY_ID = {q["id"]: q for q in QUESTS}


def _posts_or_zero(user):
    from .models import Post
    return Post.objects.filter(author=user).count()


# ---- periods ------------------------------------------------------------

def period_key(scope, when=None):
    """What "this one" means for a scope. A claim is unique per (quest, period),
    so the rollover IS the reset — nothing has to be cleared on a schedule."""
    now = when or timezone.now()
    if scope == DAILY:
        return now.strftime("%Y-%m-%d")
    if scope == WEEKLY:
        y, w, _ = now.isocalendar()
        return f"{y}-W{w:02d}"
    return "once"


def period_start(scope, when=None):
    """When the current period began — the window progress is measured over."""
    now = when or timezone.now()
    if scope == DAILY:
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if scope == WEEKLY:
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return midnight - timedelta(days=now.weekday())
    return None                      # milestones count all of time


# ---- the board, and what claiming one actually does ---------------------

def streak_days(user, when=None):
    """Consecutive days ending today on which at least one daily quest was
    claimed. Today not counting yet is deliberate — a streak is a record of
    days you turned up, and today is not over."""
    from .models import QuestClaim

    daily_ids = [q["id"] for q in QUESTS if q["scope"] == DAILY]
    days = set(QuestClaim.objects
               .filter(user=user, quest_id__in=daily_ids)
               .values_list("period", flat=True))
    now = when or timezone.now()
    n, cursor = 0, now
    while True:
        key = cursor.strftime("%Y-%m-%d")
        if key not in days:
            # Today being empty doesn't end a streak that yesterday holds up.
            if cursor.date() == now.date():
                cursor -= timedelta(days=1)
                continue
            break
        n += 1
        cursor -= timedelta(days=1)
    return n


def streak_multiplier(days):
    for need, mult in STREAK_STEPS:
        if days >= need:
            return mult
    return 1.0


def minted_today(user, when=None):
    from .models import QuestClaim
    since = (when or timezone.now()).replace(hour=0, minute=0, second=0, microsecond=0)
    return sum(QuestClaim.objects.filter(user=user, created_at__gte=since)
               .values_list("energy", flat=True))


def reward_for(quest, streak):
    """What this quest pays THIS member right now, streak included.

    Only dailies take the multiplier: a weekly or a milestone pays the number
    printed on it, because a one-off that quietly pays double to whoever kept a
    streak is a price that changes behind the member's back.
    """
    if quest["scope"] != DAILY:
        return quest["energy"]
    return int(quest["energy"] * streak_multiplier(streak))


def board(user, when=None):
    """Every quest, with progress, what it pays, and whether it can be claimed.

    The reward is on the row BEFORE it is earned — the same rule the rest of
    the app follows about never letting somebody find out by pressing.
    """
    from .models import QuestClaim

    now = when or timezone.now()
    streak = streak_days(user, now)
    minted = minted_today(user, now)
    claimed = {(c.quest_id, c.period) for c in
               QuestClaim.objects.filter(user=user).only("quest_id", "period")}

    rows, headroom = [], max(0, DAILY_ENERGY_CAP - minted)
    for q in QUESTS:
        period = period_key(q["scope"], now)
        since = period_start(q["scope"], now)
        done = min(q["count"](user, since), q["target"])
        is_claimed = (q["id"], period) in claimed
        pays = reward_for(q, streak)
        # The cap can't take a reward away, only defer it to tomorrow — so say
        # that rather than showing a claimable quest whose button refuses.
        capped = (not is_claimed) and done >= q["target"] and pays > headroom
        rows.append({
            "id": q["id"], "scope": q["scope"], "title": q["title"],
            "what": q["what"], "why": q["why"],
            "done": done, "target": q["target"],
            "energy": pays, "base_energy": q["energy"],
            "claimed": is_claimed,
            "claimable": (not is_claimed) and done >= q["target"] and not capped,
            "capped": capped,
            "app": q["app"], "target_anchor": q["anchor"],
            "period": period,
        })
    return {
        "quests": rows,
        "streak_days": streak,
        "streak_multiplier": streak_multiplier(streak),
        "next_streak_step": next((n for n, _ in reversed(STREAK_STEPS) if n > streak), None),
        "minted_today": minted,
        "daily_cap": DAILY_ENERGY_CAP,
        "cap_left": headroom,
        # Why any of this exists, said on the screen rather than only in here.
        "note": ("Energy regenerates from your reach — with none yet, quests are "
                 "where it comes from. Verify a reach source and it starts "
                 "arriving hourly on its own."),
    }


def claim(user, quest_id, when=None):
    """Pay a finished quest. Returns (row, error) — exactly one is None.

    Re-checks progress against the live data rather than trusting the board the
    client was holding: a board can be stale, minutes old, or edited on its way
    past. The unique constraint catches the double-press underneath.
    """
    from django.db import IntegrityError, transaction

    from .models import QuestClaim, award_energy

    q = BY_ID.get(str(quest_id))
    if not q:
        return None, ("no such quest", 404)

    now = when or timezone.now()
    period = period_key(q["scope"], now)
    done = q["count"](user, period_start(q["scope"], now))
    if done < q["target"]:
        return None, (f"Not finished yet — {done} of {q['target']}.", 400)

    # Already-claimed is checked BEFORE the ceiling, and the order is the whole
    # point: a member re-pressing a milestone they finished last week was being
    # told to come back tomorrow, which is an answer to a different question and
    # implies they might get paid again.
    if QuestClaim.objects.filter(user=user, quest_id=q["id"], period=period).exists():
        return None, ("Already claimed.", 409)

    streak = streak_days(user, now)
    pays = reward_for(q, streak)
    minted = minted_today(user, now)
    if minted + pays > DAILY_ENERGY_CAP:
        return None, (
            f"That's {DAILY_ENERGY_CAP} ⚡ of quests today, which is the daily "
            "ceiling. This one keeps until tomorrow — nothing is lost.", 429)

    try:
        # In its own atomic block: an IntegrityError poisons the surrounding
        # transaction, so without the savepoint the recovery below cannot run a
        # single query afterwards. The check above handles the ordinary repeat;
        # this is the two-presses-at-once race.
        with transaction.atomic():
            QuestClaim.objects.create(user=user, quest_id=q["id"], period=period,
                                      energy=pays)
    except IntegrityError:
        return None, ("Already claimed.", 409)

    # Through award_energy so it lands in LogZ with its reason — a balance that
    # moves for an unexplained reason is the thing LogZ exists to prevent.
    award_energy(user, pays, note=f"QuestZ: {q['title']}")
    return {"id": q["id"], "energy": pays, "streak_days": streak,
            "multiplier": streak_multiplier(streak)}, None


# ---- API ----------------------------------------------------------------

from rest_framework import status                                  # noqa: E402
from rest_framework.permissions import IsAuthenticated             # noqa: E402
from rest_framework.response import Response                       # noqa: E402
from rest_framework.views import APIView                           # noqa: E402


class QuestBoardView(APIView):
    """GET /api/economy/questz/ — every quest, its progress, and what it pays."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(board(request.user))


class QuestClaimView(APIView):
    """POST /api/economy/questz/<quest_id>/claim/ — take the Energy."""

    permission_classes = [IsAuthenticated]

    def post(self, request, quest_id):
        row, err = claim(request.user, quest_id)
        if err:
            detail, code = err
            return Response({"detail": detail}, status=code)
        from .models import wallet_for
        return Response({**row, "energy_balance": wallet_for(request.user).energy,
                         **board(request.user)})
