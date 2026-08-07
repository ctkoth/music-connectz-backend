"""BadgeZ — a title you wear and an effect you feel.

The rule that decides what belongs here: **a badge that only looks nice is a
sticker.** Every badge in this catalogue changes a number the member can point
at, and every effect is read by the system it affects rather than described in
copy nobody enforces. That is the same standard the rest of this app got held
to — a screen that states a rate has to be a screen something pays.

Two halves, deliberately separate:

* **The title** is what other members see — "Owner", "Founding Fifty". Titles
  are the achievement layer, and they are OPT-IN per badge, because an
  achievement is also a disclosure. "Straight Shooter" tells the room you have
  ten clean deals; "Bug Hunter" tells them you file bugs. A member decides
  which of those is anybody's business.
* **The effect** applies whether or not the badge is shown. Hiding a title must
  never cost somebody the thing they earned — that would make privacy
  expensive, which is the same as not offering it.

Earned vs gifted. Most badges are EARNED from evidence already in the database
(deals shipped, ratings given, accounts verified), so they cannot be claimed,
only met. A few are GIFTED by the owner, and those say so on their face —
knowing which is which is the difference between a leaderboard and a favour.
"""
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    BADGES,
    Badge,
    badge_effects,
    badges_for,
    grant_badge,
    membership_for,
    profile_for,
    recheck_badges,
)


def badge_dict(b, mine=False):
    spec = BADGES.get(b.key, {})
    return {
        "key": b.key,
        "name": spec.get("name", b.key),
        "emoji": spec.get("emoji", "🏅"),
        "title": spec.get("title", ""),
        "desc": spec.get("desc", ""),
        "how": spec.get("how", ""),
        "gifted": spec.get("gifted", False),
        "effects": spec.get("effects", {}),
        "effect_note": spec.get("effect_note", ""),
        "awarded_at": b.awarded_at.isoformat(),
        "awarded_by": b.awarded_by.username if b.awarded_by else "",
        # Privacy is per badge and only the holder sees the switch.
        **({"visible": b.visible} if mine else {}),
    }


class BadgezView(APIView):
    """GET /api/economy/badgez/ — the catalogue, what you hold, and what it does.

    `?username=` reads someone else's, showing only what they chose to show.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        username = (request.query_params.get("username") or "").strip()
        user = (User.objects.filter(username__iexact=username).first()
                if username else request.user)
        if not user:
            return Response({"detail": "member not found"}, status=status.HTTP_404_NOT_FOUND)
        mine = user.id == request.user.id

        if mine:
            # Re-check on read so a badge earned by yesterday's tenth collab is
            # waiting when you open the tab, rather than the next time some
            # unrelated code path happens to run.
            recheck_badges(user)

        held = badges_for(user, only_visible=not mine)
        p = profile_for(user)
        return Response({
            "username": user.username,
            "mine": mine,
            "badges": [badge_dict(b, mine=mine) for b in held],
            # The title being worn, and the ones available to wear.
            "title": p.badge_title,
            "titles": [BADGES[b.key]["title"] for b in held
                       if BADGES.get(b.key, {}).get("title") and b.visible],
            # The whole catalogue, so a member can see what is worth going after
            # instead of being surprised by a badge they never knew existed.
            "catalogue": [{"key": k, **{f: v for f, v in spec.items() if f != "check"}}
                          for k, spec in BADGES.items()],
            "effects": badge_effects(user) if mine else {},
        })

    def patch(self, request):
        """Show/hide a badge, or wear a title."""
        d = request.data or {}
        p = profile_for(request.user)

        if "key" in d and "visible" in d:
            b = Badge.objects.filter(user=request.user, key=str(d["key"])[:40]).first()
            if not b:
                return Response({"detail": "You don't hold that badge."},
                                status=status.HTTP_404_NOT_FOUND)
            b.visible = bool(d["visible"])
            b.save(update_fields=["visible"])
            # Hiding the badge that supplied your title takes the title down
            # with it — otherwise the title would leak what the switch was
            # meant to conceal.
            if not b.visible and p.badge_title == BADGES.get(b.key, {}).get("title"):
                p.badge_title = ""
                p.save(update_fields=["badge_title", "updated_at"])

        if "title" in d:
            wanted = str(d["title"])[:60]
            allowed = {BADGES[x.key]["title"] for x in badges_for(request.user)
                       if BADGES.get(x.key, {}).get("title") and x.visible}
            if wanted and wanted not in allowed:
                return Response(
                    {"detail": "That title isn't yours to wear — badges you hold "
                               "and have chosen to show are the ones you can wear.",
                     "titles": sorted(allowed)},
                    status=status.HTTP_403_FORBIDDEN,
                )
            p.badge_title = wanted
            p.save(update_fields=["badge_title", "updated_at"])

        return self.get(request)


class BadgeGiftView(APIView):
    """POST /api/economy/badgez/gift/ — the owner hands out a gifted badge.

    Only badges marked `gifted` can be given. An earned badge handed out by
    favour would make every earned badge unreadable, since nobody could tell
    which ones were met and which were granted.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .views import is_owner
        if not is_owner(request.user):
            return Response({"detail": "Only the platform owner gifts badges."},
                            status=status.HTTP_403_FORBIDDEN)
        from django.contrib.auth import get_user_model
        User = get_user_model()
        d = request.data or {}
        key = str(d.get("key", ""))[:40]
        spec = BADGES.get(key)
        if not spec:
            return Response({"detail": "No such badge.",
                             "keys": sorted(BADGES)}, status=status.HTTP_400_BAD_REQUEST)
        if not spec.get("gifted"):
            return Response(
                {"detail": f"'{spec['name']}' is earned, not gifted — it lands by "
                           "itself when the member meets it.",
                 "how": spec.get("how", "")},
                status=status.HTTP_400_BAD_REQUEST,
            )
        target = User.objects.filter(username__iexact=str(d.get("username", ""))).first()
        if not target:
            return Response({"detail": "member not found"}, status=status.HTTP_404_NOT_FOUND)

        badge, created = grant_badge(target, key, by=request.user)
        return Response({
            "granted": created, "badge": badge_dict(badge),
            "username": target.username,
            "tier": membership_for(target).tier,
            "effects": badge_effects(target),
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
