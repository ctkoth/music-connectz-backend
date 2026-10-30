"""The Plan rating: how closely a routine, AS WRITTEN, follows its goal's prescription.

Not the Thorough rating. Thorough (bodiez.thoroughness) is read off the sessions a member actually
trained and is None until there are some — that is the whole point of it, and a Planner that stamped a
10 on every routine it made would put a number there that nothing measured (CLAUDE.md's substance rule:
could a member get a good one without getting good?). This is a DIFFERENT number about a DIFFERENT thing,
named and worded as such: a check of the plan against rules that are written down, each check shown
passed or failed with the lift that decided it. It says nothing about how well anyone has trained.

Five checks, each pass / fail / not applicable, and the score is 10 × passed ÷ applicable (one decimal):

  reps     every lift's reps sit in its goal's range            (GOALS, each with its citation)
  sets     every lift's sets are within one of the goal's sets   (GOALS)
  order    compound lifts come before isolation lifts            (superset_table's declared mechanic)
  access   every lift is one this member can do                  (the server's own `accessible` flag)
  repeats  no lift appears twice

`reps` and `sets` need a goal on the routine; `order` needs at least one compound AND one isolation lift
the table knows. A check that cannot be judged is left out rather than passed — so a routine with no goal
is scored on what CAN be checked, and says so.

The Planner (the builders, and Fit to equipment) makes routines that PASS these by construction, which is
why a coach-made routine usually reads 10. That is a statement of what it is — built to the checks — and not
of how good it is for anyone; the number earns its keep when somebody edits a routine and it moves, with the
check that moved and the lift that moved it named. `polish` is the Planner's own fix for the checks it can fix
(order, reps, sets); `access` and `repeats` are the member's to resolve and are reported, never silently changed.
"""
from .superset_table import TABLE

PLAN_CAVEAT = ("Plan: how closely this routine, as written, follows its goal's prescription and puts big lifts first, "
               "out of 10 — each check is listed with the lift that decided it. It says nothing about how well you have "
               "trained; Thorough is that, and it comes from your logged sessions.")
SETS_SLACK = 1
LABELS = {
    "reps": "Reps match the goal",
    "sets": "Sets match the goal",
    "order": "Big lifts first",
    "access": "Every lift is one you can do",
    "repeats": "No lift twice",
}
ORDER_WHY = ("Heavy multi-joint lifts go first, while you are fresh; single-joint lifts after. "
             "This is the app's own ordering rule, not a citation.")


def mechanic_of(name):
    """"compound" | "isolation" | "other" | None (not in the declared table, e.g. a custom lift)."""
    row = TABLE.get(name)
    return row[0] if row else None


def _int(v):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _name(lib, row):
    return (lib.get(row.get("exercise_id")) or {}).get("name") or f"Exercise #{row.get('exercise_id')}"


def _goal(goals, key):
    return goals.get(key) if key else None


def plan(rows, goal_key, lib, goals):
    """{score, passed, applicable, goal, checks:[{key,label,ok,detail}]} — pure.

    `lib` maps exercise id -> {"name", "accessible"}; `goals` is bodiez.GOALS.
    """
    rows = [r for r in (rows or []) if isinstance(r, dict) and r.get("exercise_id")]
    g = _goal(goals, goal_key)
    glabel = g["label"] if g else None
    if not rows:
        return {"score": None, "passed": 0, "applicable": 0, "goal": glabel, "checks": [],
                "note": "No lifts yet — nothing to check."}
    checks = []

    def add(key, ok, detail):
        checks.append({"key": key, "label": LABELS[key], "ok": ok, "detail": detail})

    # reps / sets — against the goal's prescription
    if g:
        lo, hi = g["reps_low"], g["reps_high"]
        bad = [(r, _int(r.get("reps"))) for r in rows if _int(r.get("reps")) is not None
               and not lo <= _int(r.get("reps")) <= hi]
        n = sum(1 for r in rows if _int(r.get("reps")) is not None)
        add("reps", not bad,
            f"{'All ' if n > 1 else ''}{n} lift{'s' if n != 1 else ''} {'are' if n != 1 else 'is'} {lo}–{hi} reps ({glabel})."
            if not bad else "; ".join(f"{_name(lib, r)} is {v} reps — {glabel} is {lo}–{hi}" for r, v in bad) + ".")
        want = g["sets"]
        sbad = [(r, _int(r.get("sets"))) for r in rows if _int(r.get("sets")) is not None
                and abs(_int(r.get("sets")) - want) > SETS_SLACK]
        sn = sum(1 for r in rows if _int(r.get("sets")) is not None)
        add("sets", not sbad,
            f"Every lift is {want - SETS_SLACK}–{want + SETS_SLACK} sets ({glabel} is {want})."
            if not sbad else "; ".join(f"{_name(lib, r)} is {v} sets — {glabel} is {want}" for r, v in sbad) + ".")
        if sn == 0:
            checks[-1]["ok"], checks[-1]["detail"] = None, "No sets are written on these lifts."
        if n == 0:
            checks[-2]["ok"], checks[-2]["detail"] = None, "No reps are written on these lifts."
    else:
        add("reps", None, "This routine has no goal, so there is no rep range to check it against.")
        add("sets", None, "This routine has no goal, so there is no set count to check it against.")

    # order — compound before isolation, among the lifts the declared table knows. A superset PAIR is one unit (its two lifts
    # are done back to back), so it counts as a big lift if either is one: a push-pull pair of a curl and a row is not "a
    # curl before a row". Everything else is its own unit, so with no supersets this is lift against lift.
    known = [(r, mechanic_of(_name(lib, r))) for r in rows]
    seen_iso, misplaced = None, []
    for block in _blocks(rows):
        mechs = [mechanic_of(_name(lib, r)) for r in block]
        comp = next((r for r, m in zip(block, mechs) if m == "compound"), None)
        if comp is not None:
            if seen_iso is not None:
                misplaced.append((comp, seen_iso))
        elif mechs and all(m == "isolation" for m in mechs) and seen_iso is None:
            seen_iso = block[0]
    has = {m for _, m in known}
    if "compound" in has and "isolation" in has:
        add("order", not misplaced,
            "Every big lift comes before the single-joint ones." if not misplaced
            else "; ".join(f"{_name(lib, r)} (compound) comes after {_name(lib, i)} (isolation)" for r, i in misplaced) + ".")
    else:
        add("order", None, "Needs at least one big lift and one single-joint lift to compare.")

    # access — the server's own flag, never re-derived
    no = [r for r in rows if lib.get(r["exercise_id"]) and lib[r["exercise_id"]].get("accessible") is False]
    add("access", not no,
        "Every lift is one your movement settings allow." if not no
        else ", ".join(_name(lib, r) for r in no) + " — your movement settings rule it out.")

    # repeats
    seen, dup = set(), []
    for r in rows:
        k = r["exercise_id"]
        if k in seen and _name(lib, r) not in dup:
            dup.append(_name(lib, r))
        seen.add(k)
    add("repeats", not dup, "No lift appears twice." if not dup else ", ".join(dup) + " appears more than once.")

    judged = [c for c in checks if c["ok"] is not None]
    passed = sum(1 for c in judged if c["ok"])
    score = round(10.0 * passed / len(judged), 1) if judged else None
    return {"score": score, "passed": passed, "applicable": len(judged), "goal": glabel, "checks": checks}


