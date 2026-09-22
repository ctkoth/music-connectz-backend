"""BodieZ's trial door — one logged set, scored with real arithmetic, no
account. The same shape SingZ and RapZ already give a stranger, reusing the
exact table they write to.

There is no recorder here and nothing to send a model, so this door skips the
whole first half of `trial.py`'s story — no mic prompt, no file size cap, no
`GEMINI_API_KEY` gate. A visitor picks a real exercise off the public library,
types the reps and weight of a set they actually did, and gets back an
estimated one-rep max — the Epley formula (`weight * (1 + reps / 30)`), a
number lifters have used for decades and can look up themselves. That is the
same rule BodyMap and Coach already follow for members: arithmetic over a real
number the visitor typed, never a model's guess and never free — "could a
stranger get a good number without a good set?" No: change the reps or the
weight and the estimate moves with it, and a body-weight movement (no weight
typed) gets no estimate at all rather than a fabricated one.

**`TrialTake` is reused, not duplicated.** `app_key="bodiez"` slots into the
same table `trial_state`/`trial_daily_cap`/`claim_trial_take` already read,
so the one-free-take-per-browser ceiling, the per-address backstop, and the
global daily cap all apply here for free — a visitor who already spent their
trial on SingZ has spent it, period, which is the platform's own rule ("one
free take", not "one free take per app") rather than a new one invented for
this door. `TrialPublicStatsView`'s counts pick this up automatically because
it filters `TrialTake` by nothing narrower than existing.

**The funnel door key is `"bodiez"`**, added in `views.py`'s `_door_keys()`
alongside the instrument doors `trialdoorz.door_keys()` already publishes —
BodieZ is not a scored instrument (`instruments.py`'s coaches are all pitch
and audio), so it does not belong in `INSTRUMENT_APP_KEYS`, but the funnel's
`try_view`/`try_send`/`try_scored`/`try_blocked` kinds are already generic
over `app_key` and needed no new FUNNEL_KINDS entries.
"""
import secrets

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .bodiez import GOALS, REC_LABELS, SPLITS, _exercise_dict
from .clientip import client_ip
from .models import BodieZExercise, TRIAL_CLAIM_DAYS, TRIAL_PER_IP_HOURS, TrialTake, trial_daily_cap
from .trial import client_anon_id, trial_state

APP_KEY = "bodiez"


def _coach_sample(reps, weight_kg):
    """What Coach will say, honestly scoped to what ONE set can show.

    `BodieZCoachView` only ever calls a real recommendation after comparing
    two logged sessions of the same exercise — a trial gets exactly one, so
    there is nothing to compare and inventing a verdict here would be the
    substance rule's exact failure case, aimed at the one screen where being
    caught costs the most. `not_enough_data` is a REAL state Coach already
    returns to members in the same position (a freshly added exercise), read
    from `REC_LABELS` rather than retyped, so this can never say something
    the real Coach wouldn't.
    """
    return {
        "recommendation": "not_enough_data",
        "label": REC_LABELS["not_enough_data"],
        "why": ("One set is a start, not a trend — Coach compares this exercise's last "
                "two SESSIONS before it recommends anything, same as it will for you. "
                "Log this again next time you train it and Coach has something to say."),
    }


def _statz_upgrade():
    """StatZ's real price and founding seat count, read the same way
    `PublicTiersView` already does — never retyped here, or this becomes the
    tenth place a tier number lives (the exact failure `Register.jsx` shipped
    once, per the frontend's own CLAUDE.md)."""
    from .catalog import tier_ladder
    from .models import TIER_STATZ, founding_status
    ladder = tier_ladder()
    founding = founding_status()
    return {
        "tier": TIER_STATZ,
        "month_cents": ladder[TIER_STATZ]["month_cents"],
        "founding": {
            "lifetime_cents": founding["price_cents"],
            "remaining": founding["remaining"],
            "sold_out": founding["sold_out"],
        },
    }


def _estimate_1rm(reps, weight_kg):
    """Epley formula. `None` for a body-weight set — inventing a number for
    "how much could you lift" when nothing was lifted is the exact failure
    the substance rule names, so this stays honest about what it can't say."""
    if weight_kg is None or reps is None or reps <= 0:
        return None
    if reps == 1:
        return round(float(weight_kg), 1)
    return round(float(weight_kg) * (1 + reps / 30), 1)


