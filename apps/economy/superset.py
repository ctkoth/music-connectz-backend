"""Supersets: two lifts done back to back, the rest taken after the pair.

What the Coach adds here is the PAIRING, never the permission to superset. Any
member can link two rows of a routine by hand, at every tier — a superset is
just an order of work, and a tier that could say whether somebody may do two
exercises in a row would be the ladder rule's first counter-example. What is
StatZ's (or the free hour's, see `statz_trial.FEATURES`) is the Coach choosing
the partner, which is a generator in the same sense the framed-page widget is:
it adds a capability on top of a thing everybody already has, and it can switch
off again when the sample ends without taking anything the member made.

Two pairings, because they are different ideas and the member picks which:

* **compound_isolation** — one muscle, two lifts: a heavy multi-joint lift and a
  single-joint one for the same muscle (chest press and fly). Done compound
  first, which is the pre-fatigue-free order; the member can swap them by hand.
* **push_pull** — opposing muscles, one lift each: a push and a pull (chest
  press and row, triceps and biceps). Neither fatigues the other's prime mover,
  which is what makes it the pairing that saves time rather than costs reps.

Everything here is a DECLARED fact about a lift and nothing is inferred from a
name at request time. `superset_table.TABLE` says, for each library exercise by
name, whether it is compound or isolation and whether it pushes or pulls; a
lift that is not in it — a member's own custom exercise, a cardio move, a hold —
is simply never paired. `test_superset` fails when a library exercise has no
entry, the same discipline `test_bodiez_access` holds for positions, so a lift
added to the library without being classified is a red test and not a Coach that
quietly ignores it.

The partner is always a real library lift the member can actually do:
`is_accessible` is the one accessibility rule (`bodiez.accessible`), and the
equipment the member said they own is respected.

It adds at most ONE row per lift that has no partner and says which it added; the
client shows them as added, so a pairing can never silently grow a routine.
"""
from .superset_table import TABLE

COMPOUND, ISOLATION = "compound", "isolation"
PUSH, PULL = "push", "pull"

MODES = {
    "compound_isolation": {
        "label": "Compound + isolation",
        "what": "One muscle, two lifts back to back: a heavy multi-joint lift, then a single-joint one for the same muscle.",
        "example": "Bench press, then dumbbell fly",
    },
    "push_pull": {
        "label": "Push + pull",
        "what": "Opposing muscles, one lift each, back to back: while one muscle works the other rests.",
        "example": "Bench press, then barbell row",
    },
}

# Which muscle groups oppose which. Only groups where "the other side" is a real
# thing are listed: abs, cardio, forearms, calves and full-body lifts have no
# partner here and are left alone rather than paired with something arbitrary.
# The library files hamstrings and quads together as upper_legs, so legs oppose
# themselves — the force (push vs pull) is what makes it a pair there.
ANTAGONISTS = {
    "chest": ("back",),
    "shoulders": ("back",),
    "back": ("chest", "shoulders"),
    "triceps": ("biceps",),
    "biceps": ("triceps",),
    "upper_legs": ("upper_legs", "glutes"),
    "glutes": ("upper_legs", "glutes"),
}

# What a partner we ADD is prescribed, when the routine did not say. The member
# can change it like any row; it is marked `added` so it is visible as the
# Coach's, and the sets follow the lift it is paired with.
ADDED_REPS = {COMPOUND: 8, ISOLATION: 12}
DEFAULT_SETS = 3


def classify(name):
    """(mechanic, force) for a library exercise by name, or None if undeclared."""
    row = TABLE.get(name)
    if not row:
        return None
    mechanic, force = row
    return mechanic, force


def _letters():
    for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        yield c


def valid_groups(rows):
    """Rows whose `group` really is a pair: exactly two rows, side by side.

    A group is only meaningful as two ADJACENT lifts — "rest after the pair"
    needs somebody to be next to. Anything else (a lone label left by a delete,
    three rows sharing one, two with a lift between them) is dropped rather than
    guessed at, so a routine that was edited by hand can never carry a stale
    superset.
    """
    keep = {}
    for i, r in enumerate(rows):
        g = r.get("group")
        if g:
            keep.setdefault(g, []).append(i)
    good = {g for g, idx in keep.items() if len(idx) == 2 and idx[1] == idx[0] + 1}
    out = []
    for r in rows:
        r = dict(r)
        if r.get("group") and r["group"] not in good:
            r.pop("group", None)
        out.append(r)
    return out


def _relabel(rows):
    """Give every surviving pair a fresh A, B, C… in routine order."""
    names, nxt = {}, _letters()
    out = []
    for r in rows:
        r = dict(r)
        g = r.get("group")
        if g:
            if g not in names:
                names[g] = next(nxt)
            r["group"] = names[g]
        out.append(r)
    return out


