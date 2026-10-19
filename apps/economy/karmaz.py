"""What rating, voting, commenting and answering a stranger are worth.

Four things members do all day, and until now exactly one of them paid.
Rating has paid +1 ⚡ against a 20/day cap since it shipped; a vote, a comment
and a message paid nothing at all — which on a platform whose whole economy
runs on ⚡ means the three most common acts in the app were the three that
bought you nothing.

THE PROBLEM WITH PAYING FOR ENGAGEMENT, STATED FIRST
-----------------------------------------------------
Every one of these is a faucet if you get it wrong, and the wrong version of
each is the obvious version:

* **Pay per comment** and you are paying for "🔥🔥🔥". The blueprint already
  knew this and wrote the fix into the global rules: *"every comment on
  another user's post gives energy equal to its median rating 1 hour after
  it's posted."* The comment has to be judged by other people, and the delay
  is what stops it being claimed by typing.
* **Pay per message** and two accounts mint forever. This is the purest faucet
  available in this app, and the only safe version pays on the OTHER person's
  act.
* **Pay more for an upvote than a downvote** and you have bought yourself a
  platform where everything is wonderful. Pay for upvotes only and the signal
  is worthless within a week.

So the rules below are arranged so that **in every case, the thing that
triggers the payout is done by somebody other than the person being paid.**
That is the same structural property that makes Lilith's sponsorship
unfarmable, and it is the only one that survives contact with somebody who
wants the currency more than they want the platform.

WHAT IS DELIBERATELY NOT PAID
------------------------------
* Sending a message. Nothing. See above.
* Commenting on your OWN post. The blueprint says "on another user's post",
  and paying somebody to talk to themselves is the faucet with no disguise.
* Casting a vote on your own comment, or on one by an account DupeZ strongly
  links to yours.
* A downvoted comment. It earns zero — never negative. Taking ⚡ off somebody
  for an unpopular opinion turns a quality signal into a punishment and
  teaches people to say nothing.

VOTES REUSE `Reaction`, THEY DO NOT GET THEIR OWN TABLE
--------------------------------------------------------
`Reaction(user, item_id, value=±1)` has been the platform's up/down since it
shipped, keyed by an opaque `item_id` ("post:12"). Comments simply had no key
in that space and nothing counted them. They use "comment:<id>" now. A second
vote model would have been a second answer to "how many people liked this",
which is the drift this codebase keeps writing itself notes about.
"""
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import (EngagementPayout, Message, Reaction, SocialComment,
                     award_energy)

# ------------------------------------------------------------- the numbers
#
# All anchored to the one that already exists: a rating pays 1 ⚡ against a
# 20/day cap (`models.RATING_REWARD_ENERGY`). Nothing here is invented from
# nothing — each is argued against that.

# A vote is one tap; a rating is a considered 1-10. Same coin, half the
# ceiling, because it is half the thought.
VOTE_ENERGY = 1
VOTE_DAILY_CAP = 10

# **An upvote and a downvote pay exactly the same, and this is load-bearing.**
# If up paid more, the app would be buying its own praise. If only up paid, the
# down half of the signal would go unused and the score would mean nothing.
# Paying identically is what keeps a vote about the comment rather than about
# the coin. `test_karmaz` pins it.

# The blueprint's rule: a comment earns what other people thought of it, an
# hour after it lands. Net karma is that judgement — there is no separate
# comment rating and inventing one would be a second thing to collect.
KARMA_SETTLE_HOURS = 1
# One ⚡ per net upvote, so it is the community's number rather than ours.
KARMA_ENERGY_PER_NET = 1
# A ceiling anyway: one comment that goes round the platform should not be a
# month's income, and without this the reward for a viral comment is unbounded
# in a currency we mint.
KARMA_ENERGY_MAX = 10
# Below this it pays nothing. One upvote from one friend is not a judgement.
KARMA_MIN_NET = 2

# Answering somebody who has never messaged you before. The scarcer and more
# pro-social of the two acts — most cold messages go unanswered — and the one
# that cannot be spammed, because you can only reply to what you receive.
COLD_REPLY_ENERGY = 10
# And the sender, once somebody actually answers. Deliberately the SMALLER
# half: making the cold message the better-paid side would be paying for
# outbound volume, which is a word for spam.
COLD_SENT_ENERGY = 5
COLD_DAILY_CAP = 5


