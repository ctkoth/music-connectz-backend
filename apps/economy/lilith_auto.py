"""Lilith's automatic RoutineZ: she adds them to the board herself, from who the member says they are
and what they actually do — StatZ's, like every automation (Corey's call).

It is the same engine as "Lilith suggests" (`lilith_suggest.suggest`): the persona (a Designer gets a
picture, a manga page and a face routine), what they made and where it goes next (pictures → a manga
page → a cut in VideoZ), and the habits they already keep. The difference is who presses Keep: the
member, from the suggestions, or Lilith, on StatZ (or the daily sample). Every routine she adds says WHY
on its own row, so nothing on the board is a mystery.

Rules that keep an automation from becoming a nuisance or a faucet:

* **StatZ only.** `allowed` is the gate every automation uses (`statz_trial.has_statz`). A free member
  gets the suggestions and adds them by hand. `LilithAuto.on` switches it off, and it is on by default
  for StatZ.
* **At most `PER_DAY` a day** (rolling 24 hours), and never past the tier's routine ceiling.
* **Nothing the member threw away comes back.** A routine or task in the Trash is not re-added: deleting
  one of hers is the member saying no.
* **She never mints.** An automatic routine is `source="auto"`: its streak counts, and it pays nothing
  (`lilith_taskz.keep_routine`). "Automation may never mint" is the blueprint's own line.
* **Verified ones only.** Every routine she adds names an action Lilith checks against the platform's
  records, so she also keeps it herself when it happens.
"""
from datetime import timedelta

from django.utils import timezone

PER_DAY = 3
NOTE_PREFIX = "Lilith added this: "


def allowed(user):
    from .statz_trial import has_statz
    return has_statz(user)


def is_on(user):
    from .models import LilithAuto
    row = LilithAuto.objects.filter(user=user).first()
    return True if row is None else row.on


def _why(note):
    return note.split("\n", 1)[0][len(NOTE_PREFIX):] if (note or "").startswith(NOTE_PREFIX) else ""


def recent(user):
    """What she added in the last 24 hours and is still on the board, with the reason — read from the
    rows, so the screen can say it on any open, not only the one request that happened to add them."""
    from .lilith_taskz import LilithRoutine, LilithTask
    since = timezone.now() - timedelta(hours=24)
    out = [{"id": t.pk, "kind": "task", "title": t.title, "why": _why(t.note)}
           for t in LilithTask.objects.filter(user=user, source="auto", created_at__gte=since,
                                              done_at__isnull=True).exclude(bucket="trash")]
    out += [{"id": r.pk, "kind": "routine", "title": r.title, "why": _why(r.note)}
            for r in LilithRoutine.objects.filter(user=user, source="auto", created_at__gte=since,
                                                  trashed_at__isnull=True)]
    return out


def state(user, added=()):
    ok = allowed(user)
    return {
        "allowed": ok, "on": is_on(user), "per_day": PER_DAY, "added": recent(user) if ok else [],
        "what": ("Lilith adds up to %d RoutineZ a day by herself, from your personas and what you've been making, "
                 "each with the reason on it. They keep a streak and pay nothing. Delete one and she won't bring it back."
                 % PER_DAY),
        "locked": "" if ok else "Automatic RoutineZ are a StatZ feature — Lilith still suggests them below, for you to add.",
    }


def run(user):
    """Add today's automatic RoutineZ. Returns [{id, kind, title, why}] for what was added (often nothing)."""
    from .lilith_suggest import suggest
    from .lilith_taskz import LilithRoutine, LilithTask, live_routines, tier_limits
    from .models import membership_for
    if not allowed(user) or not is_on(user):
        return []
    since = timezone.now() - timedelta(hours=24)
    made = (LilithTask.objects.filter(user=user, source="auto", created_at__gte=since).count()
            + LilithRoutine.objects.filter(user=user, source="auto", created_at__gte=since).count())
    budget = PER_DAY - made
    if budget <= 0:
        return []
    live = list(live_routines(user))
    limit = tier_limits(membership_for(user).tier)["routines"]
    if limit is not None:                       # the owner's tier is unlimited (None)
        budget = min(budget, limit - len(live))
    if budget <= 0:
        return []
    have = {r.template for r in live if r.template}
    refused = set(LilithRoutine.objects.filter(user=user, trashed_at__isnull=False).values_list("template", flat=True))
    refused |= set(LilithTask.objects.filter(user=user, bucket="trash").values_list("template", flat=True))
    added = []
    for s in suggest(user, on_board_routines=have, on_board_tasks=(), task_limit=0):
        if len(added) >= budget:
            break
        if s["kind"] != "routine" or not s.get("action"):      # verified only: Lilith can check it
            continue
        key = s["key"]
        if key in have or key in refused:
            continue
        r = LilithRoutine.objects.create(
            user=user, title=s["title"], note=f"{NOTE_PREFIX}{s['why']}\n\n{s['note']}",
            cadence=s["cadence"], app_key=s["app_key"], target=s["target"],
            action=s["action"], goal=s.get("goal", 1), template=key, source="auto")
        have.add(key)
        added.append({"id": r.pk, "kind": "routine", "title": r.title, "why": s["why"]})
    return added


from rest_framework import status  # noqa: E402
from rest_framework.permissions import IsAuthenticated  # noqa: E402
from rest_framework.response import Response  # noqa: E402
from rest_framework.views import APIView  # noqa: E402


class LilithAutoView(APIView):
    """POST /api/economy/lilith/auto/ {on} — switch automatic RoutineZ on or off. Off always works;
    on needs StatZ (or the sample), and says so."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .models import LilithAuto
        on = bool((request.data or {}).get("on"))
        if on and not allowed(request.user):
            return Response({"detail": state(request.user)["locked"], **state(request.user)}, status=status.HTTP_403_FORBIDDEN)
        LilithAuto.objects.update_or_create(user=request.user, defaults={"on": on})
        return Response(state(request.user))
