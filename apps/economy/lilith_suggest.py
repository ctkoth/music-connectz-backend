"""Lilith suggests routines — from who the member says they are, and what they actually do.

Two honest signals, and nothing else:

* **Personas** — what they declared (an Independent Artist, a Manager, a Ghost Writer). A
  declaration is allowed to steer a suggestion for the reason PersonalitieZ is allowed to: it
  moves what they are SHOWN and nothing about what anyone is called, rated or paid.
* **Actions** — what the platform's own records say they did lately (`lilith_actions`). Two kinds
  of suggestion come out of it: *lock in a habit* (they already did this three or more times in
  two weeks — a streak is the cheapest next step) and *close a gap* (they take but never post, they
  post but never rate, they rate but never message).

It only SUGGESTS. Nothing is added to a board until the member taps it, so "auto-suggest" can never
become "auto-add a routine you didn't ask for" — which would also be a way to hit the routine
ceiling for them. Every suggestion carries `why`, in words, so a recommendation is never a
mystery: a ranked list with no reasons is the unexplained score this codebase refuses.

Counts are cached for ten minutes per member (one count query per verified action is too much to
pay on every open of a screen people open all day) and the cache only ever makes a suggestion
late, never wrong: a suggestion for something already on the board is dropped at render time.
"""
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from . import lilith_actions as A
from . import lilith_starters as ST

WINDOW_DAYS = 14
HABIT_AT = 3           # this many in the window and it is a habit waiting to be a streak
MAX_SUGGESTIONS = 5
MAX_TASK_SUGGESTIONS = 4
CACHE_SECONDS = 600

# persona key (letters only, lower-case — `sentencez.persona_keys` form) → starter routines, in
# the order they matter to that persona. Both the short key and the long name are listed because a
# persona is stored either way.
PERSONA_ROUTINES = {
    ("indieartist", "independentartist"): ["breathe_first", "with_the_click", "weekly_challenge", "ship_one"],
    ("producer",): ["ship_one", "release_day", "tidy_portfolio", "weekly_challenge"],
    ("mixengineer",): ["ship_one", "skill_check", "tidy_portfolio"],
    ("ghostwriter",): ["one_paragraph", "ship_one", "tidy_portfolio"],
    ("designer", "videographer", "director"): ["ship_one", "tidy_portfolio", "read_the_room"],
    ("manager", "arscout"): ["reach_out", "read_the_room", "move_a_collab", "skill_check"],
    ("weightlifter",): ["move_body", "one_paragraph"],
    ("dancer", "actor", "actress", "mime"): ["ship_one", "move_body", "tidy_portfolio"],
    ("developer",): ["ship_one", "one_paragraph"],
}

# (have, lack, routine key, sentence). `{n}` is how many of `have` in the window.
GAPS = [
    ("take_scored", "post_made", "ship_one",
     "You've had {n} take{s} scored lately and posted none. A post is how anyone finds you."),
    ("post_made", "rating_given", "three_ears",
     "You post, but haven't rated anyone lately. Ratings are +1 ⚡ each and make your own posts easier to find."),
    ("rating_given", "message_sent", "reach_out",
     "You've rated {n} lately. Tell one of those creators what you liked — it's the start of a collab."),
    ("take_scored", "skill_training", "weak_spot",
     "You record, but haven't trained. One drill a week moves whichever dimension scored lowest."),
    ("take_scored", "journal_entry", "one_paragraph",
     "You've had {n} take{s} scored lately. A few lines about what you learned makes the next one better."),
    ("post_made", "collab_started", "move_a_collab",
     "You post on your own. A collab puts a second pair of ears on the work."),
]

DEFAULTS = ["daily_singz", "three_ears", "ship_one"]


def _routine_keys_with_action():
    return {r["key"]: r for r in ST.ROUTINES if r.get("action")}


def recent_counts(user):
    """{action: count in the window} for every action the suggestions read. Cached."""
    key = f"lilith:sug:{user.pk}"
    got = cache.get(key)
    if got is not None:
        return got
    since = timezone.now() - timedelta(days=WINDOW_DAYS)
    needed = {r["action"] for r in ST.ROUTINES if r.get("action")} | {g[0] for g in GAPS} | {g[1] for g in GAPS}
    out = {a: len(A.events(user, a, since)) for a in needed}
    cache.set(key, out, CACHE_SECONDS)
    return out


