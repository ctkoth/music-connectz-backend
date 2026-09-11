"""GroupZ — the people around a member, in the five shapes they come in.

The screen has shipped in the nav since before this file existed, calling
`/api/groupz/` at a backend that was never written. Every call 404'd, and
because the client's `.catch` sets a message without ever setting the list,
the tab rendered a spinner that span forever. A member reading that does not
conclude the feature is unfinished — they conclude the app is broken, which is
the failure `CLAUDE.md` names about limits and which is worse here because
nothing was even gated. It was just missing.

**Three of the five tabs are not new data.** `Follow` has kept the graph since
long before this — mutual is a friend, one-way is a fan — and `Block` has kept
the blocklist that DMs already read. So those three are READ here, live, off
the same rows `follow_counts` reads. Copying them into a GroupZ-owned table
would have been the cheaper build and a second place for each to be wrong:
two friend counts that drift apart, and — the one that actually costs
somebody — a private blocklist that the DM rule never consults, on a screen
whose own header promises "Blocked members can never DM you."

Only Partners and Custom have no graph behind them, so only those two are
stored (`MemberGroup`).

What follows from that is the part worth keeping: **a derived group cannot be
edited by hand, and says so.** You do not add a fan — somebody decides to
follow you. Offering an "add" box that always fails would be a control that
lies; each derived row carries `can_add` / `can_remove` false and a `note`
naming the thing that DOES change it, with the tab to go and do it in. That is
the cross-pollination rule applied to a read-only row: the fact, and somewhere
to take it.
"""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Block, Follow, MemberGroup, MemberGroupMember

User = get_user_model()

# The three read off the graph, and the two that are stored. Kept as one
# ordered list so the screen's tab order and the server's answer cannot drift.
KIND_FRIENDS = "friends"
KIND_FANS = "fans"
KIND_PARTNERS = MemberGroup.KIND_PARTNERS
KIND_CUSTOM = MemberGroup.KIND_CUSTOM
KIND_BLOCKED = "blocked"

# A derived group's id is its kind. There is no row to carry a number, and a
# made-up integer would be one the next request renumbered.
DERIVED = {
    KIND_FRIENDS: {
        "title": "FriendZ",
        "note": "Mutual follows. Follow somebody who follows you and they land here.",
        "tab": "social",
    },
    KIND_FANS: {
        "title": "FanZ",
        "note": "People who follow you and you don't follow back. You can't add "
                "a fan — that's their call. Follow one back and they become a friend.",
        "tab": "social",
    },
    KIND_BLOCKED: {
        "title": "Blocked",
        "note": "Blocking is the one here you change directly — and it's the "
                "same block DMs read, so a blocked member can't message you.",
        "tab": "groupz",
    },
}


def _name(u):
    return getattr(u, "username", "") or ""


def _lookup(username):
    """Resolve a typed username to a member, or (None, reason).

    The leading @ is stripped because the screen prints handles with one and
    somebody will type it back.
    """
    handle = (username or "").strip().lstrip("@")
    if not handle:
        return None, "Type a username first."
    try:
        return User.objects.get(username__iexact=handle), ""
    except User.DoesNotExist:
        return None, f"No member called @{handle}."


def _graph(user):
    """friends / fans as id sets — the SAME derivation `follow_counts` uses.

    Deliberately not imported from there: that function returns counts and
    would have to run its external-reach half to hand back two sets. Same two
    lines, one query each, and `test_groupz` pins the two against each other so
    they cannot answer different things.
    """
    following = set(Follow.objects.filter(follower=user).values_list("following_id", flat=True))
    followers = set(Follow.objects.filter(following=user).values_list("follower_id", flat=True))
    return following & followers, followers - following


def _row(gid, kind, title, members, *, editable, note="", tab=""):
    return {
        "id": gid,
        "kind": kind,
        "title": title,
        "members": members,
        # The client hides the add/remove box on a row that cannot take one.
        # A control that is always going to be refused is worse than no
        # control: it reads as the feature being broken rather than as the
        # group being something you don't edit by hand.
        "can_add": editable,
        "can_remove": editable,
        "note": note,
        "tab": tab,
    }