def _blocks(rows):
    """Adjacent rows sharing a superset `group` move together; every other row is its own block."""
    out, i = [], 0
    while i < len(rows):
        g = rows[i].get("group")
        if g and i + 1 < len(rows) and rows[i + 1].get("group") == g:
            out.append(rows[i:i + 2]); i += 2
        else:
            out.append([rows[i]]); i += 1
    return out


def polish(rows, goal_key, lib, goals):
    """(new_rows, changes) — the Planner's fix for what it CAN fix: order, reps and sets.

    Reps and sets move to the NEAREST edge of the goal's range (the smallest change that passes), never
    to a number of the Planner's choosing. Big lifts move ahead of single-joint ones as a stable sort over
    superset blocks, so a pair stays a pair and everything else keeps its relative place. Weights, rest and
    every other field are untouched. `changes` is what the screen shows as the reason, in plain words.
    """
    rows = [dict(r) for r in (rows or []) if isinstance(r, dict) and r.get("exercise_id")]
    changes = []
    # order
    def rank(block):
        return 1 if all(mechanic_of(_name(lib, r)) == "isolation" for r in block) else 0
    blocks = _blocks(rows)
    ordered = sorted(blocks, key=rank)                       # stable
    new_rows = [r for b in ordered for r in b]
    if [id(r) for r in new_rows] != [id(r) for r in rows]:
        before = {id(r): i for i, r in enumerate(rows)}          # by identity: two identical rows are still two rows
        for pos, r in enumerate(new_rows):
            was = before[id(r)]
            if mechanic_of(_name(lib, r)) == "compound" and pos < was:
                changes.append({"kind": "order", "lift": _name(lib, r),
                                "what": f"Moved {_name(lib, r)} from {was + 1} to {pos + 1} — big lifts first."})
    rows = new_rows
    # reps / sets
    g = _goal(goals, goal_key)
    if g:
        lo, hi, want = g["reps_low"], g["reps_high"], g["sets"]
        for r in rows:
            reps = _int(r.get("reps"))
            if reps is not None and not lo <= reps <= hi:
                to = min(max(reps, lo), hi)
                changes.append({"kind": "reps", "lift": _name(lib, r),
                                "what": f"{_name(lib, r)}: {reps} → {to} reps — {g['label']} is {lo}–{hi}."})
                r["reps"] = to
            sets = _int(r.get("sets"))
            if sets is not None and abs(sets - want) > SETS_SLACK:
                to = min(max(sets, want - SETS_SLACK), want + SETS_SLACK)
                changes.append({"kind": "sets", "lift": _name(lib, r),
                                "what": f"{_name(lib, r)}: {sets} → {to} sets — {g['label']} is {want}."})
                r["sets"] = to
    for i, r in enumerate(rows):
        r["order"] = i
    return rows, changes


def explain(before, after):
    """How the score moved, and which check moved it — [] when no check changed.

    `before` / `after` are `plan()` results for the same routine; a check that went from failing to passing (or
    back) is the reason, with the detail that says which lift decided it.
    """
    was = {c["key"]: c for c in (before or {}).get("checks", [])}
    out = []
    for c in (after or {}).get("checks", []):
        old = was.get(c["key"])
        if old is None or old["ok"] == c["ok"]:
            continue
        out.append({"check": c["key"], "label": c["label"], "was": old["ok"], "now": c["ok"],
                    "why": c["detail"] if c["ok"] is False else (old["detail"] if old["ok"] is False else c["detail"])})
    return out


def compare(before, after):
    """{before, after, change, checks:[explain]} — the shape the screen shows for an edit."""
    b = (before or {}).get("score"); a = (after or {}).get("score")
    return {"before": b, "after": a,
            "change": round(a - b, 1) if a is not None and b is not None else None,
            "checks": explain(before, after)}
