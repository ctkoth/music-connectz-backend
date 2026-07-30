"""Coach 🤖 — turning logged sets into what to do next.

Two engines, both pure functions over queried rows so they're testable without a
model call:

* **Progressive overload** — increase, repeat, reduce, or deload. The rules come
  straight from the blueprint, and they're deliberately conservative: an app that
  tells you to add weight after one good session is how people get hurt.
* **BodyMap** — which muscles are undertrained, balanced, or overworked.

`ai_plan()` is the StatZ-only layer on top. It's the only part that costs
anything, and it explicitly refuses to invent exercises: the model picks from the
catalog the member can actually perform with the equipment they actually have.
"""
import logging
from collections import defaultdict
from datetime import timedelta

from django.utils import timezone

from .catalog import MUSCLE_KEYS
from .models import WorkoutSet

log = logging.getLogger("apps.bodiez")

VERDICT_INCREASE = "increase"
VERDICT_REPEAT = "repeat"
VERDICT_REDUCE = "reduce"
VERDICT_DELOAD = "deload"
VERDICT_UNKNOWN = "no_data"

# How many recent sessions of an exercise the verdict looks at. Two is the
# blueprint's rule and it's the right number — one good session is noise.
LOOKBACK_SESSIONS = 3
# Undertrained after this long untouched.
STALE_DAYS = 7
# Sets per muscle per week that count as a reasonable dose. Below is light,
# well above is where recovery starts losing.
WEEKLY_SETS_LOW = 6
WEEKLY_SETS_HIGH = 22


def _sessions_for(user, exercise, limit=LOOKBACK_SESSIONS):
    """The last few sessions' working sets for one exercise, newest first."""
    rows = (WorkoutSet.objects
            .filter(session__user=user, exercise=exercise, is_warmup=False,
                    session__status="done")
            .select_related("session")
            .order_by("-session__started_at", "set_number"))
    grouped, order = defaultdict(list), []
    for s in rows:
        if s.session_id not in grouped:
            order.append(s.session_id)
        grouped[s.session_id].append(s)
        if len(order) > limit and s.session_id not in order[:limit]:
            break
    return [grouped[sid] for sid in order[:limit]]


def overload_verdict(user, routine_exercise):
    """What to do with this exercise next time. Returns a dict, never None.

    The rules, in order:
      - hit every target rep on every working set, twice running -> increase
      - hit most of them (within 2 reps) -> repeat
      - missed on several sets -> reduce
      - performance falling across 3 sessions -> deload
    """
    target_reps = routine_exercise.reps or 0
    target_sets = routine_exercise.sets or 0
    sessions = _sessions_for(user, routine_exercise.exercise)

    if not sessions or not target_reps:
        return {
            "verdict": VERDICT_UNKNOWN,
            "detail": "No completed sets logged yet — train it once and I'll have something to say.",
            "sessions_seen": len(sessions),
        }

    def scored(sets):
        working = [s for s in sets if s.completed]
        if not working:
            return None
        hit = sum(1 for s in working if (s.reps or 0) >= target_reps)
        volume = sum(s.volume for s in working)
        top = max((float(s.weight) for s in working if s.weight is not None), default=0.0)
        return {"hit": hit, "sets": len(working), "volume": volume, "top": top}

    marks = [m for m in (scored(s) for s in sessions) if m]
    if not marks:
        return {"verdict": VERDICT_UNKNOWN, "detail": "Nothing completed yet.",
                "sessions_seen": 0}

    latest = marks[0]
    full_clears = [m for m in marks[:2] if m["hit"] >= min(target_sets, m["sets"])]

    # Falling volume across three sessions is the deload signal, and it outranks
    # a single good day — that pattern is fatigue, not progress.
    if len(marks) >= 3 and marks[0]["volume"] < marks[1]["volume"] < marks[2]["volume"]:
        return {
            "verdict": VERDICT_DELOAD,
            "detail": ("Volume has dropped three sessions running. Take a lighter week — "
                       "about 60% of your usual load, same reps."),
            "suggested_weight": round(latest["top"] * 0.6, 1) if latest["top"] else None,
            "sessions_seen": len(marks),
        }

    if len(full_clears) >= 2:
        # 2.5% is a conservative jump; the smallest plate pair on most bars is
        # 5lb total, which this rounds toward anyway.
        bump = round(latest["top"] * 0.025, 1) if latest["top"] else None
        return {
            "verdict": VERDICT_INCREASE,
            "detail": (f"You hit all {target_reps} reps across your sets two sessions running. "
                       "Add weight next time."),
            "suggested_weight": round(latest["top"] + bump, 1) if bump else None,
            "sessions_seen": len(marks),
        }

    missed = latest["sets"] - latest["hit"]
    if missed <= 2:
        return {
            "verdict": VERDICT_REPEAT,
            "detail": (f"Close — you missed the target on {missed} set(s). Run the same weight "
                       "again and finish it."),
            "suggested_weight": latest["top"] or None,
            "sessions_seen": len(marks),
        }

    return {
        "verdict": VERDICT_REDUCE,
        "detail": (f"You missed the target on {missed} sets. Drop about 10% and rebuild — "
                   "grinding a weight you can't complete isn't training, it's just tiring."),
        "suggested_weight": round(latest["top"] * 0.9, 1) if latest["top"] else None,
        "sessions_seen": len(marks),
    }