class BodieZTrialView(APIView):
    """GET availability; POST one logged set, no account: /api/economy/bodiez/trial/."""

    permission_classes = [AllowAny]

    def get(self, request):
        ip = client_ip(request)
        anon_id = client_anon_id(request)
        today, mine, ip_over = trial_state(ip, anon_id)
        cap = trial_daily_cap()
        return Response({
            "app_key": APP_KEY,
            "label": "BodieZ",
            "free": True,
            "available": not mine and not ip_over and today < cap,
            "already_used": mine,
            "address_busy": ip_over,
            "cap_reached": today >= cap,
            "per_address": (f"one free take per browser every {TRIAL_PER_IP_HOURS} hours, "
                            "shared across every trial door on the platform"),
            "claim_days": TRIAL_CLAIM_DAYS,
            # The real library, same rows a member's own exercise picker
            # reads — nothing here is a trimmed-down "trial version" of the
            # product, same reason RapZ's trial door forwards the real style
            # list rather than a shorter one.
            "exercises": [_exercise_dict(e) for e in BodieZExercise.objects.all()],
            # Coach's real, cited rep/set/rest schemes — the same table
            # `BodieZCoachView` serves members, not a trial-only summary of
            # it. A visitor picking "muscle gain" here sees the identical
            # numbers a member sees, which is the whole point of a trial: the
            # product, not a demo of it.
            "goals": GOALS,
            "splits": SPLITS,
            "upgrade": _statz_upgrade(),
        })

    def post(self, request):
        ip = client_ip(request)
        anon_id = client_anon_id(request)
        today, mine, ip_over = trial_state(ip, anon_id)
        if mine:
            return Response(
                {"detail": "You've had your free take for today. Make an account and BodieZ is yours whenever you want it.",
                 "already_used": True},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        if ip_over:
            return Response(
                {"detail": "This network has used up today's free takes — that's the connection "
                           "you're on, not you. An account gets you BodieZ on any connection.",
                 "address_busy": True},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        if today >= trial_daily_cap():
            return Response(
                {"detail": "Free takes are all spoken for today — they're limited so we can keep giving them away. Try tomorrow, or make an account.",
                 "retry_tomorrow": True},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            exercise_id = int(request.data.get("exercise_id"))
            reps = int(request.data.get("reps"))
        except (TypeError, ValueError):
            return Response({"detail": "Pick an exercise and enter reps first."},
                            status=status.HTTP_400_BAD_REQUEST)
        if reps <= 0:
            return Response({"detail": "Reps has to be at least 1."},
                            status=status.HTTP_400_BAD_REQUEST)
        ex = BodieZExercise.objects.filter(id=exercise_id).first()
        if not ex:
            return Response({"detail": "That exercise doesn't exist."},
                            status=status.HTTP_400_BAD_REQUEST)
        weight_raw = request.data.get("weight_kg")
        try:
            weight_kg = float(weight_raw) if weight_raw not in (None, "") else None
        except (TypeError, ValueError):
            weight_kg = None

        one_rm = _estimate_1rm(reps, weight_kg)
        payload = {
            "exercise": _exercise_dict(ex),
            "reps": reps,
            "weight_kg": weight_kg,
            "estimated_1rm_kg": one_rm,
            "estimate_note": (
                "Estimated with the Epley formula (weight x (1 + reps/30)) — the same "
                "arithmetic lifters have used for decades, not a model's guess. It moves "
                "only because your reps or weight would."
                if one_rm is not None else
                "Bodyweight movements don't get a 1RM estimate — there's no added weight "
                "for the formula to work from."
            ),
            "coach_sample": _coach_sample(reps, weight_kg),
        }

        # `scored=True` unconditionally: unlike a coach take, nothing here can
        # come back unscorable — a valid exercise and a positive rep count is
        # always a complete trial, whether or not a weight was entered for
        # the 1RM estimate to work from.
        take = TrialTake.objects.create(
            token=secrets.token_urlsafe(24), app_key=APP_KEY, ip=ip,
            anon_id=anon_id, result=payload, scored=True,
        )
        return Response({
            **payload,
            "trial": True,
            "cost_cents": 0,
            "claim_token": take.token,
            # The scheduler, not "today": what survives signup is the ROUTINE
            # `_claim_bodiez_trial` builds from this pick, sitting in Inbox —
            # so the account lands where that routine actually is.
            "open_in": f"{APP_KEY}:scheduler",
            "claim_hint": (f"Sign up within {TRIAL_CLAIM_DAYS} days and this exercise becomes "
                           "a real routine in your Scheduler — nothing you picked here is lost."),
            "upgrade": _statz_upgrade(),
        }, status=status.HTTP_201_CREATED)
