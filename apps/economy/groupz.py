"""GroupZ — FriendZ, FanZ, Partners, Custom and Blocked.

The blueprint: "Posts that combine other users into editable groups LOCAL TO
THE USER making the groups." Local is the whole design. A group is a note its
owner made about somebody, not a relationship those two people are in — nobody
is told they were added, nobody can see which of your lists they are on, and
there is nothing to accept.

MOST OF THIS ALREADY EXISTED, WHICH IS WHY IT HAS SO FEW ROWS
--------------------------------------------------------------
`GroupZ.jsx` has been calling `/api/groupz/` since it was written and getting a
404, so the tab sat on a spinner for ever. The obvious way to fix that is five
tables. It would also have been wrong, because three of the five kinds are
things this platform already answers:

* **FriendZ and FanZ are `Follow`.** Its own docstring says it: "mutual follows
  are friends; a one-way follower is a fan of the followed user", and
  `follow_counts` already computes exactly those two sets. A stored FriendZ
  row would drift from the follow graph within a week, and then the tab and
  the profile would disagree about who your friends are.
* **Blocked is `Block`**, which `messages_view`, `battlez`, `playlistz`,
  `social` and `moderation` already enforce. This is the one where a second
  store is not untidy but dangerous: a member reads "Blocked" on this tab,
  and the person they blocked keeps DMing them because MessageZ never heard
  about it.

So only Partners and Custom get rows. The other three are served from the
source that already decides them, and writing to them writes THERE.

THE ONE REFUSAL
---------------
**You cannot add somebody to your own FanZ.** Being a fan is their act, not
yours, and a member who can type their own fan list has a follower count that
means nothing — the substance rule with a social graph attached. `add` on FanZ
says so rather than failing quietly.

FriendZ is the softer version of the same thing: adding somebody there follows
them, which is all you can do on your own. Whether that makes you friends is up
to them, and the response says which of the two just happened rather than
claiming a friendship nobody agreed to.
"""
from django.contrib.auth import get_user_model
from django.db.models import F, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (Block, Follow, Group, GroupMember, Partnership,
                     blocked_user_ids)

User = get_user_model()

# The four kinds that are answered elsewhere. They always exist — there is
# nothing to create, because the thing they read from is always there.
DERIVED = ("friends", "fans", "partners", "blocked")

# PartnerZ: a FriendZ you have actually finished work with, this many times.
#
# Corey's rule, and it is the strongest one on this tab. "Intend to work with
# frequently" was a checkbox — you could type anybody in, so the list said what
# you hoped rather than what you did. A finished work is a thing neither of you
# can fake alone: the other person had to agree, and something outside the two
# of you had to settle.
#
# FriendZ is the gate because Corey named it: partners come from friends. It
# also means the two of you follow each other, so a partnership is never a
# surprise to one side.
#
# TWO KINDS OF WORK COUNT, and each one has a settlement a pair of accounts
# cannot manufacture between themselves:
#
# * A RELEASED CollabZ deal THAT HELD SOMETHING. Escrow paid out, and it had
#   money, SpinaZ or a stake in it. A zero-value deal was not excluded for
#   tidiness: `payers()` is empty when nobody pays, so `all_funded()` is
#   `all([]) == True`, one Fund call flips an empty deal to FUNDED, and
#   `maybe_auto_release` releases it on its own. Three of those cost nothing
#   and took no work, which is the substance rule's failure case with a
#   friendship attached.
# * A SETTLED BattleZ battle WITH A WINNER. A winner means at least one side
#   cleared BATTLE_MIN_RATINGS judges, so the room turned up. A battle that
#   settles as a draw is one nobody watched, and it does not count.
PARTNER_WORKS = 3

# The one thing being a PartnerZ is worth, and it is deliberately not a payout.
#
# Corey asked whether PartnerZ should earn a bonus "for upholding the economy
# by existing". The answer this codebase has to give is no: a per-day or
# per-week payout for HOLDING a status pays a fixed past achievement forever,
# which is the substance rule inverted — could a member get a good number
# without getting good? Yes: by getting good once, in one week, and then never
# again. It is also the exact shape of a farm, because the gate is passed once
# and the income never stops.
#
# So the benefit is the opposite shape: it costs nothing while the partnership
# is idle, and it only arrives when the two of them work together AGAIN. The
# test every future PartnerZ benefit has to pass is **would this be worth
# anything to somebody faking it?** Escrow speed answers no by construction —
# a faker owns both wallets, so their money reaching their own other account
# four days sooner is worth exactly zero. A 🍥 stipend answers yes.
#
# Four days rather than the floor, so Patron (7) stays the stronger badge and
# the two stack down to ESCROW_MIN_RELEASE_DAYS rather than one making the
# other pointless.
PARTNER_ESCROW_DAYS_OFF = 4