def body_map(user, days=7):
    """Which muscles have been trained, and how hard, over the window.

    Counts SETS, not sessions: three sets of curls and twelve sets of back are
    not the same training, and a map that treats them alike tells you nothing.
    """
    since = timezone.now() - timedelta(days=days)
    rows = (WorkoutSet.objects
            .filter(session__user=user, is_warmup=False, completed=True,
                    session__started_at__gte=since)
            .select_related("exercise", "session"))

    sets_by_muscle = defaultdict(int)
    volume_by_muscle = defaultdict(float)
    last_trained = {}
    for s in rows:
        muscles = [s.exercise.muscle] + list(s.exercise.secondary or [])
        for i, m in enumerate(muscles):
            # A secondary muscle gets half credit. A bench press trains triceps,
            # but not the way a pushdown does.
            sets_by_muscle[m] += 1 if i == 0 else 0.5
            volume_by_muscle[m] += s.volume if i == 0 else s.volume * 0.5
            when = s.session.started_at
            if m not in last_trained or when > last_trained[m]:
                last_trained[m] = when

    now = timezone.now()
    out = []
    for m in MUSCLE_KEYS:
        if m == "full-body":
            continue
        count = round(sets_by_muscle.get(m, 0), 1)
        when = last_trained.get(m)
        days_since = round((now - when).total_seconds() / 86400, 1) if when else None
        if count == 0 or (days_since is not None and days_since >= STALE_DAYS):
            state = "undertrained"
        elif count > WEEKLY_SETS_HIGH:
            state = "overworked"
        elif count < WEEKLY_SETS_LOW:
            state = "light"
        else:
            state = "balanced"
        out.append({
            "muscle": m,
            "sets": count,
            "volume": round(volume_by_muscle.get(m, 0), 1),
            "days_since": days_since,
            "state": state,
        })

    counts = {s: len([r for r in out if r["state"] == s]) for s in
              ("undertrained", "light", "balanced", "overworked")}
    return {
        "window_days": days,
        "muscles": out,
        "summary": counts,
        # Every undertrained muscle, not the first five in catalog order — a
        # "weak points" list that stops before your legs is worse than none.
        "weakest": [r["muscle"] for r in out if r["state"] == "undertrained"],
        "thresholds": {"stale_days": STALE_DAYS, "low_sets": WEEKLY_SETS_LOW,
                       "high_sets": WEEKLY_SETS_HIGH},
    }


