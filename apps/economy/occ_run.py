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
import logging

from django.db.models import F
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    OccOutput,
    OccTask,
    Transaction,
    Wallet,
    log_resource,
    membership_for,
    wallet_for,
)
from .modal_sandbox import (
    ENERGY_PER_SECOND,
    NEEDS_TIER,
    RUNNERS,
    SandboxError,
    MAX_SOURCE_CHARS,
    configured,
    limits_for,
    operator_reason,
    price_for,
    run_source,
    seconds_used_today,
    unavailable_reason,
)
from .occ_spec import tier_at_least
from .occ_workz import output_dict
from .occ_taskz import task_dict
from .resources import ENERGY

log = logging.getLogger(__name__)


def _spend_energy_up_to(user, amount):
    """Take up to `amount` ⚡ off a member, never below zero. Returns what moved.

    The sandbox bill used to be

        w = wallet_for(user); charged = min(charged, w.energy)
        w.energy -= charged; w.save(...)

    — a read-modify-write in Python with no lock and no ledger row. Two runs
    finishing together each read the same balance and the later write won, so one
    of the two bills simply vanished; and nothing in LogZ said where the ⚡ went.

    This is `models.spend_spinaz`'s shape for Energy: a CONDITIONAL atomic
    decrement the database serialises. It takes the whole amount when the balance
    covers it. When the balance has fallen short since the run was accepted
    (another spend landed while the container ran) it takes what is there and
    retries, because the sandbox already ran and was paid for by the platform —
    the honest bill is "all you had", not zero. There is no `spend_energy` in
    models.py yet; this belongs there, and is kept in the same shape so it can
    move without changing.
    """
    want = int(amount)
    for _ in range(4):
        if want <= 0:
            return 0
        wallet_for(user)                       # make sure the row exists
        moved = Wallet.objects.filter(user=user, energy__gte=want).update(
            energy=F("energy") - want, updated_at=timezone.now())
        if moved:
            return want
        have = Wallet.objects.values_list("energy", flat=True).filter(user=user).first() or 0
        want = min(want, max(0, have))
    return 0


def max_seconds_now(lim, left_today, energy):
    """The longest run this member can start RIGHT NOW: the tier's ceiling, what
    is left of today's sandbox time, and what their ⚡ pays for — whichever bites
    first. The screen asks for exactly this, so the price on the button is the
    price of the run that will be made."""
    afford = int(max(0, energy) // ENERGY_PER_SECOND) if ENERGY_PER_SECOND else lim["per_run_seconds"]
    return max(0, min(lim["per_run_seconds"], int(left_today), afford))


def run_status(user):
    """Everything the Run button needs to state its own price and its limits."""
    tier = membership_for(user).tier
    allowed = tier_at_least(tier, NEEDS_TIER)
    lim = limits_for(tier)
    used = seconds_used_today(user) if allowed else 0
    energy = wallet_for(user).energy
    left_today = max(0, lim["per_day_seconds"] - used)
    can_now = max_seconds_now(lim, left_today, energy)
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
        "seconds_left_today": left_today,
        "max_cost_per_run": price_for(lim["per_run_seconds"]),
        # What a run started now can actually be, and what it would cost at most.
        # `max_cost_per_run` is the tier's ceiling; these are the member's own
        # ceiling today, which is what the Run button has to state.
        "max_seconds_now": can_now,
        "max_cost_now": price_for(can_now),
        "energy": energy,
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

        if not st["configured"] or st["reason"]:
            # 503, not 403: it isn't the member's tier that's wrong, it's that
            # the sandbox isn't connected. Two different sentences — and the
            # member's is "Running code isn't switched on yet." The env-var names
            # are for whoever runs the server, so they go to the log.
            log.warning("OCC run refused: %s", operator_reason())
            return Response({"detail": st["reason"] or "Running code isn't switched on yet.", **st},
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
        # The last stretch of the day is usable: a run asking for more than is
        # left is CLAMPED to what is left, and only refused at zero. It used to
        # refuse any run longer than the remainder, so a member with 10s left of
        # 1,800 could not run a one-second script — the final stretch of the
        # allowance was unusable, and nothing said why.
        seconds = min(seconds, st["seconds_left_today"])
        if seconds <= 0:
            return Response(
                {"detail": f"You've used {st['seconds_used_today']}s of your "
                           f"{st['per_day_seconds']}s of sandbox time today.",
                 **st},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        # Refused up front when the ⚡ will not cover the run's ceiling, with the
        # numbers — before a container is spun up and the platform pays Modal for
        # a run nobody can be billed for. A member with 0 ⚡ used to run free:
        # the bill was capped at what they held, which was nothing.
        ceiling = price_for(seconds)
        if st["energy"] < ceiling:
            affordable = st["max_seconds_now"]
            return Response(
                {"detail": f"A run of up to {seconds}s can cost up to {ceiling} {ENERGY} and "
                           f"you have {st['energy']} {ENERGY}. "
                           + (f"Run it with a limit of {affordable}s or less, or wait — "
                              f"{ENERGY} regenerates hourly."
                              if affordable else
                              f"{ENERGY} regenerates hourly — try again once you have some."),
                 "needed": ceiling, "affordable_seconds": affordable, **st},
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        title = str(d.get("title", "") or f"Run {language}")[:200]
        task = OccTask.objects.create(
            user=request.user, title=title, kind=OccTask.KIND_BUILD,
            status=OccTask.STATUS_RUNNING, eta_seconds=seconds,
            detail=f"{language} · up to {seconds}s · up to {price_for(seconds)} {ENERGY}",
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

        # It ran. Charge for the seconds it actually took, never for the ceiling —
        # conditionally and atomically, and with a LogZ line saying what the ⚡
        # went on (the old unlocked debit wrote none).
        charged = _spend_energy_up_to(request.user, price_for(result["seconds"]))
        if charged:
            log_resource(request.user, Transaction.RES_ENERGY, -charged,
                         f"OCC run · {language} · {result['seconds']}s",
                         app_key="occ", target="occ-run")
        energy_now = wallet_for(request.user).energy

        task.status = OccTask.STATUS_DONE
        task.progress = 100
        task.run_seconds = result["seconds"]
        task.detail = (f"exit {result['exit_code']} · {result['seconds']}s · −{charged} {ENERGY}")
        task.save(update_fields=["status", "progress", "run_seconds", "detail", "updated_at"])

        # ZodiacZ — the Snake works it out. Past the charge line on purpose:
        # if the run was not real enough to bill for, it was not real enough
        # to pay for either. The stretch is a clean exit, which is the
        # difference between setting it going and getting an answer.
        from .signbonus import try_award
        try_award(request.user, "occ_run", stretch=result.get("exit_code") == 0)

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
            "seconds_allowed": seconds,
            "energy": energy_now,
            "task": task_dict(task, st["tier"]),
            "work": output_dict(work, request),
            # Where the output goes from here, rather than nowhere.
            "open_in": "occ", "target": "occ-workz",
        }, status=status.HTTP_201_CREATED)