def _names(ids):
    """Usernames for a set of ids, in one query."""
    if not ids:
        return []
    return sorted(User.objects.filter(id__in=ids).values_list("username", flat=True))


def _friends_and_fans(user):
    """(friends, fans) as id sets — the same arithmetic `follow_counts` does.

    Two queries for both, because a tab that renders five groups must not cost
    five round trips per group.
    """
    following = set(Follow.objects.filter(follower=user).values_list("following_id", flat=True))
    followers = set(Follow.objects.filter(following=user).values_list("follower_id", flat=True))
    return following & followers, followers - following


def _pair(u1, u2):
    """The two ids, smallest first — a partnership is one row, never two."""
    return (u1, u2) if u1 <= u2 else (u2, u1)


def note_work(user_ids, *, collabs=0, battles=0):
    """Tally one finished work between every pair of these people.

    Called BY the thing that just settled, once, at the moment it settles.
    Swallowed by its callers: an escrow release and a battle result have to
    land whether or not this does.
    """
    ids = sorted({int(i) for i in user_ids if i})
    for n, first in enumerate(ids):
        for second in ids[n + 1:]:
            a, b = _pair(first, second)
            row, _ = Partnership.objects.get_or_create(a_id=a, b_id=b)
            Partnership.objects.filter(pk=row.pk).update(
                collabs=F("collabs") + collabs,
                battles=F("battles") + battles,
                updated_at=timezone.now())


def works_with(user):
    """{username: {"collabs": n, "battles": n, "works": n}} — one query.

    Everybody this member has finished anything with, whether or not they are
    a FriendZ. The refusal on the PartnerZ tab reads this to say how far along
    the two of you actually are, which beats "you can't do that".
    """
    rows = (Partnership.objects
            .filter(Q(a=user) | Q(b=user))
            .select_related("a", "b"))
    out = {}
    for r in rows:
        other = r.b if r.a_id == user.pk else r.a
        out[other.username] = {"collabs": r.collabs, "battles": r.battles,
                               "works": r.works}
    return out


def partner_ids(user):
    """Ids of everybody at or over PARTNER_WORKS with this member — one query.

    FriendZ is NOT applied here. This is the work half of the rule on its own,
    because the escrow benefit reads it for people who are not on each other's
    tab and `partners_of` is the place the friendship gate belongs.
    """
    rows = (Partnership.objects
            .filter(Q(a=user) | Q(b=user))
            .annotate(works=F("collabs") + F("battles"))
            .filter(works__gte=PARTNER_WORKS)
            .values_list("a_id", "b_id"))
    return {b if a == user.pk else a for a, b in rows}


def almost_partners(user):
    """Who this member has started work with but not yet finished three of.

    The counter has been on `Partnership` since the tally replaced the scan,
    and every reader of it filters `works__gte=PARTNER_WORKS` — so a member one
    deal away from a real benefit was indistinguishable from one who had never
    worked with anybody. The number existed; nothing served it.

    That is the gain half of the cost/gain rule going missing. A status you
    only hear about once you already hold it cannot change what anybody does,
    which is the whole job of having one — the same reason the ZodiacZ panel
    publishes all twenty-four bonuses instead of only the one you earned.

    Deliberately NOT gated on FriendZ, matching `partner_ids`: the escrow
    benefit does not ask whether you follow each other, so neither does the
    sentence telling you how close you are to it. Sorted by who is closest,
    because the useful row is the one that needs one more.
    """
    # Annotated as `tally`, not `works`: `works` is a property on the model, and
    # an annotation of that name blows up with "property has no setter" the
    # moment the queryset builds an instance. `partner_ids` only gets away with
    # it because `.values_list` never instantiates one.
    rows = (Partnership.objects
            .filter(Q(a=user) | Q(b=user))
            .annotate(tally=F("collabs") + F("battles"))
            .filter(tally__gt=0, tally__lt=PARTNER_WORKS)
            .select_related("a", "b"))
    out = [{
        "username": (r.b if r.a_id == user.pk else r.a).username,
        "works": r.collabs + r.battles,
        "needs": PARTNER_WORKS - (r.collabs + r.battles),
    } for r in rows]
    return sorted(out, key=lambda x: (x["needs"], x["username"]))


def partners_of(user, friends_ids=None):
    """FriendZ who have finished PARTNER_WORKS works with this member.

    Derived rather than curated, so the list says what the two of you DID
    rather than what one of you hoped for.
    """
    if friends_ids is None:
        friends_ids, _ = _friends_and_fans(user)
    if not friends_ids:
        return set()
    return set(friends_ids) & partner_ids(user)


