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
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Block, CollabDeal, Follow, Group, GroupMember, blocked_user_ids

User = get_user_model()

# The four kinds that are answered elsewhere. They always exist — there is
# nothing to create, because the thing they read from is always there.
DERIVED = ("friends", "fans", "partners", "blocked")

# PartnerZ: a FriendZ you have actually finished work with, this many times.
#
# Corey's rule, and it is the strongest one on this tab. "Intend to work with
# frequently" was a checkbox — you could type anybody in, so the list said what
# you hoped rather than what you did. Three RELEASED collabs is a thing neither
# of you can fake alone: the other person had to agree three times, and escrow
# had to pay out three times. That is the substance rule applied to a
# friendship — could a member get a good one without getting good? Not here.
#
# FriendZ is the gate because Corey named it: partners come from friends. It
# also means the two of you follow each other, so a partnership is never a
# surprise to one side.
PARTNER_COLLABS = 3


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


def collab_counts(user):
    """{username: finished collabs with this member}, in one query.

    RELEASED only. A draft nobody funded is an intention and a funded one that
    never paid out is an argument; a released deal is escrow that actually
    settled, which is the only point at which two people demonstrably finished
    something together.

    Counted in Python rather than with `participants__contains`, which is
    Postgres-only while the suite runs on SQLite — the same gap
    `lilith_taskz._in_released_deal` documents. Bounded to deals touched since
    this member joined, because a deal released before they existed cannot
    name them.
    """
    me = user.username
    counts = {}
    rows = (CollabDeal.objects
            .filter(status=CollabDeal.STATUS_RELEASED, updated_at__gte=user.date_joined)
            .values("initiator__username", "participants")[:2000])
    for row in rows:
        names = {e.get("username") for e in (row["participants"] or [])
                 if isinstance(e, dict) and e.get("username")}
        if row["initiator__username"]:
            names.add(row["initiator__username"])
        if me not in names:
            continue
        for other in names - {me}:
            counts[other] = counts.get(other, 0) + 1
    return counts


def partners_of(user, friends_ids=None):
    """FriendZ who have finished `PARTNER_COLLABS` collabs with this member.

    Derived rather than curated, so the list says what the two of you DID
    rather than what one of you hoped for.
    """
    if friends_ids is None:
        friends_ids, _ = _friends_and_fans(user)
    if not friends_ids:
        return set()
    counts = collab_counts(user)
    earned = {n for n, c in counts.items() if c >= PARTNER_COLLABS}
    if not earned:
        return set()
    return set(User.objects.filter(id__in=friends_ids, username__in=earned)
               .values_list("id", flat=True))


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
         # The rule, on the list, because a list you cannot edit has to say
         # what puts somebody on it or it reads as broken.
         "note": f"FriendZ you've finished {PARTNER_COLLABS} collabs with. "
                 f"Earned, not added — it says what you did, not who you meant to work with."},
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
        # FriendZ (they follow you back) and escrow has to have settled between
        # you three times. Saying how it is earned beats a refusal.
        got = collab_counts(user).get(other.username, 0)
        return ({"detail": f"PartnerZ is earned, not added. You and @{other.username} have "
                           f"finished {got} collab{'' if got == 1 else 's'} — "
                           f"{PARTNER_COLLABS} released collabs between FriendZ and they land "
                           f"here on their own."},
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