def rewards():
    """Every number above, published so a screen can state it before the act.

    The gain half of the cost/gain rule. None of these cost a member anything,
    which is exactly why they get forgotten — a reward found out by accident is
    a coincidence, and a coincidence changes nobody's behaviour.
    """
    from .models import RATING_REWARD_DAILY_CAP, RATING_REWARD_ENERGY
    return [
        {"key": "rate", "what": "Rate a post, a skill or a member",
         "energy": RATING_REWARD_ENERGY, "cap": f"{RATING_REWARD_DAILY_CAP} a day",
         "why": "Rating is how everything on here gets its number. It has always paid."},
        {"key": "vote", "what": "Vote a comment up or down",
         "energy": VOTE_ENERGY, "cap": f"{VOTE_DAILY_CAP} a day",
         "why": "Up and down pay the same — otherwise the app is buying its own praise."},
        {"key": "comment_karma",
         "what": "Your comment on somebody else's post earns net upvotes",
         "energy": KARMA_ENERGY_PER_NET, "per": "net upvote",
         "cap": f"up to {KARMA_ENERGY_MAX} ⚡, settled {KARMA_SETTLE_HOURS}h after you post it",
         "why": f"Other people decide, and not for {KARMA_SETTLE_HOURS} hour(s). "
                f"Needs {KARMA_MIN_NET}+ net — one upvote from one friend is not a judgement."},
        {"key": "cold_reply", "what": "Reply to somebody who has never messaged you",
         "energy": COLD_REPLY_ENERGY, "cap": f"{COLD_DAILY_CAP} a day, once per person",
         "why": "Most cold messages go unanswered. Answering one is the scarce thing."},
        {"key": "cold_sent", "what": "Somebody new answers a message you sent",
         "energy": COLD_SENT_ENERGY, "cap": f"{COLD_DAILY_CAP} a day, once per person",
         "why": "Paid on THEIR reply, never on your send — and the smaller half, "
                "because paying for outbound volume is paying for spam."},
    ]


# ---------------------------------------------------------------- plumbing

def _paid_today(user, kind):
    since = timezone.now() - timedelta(hours=24)
    return EngagementPayout.objects.filter(user=user, kind=kind,
                                           created_at__gte=since).count()


def _pay(user, kind, ref, energy):
    """Move the ⚡ and write the row, once. Returns what landed, or 0.

    The write comes FIRST and its IntegrityError is the once-per guard: two
    requests racing the same reward both pass a `filter(...).exists()` check
    and only one survives a unique constraint. Paying first and recording
    afterwards would pay both.

    **The savepoint is not optional.** An IntegrityError raised inside an outer
    transaction — which is every request under ATOMIC_REQUESTS, and every test
    — marks that transaction broken, and the next query anywhere raises
    TransactionManagementError. So the expected collision would take down the
    whole request it was supposed to quietly absorb. `atomic()` here rolls back
    only this insert and leaves everything around it usable.
    """
    if not user or energy <= 0:
        return 0
    try:
        with transaction.atomic():
            EngagementPayout.objects.create(user=user, kind=kind, ref=str(ref)[:64],
                                            energy=energy)
    except IntegrityError:
        return 0                     # already paid for this exact thing
    award_energy(user, energy, f"{kind.replace('_', ' ')}",
                 app_key="postz", target=str(ref)[:64])
    return energy


def _same_person(a, b):
    """DupeZ's answer, not ours. It already decides what one person is, and a
    second definition here would disagree with it inside a year."""
    from .dupez import has_strong, signals_between
    try:
        return has_strong(signals_between(a, b))
    except Exception:
        # A failure in the duplicate check must not stop the platform paying
        # legitimate members, and must not pay a duplicate either — so it
        # refuses. The safe direction for a faucet is closed.
        return True


# ------------------------------------------------------------------ votes

def comment_key(comment_id):
    """The `Reaction.item_id` a comment's votes live under."""
    return f"comment:{comment_id}"


def karma_for(comment_id):
    """(up, down, net) for one comment, off the shared Reaction table."""
    rows = Reaction.objects.filter(item_id=comment_key(comment_id))
    up = rows.filter(value=1).count()
    down = rows.filter(value=-1).count()
    return up, down, up - down