def partner_pairs_among(user_ids):
    """{frozenset({id, id}), ...} for every partnered pair in this set.

    One query for a whole deal, so `collab.escrow_release_days` can ask "is
    every payer a partner of every payee" without a scan per card.
    """
    ids = {int(i) for i in user_ids if i}
    if len(ids) < 2:
        return set()
    rows = (Partnership.objects
            .filter(a_id__in=ids, b_id__in=ids)
            .annotate(works=F("collabs") + F("battles"))
            .filter(works__gte=PARTNER_WORKS)
            .values_list("a_id", "b_id"))
    return {frozenset((a, b)) for a, b in rows}


def board(user):
    """Every group this member has, in the order the tab renders them."""
    friends, fans = _friends_and_fans(user)
    # Only who THEY blocked. `blocked_user_ids` also returns people who blocked
    # them, which is right for hiding content and wrong for a list somebody is
    # meant to edit — you cannot unblock somebody who blocked you.
    blocked = set(Block.objects.filter(blocker=user).values_list("blocked_id", flat=True))

    partners = partners_of(user, friends)
    rows = [
        {"id": "friends", "kind": "friends", "title": "", "derived": True,
         "members": _names(friends),
         "note": "Mutual follows. Follow somebody who follows you and they land here."},
        {"id": "fans", "kind": "fans", "title": "", "derived": True,
         "members": _names(fans),
         "note": "People who follow you and you don't follow back. Theirs to decide, not yours."},
        {"id": "partners", "kind": "partners", "title": "", "derived": True,
         "members": _names(partners),
         # Added BESIDE `members`, never folded into it: the client reading
         # this is in the other repo and the two deploy independently, so an
         # endpoint may grow a key ahead of its client and may never lose one.
         # An older build renders the list it always did and ignores this.
         "almost": almost_partners(user),
         # The rule, on the list, because a list you cannot edit has to say
         # what puts somebody on it or it reads as broken.
         # The rule, plus what it is worth, because a list you cannot edit has
         # to say what puts somebody on it AND why you'd want them there.
         "note": f"FriendZ you've finished {PARTNER_WORKS} works with — a CollabZ deal "
                 f"that paid out, or a battle the room decided. Earned, not added. "
                 f"Escrow between PartnerZ releases {PARTNER_ESCROW_DAYS_OFF} days sooner."},
    ]

    owned = list(Group.objects.filter(owner=user).prefetch_related("memberships__member"))
    for g in owned:
        rows.append({
            "id": str(g.pk), "kind": g.kind, "title": g.title, "derived": False,
            "members": sorted(m.member.username for m in g.memberships.all()),
            "note": "",
        })

    rows.append({"id": "blocked", "kind": "blocked", "title": "", "derived": True,
                 "members": _names(blocked),
                 "note": "They can't message you, enter your battles, or see your playlists."})
    return rows


def _target(username):
    return User.objects.filter(username__iexact=(username or "").strip()).first()


def _own_group(user, gid):
    try:
        return Group.objects.filter(owner=user, pk=int(gid)).first()
    except (TypeError, ValueError):
        return None


