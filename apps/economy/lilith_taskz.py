"""Lilith — the task manager, and the reward rules that keep it from being a mint.

The blueprint calls it "Apple Things-style productivity with Music ConnectZ
mission logic". The productivity half is easy. The half that can sink the
platform is the rewards, so that is what most of this file is about.

**The danger, stated plainly.** Paying a member currency for ticking a box
they typed themselves is paying them to type. Write "task: breathe", tick it,
collect, repeat — the substance rule's exact failure case ("could a member get
a good number without getting good?"), with a wallet attached.

**The shape that fixes it: Lilith routes, it does not mint.** A task that
points at a real action — record a take, rate three posts, reply to a collab —
pays whatever that action already pays, through the hooks those actions
already have. Lilith adds XP and a streak. It does not hand out a second
reward for the same work, and it never invents one for work nobody can see.

Corey's call, against the recommendation on this page and recorded here
because a decision is worth more written down than won: a self-made task DOES
pay a token 🍥, hard-capped. So the caps below are not belt-and-braces, they
are the only thing between this feature and a faucet. Read them as load-
bearing.

Four numbers, anchored to the economy that already exists rather than
invented: a referral pays 300/100, onboarding pays 150, a rating pays 1 ⚡
against a 20/day cap, and a ZodiacZ bonus is 20/50 with a 3/day cap.
"""
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

# The choice tuples live in models.py beside the columns they define, exactly
# as FUNNEL_KINDS does — a `choices=` argument is part of a column, and
# keeping it here would mean models.py importing this file while this file
# imports models.py.
from .models import (BUCKETS, KINDS, LilithPayout, LilithRoutine,  # noqa: E402
                     LilithSponsorship, LilithTask, SOURCES)


# ------------------------------------------------------------- the economy

# A self-made task. One coin, three a day — the same daily ceiling ZodiacZ
# uses, for the same reason: it stops somebody clearing the board in one
# afternoon. 3/day is ~90 a month, under a third of one referral.
SELF_TASK_SPINAZ = 1
SELF_TASK_DAILY_CAP = 3
# NO ⚡ on a self-made task, deliberately. Paying a token coin for a typed
# checkbox is already one faucet more than this file recommends; adding a
# second currency to the same unverified action doubles it for nothing. The
# XP is the reward here, and XP is the resource effort is allowed to move.
SELF_TASK_ENERGY = 0

# XP is the resource effort is allowed to move (CLAUDE.md: "XP and badges may
# reward effort. Ratings and skill levels may not"), so it scales with the
# work and needs no cap of its own.
XP_FOR = {"quick": 5, "standard": 10, "deep": 25, "boss": 40, "auto": 0, "statz": 15}

# Keeping a routine is the one thing here that cannot be faked by typing —
# you cannot backdate consistency. So it is the biggest payer, and it pays at
# milestones rather than per tick so it is a habit rather than a wage.
ROUTINE_MILESTONES = {7: 20, 30: 50, 100: 150}                # daily (kept under this name: others read it)
# ⚡ beside the coin at each milestone. Cheap for us, and it hands back the
# capacity to keep doing the thing that earned it — which is the point of a
# streak reward rather than a trophy.
ROUTINE_MILESTONE_ENERGY = {7: 10, 30: 25, 100: 50}

# Weekly and monthly routines count PERIODS, so their rungs are fewer — but the same three payouts.
# That is deliberate: what cannot be faked is TIME, and 26 weeks or 12 months takes longer than 100
# days, with far fewer ticks to farm. Each rung is the same 20 / 50 / 150 🍥 (and ⚡) as the daily one.
CADENCE_MILESTONES = {
    "daily": ROUTINE_MILESTONES,
    "weekly": {4: 20, 12: 50, 26: 150},
    "monthly": {3: 20, 6: 50, 12: 150},
}
CADENCE_MILESTONE_ENERGY = {
    "daily": ROUTINE_MILESTONE_ENERGY,
    "weekly": {4: 10, 12: 25, 26: 50},
    "monthly": {3: 10, 6: 25, 12: 50},
}
CADENCES = ("daily", "weekly", "monthly")
PERIOD_NOUN = {"daily": "day", "weekly": "week", "monthly": "month"}
PERIOD_NOW = {"daily": "today", "weekly": "this week", "monthly": "this month"}

# Three in a day, and every Today task cleared. XP only: both are counts of
# things already rewarded once, and paying coin again would be paying twice
# for one afternoon.
COMBO_CHAIN_XP = 15
CLEAN_SWEEP_XP = 30

# ⚡ IS THE RIGHT CURRENCY FOR HELPING, AND 🍥 IS NOT.
#
# Energy cannot be cashed out and cannot leave the platform — it is spent
# HERE, so paying it funds more activity instead of inflating anything. 🍥
# converts to PromptZ at the catalog.SPINAZ_PER_PROMPTZ rate, which is real
# model spend, so every coin has a cost to us. The rule that falls out:
# **pay ⚡ generously, pay 🍥 carefully.**
#
# 50 ⚡ is Corey's number and it is the right one. Onboarding grants exactly
# 50, so this says helping a newcomer is worth what arriving is worth; a free
# member passively regenerates 48 a day (ENERGY_FLOOR_PER_HOUR), so it is
# about a day of capacity; and a rating pays 1, so it ranks this at fifty
# ratings — which is roughly the truth.
COLLAB_WITH_BEGINNER_ENERGY = 50
# Capped per day like every other faucet: many beginners must not become a
# job, and the ceiling is what stops it.
COLLAB_WITH_BEGINNER_DAILY_CAP = 3

# Helping somebody who is still new. The largest payout in this file, and the
# only one that is not paid for effort at all — see `graduate` below.
#
# Double the collab grant in ⚡ because graduation is the OUTCOME the platform
# actually wants and is the hardest thing here to fake, being gated on a third
# party's behaviour rather than the helper's.
SPONSOR_GRADUATION_ENERGY = 100
SPONSOR_GRADUATION_SPINAZ = 200
# And helping somebody already established. Deliberately small: the platform's
# scarce good is a member's FIRST real collaboration, not their fiftieth.
HELP_GRADUATED_SPINAZ = 5
HELP_GRADUATED_DAILY_CAP = 3


def tier_limits(tier):
    """What each tier gets, per the blueprint's automation boundaries.

    A ladder of HOW MANY and HOW CLEVER, never whether: a free member has a
    working task manager, which is the whole product Apple gives away. The
    tiers buy automation, not access — `catalog.py`'s rule that a limit may
    never say "whether" applies here as much as anywhere.
    """
    t = (tier or "free").lower()
    return {
        "active_tasks": {"free": 50, "premium": 250}.get(t, 1000),
        "routines": {"free": 3, "premium": 12}.get(t, 50),

        # These five were `t == "statz"` — five booleans directly under a
        # docstring promising a ladder of how many and how clever, "never
        # whether". They are numbers now, and every tier gets a working one.
        #
        # It mattered more than an unbuilt feature usually would, because the
        # tab RENDERS this: a free member was told "StatZ adds auto-schedule,
        # persona automation and AI breakdowns" on every visit. A capability
        # named and withheld is how somebody decides an app is not for them,
        # and they decide it before the feature they were refused even exists.
        "auto_schedule_days": {"free": 1, "premium": 7}.get(t, 30),
        "automation_rules": {"free": 2, "premium": 10}.get(t, 50),
        "recurring_quests": {"free": 1, "premium": 5}.get(t, 25),
        # Priced per run out of the member's daily AI allowance, like every
        # other model call — so the ladder here is the allowance, not a flag.
        "ai_breakdown": True,

        # A SORT, not a score. It was "smart_priority", which would have been a
        # single blended number computed from deadline, money impact and
        # "growth value" — fields the member typed, presented back as
        # judgement. Members learn to pad the fields rather than do the work,
        # which is `directz_ai_rating` wearing a to-do list. Ordering by a
        # named axis is honest; scoring by a secret blend of them is not.
        "priority_sort": True,

        # Premium and up.
        "reward_customization": t in ("premium", "statz"),
    }