def vote_on_comment(voter, comment, value):
    """Cast, change or clear a vote. Returns what it paid and the new karma.

    Clearing a vote does NOT claw the ⚡ back. Two reasons: the member did the
    work of forming a judgement, and a reward that can be taken away by
    changing your mind is a reason not to change your mind. The unique
    constraint means it cannot be collected twice either way.
    """
    value = max(-1, min(1, int(value or 0)))
    key = comment_key(comment.pk)
    if value == 0:
        Reaction.objects.filter(user=voter, item_id=key).delete()
        up, down, net = karma_for(comment.pk)
        return {"value": 0, "energy": 0, "up": up, "down": down, "net": net}

    Reaction.objects.update_or_create(user=voter, item_id=key,
                                      defaults={"value": value})
    energy = 0
    capped = False
    # Voting on your own comment pays nothing, and neither does voting on one
    # by an account tied to yours. Both are the same person clapping.
    if voter.pk != comment.user_id and not _same_person(voter, comment.user):
        if _paid_today(voter, EngagementPayout.KIND_VOTE) >= VOTE_DAILY_CAP:
            capped = True
        else:
            # ref is the COMMENT, not the vote, so flipping up and down and up
            # again pays exactly once.
            energy = _pay(voter, EngagementPayout.KIND_VOTE, key, VOTE_ENERGY)
    up, down, net = karma_for(comment.pk)
    return {"value": value, "energy": energy, "capped": capped,
            "up": up, "down": down, "net": net}


# ------------------------------------------------- what a comment earns

def due(comment):
    """Is this comment old enough to settle, and not settled already?"""
    return (comment.karma_settled_at is None
            and comment.created_at is not None
            and timezone.now() >= comment.created_at + timedelta(hours=KARMA_SETTLE_HOURS))


def _decide(comment, net, post_author_id):
    """(energy, why) for one comment. No writes — so the batch path and the
    single-row path cannot disagree about what a comment is owed."""
    if post_author_id is not None and post_author_id == comment.user_id:
        # The blueprint says "on another user's post" and means it.
        return 0, "your own post"
    if net < KARMA_MIN_NET:
        return 0, f"needed {KARMA_MIN_NET} net upvotes, had {net}"
    return min(net * KARMA_ENERGY_PER_NET, KARMA_ENERGY_MAX), ""


def _stamp(comment, energy):
    """Mark it settled. Stamped even when it paid nothing — a settle of 0 is a
    settled comment, and leaving it null would make every read re-count the
    votes on every old comment in the feed, for ever."""
    comment.karma_settled_at = timezone.now()
    comment.karma_energy = energy


def settle_comment(comment, *, post_author_id=None, net=None):
    """Pay a comment's author what the votes said, an hour on. Once, ever.

    The single-row path, used by the sweep. `settle_visible` is the one the
    app calls on a read, and it batches.
    """
    if not due(comment):
        return None
    if net is None:
        _, _, net = karma_for(comment.pk)
    energy, reason = _decide(comment, net, post_author_id)
    if energy:
        energy = _pay(comment.user, EngagementPayout.KIND_COMMENT_KARMA,
                      f"comment:{comment.pk}", energy)
    _stamp(comment, energy)
    comment.save(update_fields=["karma_settled_at", "karma_energy"])
    return {"energy": energy, "net": net, "why": reason}


def settle_visible(comments, *, post_author_id=None):
    """Settle whichever of these are due. Best-effort, and never the reason a
    feed fails to render: a reward that did not land is recoverable by the
    sweep, and a 500 on a comment list is not.

    **Reading a dormant thread costs the same whether it holds two comments or
    a hundred.** The karma is counted in one query and the stamps go back in
    one `bulk_update` — a per-row count AND a per-row save were both in the
    first version of this, and the query-count test caught the save after the
    count was already fixed. Only a comment that actually EARNS costs extra
    queries, which is currency moving and cannot be batched away.
    """
    ready = [c for c in comments if c is not None and due(c)]
    if not ready:
        return 0
    nets = karma_map([c.pk for c in ready])
    total = 0
    for c in ready:
        try:
            energy, _ = _decide(c, nets.get(c.pk, {}).get("net", 0), post_author_id)
            if energy:
                energy = _pay(c.user, EngagementPayout.KIND_COMMENT_KARMA,
                              f"comment:{c.pk}", energy)
            _stamp(c, energy)
            total += energy
        except Exception:
            _stamp(c, 0)
            continue
    try:
        SocialComment.objects.bulk_update(ready, ["karma_settled_at", "karma_energy"])
    except Exception:
        pass
    return total


# --------------------------------------------------- answering a stranger

def _pair_ref(a, b):
    """Stable for the pair regardless of who is asking, so "once per person"
    is once per PAIR rather than once per direction."""
    lo, hi = sorted([a.pk, b.pk])
    return f"pair:{lo}:{hi}"