def change(user, gid, action, username):
    """Add or remove somebody. Returns (payload, http_status).

    Every branch goes to the store that actually decides the thing, so this
    function is mostly a router — which is the point.
    """
    other = _target(username)
    if not other:
        return {"detail": f"No member called @{username}."}, status.HTTP_404_NOT_FOUND
    if other.pk == user.pk:
        return {"detail": "You can't put yourself in your own group."}, status.HTTP_400_BAD_REQUEST
    adding = action == "add"

    if gid == "partners":
        # Neither half of this is yours to type: the other person has to be a
        # FriendZ (they follow you back) and something has to have SETTLED
        # between you three times. Saying how far along you are beats a
        # refusal — the number is the whole answer to "why aren't they here".
        got = works_with(user).get(other.username) or {}
        done = int(got.get("works") or 0)
        return ({"detail": f"PartnerZ is earned, not added. You and @{other.username} have "
                           f"finished {done} work{'' if done == 1 else 's'} together "
                           f"({int(got.get('collabs') or 0)} paid-out collabs, "
                           f"{int(got.get('battles') or 0)} decided battles) — "
                           f"{PARTNER_WORKS} between FriendZ and they land here on their own."},
                status.HTTP_400_BAD_REQUEST)

    if gid == "fans":
        # The one refusal. A member who can type their own fan list has a
        # follower count that means nothing.
        return ({"detail": "FanZ isn't a list you can edit — somebody becomes a fan by "
                           "following you. Add them to FriendZ to follow them back."},
                status.HTTP_400_BAD_REQUEST)

    if gid == "friends":
        if adding:
            if other.pk in blocked_user_ids(user):
                return {"detail": "You've blocked each other."}, status.HTTP_403_FORBIDDEN
            Follow.objects.get_or_create(follower=user, following=other)
            mutual = Follow.objects.filter(follower=other, following=user).exists()
            # Says which of the two actually happened. Claiming a friendship
            # the other person has not agreed to would be the fan problem
            # wearing a nicer word.
            return ({"detail": f"You're friends with @{other.username}." if mutual else
                     f"Following @{other.username}. They're in FriendZ once they follow back."},
                    status.HTTP_200_OK)
        Follow.objects.filter(follower=user, following=other).delete()
        return {"detail": f"Unfollowed @{other.username}."}, status.HTTP_200_OK

    if gid == "blocked":
        if adding:
            Block.objects.get_or_create(blocker=user, blocked=other)
            # Blocking somebody you follow and leaving the follow in place is
            # the tab saying one thing and the feed doing another.
            Follow.objects.filter(follower=user, following=other).delete()
            Follow.objects.filter(follower=other, following=user).delete()
            return ({"detail": f"@{other.username} is blocked — no messages, battles or playlists."},
                    status.HTTP_200_OK)
        Block.objects.filter(blocker=user, blocked=other).delete()
        return {"detail": f"@{other.username} unblocked."}, status.HTTP_200_OK

    g = _own_group(user, gid)
    if not g:
        return {"detail": "No such group."}, status.HTTP_404_NOT_FOUND
    if adding:
        if other.pk in blocked_user_ids(user):
            return ({"detail": f"@{other.username} is blocked. Unblock them first."},
                    status.HTTP_403_FORBIDDEN)
        GroupMember.objects.get_or_create(group=g, member=other)
        return {"detail": f"@{other.username} added."}, status.HTTP_200_OK
    GroupMember.objects.filter(group=g, member=other).delete()
    return {"detail": f"@{other.username} removed."}, status.HTTP_200_OK


class GroupsView(APIView):
    """GET / POST /api/groupz/"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(board(request.user))

    def post(self, request):
        kind = str((request.data or {}).get("kind") or "").strip().lower()
        title = str((request.data or {}).get("title") or "").strip()[:120]
        if kind in DERIVED:
            # Nothing to create — these are always there, because the thing
            # they read from is always there. Answering OK rather than 400 so
            # a client that presses Create on one is not told off for asking
            # about something that already exists.
            return Response(board(request.user))
        if kind not in dict(Group.KINDS):
            return Response({"detail": "That isn't a kind of group."},
                            status=status.HTTP_400_BAD_REQUEST)
        if kind == Group.KIND_CUSTOM and not title:
            return Response({"detail": "A custom group needs a name."},
                            status=status.HTTP_400_BAD_REQUEST)
        # One Partners group, many Custom ones. Partners is a role rather than
        # a folder — "people I intend to work with frequently" is one list.
        if kind == Group.KIND_PARTNERS:
            Group.objects.get_or_create(owner=request.user, kind=kind,
                                        defaults={"title": title})
        else:
            Group.objects.create(owner=request.user, kind=kind, title=title)
        return Response(board(request.user), status=status.HTTP_201_CREATED)


class GroupMemberView(APIView):
    """POST /api/groupz/<gid>/<add|remove>/"""
    permission_classes = [IsAuthenticated]

    def post(self, request, gid, action):
        if action not in ("add", "remove"):
            return Response({"detail": "Unknown action."}, status=status.HTTP_400_BAD_REQUEST)
        body, code = change(request.user, gid, action,
                            (request.data or {}).get("username"))
        if code >= 400:
            return Response(body, status=code)
        return Response({**body, "groups": board(request.user)}, status=code)


class GroupDeleteView(APIView):
    """DELETE /api/groupz/<gid>/ — only a group the member actually owns.

    The derived three cannot be deleted, and saying so is better than a 404:
    "there is no such group" would be untrue of a list the member is looking at.
    """
    permission_classes = [IsAuthenticated]

    def delete(self, request, gid):
        if gid in DERIVED:
            return Response({"detail": "FriendZ, FanZ and Blocked aren't lists you can delete — "
                                       "they follow who you follow and who you've blocked."},
                            status=status.HTTP_400_BAD_REQUEST)
        g = _own_group(request.user, gid)
        if not g:
            return Response({"detail": "No such group."}, status=status.HTTP_404_NOT_FOUND)
        g.delete()
        return Response(board(request.user))