# ------------------------------------------------------------------- voice

# Lilith is warm and certain, never chirpy, and never a nag. A task manager
# that scolds is one people close — the whole reason somebody keeps an app
# like this is that opening it does not feel like being told off.
#
# Written here rather than in the client for the reason every string in this
# codebase is: one voice stated in three screens reads three ways within a
# year. The art is gothic and the voice is soft on purpose — warmth in a dark
# room reads as intimacy; the same words on a bright one read as a corporate
# assistant.
VOICE = {
    "greet_morning": "Morning. Three things matter today — the rest can wait.",
    "greet_evening": "Late one. Pick the smallest thing and let the rest go.",
    "empty": "Nothing here. That's allowed.",
    "done_one": "Good. That one's closed.",
    "combo": "Three today. You're in it now.",
    "sweep": "Everything you set out to do. Rare, that.",
    "streak_kept": "{days} in a row. You keep showing up.",
    "streak_lost": "The run ended. It counted while it lasted — start another.",
    "milestone": "{days}. That isn't luck.",
    "sponsor_paid": "{who} made their first collab. You had a hand in that.",
    "capped": "That's today's coin. The XP still counts, and so does tomorrow.",
}

# The four models live in models.py with every other model in this app.
# Django only discovers models.py, so a model class in here would never get a
# table — silently, with no migration and no error. The RULES stay here; the
# columns live where the app actually looks for them.
# ------------------------------------------------------------- paying out

def _paid_today(user, kind):
    """How many payouts of one kind this member has had in 24 hours."""
    since = timezone.now() - timedelta(hours=24)
    return LilithPayout.objects.filter(user=user, kind=kind, created_at__gte=since).count()


def _pay(user, kind, *, spinaz=0, energy=0, xp=0, ref=""):
    """Move the resources and write the row. One place, so the ledger cannot
    disagree with the wallet."""
    from .models import award_energy, award_spinaz
    # app_key/target ride along so the LogZ row is a door back to Lilith
    # rather than a sentence — the gap CLAUDE.md names as this rule's own
    # counter-example. A reward written today with no way back to what earned
    # it is one more row for that sweep to fix later.
    if spinaz:
        award_spinaz(user, spinaz, f"Lilith — {kind}", app_key="lilith", target="lilith:logbook")
    if energy:
        award_energy(user, energy, f"Lilith — {kind}", app_key="lilith", target="lilith:logbook")
    if xp:
        _award_xp(user, xp)
    return LilithPayout.objects.create(user=user, kind=kind, spinaz=spinaz,
                                       energy=energy, xp=xp, ref=str(ref)[:64])


def _award_xp(user, xp):
    """XP goes to the SkillZ profile that already holds it, under Lilith's own
    app_key. A second XP store would be a second answer to "what level am I"."""
    try:
        from apps.skillz.models import TrainingProfile
        prof, _ = TrainingProfile.objects.get_or_create(user=user, app_key="lilith")
        prof.xp = (prof.xp or 0) + xp
        prof.save(update_fields=["xp"])
    except Exception:
        # A task must complete whether or not the XP lands, the same way
        # signbonus.try_award swallows: the member did the thing.
        pass


def complete(task):
    """Tick a task. Returns what it paid and why, for the screen to state.

    The whole rule in one function: **what a task pays depends on where it
    came from**, because that is the only thing that says whether anybody
    verified it happened.
    """
    if task.done_at:
        return {"already": True, "spinaz": 0, "energy": 0, "xp": 0}

    task.done_at = timezone.now()
    task.bucket = "logbook"
    task.save(update_fields=["done_at", "bucket"])

    xp = XP_FOR.get(task.kind, 10)
    spinaz = energy = 0
    note = ""

    if task.source == "self":
        # Typed by the member and verified by nobody. Token coin, hard cap.
        if _paid_today(task.user, LilithPayout.KIND_SELF) < SELF_TASK_DAILY_CAP:
            spinaz = SELF_TASK_SPINAZ
        else:
            note = VOICE["capped"]
    elif task.source == "auto":
        # Automation may not mint. The blueprint's own boundary.
        spinaz = 0
    # `platform` pays nothing HERE on purpose: the action it points at has its
    # own economy and already paid. Paying again would be paying twice for one
    # piece of work, which is how a reward stops meaning anything.

    _pay(task.user, LilithPayout.KIND_SELF if spinaz else "task_xp",
         spinaz=spinaz, energy=energy, xp=xp, ref=f"task:{task.pk}")

    out = {"already": False, "spinaz": spinaz, "energy": energy, "xp": xp,
           "note": note, "said": VOICE["done_one"]}
    out.update(_combo_and_sweep(task.user))
    if task.routine_id:
        out["routine"] = keep_routine(task.routine)
    return out


def _combo_and_sweep(user):
    """Three in a day, and a cleared Today. XP only — both are counts of work
    already rewarded once, and coin again would pay twice for one afternoon."""
    since = timezone.now() - timedelta(hours=24)
    done = LilithTask.objects.filter(user=user, done_at__gte=since).count()
    out = {}
    if done == 3:
        _award_xp(user, COMBO_CHAIN_XP)
        out["combo"] = {"xp": COMBO_CHAIN_XP, "said": VOICE["combo"]}
    left = LilithTask.objects.filter(user=user, bucket="today", done_at__isnull=True).count()
    if not left and done:
        _award_xp(user, CLEAN_SWEEP_XP)
        out["sweep"] = {"xp": CLEAN_SWEEP_XP, "said": VOICE["sweep"]}
    return out


def period_start(d, cadence):
    """The first day of the period `d` falls in: the day, the ISO week's Monday, the month's 1st."""
    if cadence == "weekly":
        return d - timedelta(days=d.weekday())
    if cadence == "monthly":
        return d.replace(day=1)
    return d


def previous_period_start(start, cadence):
    if cadence == "weekly":
        return start - timedelta(days=7)
    if cadence == "monthly":
        return (start - timedelta(days=1)).replace(day=1)
    return start - timedelta(days=1)


def kept_this_period(routine, today=None):
    today = today or timezone.localdate()
    c = routine.cadence if routine.cadence in CADENCES else "daily"
    return bool(routine.last_done and period_start(routine.last_done, c) == period_start(today, c))


def _count(n, cadence):
    return f"{n} {PERIOD_NOUN[cadence]}{'' if n == 1 else 's'}"


