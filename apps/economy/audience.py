"""Who a viewer IS to each member on screen, resolved once per request.

`visibility.py` started as a rank — private < member < public, one comparison.
FriendZ, FanZ, PartnerZ and a custom GroupZ are not ranks. They are SETS, and
they overlap without nesting: a fan is not "more" than a member, and a PartnerZ
need not be a friend. So the question stops being "is this level high enough"
and becomes "is this viewer in the set this field names".

WHY THIS IS A CONTEXT AND NOT A FUNCTION CALL
A member search renders fifty cards. Asking "is the viewer a friend / fan /
partner / group member of THIS member" per card is four questions fifty times,
on a screen that costs one query today. This resolves every relation the viewer
has, for the whole set of members on screen, in four queries total — and then
answers with none.

It is the shape `offerz_engine._context` already uses for the same reason, and
the shape `partner_pairs_among` was written in when a per-card partnership
lookup turned out to be impossible.

THE SETS ARE THE OWNER'S, READ FROM WHERE THEY ALREADY LIVE
Nothing here stores a second copy of a relationship. FriendZ and FanZ come off
`Follow`, PartnerZ off the `Partnership` tally, and a custom group off
`GroupMember` — the same sources GroupZ serves, so "who can see this" and
"who's in my circle" can never disagree.
"""
from django.db.models import F, Q

from .groupz import PARTNER_WORKS
from .models import Follow, GroupMember, Partnership

# The audiences a field may name, beyond the three that are not relationships.
FRIENDS = "friends"
FANS = "fans"
PARTNERZ = "partnerz"
RELATIONS = (FRIENDS, FANS, PARTNERZ)

# A custom group is named by id: "group:12". The owner's own group, so the id
# is only meaningful against the member whose field is being read — which is
# exactly right, because a group is local to its owner.
GROUP_PREFIX = "group:"


def is_group(token):
    return isinstance(token, str) and token.startswith(GROUP_PREFIX)


def group_id(token):
    try:
        return int(token[len(GROUP_PREFIX):])
    except (TypeError, ValueError):
        return None


class Audience:
    """What `viewer` is to each of `owner_ids`. Built once, asked many times.

    A viewer is always in their OWN every audience — a member rendering their
    own card must never have their own fields blanked, which reads as data
    loss rather than as privacy.
    """

    def __init__(self, viewer, owner_ids):
        self.viewer = viewer
        self.vid = getattr(viewer, "pk", None) if getattr(
            viewer, "is_authenticated", False) else None
        ids = {int(i) for i in owner_ids if i}
        self.friends = set()
        self.fans = set()
        self.partners = set()
        self.groups = set()
        if not self.vid or not ids:
            return

        # Two directions of Follow, bounded to the members on screen.
        following = set(Follow.objects.filter(
            follower_id=self.vid, following_id__in=ids).values_list("following_id", flat=True))
        followers = set(Follow.objects.filter(
            following_id=self.vid, follower_id__in=ids).values_list("follower_id", flat=True))
        self.friends = following & followers
        # A FAN of the owner is somebody who follows THEM. The viewer is in an
        # owner's FanZ audience when the viewer follows the owner and the owner
        # does not follow back — the owner's own definition, read from their
        # side, not the viewer's.
        self.fans = following - followers

        rows = (Partnership.objects
                .filter(Q(a_id=self.vid, b_id__in=ids) | Q(b_id=self.vid, a_id__in=ids))
                .annotate(tally=F("collabs") + F("battles"))
                .filter(tally__gte=PARTNER_WORKS)
                .values_list("a_id", "b_id"))
        self.partners = {b if a == self.vid else a for a, b in rows}

        # Which of these owners' groups the viewer is in. Keyed by group id,
        # because a field names one specific group rather than "any group".
        self.groups = set(GroupMember.objects.filter(
            member_id=self.vid, group__owner_id__in=ids).values_list("group_id", flat=True))

    def allows(self, owner_id, token):
        """Is the viewer in the audience `token` names, for this owner?"""
        if self.vid and int(owner_id) == self.vid:
            return True
        if token == FRIENDS:
            return int(owner_id) in self.friends
        if token == FANS:
            return int(owner_id) in self.fans
        if token == PARTNERZ:
            return int(owner_id) in self.partners
        if is_group(token):
            gid = group_id(token)
            return gid is not None and gid in self.groups
        return False


def for_one(viewer, owner):
    """The single-member case, which is most of the callers."""
    return Audience(viewer, [getattr(owner, "pk", owner)])