def cold_reply(sender, recipient):
    """`sender` is replying to `recipient`. Pay both if this is the answer to a
    genuine cold approach.

    Everything about it is read from the two people's message history rather
    than passed in, because a caller that decided "this is a first reply" would
    be the second place that rule lives — and it is the rule the whole payout
    rests on.
    """
    if sender.pk == recipient.pk:
        return None
    # They messaged us first, and we have never messaged them: this is a reply
    # to a cold approach, which is the only shape that pays.
    they_started = Message.objects.filter(sender=recipient, recipient=sender).exists()
    we_have_spoken = Message.objects.filter(sender=sender, recipient=recipient).exists()
    if not they_started or we_have_spoken:
        return None
    if _same_person(sender, recipient):
        return None

    ref = _pair_ref(sender, recipient)
    got = {"reply": 0, "sent": 0, "capped": False}
    if _paid_today(sender, EngagementPayout.KIND_COLD_REPLY) >= COLD_DAILY_CAP:
        got["capped"] = True
    else:
        got["reply"] = _pay(sender, EngagementPayout.KIND_COLD_REPLY, ref, COLD_REPLY_ENERGY)
    # The other half. Their cap is their own — one member's busy day must not
    # be the reason somebody else goes unpaid for being answered.
    if _paid_today(recipient, EngagementPayout.KIND_COLD_SENT) < COLD_DAILY_CAP:
        got["sent"] = _pay(recipient, EngagementPayout.KIND_COLD_SENT, ref, COLD_SENT_ENERGY)
    return got


def karma_map(comment_ids):
    """{comment_id: {up, down, net}} for a whole list, in one query.

    The per-comment version of this on a hundred-comment feed is two hundred
    counts. The feed already has a query-count test for exactly this shape of
    mistake, and a comment list is the same shape.
    """
    from django.db.models import Count, Q
    if not comment_ids:
        return {}
    keys = {comment_key(i): i for i in comment_ids}
    out = {i: {"up": 0, "down": 0, "net": 0} for i in comment_ids}
    rows = (Reaction.objects.filter(item_id__in=list(keys))
            .values("item_id")
            .annotate(up=Count("pk", filter=Q(value=1)),
                      down=Count("pk", filter=Q(value=-1))))
    for r in rows:
        cid = keys.get(r["item_id"])
        if cid is not None:
            out[cid] = {"up": r["up"], "down": r["down"], "net": r["up"] - r["down"]}
    return out


def my_votes(user, comment_ids):
    """{comment_id: ±1} for this member, scoped to the comments on screen.

    Scoped rather than "every comment vote they have ever cast": the unscoped
    version reads the member's whole voting history to render one post, and
    grows for ever with the account.
    """
    if not user or not getattr(user, "is_authenticated", False) or not comment_ids:
        return {}
    keys = {comment_key(i): i for i in comment_ids}
    return {keys[r.item_id]: r.value
            for r in Reaction.objects.filter(user=user, item_id__in=list(keys))
            if r.item_id in keys}


# ----------------------------------------------------------------- the API

from rest_framework.permissions import IsAuthenticated       # noqa: E402
from rest_framework.response import Response                  # noqa: E402
from rest_framework.views import APIView                      # noqa: E402


class KarmaRewardsView(APIView):
    """GET /api/economy/karmaz/ — what these four acts pay, and how much of
    today's allowance is left.

    Published so a screen can state the gain BEFORE the button, which is the
    half of the cost/gain rule that gets forgotten: nothing here costs a member
    anything, so there is no bill to discover — only a reward to miss.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import RATING_REWARD_DAILY_CAP, Transaction, RATING_NOTE
        rated = Transaction.objects.filter(
            user=request.user, resource=Transaction.RES_ENERGY,
            note__startswith=RATING_NOTE,
            created_at__gte=timezone.now() - timedelta(hours=24)).count()
        return Response({
            "rewards": rewards(),
            "today": {
                "rated": rated, "rate_cap": RATING_REWARD_DAILY_CAP,
                "voted": _paid_today(request.user, EngagementPayout.KIND_VOTE),
                "vote_cap": VOTE_DAILY_CAP,
                "replied": _paid_today(request.user, EngagementPayout.KIND_COLD_REPLY),
                "cold_cap": COLD_DAILY_CAP,
            },
            "settle_hours": KARMA_SETTLE_HOURS,
            "karma_min_net": KARMA_MIN_NET,
        })