def _stable_ref(routine, streak):
    """A reference for a milestone that survives deleting and re-making the routine. The rung is
    once-for-life per STARTER (or per title for one the member wrote), not once per row — else the
    way to re-earn 20 🍥 at day seven is to delete the routine and start over."""
    import hashlib
    who = routine.template or "t" + hashlib.sha1((routine.title or "").strip().lower().encode()).hexdigest()[:10]
    return f"ms:{who}:{routine.cadence}:{streak}"[:64]


def keep_routine(routine, on=None):
    """Advance a streak, and pay a milestone the first time it is reached.

    Consistency is the one thing in this app that cannot be faked by typing —
    you cannot backdate a habit — which is why it is the biggest earner here
    and why it needs no cap beyond once-each. A streak counts PERIODS in a row:
    days, ISO weeks (Monday to Sunday) or calendar months, per `routine.cadence`.
    Keeping a weekly routine twice in one week is one keep, not two.
    """
    cadence = routine.cadence if routine.cadence in CADENCES else "daily"
    today = on or timezone.localdate()
    if kept_this_period(routine, today):
        return {"streak": routine.streak, "already": True}

    now_p = period_start(today, cadence)
    last_p = period_start(routine.last_done, cadence) if routine.last_done else None
    routine.streak = routine.streak + 1 if last_p == previous_period_start(now_p, cadence) else 1
    routine.longest = max(routine.longest, routine.streak)
    routine.last_done = today

    paid = None
    rungs = CADENCE_MILESTONES[cadence]
    reward = rungs.get(routine.streak)
    ref = _stable_ref(routine, routine.streak)
    if reward and routine.streak not in (routine.paid_milestones or []) \
            and not LilithPayout.objects.filter(user=routine.user, kind=LilithPayout.KIND_MILESTONE, ref=ref).exists():
        energy = CADENCE_MILESTONE_ENERGY[cadence].get(routine.streak, 0)
        _pay(routine.user, LilithPayout.KIND_MILESTONE, spinaz=reward, energy=energy, ref=ref)
        routine.paid_milestones = list(routine.paid_milestones or []) + [routine.streak]
        paid = {"days": routine.streak, "periods": routine.streak, "cadence": cadence,
                "spinaz": reward, "energy": energy,
                "said": VOICE["milestone"].format(days=_count(routine.streak, cadence))}

    routine.save(update_fields=["streak", "longest", "last_done", "paid_milestones"])
    return {"streak": routine.streak, "longest": routine.longest, "cadence": cadence,
            "milestone": paid, "said": VOICE["streak_kept"].format(days=_count(routine.streak, cadence))}


# --------------------------------------------------------------- the trash

TRASH_DAYS = 30


def open_tasks(user):
    """Tasks that are still to do: not done, and not in the Trash. Every ceiling, sweep and count
    reads this one definition, so a trashed task cannot fill a tier's quota or tick itself."""
    return LilithTask.objects.filter(user=user, done_at__isnull=True).exclude(bucket="trash")


def live_routines(user):
    return LilithRoutine.objects.filter(user=user, trashed_at__isnull=True)


def purge_trash(user):
    """Empty what has sat in the Trash for TRASH_DAYS. Run on a board read (no cron; idempotent)."""
    cutoff = timezone.now() - timedelta(days=TRASH_DAYS)
    LilithTask.objects.filter(user=user, bucket="trash", trashed_at__lt=cutoff).delete()
    LilithRoutine.objects.filter(user=user, trashed_at__lt=cutoff).delete()


# ------------------------------------------- call-to-action: Lilith keeps them

def _progress_label(n, goal, cadence=None):
    return {"done": n, "goal": goal, "met": n >= goal,
            "period": PERIOD_NOW.get(cadence, "since you set it")}


def sweep_routine(routine):
    """Keep a verified routine for the member, from the platform's own records.

    Only rows created AFTER the routine existed count (you cannot backdate a habit), and the
    streak is caught up period by period — so the board not being opened for a week does not
    break a run the member actually kept. Returns (kept: list of keep_routine results, progress).
    """
    from . import lilith_actions as A
    cadence = routine.cadence if routine.cadence in CADENCES else "daily"
    goal = max(1, routine.goal or 1)
    since = routine.created_at
    dates = [A.localdate(ts) for ts in A.events(routine.user, routine.action, since)]
    per = {}
    for d in dates:
        p = period_start(d, cadence)
        n, latest = per.get(p, (0, d))
        per[p] = (n + 1, max(latest, d))
    last_p = period_start(routine.last_done, cadence) if routine.last_done else None
    kept = []
    for p in sorted(per):
        n, latest = per[p]
        if n >= goal and (last_p is None or p > last_p):
            res = keep_routine(routine, on=latest)
            if not res.get("already"):
                kept.append(res)
    now_p = period_start(timezone.localdate(), cadence)
    return kept, _progress_label(per.get(now_p, (0, None))[0], goal, cadence)


def sweep_task(task):
    """Tick a verified task when the records show the member did it `goal` times since it was made."""
    from . import lilith_actions as A
    goal = max(1, task.goal or 1)
    n = len(A.events(task.user, task.action, task.created_at))
    if n >= goal and not task.done_at:
        return complete(task), _progress_label(n, goal)
    return None, _progress_label(n, goal)


def sweep(user):
    """Run every verified task and routine. Returns (swept, progress): what Lilith just closed,
    and where each stands. Idempotent, and it never raises — the board must open."""
    swept, progress = [], {}
    try:
        for t in open_tasks(user).exclude(action=""):
            res, prog = sweep_task(t)
            progress[("task", t.pk)] = prog
            if res:
                swept.append({"kind": "task", "id": t.pk, "title": t.title, **res})
        for r in live_routines(user).exclude(action=""):
            kept, prog = sweep_routine(r)
            progress[("routine", r.pk)] = prog
            for k in kept:
                swept.append({"kind": "routine", "id": r.pk, "title": r.title, **k})
    except Exception:                                          # pragma: no cover
        import logging
        logging.getLogger(__name__).exception("lilith sweep failed")
    return swept, progress


# -------------------------------------------------- helping somebody new

# How long an account counts as "new" if it never graduates. Without a ceiling
# a sponsorship sits open forever and pays out on a collab two years later,
# which is not the behaviour anybody is being rewarded for.
NEW_FOR_DAYS = 60


def is_beginner(user):
    """Still new, in the sense Corey defined: has not yet completed a real
    collab or battle WITH ANOTHER MEMBER.

    Not account age, and not post count. Graduation is a two-sided act —
    somebody else had to agree — which is exactly why it is the line: it is
    the first thing a member does that another person had to say yes to.
    """
    from .models import BattleEntry, CollabDeal

    # RELEASED, not merely created. A draft nobody funded is an intention; a
    # released deal is escrow that actually paid out, which is the point at
    # which two people finished something together.
    #
    # `participants` is a JSON list of {"username": ...}, so membership is
    # checked against the column rather than a join — there is no FK to
    # follow, and inventing one here would be a second model of who is in a
    # deal.
    if CollabDeal.objects.filter(initiator=user, status=CollabDeal.STATUS_RELEASED).exists():
        return False
    if _in_released_deal(user):
        return False
    if BattleEntry.objects.filter(user=user).exists():
        return False
    return True