def groups_for(user):
    """All five, in screen order. Derived rows are always present even when
    empty — an absent row makes the client offer a "Create" button for a group
    that cannot be created."""
    friends, fans = _graph(user)
    names = dict(
        User.objects.filter(id__in=friends | fans).values_list("id", "username")
    )
    blocked = list(
        Block.objects.filter(blocker=user)
        .select_related("blocked")
        .values_list("blocked__username", flat=True)
    )

    # `title` is blank on every group whose kind already names it — the screen
    # prints the kind as the section heading, so a title that repeats it
    # renders "FriendZ" twice, one line apart. Only a custom group, where the
    # name is the one thing telling two of them apart, carries one.
    out = [
        _row(KIND_FRIENDS, KIND_FRIENDS, "",
             sorted(names[i] for i in friends if i in names),
             editable=False, note=DERIVED[KIND_FRIENDS]["note"],
             tab=DERIVED[KIND_FRIENDS]["tab"]),
        _row(KIND_FANS, KIND_FANS, "",
             sorted(names[i] for i in fans if i in names),
             editable=False, note=DERIVED[KIND_FANS]["note"],
             tab=DERIVED[KIND_FANS]["tab"]),
    ]

    # The stored two, each with its members in one pass rather than a query per
    # group — a member with ten custom groups must not cost ten round trips.
    stored = list(
        MemberGroup.objects.filter(owner=user)
        .prefetch_related("rows__user")
    )
    for g in stored:
        out.append(_row(g.id, g.kind, g.title if g.kind == KIND_CUSTOM else "",
                        sorted(_name(r.user) for r in g.rows.all()),
                        editable=True))

    out.append(_row(KIND_BLOCKED, KIND_BLOCKED, "",
                    sorted(b for b in blocked if b),
                    editable=True, note=DERIVED[KIND_BLOCKED]["note"],
                    tab=DERIVED[KIND_BLOCKED]["tab"]))
    return out


class GroupZView(APIView):
    """`GET /api/groupz/` — the five groups. `POST` — start a stored one."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(groups_for(request.user))

    def post(self, request):
        kind = str(request.data.get("kind") or "").strip().lower()
        title = str(request.data.get("title") or "").strip()[:60]

        if kind in DERIVED:
            # Not an error the member caused, so it names what the group IS
            # rather than refusing flatly.
            return Response(
                {"detail": f"{DERIVED[kind]['title']} isn't a group you create — "
                           f"{DERIVED[kind]['note'][0].lower()}{DERIVED[kind]['note'][1:]}"},
                status=status.HTTP_400_BAD_REQUEST)
        if kind not in (KIND_PARTNERS, KIND_CUSTOM):
            return Response({"detail": "Unknown group kind."},
                            status=status.HTTP_400_BAD_REQUEST)
        if kind == KIND_CUSTOM and not title:
            return Response({"detail": "Give the custom group a name."},
                            status=status.HTTP_400_BAD_REQUEST)

        # Partners is one group, not a list of them — the screen renders it as
        # a single named box and a second would have no way to be told apart.
        if kind == KIND_PARTNERS:
            g, _ = MemberGroup.objects.get_or_create(owner=request.user, kind=kind,
                                                     defaults={"title": "Partners"})
        else:
            if MemberGroup.objects.filter(owner=request.user, kind=kind,
                                          title__iexact=title).exists():
                return Response({"detail": f"You already have a group called “{title}”."},
                                status=status.HTTP_400_BAD_REQUEST)
            g = MemberGroup.objects.create(owner=request.user, kind=kind, title=title)
        return Response({"id": g.id, "kind": g.kind, "title": g.title},
                        status=status.HTTP_201_CREATED)


class GroupMemberView(APIView):
    """`POST /api/groupz/<gid>/add|remove/` — put somebody in, or take them out.

    `gid` is an integer for a stored group and a kind for a derived one, which
    is what lets Blocked share this route: blocking IS adding somebody to a
    group, it just happens to be the one group whose row lives in `Block` so
    that the DM rule can read it.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, gid, action):
        if action not in ("add", "remove"):
            return Response({"detail": "Unknown action."},
                            status=status.HTTP_400_BAD_REQUEST)

        who, why = _lookup(request.data.get("username"))
        if why:
            return Response({"detail": why}, status=status.HTTP_400_BAD_REQUEST)
        if who.id == request.user.id:
            return Response({"detail": "That's you."},
                            status=status.HTTP_400_BAD_REQUEST)

        gid = str(gid)

        if gid == KIND_BLOCKED:
            if action == "add":
                Block.objects.get_or_create(blocker=request.user, blocked=who)
                # Blocking somebody you follow and leaving the follow in place
                # would leave them in FriendZ on the same screen that says they
                # are blocked. Both directions go.
                Follow.objects.filter(follower=request.user, following=who).delete()
                Follow.objects.filter(follower=who, following=request.user).delete()
            else:
                Block.objects.filter(blocker=request.user, blocked=who).delete()
            return Response({"ok": True})

        if gid in DERIVED:
            return Response(
                {"detail": f"{DERIVED[gid]['title']} isn't edited by hand — "
                           f"{DERIVED[gid]['note']}"},
                status=status.HTTP_400_BAD_REQUEST)

        try:
            group = MemberGroup.objects.get(id=int(gid), owner=request.user)
        except (MemberGroup.DoesNotExist, ValueError):
            # Same answer for "not yours" as for "not there", so the id range
            # can't be walked to learn whose groups exist.
            return Response({"detail": "That group isn't there."},
                            status=status.HTTP_404_NOT_FOUND)

        if action == "add":
            MemberGroupMember.objects.get_or_create(group=group, user=who)
        else:
            MemberGroupMember.objects.filter(group=group, user=who).delete()
        return Response({"ok": True})
