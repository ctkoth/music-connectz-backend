"""BattleZ — a challenge, its entries, and the same door everything else has.

BattleZ has been in the tab bar since the app was written and has never had a
single row behind it, which made "BattleZ carries the range gates" a promise
with nothing to enforce. This is the smallest honest version:

* the challenge carries the WORK in the PostZ format — record or upload
  audio/video, an image, and the lyrics or script;
* entering carries the same;
* who may enter is decided by the same five exclusive ranges search, VenueZ and
  CollabZ use, from one spec, so what a host advertises and what the door
  enforces cannot diverge;
* judging is not reimplemented — a battle and every entry live in the item space
  RateZ already serves, so they get ratings and a comment thread for free.
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import over_char_limit
from .gates import clean_gates, describe, failing_gate, member_metrics, refusal
from .models import (
    Battle,
    BattleEntry,
    award_spinaz,
    blocked_user_ids,
    item_rating_median,
    membership_for,
    notify,
    profile_for,
    wallet_for,
)


def _media(d, prefix=""):
    return {
        "media_type": str(d.get(f"{prefix}media_type", "") or "")[:24],
        "media_url": str(d.get(f"{prefix}media_url", "") or "")[:500],
        "image_url": str(d.get(f"{prefix}image_url", "") or "")[:500],
        "lyrics": str(d.get(f"{prefix}lyrics", "") or ""),
    }


def entry_dict(e, request=None):
    user = getattr(request, "user", None)
    return {
        "id": e.id,
        "user": e.user.username,
        "mine": bool(user and getattr(user, "is_authenticated", False) and e.user_id == user.id),
        "title": e.title,
        "media_type": e.media_type,
        "media_url": e.media_url,
        "image_url": e.image_url,
        "lyrics": e.lyrics,
        # Judged through the shared item space, not a second rating system.
        "item_key": e.item_key,
        "rating": item_rating_median(e.item_key),
        "created_at": e.created_at.isoformat(),
    }


def battle_dict(b, request=None, with_entries=True):
    user = getattr(request, "user", None)
    me = bool(user and getattr(user, "is_authenticated", False))
    out = {
        "id": b.id,
        "host": b.host.username,
        "mine": bool(me and b.host_id == user.id),
        "title": b.title,
        "description": b.description,
        "genre": b.genre,
        "media_type": b.media_type,
        "media_url": b.media_url,
        "image_url": b.image_url,
        "lyrics": b.lyrics,
        "gates": b.gates or {},
        "entry_spinaz": b.entry_spinaz,
        "status": b.status,
        "item_key": b.item_key,
        "rating": item_rating_median(b.item_key),
        "entry_count": b.entries.count(),
        "created_at": b.created_at.isoformat(),
    }
    if me:
        out["entered"] = b.entries.filter(user=user).exists()
    if with_entries:
        entries = list(b.entries.select_related("user"))
        # Best-judged first — a battle with no leaderboard is just a thread.
        entries.sort(key=lambda e: (item_rating_median(e.item_key) or 0), reverse=True)
        out["entries"] = [entry_dict(e, request) for e in entries]
    return out


class BattlesView(APIView):
    """GET the open battles; POST hosts one."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (Battle.objects.select_related("host")
              .exclude(host_id__in=blocked_user_ids(request.user))[:200])
        return Response({"battles": [battle_dict(b, request, with_entries=False) for b in qs]})

    def post(self, request):
        d = request.data or {}
        title = str(d.get("title", "")).strip()
        if not title:
            return Response({"detail": "Give the battle a name."},
                            status=status.HTTP_400_BAD_REQUEST)
        description = str(d.get("description", "") or "")
        cap = over_char_limit(description, membership_for(request.user).tier)
        if cap:
            return Response(
                {"detail": f"That's over your {cap:,}-character limit — upgrade in MembershipZ for more room.",
                 "char_limit": cap},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            entry_spinaz = max(0, int(d.get("entry_spinaz") or 0))
        except (TypeError, ValueError):
            entry_spinaz = 0
        b = Battle.objects.create(
            host=request.user, title=title[:160], description=description,
            genre=str(d.get("genre", "") or "")[:40],
            gates=clean_gates(d.get("gates")), entry_spinaz=entry_spinaz,
            **_media(d),
        )
        return Response(battle_dict(b, request), status=status.HTTP_201_CREATED)


class BattleDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        b = Battle.objects.select_related("host").filter(pk=pk).first()
        if not b:
            return Response({"detail": "battle not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(battle_dict(b, request))

    def patch(self, request, pk):
        """The host closes it. Closing is the only edit — a challenge whose
        terms change after people have entered isn't a challenge."""
        b = Battle.objects.filter(pk=pk, host=request.user).first()
        if not b:
            return Response({"detail": "battle not found"}, status=status.HTTP_404_NOT_FOUND)
        if str((request.data or {}).get("status", "")).lower() == Battle.STATUS_CLOSED:
            b.status = Battle.STATUS_CLOSED
            b.save(update_fields=["status", "updated_at"])
        return Response(battle_dict(b, request))


class BattleEnterView(APIView):
    """POST enters the battle — gated, priced, and in the PostZ format."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        b = Battle.objects.select_related("host").filter(pk=pk).first()
        if not b:
            return Response({"detail": "battle not found"}, status=status.HTTP_404_NOT_FOUND)
        if b.status != Battle.STATUS_OPEN:
            return Response({"detail": "This battle is closed."}, status=status.HTTP_409_CONFLICT)
        if b.host_id == request.user.id:
            return Response({"detail": "You can't enter your own battle."},
                            status=status.HTTP_400_BAD_REQUEST)
        if b.entries.filter(user=request.user).exists():
            return Response({"detail": "You're already in this one."},
                            status=status.HTTP_409_CONFLICT)

        # The same five ranges, evaluated exactly as search evaluates them.
        if b.gates:
            host_p = profile_for(b.host)
            origin = ((host_p.lat, host_p.lng)
                      if (host_p.share_location and host_p.lat is not None) else (None, None))
            failed = failing_gate(member_metrics(profile_for(request.user), origin), b.gates)
            if failed:
                return Response(refusal(failed, b.gates), status=status.HTTP_403_FORBIDDEN)

        w = wallet_for(request.user)
        if b.entry_spinaz and (w.spinaz or 0) < b.entry_spinaz:
            return Response(
                {"detail": f"Entry costs {b.entry_spinaz} SpinaZ and you have {w.spinaz or 0}.",
                 "entry_spinaz": b.entry_spinaz},
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        d = request.data or {}
        entry = BattleEntry.objects.create(
            battle=b, user=request.user, title=str(d.get("title", "") or "")[:160], **_media(d),
        )
        if b.entry_spinaz:
            # Entry goes to the host. Stated on the button before it's pressed.
            award_spinaz(request.user, -b.entry_spinaz, f"BattleZ entry: {b.title}")
            award_spinaz(b.host, b.entry_spinaz, f"BattleZ entry from @{request.user.username}")
        notify(b.host, "join", f"@{request.user.username} entered '{b.title}' ⚔️",
               actor=request.user, item_id=b.item_key)
        return Response({"entry": entry_dict(entry, request),
                         "battle": battle_dict(b, request)},
                        status=status.HTTP_201_CREATED)

    def delete(self, request, pk):
        """Withdraw. The entry fee is NOT returned — it was paid to the host for
        their time the moment it was accepted, and refunding on withdrawal would
        make the fee meaningless."""
        b = Battle.objects.filter(pk=pk).first()
        if not b:
            return Response({"detail": "battle not found"}, status=status.HTTP_404_NOT_FOUND)
        b.entries.filter(user=request.user).delete()
        return Response(battle_dict(b, request))