def _in_released_deal(user):
    """Is this member named in a released deal they did not initiate?

    `participants__contains` is Postgres-only and the suite runs on SQLite —
    the gap CLAUDE.md says to respect. `offerz_engine` answers that by
    skipping the query where it cannot run, which is right there (a missing
    offer) and wrong here: skipping would make every non-initiator a beginner
    forever, on the backend every test uses, so the guard against paying
    somebody twice would be untested and would look like it worked.

    So the fallback scans in Python instead, bounded to deals touched since
    the member joined — a deal released before they existed cannot name them.
    """
    from django.db import connection
    from .models import CollabDeal

    qs = CollabDeal.objects.filter(status=CollabDeal.STATUS_RELEASED)
    if connection.vendor == "postgresql":
        return qs.filter(participants__contains=[{"username": user.username}]).exists()
    rows = qs.filter(updated_at__gte=user.date_joined).values_list("participants", flat=True)
    return any(isinstance(e, dict) and e.get("username") == user.username
               for parts in rows[:2000] for e in (parts or []))


def sponsor(helper, newcomer):
    """Record that `helper` is helping `newcomer`. Pays nothing yet."""
    if helper == newcomer or not is_beginner(newcomer):
        return None
    row, _ = LilithSponsorship.objects.get_or_create(helper=helper, newcomer=newcomer)
    return row


def graduate(newcomer, partner=None, partners=()):
    """The newcomer completed a real collab or battle. Pay whoever helped.

    Every guard lives here rather than at the call site, because a payout rule
    spread across three callers is three rules within a year.

    `partners` is the OTHER people on the thing that graduated them — a battle
    or a five-way collab has more than one, and a rule that only checked the
    first would pay a two-person circle the moment they invited a third.
    """
    others = {p for p in (list(partners) + [partner]) if p is not None}
    from .dupez import has_strong, signals_between

    paid = []
    open_rows = LilithSponsorship.objects.filter(newcomer=newcomer, paid=False,
                                                 graduated_at__isnull=True)
    for row in open_rows.select_related("helper"):
        row.graduated_at = timezone.now()

        # 1. A pair cannot be its own loop. If the thing that graduated them
        #    was done WITH the helper, the helper is not a sponsor, they are
        #    the other half of a two-person circle.
        if row.helper in others:
            row.refused = "graduated with the helper"
        # 2. DupeZ decides what one person is, and it already does. A strong
        #    signal between the two accounts means this is somebody paying
        #    themselves.
        elif has_strong(signals_between(row.helper, newcomer)):
            row.refused = "accounts strongly linked"
        # 3. Stale. A sponsorship from eighteen months ago is not what caused
        #    this.
        elif row.created_at < timezone.now() - timedelta(days=NEW_FOR_DAYS):
            row.refused = "sponsorship older than the new-member window"
        else:
            _pay(row.helper, LilithPayout.KIND_SPONSOR,
                 spinaz=SPONSOR_GRADUATION_SPINAZ, energy=SPONSOR_GRADUATION_ENERGY,
                 ref=f"grad:{newcomer.pk}")
            row.paid = True
            paid.append({
                "helper": row.helper.username,
                "spinaz": SPONSOR_GRADUATION_SPINAZ,
                "energy": SPONSOR_GRADUATION_ENERGY,
                "said": VOICE["sponsor_paid"].format(who=newcomer.username),
            })
        row.save(update_fields=["graduated_at", "paid", "refused"])
    return paid


def collabed_with_beginner(user, other, *, beginner=None):
    """`user` completed a collab or battle with somebody still new. Pay ⚡.

    Separate from sponsorship and much smaller: this is the act itself rather
    than the outcome of helping somebody over months, and it happens far more
    often, so it is capped per day.

    **`beginner` must be read BEFORE the thing completes.** `is_beginner`
    answers off released deals and battle entries, so by the time a caller has
    one to report, the newcomer is no longer new by its own definition and
    every one of these payouts would be zero. The ordering trap is the whole
    reason this parameter exists; `settle_together` is the caller that gets it
    right.
    """
    from .dupez import has_strong, signals_between
    if user == other:
        return None
    if not (is_beginner(other) if beginner is None else beginner):
        return None
    if has_strong(signals_between(user, other)):
        return None
    if _paid_today(user, "collab_beginner") >= COLLAB_WITH_BEGINNER_DAILY_CAP:
        return {"capped": True, "energy": 0, "said": VOICE["capped"]}
    _pay(user, "collab_beginner", energy=COLLAB_WITH_BEGINNER_ENERGY,
         ref=f"beginner:{other.pk}")
    return {"capped": False, "energy": COLLAB_WITH_BEGINNER_ENERGY}


def helped_graduated(user, other, *, beginner=None):
    """The same act with somebody already established. Deliberately small.

    The platform's scarce good is a member's FIRST real collaboration, not
    their fiftieth — so this exists to not be zero, rather than to compete.
    """
    if user == other:
        return None
    if (is_beginner(other) if beginner is None else beginner):
        return None
    if _paid_today(user, LilithPayout.KIND_HELP) >= HELP_GRADUATED_DAILY_CAP:
        return {"capped": True, "spinaz": 0}
    _pay(user, LilithPayout.KIND_HELP, spinaz=HELP_GRADUATED_SPINAZ, ref=f"help:{other.pk}")
    return {"capped": False, "spinaz": HELP_GRADUATED_SPINAZ}


# ---------------------------------------------- the one call sites make

def beginners_among(users):
    """Who, of these people, is still new — read BEFORE the thing completes.

    Two people finishing a collab together both stop being beginners the
    instant the deal flips to RELEASED, so a caller that asked afterwards
    would find nobody new and pay nothing, forever, with no error to notice.
    That is the entire reason this is a separate call.
    """
    return {u.pk for u in users if u is not None and is_beginner(u)}


def settle_together(users, was_beginner):
    """Everyone who just finished a collab or battle together. Pay the helping.

    `was_beginner` is the set of pks from `beginners_among`, taken before the
    thing completed. One function so the three payouts cannot get out of step
    across call sites — CLAUDE.md's "a payout rule spread across three callers
    is three rules within a year", applied before it happens rather than after.

    It swallows, like `signbonus.try_award`: releasing escrow and entering a
    battle must succeed whether or not a bonus does.
    """
    people = [u for u in users if u is not None]
    out = {"beginner": [], "help": [], "graduated": []}
    try:
        for a in people:
            for b in people:
                if a.pk == b.pk:
                    continue
                if b.pk in was_beginner:
                    got = collabed_with_beginner(a, b, beginner=True)
                    if got and not got.get("capped"):
                        out["beginner"].append({"who": b.username, **got})
                else:
                    got = helped_graduated(a, b, beginner=False)
                    if got and not got.get("capped"):
                        out["help"].append({"who": b.username, **got})
        # And the sponsorships. A newcomer graduates once — the payout goes to
        # whoever signed up to help them, never to the people in the room.
        for b in people:
            if b.pk in was_beginner:
                paid = graduate(b, partners=people)
                if paid:
                    out["graduated"].append({"who": b.username, "paid": paid})
    except Exception:
        pass
    return out

# ------------------------------------------------------- what it all pays

