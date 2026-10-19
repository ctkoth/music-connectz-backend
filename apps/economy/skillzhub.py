"""SkillZ — the hub that holds every instrument coach.

SingZ, RapZ, GuitarZ, BassZ, KeyZ, DrumZ and ViolinZ are seven coaches that
each had a screen and no front door that said, in one place, which of them
exist, which are switched on, what a take costs and what the member has done in
each. This is that place, and it is the cost/gain rule applied to a menu: the
price of a take is on every tile BEFORE the coach is opened.

It decides nothing and charges nothing — the same shape as `intelligencez.py`,
which it follows on purpose.

* The coaches are read off `INSTRUMENT_APP_KEYS`'s own list (`instruments.
  INSTRUMENTS`), never typed again here, and every one of them has a mounted
  route (`test_instrument_routes` pins that). A coach that is not in
  `INSTRUMENTS` is not on the hub.
* The price is the one the coach's own GET states (`ai_cost("standard")`, a free
  daily prompt when one is left), so the hub cannot quote a number the coach
  then contradicts. `test_skillzhub` pins that the two agree.
* `scores` is what each coach scores a take on, read from `instruments.py` — the
  one place a dimension is defined — so a drummer is not described in a
  singer's words.
* `count` is the member's own coached takes, `level`/`xp` their SkillZ tree
  progress. Each is ONE aggregate for all seven, not a query per coach.

What is NOT on it, and is served as `coming` rather than as a tile: DJ, producer,
A&R, illustration and video. The SkillZ artwork shows people doing those; there is
no coach, no scored take and no skill tree for any of them, and a tile that opens
nothing is the dead door this codebase keeps finding. `coming` is names only —
no price, no tab, nothing to press — so a screen can say "not built yet" and
nothing else.

`in_app` is every coach: the standalone SkillZ app sells nothing, and every coach
runs on the free daily prompts, falling back to PromptZ the member already holds.
"""
import re

from django.db.models import Count
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import ai_cost
from .gemini import _key
from .instruments import INSTRUMENTS, scores_for
from .models import (TakeScore, daily_prompt_covers, daily_prompt_state, membership_for)

RECENT_MAX = 8

# (key, emoji, icon). Order is the order the hub shows them: voices, strings and
# keys, then percussion — the grouping the ToolZ menu already uses.
COACHES = [
    ("singz", "🎤", "singz.png"),
    ("rapz", "🗣️", "rapz.png"),
    ("guitarz", "🎸", "guitarz.png"),
    ("bassz", "🎸", "bassz.png"),
    ("keyz", "🎹", "keyz.png"),
    ("violinz", "🎻", "violinz.png"),
    ("flutez", "🪈", "flutez.png"),
    ("saxz", "🎷", "saxz.png"),
    ("clarinetz", "🎼", "clarinetz.png"),
    ("trumpetz", "🎺", "trumpetz.png"),
    ("drumz", "🥁", "drumz.png"),
]

# Named on the SkillZ artwork, built nowhere. Names only — see the module docstring.
COMING = ["DJ", "Producer", "A&R", "Illustrator", "Videographer"]

_EMOJI = re.compile(r"\s*[^\w\s&'/-]+\s*$", re.UNICODE)


def _plain(label):
    """"Flow 🌊" -> "Flow": the dimension's name without its mark, for a sentence."""
    return _EMOJI.sub("", str(label)).strip()


def _desc(key):
    p = INSTRUMENTS[key]
    names = [_plain(v).lower() for v in p["scores"].values()]
    return (f"{p['coach'].capitalize()}: send a take and get it scored on "
            f"{', '.join(names[:-1])} and {names[-1]} — plus what worked, what to fix and a drill.")


def _price(daily_left):
    cost = ai_cost("standard")
    return {"kind": "prompt", "cost_cents": cost,
            "free_today": daily_left > 0 and daily_prompt_covers(cost),
            "daily_remaining": daily_left}


def _stats(user):
    counts = {r["app_key"]: r["n"] for r in
              TakeScore.objects.filter(user=user).values("app_key").annotate(n=Count("id"))}
    from apps.skillz.models import TrainingProfile
    prof = {p.app_key: p for p in
            TrainingProfile.objects.filter(user=user, app_key__in=[k for k, _, _ in COACHES])}
    return counts, prof


def _snippet(row):
    bits = [INSTRUMENTS.get(row.app_key, {}).get("label", row.app_key)]
    bits.append(f"{row.overall}/10" if row.overall is not None else "not scored")
    if row.genre:
        bits.append(row.genre)
    return " · ".join(bits)


def recent_for(user, limit=RECENT_MAX):
    """The member's newest coached takes across every coach, newest first. One
    query, sliced in SQL, narrowed to the columns the label needs (`context` and
    `scores` can be large)."""
    keys = [k for k, _, _ in COACHES]
    rows = (TakeScore.objects.filter(user=user, app_key__in=keys)
            .only("id", "app_key", "overall", "genre", "created_at")[:limit])
    return [{"app": r.app_key, "id": r.id, "label": _snippet(r),
             "created_at": r.created_at.isoformat(),
             # The coach screen the take was scored in; its progress panel lists it.
             "tab": r.app_key, "target": f"{r.app_key}-progress"}
            for r in rows]


class SkillZHubView(APIView):
    """GET /api/economy/skillz/ — the coaches, what a take costs before any is
    opened, and what the member has done in each."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        tier = membership_for(user).tier
        allowance, used, remaining = daily_prompt_state(user)
        configured = bool(_key())
        counts, prof = _stats(user)
        price = _price(remaining)
        apps = []
        for key, emoji, icon in COACHES:
            p = prof.get(key)
            xp = p.xp if p else 0
            apps.append({
                "key": key, "label": INSTRUMENTS[key]["label"], "emoji": emoji, "icon": icon,
                "desc": _desc(key), "built": True, "tab": key,
                "configured": configured, "in_app": True, "standalone": True,
                "price": price, "count": counts.get(key, 0),
                "xp": xp, "level": 1 + xp // 500,
                # The dimensions a take here is scored on, from the one place
                # they are defined — never retyped on the screen.
                "scores": list(scores_for(key).values()),
            })
        return Response({
            "tier": tier,
            "apps": apps,
            "recent": recent_for(user),
            "daily": {"allowance": allowance, "used": used, "remaining": remaining},
            "coming": COMING,
        })