def signals(user):
    """Profile and activity FACTS the suggestions read, in one cached dict (ten minutes).

    Profile: is there a bio, links, a persona, an ID check. Activity: has this member ever posted,
    shared a card, started a collab, invited anyone; how many collabs are waiting on THEIR answer; how
    their last take scored. Facts, not scores — each is a yes/no or a count a member can verify against
    their own profile, and each becomes a sentence in a reason."""
    key = f"lilith:sig:{user.pk}"
    got = cache.get(key)
    if got is not None:
        return got
    from . import models as M
    from .models import is_minor, profile_for
    from .personaz import links_of, personas_of
    p = profile_for(user)
    last = M.TakeScore.objects.filter(user=user, overall__isnull=False).order_by("-created_at").first()
    waiting = 0
    for cp in M.CollabParticipant.objects.filter(user=user).select_related("deal")[:50]:
        d = cp.deal
        if d.status not in M._DEAL_OVER and d.initiator_id != user.id and not M._deal_accepted(d, user):
            waiting += 1
    out = {
        "bio": bool((p.bio or "").strip()),
        "links": len(links_of(p)),
        "personas": len(personas_of(p)),
        "adult": not is_minor(user),
        "verified_18": bool(p.verified_18plus),
        "ever_posted": M.Post.objects.filter(author=user).exists(),
        "ever_shared_card": M.ScoreShare.objects.filter(user=user).exists(),
        "ever_collab": M.CollabDeal.objects.filter(initiator=user).exists(),
        "ever_invited": M.Referral.objects.filter(referrer=user).exists(),
        "collabs_waiting": waiting,
        "last_take": float(last.overall) if last and last.overall is not None else None,
        "last_take_app": last.app_key if last else "",
    }
    cache.set(key, out, CACHE_SECONDS)
    return out


def _persona_names(user):
    from .models import profile_for
    from .personaz import personas_of
    import re
    out = []
    for p in personas_of(profile_for(user)):
        raw = str(p.get("name") or p.get("key") or "")
        keys = {re.sub(r"[^a-z]", "", str(p.get(f, "")).lower()) for f in ("key", "name")} - {""}
        if keys:
            out.append((raw or "your persona", keys))
    return out


def instruments_of(user):
    """[(coach app_key, how, n)] — the coaches this member works on, most-used first.

    Two sources, said in the reason: what they TAKE (scored takes in the last 90 days — the records;
    `n` is how many) and what their persona skills SAY they are (🎤 Rapper → RapZ, via the same role
    table that labels them on their card; `n` is 0). Takes come first because a declaration of
    "guitarist" from someone who has only ever sent rap takes is the weaker fact.
    """
    from django.db.models import Count
    from .models import TakeScore, profile_for
    from .personaz import ROLE_COACH, personas_of, role_pairs
    since = timezone.now() - timedelta(days=90)
    rows = (TakeScore.objects.filter(user=user, created_at__gte=since, overall__isnull=False)
            .values("app_key").annotate(n=Count("id")).order_by("-n"))
    out = [(r["app_key"], "takes", r["n"]) for r in rows if r["app_key"] in ST.INSTRUMENT_PACKS]
    seen = {a for a, _, _ in out}
    for p in personas_of(profile_for(user)):
        for _emoji, role in role_pairs(p):
            app = ROLE_COACH.get(role)
            if app and app in ST.INSTRUMENT_PACKS and app not in seen:
                out.append((app, "skill", 0))
                seen.add(app)
    return out