def rewards_table():
    """Every number this file can pay, published BEFORE anything is pressed.

    The cost/gain rule with nothing on the cost side: Lilith spends none of a
    member's resources, so this is all gain — and the gain half is the half
    that gets forgotten. A reward found out by accident is a coincidence, and
    a coincidence changes nobody's behaviour.

    It is also the honest version of the caps. A member who ticks a fourth
    self-made task and gets no coin has met a rule; if they were not told the
    rule first, they have met a bug.
    """
    return [
        {"key": "self_task", "what": "Tick a task you wrote yourself",
         "spinaz": SELF_TASK_SPINAZ, "energy": SELF_TASK_ENERGY,
         "xp": XP_FOR["standard"], "cap": f"{SELF_TASK_DAILY_CAP} a day",
         "why": "Nobody verified it happened, so the coin is a token and the XP is the reward."},
        {"key": "platform_task", "what": "Tick a task that points at a real action",
         "spinaz": 0, "energy": 0, "xp": XP_FOR["standard"], "cap": "",
         "why": "The action itself already pays. Lilith routes you to it, it does not pay twice."},
        {"key": "auto_task", "what": "An automation ticks one for you",
         "spinaz": 0, "energy": 0, "xp": 0, "cap": "",
         "why": "Automation may never mint. A rule that earns while you sleep is pay-to-win."},
        {"key": "combo", "what": "Three done in a day",
         "spinaz": 0, "energy": 0, "xp": COMBO_CHAIN_XP, "cap": "once a day"},
        {"key": "sweep", "what": "Clear everything in Today",
         "spinaz": 0, "energy": 0, "xp": CLEAN_SWEEP_XP, "cap": "once a day"},
    ] + [
        {"key": f"routine_{c}_{d}",
         "what": f"Keep a {c} routine {d} {PERIOD_NOUN[c]}s running",
         "spinaz": CADENCE_MILESTONES[c][d], "energy": CADENCE_MILESTONE_ENERGY[c][d],
         "xp": 0, "cap": "once, for life",
         "why": "Consistency is the one thing here nobody can fake by typing."}
        for c in CADENCES for d in sorted(CADENCE_MILESTONES[c])
    ] + [
        {"key": "collab_beginner",
         "what": "Finish a collab or battle with a member who is still new",
         "spinaz": 0, "energy": COLLAB_WITH_BEGINNER_ENERGY, "xp": 0,
         "cap": f"{COLLAB_WITH_BEGINNER_DAILY_CAP} a day",
         "why": "⚡ is spent here and cannot be cashed out, so it can be generous."},
        {"key": "sponsor_graduation",
         "what": "Somebody you helped completes their first collab or battle",
         "spinaz": SPONSOR_GRADUATION_SPINAZ, "energy": SPONSOR_GRADUATION_ENERGY,
         "xp": 0, "cap": "once per member you help",
         "why": "It pays on THEIR outcome, with somebody other than you, so it cannot be farmed alone."},
        {"key": "help_graduated", "what": "Help a member who is already established",
         "spinaz": HELP_GRADUATED_SPINAZ, "energy": 0, "xp": 0,
         "cap": f"{HELP_GRADUATED_DAILY_CAP} a day",
         "why": "Worth something, deliberately less: the scarce good is a member's FIRST collab."},
    ]


# --------------------------------------------------------------- the board

def _action_bits(obj, progress):
    return {"action": obj.action or "", "goal": obj.goal or 1,
            "verified": bool(obj.action),
            "progress": (progress or {}).get(("task" if isinstance(obj, LilithTask) else "routine", obj.pk))}


def _task_dict(t, progress=None):
    return {**_action_bits(t, progress),
        "id": t.pk, "title": t.title, "note": t.note, "kind": t.kind,
        "bucket": t.bucket, "source": t.source,
        "app_key": t.app_key, "target": t.target,
        "due": t.due.isoformat() if t.due else None,
        "routine_id": t.routine_id,
        "done_at": t.done_at.isoformat() if t.done_at else None,
        # What ticking THIS one pays, on the row, before it is ticked. A board
        # that stated one average price for six different sources would be
        # stating a price nobody can check.
        "pays": {"spinaz": SELF_TASK_SPINAZ if t.source == "self" else 0,
                 "energy": 0,
                 "xp": XP_FOR.get(t.kind, 10)},
        # The cross-pollination half: a task that names an action carries the
        # jump to the control that performs it, not the tab it lives on.
        "open_in": {"tab": t.app_key, "target": t.target} if t.app_key else None,
    }


def _routine_dict(r, progress=None):
    cadence = r.cadence if r.cadence in CADENCES else "daily"
    rungs = CADENCE_MILESTONES[cadence]
    nxt = min((d for d in sorted(rungs) if d > r.streak), default=None)
    kept = kept_this_period(r)
    return {
        **_action_bits(r, progress),
        "id": r.pk, "title": r.title, "note": r.note, "streak": r.streak, "longest": r.longest,
        "cadence": cadence, "unit": PERIOD_NOUN[cadence], "period_now": PERIOD_NOW[cadence],
        "last_done": r.last_done.isoformat() if r.last_done else None,
        "app_key": r.app_key, "target": r.target,
        "open_in": {"tab": r.app_key, "target": r.target} if r.app_key else None,
        # `done_today` is the older name; it now means "kept in this routine's current period".
        "done_today": kept, "done_period": kept,
        "next_milestone": ({"days": nxt, "periods": nxt, "unit": PERIOD_NOUN[cadence],
                            "spinaz": rungs[nxt],
                            "energy": CADENCE_MILESTONE_ENERGY[cadence][nxt],
                            "away": nxt - r.streak} if nxt else None),
    }


def _suggested(user, routines):
    """Routines Lilith thinks this member should have, with the reason. Never raises."""
    try:
        from .lilith_suggest import suggest
        tasks = LilithTask.objects.filter(user=user, done_at__isnull=True).exclude(template="").exclude(bucket="trash")
        return suggest(user, on_board_routines={r.template for r in routines if r.template},
                       on_board_tasks=set(tasks.values_list("template", flat=True)))
    except Exception:                                        # pragma: no cover
        return []


def starters_for(user, tasks, routines):
    """The ready-made tasks and routines, each marked if it is already on this board. Built from
    the rows `board` already fetched, so the catalogue costs no extra query."""
    from . import lilith_starters as ST
    have_t = {t.template for t in tasks if t.template and not t.done_at}
    have_r = {r.template for r in routines if r.template}
    return {
        "tasks": [{**{k: t[k] for k in ("key", "title", "note", "kind", "bucket", "app_key", "target")},
                   "verified": bool(t.get("action")), "goal": t.get("goal", 1),
                   "on_board": t["key"] in have_t,
                   "pays": {"spinaz": 0, "energy": 0, "xp": XP_FOR.get(t["kind"], 10)}}
                  for t in ST.TASKS],
        "routines": [{**{k: r[k] for k in ("key", "title", "note", "cadence", "app_key", "target")},
                      "verified": bool(r.get("action")), "goal": r.get("goal", 1),
                      "on_board": r["key"] in have_r,
                      "milestones": [{"periods": d, "unit": PERIOD_NOUN[r["cadence"]],
                                      "spinaz": CADENCE_MILESTONES[r["cadence"]][d],
                                      "energy": CADENCE_MILESTONE_ENERGY[r["cadence"]][d]}
                                     for d in sorted(CADENCE_MILESTONES[r["cadence"]])]}
                     for r in ST.ROUTINES],
    }


