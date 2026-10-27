"""InventoryZ — the profile inventory, rated piece by piece and in total.

Corey's ask: members post their equipment, instruments and clothes and get
rated on each piece and in total. The inventory ALREADY EXISTS — it is
`Profile.inventory` ([{name, kind, where, note, photo}], cleaned by
`social.clean_inventory`, edited in ProfileZ's profile fields, searchable in
GenreZ). This module adds ratings on top of it and nothing else, because a
second place to list your gear would be two lists that disagree within a week.

WHAT THE RATING IS. Members rating a piece is a TASTE judgement by people who
looked at it — "how members rate this" — and the screen says so. It never
feeds a skill level, a royalty, a price or a search rank, and the total is not
a measurement of the member. It measures exactly what it says and no more.

HOW. A piece is rated through the ONE rating path the platform has
(`SocialView` rate) on the item id `gear:<owner id>:<slug of the name>`, so the
1-10 scale, the edit window and the rater's own ⚡ reward and daily cap are the
same as for a post. The name is the identity because the cleaner already folds
repeats of a name, so it is unique per profile; the cost is that RENAMING a
piece starts its ratings again, which the editor says.
`post_interaction_block` refuses the owner rating their own pieces.

- **Individual**: each piece's median and count; None until somebody has.
- **Total**: the median of EVERY rating across the member's current pieces,
  None until `TOTAL_MIN_RATINGS` exist — one rater cannot make a total.
- Ratings of a piece that has been removed are not shown or counted.
"""
import re

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ItemRating, _median, item_rating_medians, profile_for

ICON = "🎒"
TOTAL_MIN_RATINGS = 3
RATING_NOTE = ("How members rate this piece, 1 to 10 — their taste, not a measure of you. "
               "It never moves a skill, a price or a royalty.")
RENAME_NOTE = "Renaming a piece starts its ratings again — the name is what was rated."


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")[:60]


def item_key(owner_id, name):
    return f"gear:{owner_id}:{slug(name)}"


def owner_of(item_id):
    """The owner's user id for a `gear:` item, or None."""
    m = re.fullmatch(r"gear:(\d+):[a-z0-9-]+", str(item_id or ""))
    return int(m.group(1)) if m else None


def inventory_for(owner, viewer):
    """The owner's pieces with each one's rating and the total. Three queries."""
    mine = owner.id == viewer.id
    pieces = [x for x in (profile_for(owner).inventory or []) if isinstance(x, dict) and x.get("name")]
    keys = [item_key(owner.id, x["name"]) for x in pieces]
    medians = item_rating_medians(keys)
    scores = {}
    for k, s in ItemRating.objects.filter(item_id__in=keys).values_list("item_id", "score"):
        scores.setdefault(k, []).append(s)
    my = dict(ItemRating.objects.filter(item_id__in=keys, user=viewer).values_list("item_id", "score"))

    rows = []
    for x, k in zip(pieces, keys):
        rows.append({**x, "item_id": k, "rating": medians.get(k),
                     "rating_count": len(scores.get(k, [])), "my_rating": my.get(k),
                     "can_rate": not mine})
    every = [s for k in keys for s in scores.get(k, [])]
    out = {
        "username": owner.username, "mine": mine, "icon": ICON, "items": rows,
        "total": {
            "rating": _median(every) if len(every) >= TOTAL_MIN_RATINGS else None,
            "count": len(every),
            "pieces_rated": sum(1 for k in keys if scores.get(k)),
            "min_ratings": TOTAL_MIN_RATINGS,
            "how": (f"The median of every rating across the pieces, once there are "
                    f"{TOTAL_MIN_RATINGS} — one rater cannot make a total."),
        },
        "rating_note": RATING_NOTE,
    }
    if mine:
        out["rename_note"] = RENAME_NOTE
        out["edit_in"] = {"tab": "profilez", "target": "profile-fields"}
    else:
        # The gain half, before the rating: what this rater's first rating of a
        # piece pays them, and how many paid ratings are left today.
        from .ratez import rating_reward
        out["rating_reward"] = rating_reward(viewer)
    return out


class InventoryView(APIView):
    """GET /api/economy/inventoryz/?username= — a member's inventory with its ratings."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        name = (request.query_params.get("username") or "").strip()
        owner = (get_user_model().objects.filter(username__iexact=name).first()
                 if name else request.user)
        if not owner:
            return Response({"detail": "member not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(inventory_for(owner, request.user))
