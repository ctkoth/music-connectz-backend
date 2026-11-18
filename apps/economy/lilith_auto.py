"""Lilith's automatic tasks: she adds them to the board herself, from who the member says they are
and what they actually do — StatZ's, like every automation (Corey's call).

It is the same engine as "Lilith suggests" (`lilith_suggest.suggest`): the persona (a Designer gets
Image ConnectZ, ImageZ, MangaZ and FaceZ tasks), what they made and where it goes next (pictures →
a manga page → a cut in VideoZ), and the gaps in what they do. The difference is who presses Add.
On StatZ (or the daily sample) she presses it, and every task she adds says WHY on its own row, so
nothing on the board is a mystery.

Rules that keep an automation from becoming a nuisance or a faucet:

* **At most `PER_DAY` a day** (rolling 24 hours), and never past the tier's open-task ceiling.
* **Nothing the member threw away comes back.** A task in the Trash, or done in the last
  `REST_DAYS`, is not re-added: deleting one of hers is the member saying no.
* **She never mints.** An automatic task is `source="auto"`, which pays XP for its size and no 🍥
  (`lilith_taskz.complete`): "automation may never mint" is the blueprint's own line.
* **Verified ones only.** Every task she adds names an action Lilith checks against the platform's
  records, so she also ticks it herself when it happens.
* **Off is a switch.** On by default for StatZ; `LilithAuto.on` turns it off and keeps it off.
"""
from datetime import timedelta

from django.utils import timezone

PER_DAY = 3
REST_DAYS = 14
NOTE_PREFIX = "Lilith added this: "


def allowed(user):
    from .statz_trial import has_statz
    return has_statz(user)


def is_on(user):
    from .models import LilithAuto
    row = LilithAuto.objects.filter(user=user).first()
    return True if row is None else row.on


def state(user, added=()):
    ok = allowed(user)
    return {
        "allowed": ok, "on": is_on(user), "per_day": PER_DAY, "added": list(added),
        "what": ("Lilith adds up to %d tasks a day by herself, from your personas and what you've been making, "
                 "each with the reason on it. Delete one and she won't bring it back." % PER_DAY),
        "locked": "" if ok else "Automatic tasks are a StatZ feature — Lilith still suggests them below, for you to add.",
    }


def run(user):
    """Add today's automatic tasks. Returns [{id, title, why}] for what was added (often nothing)."""
    from .lilith_starters import task_by_key
    from .lilith_suggest import suggest
    from .lilith_taskz import LilithTask, live_routines, open_tasks, tier_limits
    from .models import membership_for
    if not allowed(user) or not is_on(user):
        return []
    now = timezone.now()
    budget = PER_DAY - LilithTask.objects.filter(user=user, source="auto", created_at__gte=now - timedelta(hours=24)).count()
    if budget <= 0:
        return []
    room = tier_limits(membership_for(user).tier)["active_tasks"] - open_tasks(user).count()
    budget = min(budget, room)
    if budget <= 0:
        return []
    have = set(open_tasks(user).values_list("template", flat=True))
    refused = set(LilithTask.objects.filter(user=user, bucket="trash").values_list("template", flat=True))
    rested = set(LilithTask.objects.filter(user=user, done_at__gte=now - timedelta(days=REST_DAYS)).values_list("template", flat=True))
    routines = [r.template for r in live_routines(user)]
    added = []
    for s in suggest(user, on_board_routines=routines, on_board_tasks=have, task_limit=50):
        if len(added) >= budget:
            break
        if s["kind"] != "task" or not s.get("action"):
            continue
        key = s["key"]
        if key in have or key in refused or key in rested:
            continue
        spec = task_by_key(key)
        if not spec:
            continue
        t = LilithTask.objects.create(
            user=user, title=spec["title"], note=f"{NOTE_PREFIX}{s['why']}\n\n{spec['note']}", kind=spec["kind"],
            bucket=spec["bucket"], source="auto", app_key=s["app_key"], target=spec["target"], template=key,
            action=spec.get("action", ""), goal=spec.get("goal", 1))
        have.add(key)
        added.append({"id": t.pk, "title": t.title, "why": s["why"]})
    return added


from rest_framework import status  # noqa: E402
from rest_framework.permissions import IsAuthenticated  # noqa: E402
from rest_framework.response import Response  # noqa: E402
from rest_framework.views import APIView  # noqa: E402


class LilithAutoView(APIView):
    """POST /api/economy/lilith/auto/ {on} — switch automatic tasks on or off. Off always works;
    on needs StatZ (or the sample), and says so."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .models import LilithAuto
        on = bool((request.data or {}).get("on"))
        if on and not allowed(request.user):
            return Response({"detail": state(request.user)["locked"], **state(request.user)}, status=status.HTTP_403_FORBIDDEN)
        LilithAuto.objects.update_or_create(user=request.user, defaults={"on": on})
        return Response(state(request.user))