def _pick(library, want, in_routine, is_accessible, equipment):
    """The first library lift satisfying `want`, in library order.

    Library order (id), never name order: the curated first choice for a muscle
    is the one a member has always been shown, and sorting by name would let a
    newer row displace it for everybody (the same note `bodiezPick.js` carries).
    """
    for ex in sorted(library, key=lambda e: e.id):
        if ex.id in in_routine or getattr(ex, "created_by_id", None):
            continue
        if equipment and ex.equipment not in equipment:
            continue
        if not is_accessible(ex):
            continue
        if want(ex):
            return ex
    return None


def pair_rows(rows, library, mode, *, add=True, equipment=(), is_accessible=lambda ex: True):
    """Pair the rows of a routine. Pure: no database, no tier, no request.

    `rows` are routine rows (dicts with `exercise_id`, `sets`, `reps`, …) in
    routine order; `library` is every exercise the member may use, as objects with
    `id`, `name`, `muscle_group`, `equipment` and `created_by_id`. Returns the new
    rows, what was paired and why, what was added, and what was left alone.

    A pair already in the routine (a valid `group`, made by hand or by an earlier
    run) is left exactly as it is, so running this twice changes nothing the
    second time.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {sorted(MODES)}")
    by_id = {ex.id: ex for ex in library}
    rows = valid_groups([dict(r) for r in rows])
    equipment = tuple(equipment or ())
    in_routine = {r.get("exercise_id") for r in rows}

    def info(r):
        """(exercise, mechanic, force) for a library lift we may pair, else None."""
        ex = by_id.get(r.get("exercise_id"))
        if ex is None or getattr(ex, "created_by_id", None):
            return None
        c = classify(ex.name)
        return (ex, c[0], c[1]) if c else None

    def fits(a, b):
        """Whether lift `a` and lift `b` make a pair in this mode."""
        (ax, amech, aforce), (bx, bmech, bforce) = a, b
        if mode == "compound_isolation":
            return ax.muscle_group == bx.muscle_group and {amech, bmech} == {COMPOUND, ISOLATION}
        return (aforce in (PUSH, PULL) and bforce in (PUSH, PULL) and aforce != bforce
                and bx.muscle_group in ANTAGONISTS.get(ax.muscle_group, ()))

    def leads(a):
        """The lift that goes first: compound before isolation, push before pull."""
        _ex, mech, force = a
        return mech == COMPOUND if mode == "compound_isolation" else force == PUSH

    locked = {i for i, r in enumerate(rows) if r.get("group")}   # already a pair
    partner = {}                                                  # i -> j, both existing rows
    adds = {}                                                     # i -> (new row)
    why = {}

    for i, r in enumerate(rows):
        if i in locked or i in partner or i in partner.values():
            continue
        me = info(r)
        if me is None:
            continue
        j = next((j for j, s in enumerate(rows)
                  if j != i and j not in locked and j not in partner and j not in partner.values()
                  and info(s) is not None and fits(me, info(s))), None)
        if j is not None:
            partner[i] = j
            why[i] = _why(mode, me[0])
            continue
        if not add:
            continue
        ex, mech, force = me
        if mode == "compound_isolation":
            wanted = ISOLATION if mech == COMPOUND else COMPOUND
            pick = _pick(library, lambda e: (classify(e.name) or (None,))[0] == wanted
                         and e.muscle_group == ex.muscle_group, in_routine, is_accessible, equipment)
        else:
            if force not in (PUSH, PULL):
                continue
            want_force = PULL if force == PUSH else PUSH
            groups = ANTAGONISTS.get(ex.muscle_group, ())
            pick = None
            # The same kind of lift first (a compound for a compound), so the
            # pair is two lifts of comparable effort and not a heavy lift and a
            # warm-up; any kind only if there is no such lift to give.
            for same_kind in (True, False):
                pick = _pick(library, lambda e, sk=same_kind: bool(classify(e.name))
                             and classify(e.name)[1] == want_force and e.muscle_group in groups
                             and ((classify(e.name)[0] == mech) == sk),
                             in_routine, is_accessible, equipment)
                if pick:
                    break
        if pick is None:
            continue
        in_routine.add(pick.id)
        kind = classify(pick.name)[0]
        adds[i] = {"exercise_id": pick.id, "sets": r.get("sets") or DEFAULT_SETS,
                   "reps": ADDED_REPS[kind], "weight_kg": None, "added": True}
        why[i] = _why(mode, ex)

    # Rebuild with every pair side by side, the leading lift first. A partner
    # that was further down the routine moves up beside its lift; nothing else
    # moves.
    out, marks, emitted, pair_why = [], [], set(), {}
    for i, r in enumerate(rows):
        if i in emitted:
            continue
        if i in locked:
            # Valid groups are two adjacent rows: emit the pair as it stands.
            g = r["group"]
            for k in range(i, len(rows)):
                if rows[k].get("group") == g:
                    out.append(dict(rows[k])); marks.append(("lock", g)); emitted.add(k)
            continue
        if i in partner or i in adds:
            if i in partner:
                j = partner[i]
                first, second = (rows[i], rows[j]) if leads(info(rows[i])) else (rows[j], rows[i])
                emitted.update((i, j))
            else:
                new = adds[i]
                first, second = (rows[i], new) if leads(info(rows[i])) else (new, rows[i])
                emitted.add(i)
            out += [dict(first), dict(second)]
            marks += [("new", i), ("new", i)]
            pair_why[("new", i)] = why[i]
            continue
        out.append(dict(r)); marks.append(None); emitted.add(i)

    # Fresh labels A, B, C… in routine order, one run across old pairs and new.
    labels, nxt, pairs = {}, _letters(), []
    for idx, (row, mark) in enumerate(zip(out, marks)):
        row["order"] = idx
        if mark is None:
            row.pop("group", None)
            continue
        if mark not in labels:
            labels[mark] = next(nxt)
            if mark in pair_why:
                pairs.append({"group": labels[mark], "why": pair_why[mark],
                              "exercise_ids": [row["exercise_id"], out[idx + 1]["exercise_id"]]})
        row["group"] = labels[mark]
    return {
        "exercises": out,
        "pairs": pairs,
        "added": [n["exercise_id"] for n in adds.values()],
        "left_single": [r["exercise_id"] for r in out if not r.get("group")],
    }


PAIR_MODES = ("compound_isolation", "push_pull")
BOTH = "both"

# Served with the two single modes so a member can choose all of them in one go.
# It is not a third pairing rule: it is the two rules, run in order, with a lift
# allowed in one pair only.
BOTH_MODE = {
    "key": BOTH,
    "label": "Both",
    "what": "Both pairings in one go: compound + isolation first, then push + pull on the lifts still single. A lift is in one pair at most; where the two want the same lift, compound + isolation keeps it and the Coach says so.",
    "example": "Bench press with dumbbell fly, then the lifts left over, push against pull",
}

CONFLICT_SENTENCE = ("Push + pull's pairs for {names} cannot all be kept alongside compound + isolation, "
                     "because a lift can be in one pair only. Both keeps the compound + isolation pairs. "
                     "{offer} on its own pairs more of this routine ({n} pairs against {m}).")


def _label(mode):
    return MODES[mode]["label"]


def pair_both(rows, library, *, add=True, equipment=(), is_accessible=lambda ex: True):
    """Both pairings for one routine: two standalone proposals and one merged plan.

    `proposals` are each exactly what that single mode returns on the original rows,
    so each is a valid pairing on its own. The merged plan runs compound + isolation
    first, then push + pull over the rows that are still single; pass one's pairs are
    locked for pass two, so no lift is ever in two pairs. Where a push + pull pair of
    the standalone proposal cannot be kept in the merged plan, that is reported as a
    conflict with the sentence and the proposal that pairs more — never dropped quietly.
    """
    kw = dict(add=add, equipment=equipment, is_accessible=is_accessible)
    proposals = {m: pair_rows(rows, library, m, **kw) for m in PAIR_MODES}
    first = proposals["compound_isolation"]
    merged = pair_rows(first["exercises"], library, "push_pull", **kw)

    by_id = {ex.id: ex for ex in library}
    why = {}
    for mode, res in (("compound_isolation", first), ("push_pull", merged)):
        for p in res["pairs"]:
            why[frozenset(p["exercise_ids"])] = (mode, p["why"])

    final = merged["exercises"]
    members = {}
    for r in final:
        if r.get("group"):
            members.setdefault(r["group"], []).append(r["exercise_id"])
    pairs = []
    for g, ids_ in members.items():
        key = frozenset(ids_)
        if key not in why:            # a pair the member made by hand, not one the Coach made
            continue
        mode, reason = why[key]
        pairs.append({"group": g, "mode": mode, "why": reason, "exercise_ids": ids_})

    kept = {frozenset(q["exercise_ids"]) for q in pairs}
    lost_pp = [p for p in proposals["push_pull"]["pairs"] if frozenset(p["exercise_ids"]) not in kept]

    conflict = None
    if lost_pp:
        lost_ids = []
        for p in lost_pp:
            for i in p["exercise_ids"]:
                if i not in lost_ids:
                    lost_ids.append(i)
        where = {r["exercise_id"]: k for k, r in enumerate(proposals["push_pull"]["exercises"])}
        lost_ids.sort(key=lambda i: where[i])
        n_ci = len(proposals["compound_isolation"]["pairs"])
        n_pp = len(proposals["push_pull"]["pairs"])
        offer = "push_pull" if n_pp > n_ci else "compound_isolation"
        names = [by_id[i].name for i in lost_ids]
        conflict = {
            "exercise_ids": lost_ids,
            "names": names,
            "offer": offer,
            "sentence": CONFLICT_SENTENCE.format(
                names=", ".join(names), offer=_label(offer),
                n=max(n_ci, n_pp), m=min(n_ci, n_pp)),
        }

    return {
        "exercises": final,
        "pairs": pairs,
        "added": first["added"] + merged["added"],
        "left_single": merged["left_single"],
        "proposals": {m: {k: proposals[m][k] for k in ("exercises", "pairs", "added", "left_single")}
                      for m in PAIR_MODES},
        "coexist": conflict is None,
        "conflict": conflict,
    }


def _why(mode, ex):
    if mode == "compound_isolation":
        return f"Same muscle ({ex.muscle_group.replace('_', ' ')}): a compound lift and an isolation lift."
    return "Opposing muscles: while one works, the other rests."


# ---- The endpoint ---------------------------------------------------------

from rest_framework import status as http  # noqa: E402
from rest_framework.permissions import IsAuthenticated  # noqa: E402
from rest_framework.response import Response  # noqa: E402
from rest_framework.views import APIView  # noqa: E402

FEATURE = "coach_pairing"


class BodieZPairView(APIView):
    """GET what the Coach can pair and whether this member may; POST to pair a routine.

    The Coach picks the partners and the screen decides nothing: the modes, their
    plain-language descriptions and the example all come from here, so the labels a
    member reads cannot drift from the rule that runs. GET is open to every tier on
    purpose — the control states what it does and what it needs BEFORE it is pressed,
    which for a member without StatZ is the free hour or the upgrade, never a surprise
    refusal. POST is the StatZ part (or the sample's hour), and it is refused with the
    upgrade door attached rather than a bare 403.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .statz_trial import UPGRADE, has_statz, state
        return Response({
            "modes": [{"key": k, **v} for k, v in MODES.items()] + [BOTH_MODE],
            "allowed": has_statz(request.user),
            "feature": FEATURE,
            "sample": state(request.user),
            "upgrade": UPGRADE,
            "manual": "You can always link two lifts by hand, at any tier.",
        })

    def post(self, request):
        from .bodiez import accessible
        from .models import BodieZAccess, BodieZExercise
        from .statz_trial import UPGRADE, has_statz

        if not has_statz(request.user):
            return Response({
                "detail": "Pairing is a StatZ feature. You can still link two lifts by hand.",
                "statz_feature": FEATURE, "upgrade": UPGRADE,
            }, status=http.HTTP_403_FORBIDDEN)

        d = request.data or {}
        mode = d.get("mode")
        if mode not in MODES and mode != BOTH:
            return Response({"detail": f"mode must be one of {sorted(MODES) + [BOTH]}."},
                            status=http.HTTP_400_BAD_REQUEST)
        rows = d.get("exercises")
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            return Response({"detail": "exercises must be the routine's rows."},
                            status=http.HTTP_400_BAD_REQUEST)
        if len(rows) > 60:
            return Response({"detail": "That routine is too long to pair."},
                            status=http.HTTP_400_BAD_REQUEST)
        library = list(BodieZExercise.objects.visible(request.user))
        known = {e.id for e in library}
        bad = [r.get("exercise_id") for r in rows if r.get("exercise_id") not in known]
        if bad:
            return Response({"detail": f"Unknown exercise id(s): {bad}"},
                            status=http.HTTP_400_BAD_REQUEST)
        equipment = d.get("equipment") or []
        if not isinstance(equipment, list):
            equipment = []
        access = BodieZAccess.objects.filter(user=request.user).first()
        kw = dict(add=bool(d.get("add", True)),
                  equipment=[str(e) for e in equipment],
                  is_accessible=lambda ex: accessible(ex, access))
        names = {e.id: e.name for e in library}

        def name(res):
            for p in res["pairs"]:
                p["names"] = [names[i] for i in p["exercise_ids"]]
            return res

        if mode == BOTH:
            result = pair_both(rows, library, **kw)
            name(result)
            for res in result["proposals"].values():
                name(res)
            return Response(result)

        # Single modes: the response shape is unchanged from before "both" existed.
        return Response(name(pair_rows(rows, library, mode, **kw)))
