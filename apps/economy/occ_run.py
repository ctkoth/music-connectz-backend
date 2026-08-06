"""POST /api/economy/occ/run/ — OCC runs your code, for real.

GET first. The GET is not decoration: it is how the price, the ceiling and
what's left today reach the button BEFORE anything is spent. A price discovered
by paying it is not a price, it's a bill.

What a run leaves behind, both of them on purpose:

* a **TaskZ** row, because the spec's rule is one list and one truth — a run is
  a thing OCC did, and it belongs in the same list as an edit or a commit;
* a **WorkZ** output, so the thing that came out of the sandbox can be posted,
  rated, commented on, or carried into another app. A result you can only look
  at is the dead end this app doesn't allow.
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import OccOutput, OccTask, membership_for, wallet_for
from .modal_sandbox import (
    ENERGY_PER_SECOND,
    NEEDS_TIER,
    RUNNERS,
    SandboxError,
    MAX_SOURCE_CHARS,
    configured,
    limits_for,
    price_for,
    run_source,
    seconds_used_today,
    unavailable_reason,
)
from .occ_spec import tier_at_least
from .occ_workz import output_dict
from .occ_taskz import task_dict


def run_status(user):
    """Everything the Run button needs to state its own price and its limits."""
    tier = membership_for(user).tier
    allowed = tier_at_least(tier, NEEDS_TIER)
    lim = limits_for(tier)
    used = seconds_used_today(user) if allowed else 0
    return {
        "configured": configured(),
        "reason": unavailable_reason(),
        "allowed": allowed and configured(),
        "tier": tier,
        "required_tier": NEEDS_TIER,
        # The price, up front.
        "cost": {"resource": "energy", "per_second": ENERGY_PER_SECOND},
        "per_run_seconds": lim["per_run_seconds"],
        "per_day_seconds": lim["per_day_seconds"],
        "seconds_used_today": used,
        "seconds_left_today": max(0, lim["per_day_seconds"] - used),
        "max_cost_per_run": price_for(lim["per_run_seconds"]),
        "energy": wallet_for(user).energy,
        "languages": sorted(RUNNERS.keys()),
        # Stated rather than discovered: a run that never started is free.
        "billing_note": "You're charged for the seconds the sandbox actually ran. "
                        "A run that never starts costs nothing. Code that runs and "
                        "fails still ran — that's the error you asked for.",
    }


class OccRunView(APIView):
    """GET the price and the limits; POST runs the code."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(run_status(request.user))

    def post(self, request):
        d = request.data or {}
        st = run_status(request.user)

        if not st["configured"]:
            # 503, not 403: it isn't the member's tier that's wrong, it's that
            # the sandbox isn't connected. Two different sentences.
            return Response({"detail": st["reason"], **st},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if not tier_at_least(st["tier"], NEEDS_TIER):
            return Response(
                {"detail": "Running code is a StatZ feature — it's a container per run, "
                           "and that's what the tier pays for.",
                 "required_tier": NEEDS_TIER, **st},
                status=status.HTTP_403_FORBIDDEN,
            )

        language = str(d.get("language", "python")).lower()
        if language not in RUNNERS:
            return Response({"detail": f"OCC can't run {language} yet.",
                             "languages": st["languages"]},
                            status=status.HTTP_400_BAD_REQUEST)
        source = str(d.get("source", "") or "")
        if not source.strip():
            return Response({"detail": "There's no code to run."},
                            status=status.HTTP_400_BAD_REQUEST)
        if len(source) > MAX_SOURCE_CHARS:
            return Response({"detail": f"That file is over {MAX_SOURCE_CHARS:,} characters."},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            seconds = int(d.get("seconds") or st["per_run_seconds"])
        except (TypeError, ValueError):
            seconds = st["per_run_seconds"]
        seconds = max(1, min(seconds, st["per_run_seconds"]))
        if seconds > st["seconds_left_today"]:
            return Response(
                {"detail": f"You've used {st['seconds_used_today']}s of your "
                           f"{st['per_day_seconds']}s of sandbox time today.",
                 **st},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        title = str(d.get("title", "") or f"Run {language}")[:200]
        task = OccTask.objects.create(
            user=request.user, title=title, kind=OccTask.KIND_BUILD,
            status=OccTask.STATUS_RUNNING, eta_seconds=seconds,
            detail=f"{language} · up to {seconds}s · up to {price_for(seconds)} ⚡",
        )

        try:
            result = run_source(language, source, seconds=seconds)
        except SandboxError as exc:
            # Nothing usable came back, so nothing is charged — the same rule
            # the vocal coach bills on.
            task.status = OccTask.STATUS_FAILED
            task.detail = str(exc)
            task.save(update_fields=["status", "detail", "updated_at"])
            return Response({"detail": str(exc), "charged": 0,
                             "task": task_dict(task, st["tier"])},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        # It ran. Charge for the seconds it actually took, never for the ceiling.
        charged = price_for(result["seconds"])
        w = wallet_for(request.user)
        charged = min(charged, max(0, w.energy))
        if charged:
            w.energy -= charged
            w.save(update_fields=["energy", "updated_at"])

        task.status = OccTask.STATUS_DONE
        task.progress = 100
        task.run_seconds = result["seconds"]
        task.detail = (f"exit {result['exit_code']} · {result['seconds']}s · −{charged} ⚡")
        task.save(update_fields=["status", "progress", "run_seconds", "detail", "updated_at"])

        # And it becomes WorkZ, so the output isn't trapped in a console pane.
        body = result["stdout"] or result["stderr"] or "(no output)"
        work = OccOutput.objects.create(
            user=request.user, task=task, tab="console",
            input_text=source[:MAX_SOURCE_CHARS],
            title=title[:160], description=body[:20000], media_type="code",
            skills_used=[language],
        )

        return Response({
            **result,
            "charged": charged,
            "energy": w.energy,
            "task": task_dict(task, st["tier"]),
            "work": output_dict(work, request),
            # Where the output goes from here, rather than nowhere.
            "open_in": "occ", "target": "occ-workz",
        }, status=status.HTTP_201_CREATED)