def readiness(user):
    """A crude readiness read from what's actually logged.

    Deliberately crude and deliberately labelled as such: without sleep or HRV
    input, a confident-looking readiness score would be a number pretending to
    be a measurement.
    """
    since = timezone.now() - timedelta(days=7)
    sessions = user.bodiez_sessions.filter(started_at__gte=since, status="done")
    count = sessions.count()
    efforts = [s.perceived_effort for s in sessions if s.perceived_effort]
    avg_effort = round(sum(efforts) / len(efforts), 1) if efforts else None

    last = user.bodiez_sessions.filter(status="done").order_by("-started_at").first()
    hours_since = None
    if last:
        hours_since = round((timezone.now() - last.started_at).total_seconds() / 3600, 1)

    if count >= 6 and (avg_effort or 0) >= 8:
        state, detail = "fatigued", "Six-plus hard sessions this week. A rest day is training too."
    elif hours_since is not None and hours_since < 12:
        state, detail = "recovering", "You trained within the last 12 hours — go lighter or hit another split."
    elif count == 0:
        state, detail = "fresh", "Nothing logged this week. Good time to start."
    else:
        state, detail = "ready", "Recovery looks fine. Train."

    return {
        "state": state,
        "detail": detail,
        "sessions_this_week": count,
        "avg_effort": avg_effort,
        "hours_since_last": hours_since,
        # Said plainly rather than dressed up as a score.
        "basis": "session count, self-reported effort, and time since last session only "
                 "— no sleep or HRV input.",
    }


AI_COACH_STYLE = (
    "YOU ARE THE BODIEZ COACH — a strength coach writing one training routine for one member.\n"
    "HARD RULES:\n"
    "- Pick exercises ONLY from the catalog list given below. Never invent a movement, and never "
    "name one that needs equipment they don't have — a routine they can't perform is worse than "
    "no routine.\n"
    "- Respect the split, the days per week, and the goal they asked for.\n"
    "- Give every exercise sets, reps and rest seconds. Compound lifts first, isolation after.\n"
    "- Rest: 2-3 min for heavy compounds, 60-90s for isolation. Hypertrophy 8-12 reps, strength "
    "3-6, endurance 15+.\n"
    "- You are not a doctor. No injury diagnosis, no medical advice.\n"
    "OUTPUT: a JSON object {\"name\", \"goal\", \"split\", \"days_per_week\", \"exercises\": "
    "[{\"key\", \"sets\", \"reps\", \"rest_seconds\", \"superset_group\", \"notes\"}]}. "
    "JSON only, no prose around it."
)


def ai_plan(user, goal, equipment, days_per_week=3, split="custom", focus=None):
    """StatZ: have Corey write a routine from the catalog. Returns (plan, error).

    The model is handed the filtered exercise list — the movements this member
    can actually do in the room they described — and told to pick from it. That
    constraint is what makes the output usable rather than a plausible-sounding
    plan featuring a machine they don't own.
    """
    from .catalog import exercises_for

    available = exercises_for(equipment=equipment, muscles=focus)
    if not available:
        return None, ("Nothing in the catalog matches that equipment. Add a few more items — "
                      "bodyweight alone still gets you a real routine.")

    catalog_lines = "\n".join(
        f"- {e['key']}: {e['name']} ({e['muscle']}, {e['pattern']}, {e['difficulty']})"
        for e in available[:120]
    )
    prompt = (
        f"Goal: {goal}. Split: {split}. Days per week: {days_per_week}."
        + (f" Focus muscles: {', '.join(focus)}." if focus else "")
        + f"\n\nEXERCISES YOU MAY USE:\n{catalog_lines}"
    )

    try:
        import anthropic

        from apps.economy.occ import MODEL_BY_VOICE, OCC_LLM_MODEL, _create_with_fallback

        client = anthropic.Anthropic()
        resp = _create_with_fallback(
            client, MODEL_BY_VOICE.get("corey-gpt", OCC_LLM_MODEL), OCC_LLM_MODEL,
            max_tokens=2000, system=AI_COACH_STYLE,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    except Exception as exc:
        log.info("bodiez: AI coach unavailable (%s)", str(exc)[:160])
        return None, "The AI coach isn't available right now."

    import json
    import re

    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None, "The coach didn't return a usable plan."
    try:
        plan = json.loads(match.group(0))
    except ValueError:
        return None, "The coach didn't return a usable plan."

    # Trust nothing: drop any exercise the member can't actually perform, even
    # though the prompt forbade it. A model that hallucinates one lift shouldn't
    # produce a routine that half-works.
    allowed = {e["key"] for e in available}
    kept = [x for x in (plan.get("exercises") or [])
            if isinstance(x, dict) and x.get("key") in allowed]
    if not kept:
        return None, "The coach picked exercises you don't have the equipment for."
    plan["exercises"] = kept[:20]
    plan["dropped"] = len(plan.get("exercises") or []) != len(kept)
    return plan, ""