def _greeting():
    """Warm, brief, and never a scold. Hour is the server's, which is wrong for
    somebody in another timezone — so the copy never claims a clock, only a
    mood, and being wrong about that costs nothing."""
    return VOICE["greet_morning"] if timezone.localtime().hour < 17 else VOICE["greet_evening"]


def board(user):
    from .models import membership_for
    from . import lilith_actions as A
    tier = membership_for(user).tier
    limits = tier_limits(tier)
    # Lilith closes what the member has already DONE before drawing the board, so the board is
    # never behind the records. (A write on a read, deliberately: there is no cron to do it, and
    # every call is idempotent.)
    purge_trash(user)
    swept, progress = sweep(user)

    tasks = list(LilithTask.objects.filter(user=user).select_related()[:500])
    open_list = [t for t in tasks if not t.done_at and t.bucket != "trash"]
    buckets = {key: [] for key, _ in BUCKETS}
    for t in tasks:
        buckets.setdefault(t.bucket, []).append(_task_dict(t, progress))

    routines = list(live_routines(user))
    trashed_routines = list(LilithRoutine.objects.filter(user=user, trashed_at__isnull=False))
    since = timezone.now() - timedelta(hours=24)
    return {
        "said": _greeting() if open_list else VOICE["empty"],
        "tier": tier,
        "limits": limits,
        "buckets": buckets,
        "kinds": [{"key": k, "label": v, "xp": XP_FOR.get(k, 10)} for k, v in KINDS],
        "bucket_labels": [{"key": k, "label": v} for k, v in BUCKETS],
        "routines": [_routine_dict(r, progress) for r in routines],
        "trash_routines": [{**_routine_dict(r), "trashed_at": r.trashed_at.isoformat()} for r in trashed_routines],
        "trash_days": TRASH_DAYS,
        "swept": swept,
        "actions": A.catalogue(),
        "suggested": _suggested(user, routines),
        "starters": starters_for(user, [t for t in tasks if t.bucket != "trash"], routines),
        "rewards": rewards_table(),
        # The caps, as counters rather than rules, so a member can see how
        # much of today's allowance is left before they spend the effort.
        "today": {
            "self_paid": _paid_today(user, LilithPayout.KIND_SELF),
            "self_cap": SELF_TASK_DAILY_CAP,
            "done": LilithTask.objects.filter(user=user, done_at__gte=since).count(),
            "combo_at": 3,
        },
        "at_task_limit": len(open_list) >= limits["active_tasks"],
        "at_routine_limit": len(routines) >= limits["routines"],
    }


# ----------------------------------------------------------------- the API

from rest_framework import status  # noqa: E402
from rest_framework.permissions import IsAuthenticated  # noqa: E402
from rest_framework.response import Response  # noqa: E402
from rest_framework.views import APIView  # noqa: E402

_KIND_KEYS = {k for k, _ in KINDS}
_BUCKET_KEYS = {k for k, _ in BUCKETS}


class LilithBoardView(APIView):
    """GET /api/economy/lilith/ — everything one open of the app needs.

    One request rather than five, because this renders on every open and a
    board assembled from five round trips is a board that flickers.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(board(request.user))


def _clean_action(d, A):
    """(action, goal) from a request: only a key the server verifies, goal 1..50, else ("", 1)."""
    action = str(d.get("action") or "")
    if action not in A.specs():
        return "", 1
    try:
        goal = int(d.get("goal") or 1)
    except (TypeError, ValueError):
        goal = 1
    return action, max(1, min(50, goal))


class LilithTaskListView(APIView):
    """POST /api/economy/lilith/tasks/ — add one."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .models import membership_for
        d = request.data
        title = (d.get("title") or "").strip()
        if not title:
            return Response({"detail": "A task needs a title."}, status=400)

        limits = tier_limits(membership_for(request.user).tier)
        open_now = open_tasks(request.user).count()
        if open_now >= limits["active_tasks"]:
            # A ladder that says HOW MANY, never whether — and it says what
            # the next rung buys rather than only refusing.
            return Response({
                "detail": f"{limits['active_tasks']} open tasks is this tier's ceiling. "
                          "Finish or archive one, or a tier up raises it.",
                "at_limit": True, "active_tasks": limits["active_tasks"],
            }, status=status.HTTP_402_PAYMENT_REQUIRED)

        kind = d.get("kind") if d.get("kind") in _KIND_KEYS else "standard"
        bucket = d.get("bucket") if d.get("bucket") in _BUCKET_KEYS else "inbox"
        # A member may not declare their own task a `platform` one — that is
        # the flag that decides what it pays, and a client that could set it
        # could set its own price.
        source = "platform" if (d.get("app_key") or "").strip() else "self"
        # A call-to-action: the member picks WHAT from the server's list of verifiable actions,
        # and the control it opens comes from that list, not from the request.
        from . import lilith_actions as A
        action, goal = _clean_action(d, A)
        app_key, target = str(d.get("app_key") or "")[:32], str(d.get("target") or "")[:64]
        if action:
            spec = A.specs()[action]
            app_key, target, source = spec["app_key"], spec["target"], "platform"

        t = LilithTask.objects.create(
            user=request.user, title=title[:140],
            note=str(d.get("note") or "")[:2000],
            kind=kind, bucket=bucket, source=source,
            app_key=app_key, target=target, action=action, goal=goal,
            due=d.get("due") or None,
        )
        return Response(_task_dict(t), status=status.HTTP_201_CREATED)


