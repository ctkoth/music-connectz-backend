"""ChallengeZ — who may call a member out, and the screen that lists the call-outs.

BattleZ already had the call-out itself: `BattleChallengeView` starts a 1v1 PENDING,
`BattleRespondView` accepts or declines it, a decline refunds the challenger. What
it lacked was a say for the DEFENDER and a way in from a post:

* a challenge can start from a PostZ post (`post_id`), aimed at that post's author;
* a defender sets filters — genres, the five ranges applied to the challenger, a
  mute list, a pause — and may let anything that clears them open automatically;
* BattleZ lists incoming and sent challenges in one place.

The cost/gain rule decides one thing here. A challenger who is refused by a filter
is told so BEFORE anything is charged, and nothing is charged: the filter check runs
ahead of the energy spend, exactly like the range gates did. So there is no "declined
bin" the challenger paid into — a refusal at the door is free and says why.

Nothing here touches a rating, a median or a leaderboard. A filter changes who can
reach you, never what anybody is called.
"""
from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import BATTLE_CALLOUT_ENERGY
from .gates import clean_gates, describe, failing_gate, member_metrics
from .models import Battle, ChallengeFilter, profile_for

User = get_user_model()

MAX_GENRES = 12
MAX_MUTED = 200


def filter_for(user):
    """The member's filter row, or None. No row means open to everybody."""
    return ChallengeFilter.objects.filter(user=user).first()


def door_check(defender, challenger, genre=""):
    """Why `challenger` may not call `defender` out, or None.

    Returns `(code, sentence)`. Order matters for what the challenger is told:
    a paused or muted defender gets a generic sentence that does not say which,
    because "you are on their mute list" is an answer nobody asked for and a
    mute that announces itself is a block with extra steps.
    """
    f = filter_for(defender)
    if f is None:
        return None
    if f.paused:
        return ("not_taking", f"@{defender.username} isn't taking challenges right now.")
    if f.muted.filter(pk=challenger.pk).exists():
        return ("not_taking", f"@{defender.username} isn't taking challenges right now.")
    wanted = [str(g).lower() for g in (f.genres or [])]
    if wanted and str(genre or "").strip().lower() not in wanted:
        return ("genre", f"@{defender.username} only takes challenges in: {', '.join(f.genres)}. "
                         "Pick one of those genres.")
    if f.gates:
        failed = failing_gate(member_metrics(profile_for(challenger)), f.gates)
        if failed:
            return ("range", f"@{defender.username} only takes challenges from members with "
                             f"{describe(failed, f.gates)}.")
    return None


def auto_accepts(defender):
    f = filter_for(defender)
    return bool(f and f.auto_accept and not f.paused)


def filter_dict(f):
    if f is None:
        return {"paused": False, "genres": [], "gates": {}, "muted": [], "auto_accept": False}
    return {
        "paused": f.paused,
        "genres": list(f.genres or []),
        "gates": f.gates or {},
        "muted": sorted(f.muted.values_list("username", flat=True)),
        "auto_accept": f.auto_accept,
    }


class ChallengeFilterView(APIView):
    """GET / PUT /api/economy/battlez/challengez/filters/ — the defender's door.

    PUT replaces the whole filter, which is the honest shape for a settings form:
    what the screen shows is what is stored, with no merge rules to guess at.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(filter_dict(filter_for(request.user)))

    def put(self, request):
        d = request.data or {}
        genres = []
        for g in (d.get("genres") or [])[:MAX_GENRES]:
            g = str(g).strip()[:40]
            if g and g.lower() not in [x.lower() for x in genres]:
                genres.append(g)
        names = [str(n).strip().lstrip("@") for n in (d.get("muted") or [])[:MAX_MUTED]]
        muted = list(User.objects.filter(username__in=[n for n in names if n])
                     .exclude(pk=request.user.pk))
        f, _ = ChallengeFilter.objects.get_or_create(user=request.user)
        f.paused = bool(d.get("paused", False))
        f.auto_accept = bool(d.get("auto_accept", False))
        f.genres = genres
        f.gates = clean_gates(d.get("gates"))
        f.save()
        f.muted.set(muted)
        return Response(filter_dict(f))


def _card(b, request):
    from .battlez import battle_dict
    out = battle_dict(b, request, with_entries=False)
    out["source_item"] = b.source_item
    # Every row says what each button does to the wallet BEFORE it is pressed.
    out["accept_cost"] = {"resource": "energy", "amount": 0}
    out["decline_refunds_challenger"] = {"resource": "energy", "amount": BATTLE_CALLOUT_ENERGY}
    # And where to take it next — a challenge made from a post can open that post.
    out["open_in"] = ({"tab": "postz", "target": b.source_item} if b.source_item else None)
    return out


class ChallengeInboxView(APIView):
    """GET /api/economy/battlez/challengez/ — the member's challenges, in one list.

    `incoming` is every 1v1 somebody aimed at them that is still waiting; `sent` is
    every one they started that has not settled. Both are the same Battle rows the
    rest of BattleZ reads, so accepting from here and accepting from a battle card
    are one code path.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        base = (Battle.objects.filter(mode=Battle.MODE_1V1)
                .select_related("host", "opponent"))
        incoming = base.filter(opponent=request.user, status=Battle.STATUS_PENDING)[:100]
        sent = base.filter(host=request.user).exclude(
            status__in=[Battle.STATUS_SETTLED, Battle.STATUS_CLOSED])[:100]
        return Response({
            "callout_cost_energy": BATTLE_CALLOUT_ENERGY,
            "incoming": [_card(b, request) for b in incoming],
            "sent": [_card(b, request) for b in sent],
            "filters": filter_dict(filter_for(request.user)),
        })