def suggest(user, on_board_routines=(), on_board_tasks=()):
    """Up to MAX_SUGGESTIONS routines, best first, each with the reason it was picked.

    `on_board_*` are the template keys already on the member's board; those are dropped here, so
    a stale cache never re-offers what they have added."""
    have = set(on_board_routines)
    counts = recent_counts(user)
    scored = {}     # key → (score, reason_kind, why)

    def offer(key, score, kind, why):
        if key in have or not ST.routine_by_key(key):
            return
        if key not in scored or score > scored[key][0]:
            scored[key] = (score, kind, why)

    # 1. personas — what they said they are
    for name, keys in _persona_names(user):
        for plist, routines in PERSONA_ROUTINES.items():
            if keys & set(plist):
                for i, rk in enumerate(routines):
                    offer(rk, 6 - i * 0.5, "persona", f"You're a {name}.")

    # 1b. the instrument they work on — a rapper gets RapZ, freestyle and bars; a drummer DrumZ
    for app, how, n in instruments_of(user)[:2]:
        label = ST._label(app)
        why = (f"You've sent {n} {label} take{'' if n == 1 else 's'} in the last 90 days." if how == "takes"
               else f"Your skills say you play {label}.")
        for i, rk in enumerate(ST.INSTRUMENT_PACKS[app]):
            offer(rk, 8 - i * 0.6, "instrument", why)

    # 2. habits waiting to be streaks — what they actually did
    for rk, r in _routine_keys_with_action().items():
        n = counts.get(r["action"], 0)
        goal = max(1, r.get("goal", 1))
        if n >= max(HABIT_AT, goal):
            unit = A.specs()[r["action"]]["unit"]
            offer(rk, 4 + min(n, 20) / 4, "habit",
                  f"You've done this {n} times in the last {WINDOW_DAYS} days ({unit}s). Make it a streak.")

    # 3. gaps — what they do not
    for have_a, lack_a, rk, sentence in GAPS:
        n = counts.get(have_a, 0)
        if n >= 1 and counts.get(lack_a, 0) == 0:
            offer(rk, 3 + min(n, 10) / 5, "gap", sentence.format(n=n, s="" if n == 1 else "s"))

    # 4. one-off tasks — from the profile (what is missing) and from what just happened
    sig = signals(user)
    have_t = set(on_board_tasks)
    tasks = {}

    def offer_task(key, score, kind, why):
        if key in have_t or not ST.task_by_key(key):
            return
        if key not in tasks or score > tasks[key][0]:
            tasks[key] = (score, kind, why)

    if sig["collabs_waiting"]:
        n = sig["collabs_waiting"]
        offer_task("answer_collab", 9, "activity",
                   f"{n} collab{' is' if n == 1 else 's are'} waiting for your answer.")
    if not sig["personas"]:
        offer_task("pick_persona", 7, "profile", "You haven't said what you are yet — no persona on your profile.")
    if not sig["bio"]:
        offer_task("finish_profile", 6, "profile", "Your bio is empty. It's the first thing a collaborator reads.")
    if not sig["links"]:
        offer_task("portfolio_links", 5.5, "profile", "You have no links on your profile for people to open.")
    if sig["adult"] and not sig["verified_18"]:
        offer_task("verify_18", 4, "profile", "You haven't verified 18+, which unlocks money battles.")
    if sig["last_take"] is not None and sig["last_take"] < 5:
        offer_task("fix_weakest", 8, "activity", f"Your last take scored {sig['last_take']:g}. One drill on the lowest dimension moves it fastest.")
    if sig["last_take"] is not None and not sig["ever_shared_card"]:
        offer_task("share_card", 4.5, "activity", "You've been scored but never shared a card. Anyone who joins from it is a referral.")
    if sig["ever_posted"] is False and sig["last_take"] is not None:
        offer_task("post_finished", 5, "activity", "You've been scored but haven't posted anything yet.")
    if sig["ever_posted"] and not sig["ever_collab"]:
        offer_task("start_collab", 4.5, "activity", "You post on your own. A collab puts a second pair of ears on the work.")
    if not sig["ever_invited"] and sig["ever_posted"]:
        offer_task("invite_musician", 3, "activity", "You haven't invited anyone. Your handle is the code and you're both paid.")
    for app, how, n in instruments_of(user)[:1]:
        if f"take_{app}" in ST.TASK_KEYS and how == "takes":
            offer_task(f"take_{app}", 5, "instrument", f"You work in {ST._label(app)} — record today's take.")

    ranked = sorted(scored.items(), key=lambda kv: -kv[1][0])[:MAX_SUGGESTIONS]
    if not ranked:                                   # a brand-new member with no signal at all
        ranked = [(k, (1, "start", "A small place to begin.")) for k in DEFAULTS if k not in have][:MAX_SUGGESTIONS]

    inst = instruments_of(user)
    main = inst[0][0] if inst else ""
    out = []
    for key, (score, kind, why) in ranked:
        r = ST.routine_by_key(key)
        app_key = main if (main and key in ST.INSTRUMENT_AWARE) else r["app_key"]
        out.append({"kind": "routine", "key": key, "title": r["title"], "note": r["note"],
                    "cadence": r["cadence"], "app_key": app_key, "target": r["target"],
                    "action": r.get("action", ""), "goal": r.get("goal", 1),
                    "why": why, "because": kind})
    for key, (score, kind, why) in sorted(tasks.items(), key=lambda kv: -kv[1][0])[:MAX_TASK_SUGGESTIONS]:
        t = ST.task_by_key(key)
        app_key = main if (main and key in ST.INSTRUMENT_AWARE) else t["app_key"]
        out.append({"kind": "task", "key": key, "title": t["title"], "note": t["note"], "cadence": "",
                    "app_key": app_key, "target": t["target"], "action": t.get("action", ""),
                    "goal": t.get("goal", 1), "why": why, "because": kind})
    return out