class LilithTaskDetailView(APIView):
    """PATCH / DELETE /api/economy/lilith/tasks/<id>/"""
    permission_classes = [IsAuthenticated]

    def _own(self, request, task_id):
        return LilithTask.objects.filter(pk=task_id, user=request.user).first()

    def patch(self, request, task_id):
        t = self._own(request, task_id)
        if not t:
            return Response({"detail": "No such task."}, status=404)
        d = request.data
        fields = []
        if "title" in d and str(d["title"]).strip():
            t.title = str(d["title"]).strip()[:140]
            fields.append("title")
        if "note" in d:
            t.note = str(d["note"] or "")[:2000]
            fields.append("note")
        if d.get("bucket") in _BUCKET_KEYS:
            t.bucket = d["bucket"]
            t.trashed_at = timezone.now() if d["bucket"] == "trash" else None
            fields.append("trashed_at")
            fields.append("bucket")
        if d.get("kind") in _KIND_KEYS:
            t.kind = d["kind"]
            fields.append("kind")
        if "due" in d:
            t.due = d["due"] or None
            fields.append("due")
        if fields:
            t.save(update_fields=fields)
        return Response(_task_dict(t))

    def delete(self, request, task_id):
        t = self._own(request, task_id)
        if not t:
            return Response({"detail": "No such task."}, status=404)
        t.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class LilithTaskCompleteView(APIView):
    """POST /api/economy/lilith/tasks/<id>/complete/ — tick it, and say what
    it paid.

    The response reports what the SERVER actually paid, never what the row
    said it would: the daily cap is the server's and a client that printed its
    own optimistic figure would be the second place the cap lives.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, task_id):
        t = LilithTask.objects.filter(pk=task_id, user=request.user).first()
        if not t:
            return Response({"detail": "No such task."}, status=404)
        if t.bucket == "trash":
            return Response({"detail": "It's in the Trash. Move it back first."}, status=400)
        if t.action and not t.done_at:
            # Verified: Lilith ticks it herself from the records. A member's own tick would turn a
            # checked claim into a typed one.
            res, prog = sweep_task(t)
            if not res:
                return Response({"verified": True, "done": False, "progress": prog,
                                 "detail": f"Lilith ticks this one herself once you've done it — "
                                           f"{prog['done']} of {prog['goal']} so far."}, status=409)
            res["task"] = _task_dict(t, {("task", t.pk): prog})
            return Response(res)
        out = complete(t)
        out["task"] = _task_dict(t)
        out["today"] = {"self_paid": _paid_today(request.user, LilithPayout.KIND_SELF),
                        "self_cap": SELF_TASK_DAILY_CAP}
        return Response(out)


class LilithRoutineListView(APIView):
    """GET / POST /api/economy/lilith/routines/"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = live_routines(request.user)
        return Response({"routines": [_routine_dict(r) for r in rows],
                         "milestones": [{"days": d, "spinaz": ROUTINE_MILESTONES[d],
                                         "energy": ROUTINE_MILESTONE_ENERGY[d]}
                                        for d in sorted(ROUTINE_MILESTONES)],
                         "cadences": {c: [{"periods": d, "unit": PERIOD_NOUN[c],
                                           "spinaz": CADENCE_MILESTONES[c][d],
                                           "energy": CADENCE_MILESTONE_ENERGY[c][d]}
                                          for d in sorted(CADENCE_MILESTONES[c])] for c in CADENCES}})

    def post(self, request):
        from .models import membership_for
        d = request.data
        title = (d.get("title") or "").strip()
        if not title:
            return Response({"detail": "A routine needs a title."}, status=400)
        limits = tier_limits(membership_for(request.user).tier)
        if live_routines(request.user).count() >= limits["routines"]:
            return Response({
                "detail": f"{limits['routines']} routines is this tier's ceiling. "
                          "A tier up raises it.",
                "at_limit": True, "routines": limits["routines"],
            }, status=status.HTTP_402_PAYMENT_REQUIRED)
        cadence = d.get("cadence") if d.get("cadence") in CADENCES else "daily"
        from . import lilith_actions as A
        action, goal = _clean_action(d, A)
        app_key, target = str(d.get("app_key") or "")[:32], str(d.get("target") or "")[:64]
        if action:
            spec = A.specs()[action]
            app_key, target = spec["app_key"], spec["target"]
        r = LilithRoutine.objects.create(
            user=request.user, title=title[:140], cadence=cadence,
            note=str(d.get("note") or "")[:500], action=action, goal=goal,
            app_key=app_key, target=target,
        )
        return Response(_routine_dict(r), status=status.HTTP_201_CREATED)


class LilithRoutineDetailView(APIView):
    """POST (keep) / DELETE /api/economy/lilith/routines/<id>/"""
    permission_classes = [IsAuthenticated]

    def post(self, request, routine_id):
        r = LilithRoutine.objects.filter(pk=routine_id, user=request.user).first()
        if not r:
            return Response({"detail": "No such routine."}, status=404)
        if r.trashed_at:
            return Response({"detail": "It's in the Trash. Move it back first."}, status=400)
        if r.action:
            kept, prog = sweep_routine(r)
            if not kept and not kept_this_period(r):
                return Response({"verified": True, "kept": False, "progress": prog,
                                 "detail": f"Lilith keeps this one herself once you've done it — "
                                           f"{prog['done']} of {prog['goal']} {PERIOD_NOW[r.cadence]} so far."},
                                status=409)
            out = kept[-1] if kept else {"streak": r.streak, "already": True}
            out["routine"] = _routine_dict(r, {("routine", r.pk): prog})
            return Response(out)
        out = keep_routine(r)
        out["routine"] = _routine_dict(r)
        return Response(out)

    def delete(self, request, routine_id):
        r = LilithRoutine.objects.filter(pk=routine_id, user=request.user).first()
        if not r:
            return Response({"detail": "No such routine."}, status=404)
        r.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class LilithSponsorView(APIView):
    """POST /api/economy/lilith/sponsor/ — say you are helping somebody new.

    It records an intention and pays nothing. The payout happens when THEY
    graduate, with somebody else, which is the whole reason this cannot be
    farmed: the helper controls none of the three conditions.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django.contrib.auth import get_user_model
        who = (request.data.get("username") or "").strip()
        other = get_user_model().objects.filter(username__iexact=who).first()
        if not other:
            return Response({"detail": "No such member."}, status=404)
        row = sponsor(request.user, other)
        if not row:
            return Response({"detail": "They have already completed a collab or "
                                       "battle, so they are not new any more.",
                             "sponsored": False}, status=400)
        return Response({
            "sponsored": True,
            "newcomer": other.username,
            "pays_on": "their first completed collab or battle with somebody else",
            "spinaz": SPONSOR_GRADUATION_SPINAZ,
            "energy": SPONSOR_GRADUATION_ENERGY,
        }, status=status.HTTP_201_CREATED)


def _coach_for(request, spec, key):
    from . import lilith_actions as A
    app = str(request.data.get("app_key") or "")
    from .lilith_starters import INSTRUMENT_AWARE
    if key in INSTRUMENT_AWARE and app in A.coaches():
        return app
    return spec["app_key"]


class LilithStarterAddView(APIView):
    """POST /api/economy/lilith/starters/ {kind: "task"|"routine", key} — put a starter on my board.

    The same ceilings as adding one by hand, and the content comes ONLY from the server's own list
    (`lilith_starters`): a client that could name its own app_key here would be naming its own
    `platform` source, which is the flag that decides what a task pays. Adding one that is already
    on the board is a no-op that says so, rather than a second copy.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from . import lilith_starters as ST
        from .models import membership_for
        kind = str(request.data.get("kind") or "")
        key = str(request.data.get("key") or "")
        limits = tier_limits(membership_for(request.user).tier)

        if kind == "task":
            spec = ST.task_by_key(key)
            if not spec:
                return Response({"detail": "No such starter."}, status=404)
            if open_tasks(request.user).filter(template=key).exists():
                return Response({"detail": "That one is already on your board.", "already": True}, status=200)
            back = LilithTask.objects.filter(user=request.user, template=key, bucket="trash").first()
            if back:                                  # it is in the Trash: bring it back, don't make a second copy
                back.bucket, back.trashed_at = spec["bucket"], None
                back.save(update_fields=["bucket", "trashed_at"])
                return Response({**_task_dict(back), "restored": True}, status=200)
            if open_tasks(request.user).count() >= limits["active_tasks"]:
                return Response({"detail": f"{limits['active_tasks']} open tasks is this tier's ceiling. "
                                           "Finish or archive one, or a tier up raises it.",
                                 "at_limit": True}, status=status.HTTP_402_PAYMENT_REQUIRED)
            t = LilithTask.objects.create(
                user=request.user, title=spec["title"], note=spec["note"], kind=spec["kind"],
                bucket=spec["bucket"], source="platform", app_key=_coach_for(request, spec, key),
                target=spec["target"], template=key,
                action=spec.get("action", ""), goal=spec.get("goal", 1))
            return Response(_task_dict(t), status=status.HTTP_201_CREATED)

        if kind == "routine":
            spec = ST.routine_by_key(key)
            if not spec:
                return Response({"detail": "No such starter."}, status=404)
            # The member may keep it on a different rhythm than the starter's own. Only WHICH of the
            # three, from the closed list: the title, action and goal still come from the server.
            cadence = str(request.data.get("cadence") or spec["cadence"])
            if cadence not in CADENCES:
                return Response({"detail": "Choose daily, weekly or monthly."}, status=400)
            if live_routines(request.user).filter(template=key).exists():
                return Response({"detail": "That one is already on your board.", "already": True}, status=200)
            back = LilithRoutine.objects.filter(user=request.user, template=key, trashed_at__isnull=False).first()
            if back:
                back.trashed_at = None
                back.save(update_fields=["trashed_at"])
                return Response({**_routine_dict(back), "restored": True}, status=200)
            if live_routines(request.user).count() >= limits["routines"]:
                return Response({"detail": f"{limits['routines']} routines is this tier's ceiling. "
                                           "A tier up raises it.", "at_limit": True},
                                status=status.HTTP_402_PAYMENT_REQUIRED)
            r = LilithRoutine.objects.create(
                user=request.user, title=spec["title"], note=spec["note"], cadence=cadence,
                app_key=_coach_for(request, spec, key), target=spec["target"], template=key,
                action=spec.get("action", ""), goal=spec.get("goal", 1))
            return Response(_routine_dict(r), status=status.HTTP_201_CREATED)

        return Response({"detail": "Say whether it is a task or a routine."}, status=400)


class LilithMoveView(APIView):
    """POST /api/economy/lilith/move/ {kind: "task"|"routine", id, to, bucket?} — move any entry anywhere.

    * a task → any bucket (not the Logbook, which is where DONE things go and only ticking puts them there)
    * a task → a routine: `to` is "daily" | "weekly" | "monthly"
    * a routine → a task: `to` is "task" (lands in `bucket`, default Today) — the streak goes with it
    * a routine → another cadence: `to` is "daily" | "weekly" | "monthly"

    The entry keeps what it points at (`app_key`, `target`) and, if it is a verified call-to-action, its
    `action` and `goal` — so a verified task becomes a verified routine and back. What does NOT carry is
    anything that was earned: a finished task cannot be moved (it is history), a routine moved to another
    cadence restarts its run (a streak of weeks is not a streak of days), and a routine turned into a task
    loses its streak — the response says so, and the screen asks first. Nothing here pays, and no loop
    through it pays twice: milestone rungs are once-for-life by their ledger ref, and a task's XP is paid
    on completion, once per task.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .models import membership_for
        d = request.data
        kind, to = str(d.get("kind") or ""), str(d.get("to") or "")
        try:
            pk = int(d.get("id"))
        except (TypeError, ValueError):
            return Response({"detail": "Say which entry."}, status=400)
        limits = tier_limits(membership_for(request.user).tier)

        if kind == "task":
            t = LilithTask.objects.filter(pk=pk, user=request.user).first()
            if not t:
                return Response({"detail": "No such task."}, status=404)
            if t.done_at:
                return Response({"detail": "A finished task is history — it stays in the Logbook."}, status=400)
            if to in _BUCKET_KEYS and to != "logbook":
                if to != "trash" and t.bucket == "trash" and open_tasks(request.user).count() >= limits["active_tasks"]:
                    return Response({"detail": f"{limits['active_tasks']} open tasks is this tier's ceiling — "
                                               "there's no room to bring it back.", "at_limit": True},
                                    status=status.HTTP_402_PAYMENT_REQUIRED)
                t.bucket = to
                t.trashed_at = timezone.now() if to == "trash" else None
                t.save(update_fields=["bucket", "trashed_at"])
                return Response({"moved": "trash" if to == "trash" else "bucket", "task": _task_dict(t)})
            if to in CADENCES:
                if live_routines(request.user).count() >= limits["routines"]:
                    return Response({"detail": f"{limits['routines']} routines is this tier's ceiling. "
                                               "A tier up raises it.", "at_limit": True},
                                    status=status.HTTP_402_PAYMENT_REQUIRED)
                r = LilithRoutine.objects.create(
                    user=request.user, title=t.title, note=(t.note or "")[:500], cadence=to,
                    app_key=t.app_key, target=t.target, action=t.action, goal=t.goal or 1)
                t.delete()
                return Response({"moved": "routine", "routine": _routine_dict(r)}, status=status.HTTP_201_CREATED)
            return Response({"detail": "Move it to a bucket or to a routine cadence."}, status=400)

        if kind == "routine":
            r = LilithRoutine.objects.filter(pk=pk, user=request.user).first()
            if not r:
                return Response({"detail": "No such routine."}, status=404)
            if to == "trash":
                r.trashed_at = timezone.now()
                r.save(update_fields=["trashed_at"])
                return Response({"moved": "trash", "routine": _routine_dict(r)})
            if r.trashed_at and to in CADENCES + ("task",) \
                    and live_routines(request.user).count() >= limits["routines"] and to != "task":
                return Response({"detail": f"{limits['routines']} routines is this tier's ceiling — "
                                           "there's no room to bring it back.", "at_limit": True},
                                status=status.HTTP_402_PAYMENT_REQUIRED)
            if to in CADENCES:
                if to == r.cadence and not r.trashed_at:
                    return Response({"moved": "same", "routine": _routine_dict(r)})
                lost = r.streak
                restored = bool(r.trashed_at)
                # Same cadence out of the Trash is a plain restore — the run is whatever time made it.
                reset = to != r.cadence
                if reset:
                    r.cadence, r.streak, r.last_done = to, 0, None
                r.trashed_at = None
                r.save(update_fields=["cadence", "streak", "last_done", "trashed_at"])
                return Response({"moved": "restored" if restored and not reset else "cadence",
                                "streak_reset": reset and bool(lost), "lost_streak": lost if reset else 0,
                                "routine": _routine_dict(r)})
            if to == "task":
                if open_tasks(request.user).count() >= limits["active_tasks"]:
                    return Response({"detail": f"{limits['active_tasks']} open tasks is this tier's ceiling. "
                                               "Finish or delete one first.", "at_limit": True},
                                    status=status.HTTP_402_PAYMENT_REQUIRED)
                bucket = d.get("bucket") if d.get("bucket") in _BUCKET_KEYS and d.get("bucket") != "logbook" else "today"
                lost = r.streak
                t = LilithTask.objects.create(
                    user=request.user, title=r.title, note=r.note or "", kind="standard", bucket=bucket,
                    source="platform" if r.app_key else "self", app_key=r.app_key, target=r.target,
                    action=r.action, goal=r.goal or 1)
                r.delete()
                return Response({"moved": "task", "lost_streak": lost, "task": _task_dict(t)},
                                status=status.HTTP_201_CREATED)
            return Response({"detail": "Move it to another cadence, or to a task."}, status=400)

        return Response({"detail": "Say whether it is a task or a routine."}, status=400)


class LilithTrashView(APIView):
    """DELETE /api/economy/lilith/trash/ — empty the Trash for good (tasks and routines).

    Anything older than TRASH_DAYS goes on its own; this is the member doing it sooner. Irreversible,
    so the screen asks first and the response says how many went."""
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        t, _ = LilithTask.objects.filter(user=request.user, bucket="trash").delete()
        r, _ = LilithRoutine.objects.filter(user=request.user, trashed_at__isnull=False).delete()
        return Response({"deleted": {"tasks": t, "routines": r}})
