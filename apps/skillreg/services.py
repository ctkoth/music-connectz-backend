"""Pure-ish logic: experience, medians, exclusive gates, rating-weighted split."""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Q

from .models import (GateSkillReq, MemberFacet, Skill, SkillGate, UserSkill,
                     WorkRating, WorkSkillTag)

MIN_RATINGS = getattr(settings, "SKILLREG_MIN_RATINGS", 3)   # matches BattleZ minimum
DEV_TAX_BPS = getattr(settings, "SKILLREG_DEV_TAX_BPS", 500)  # 5% developer royalty
ADULT_AGE = 18


# ---------- experience ----------
def months_between(start: date, end: date) -> int:
    m = (end.year - start.year) * 12 + end.month - start.month
    if end.day < start.day:
        m -= 1
    return max(m, 0)


def experience(learned_at: date, today: date | None = None) -> dict:
    total = months_between(learned_at, today or date.today())
    y, mo = divmod(total, 12)
    parts = []
    if y:
        parts.append(f"{y} yr{'s' if y != 1 else ''}")
    if mo or not y:
        parts.append(f"{mo} mo{'s' if mo != 1 else ''}")
    return {"years": y, "months": mo, "total_months": total, "label": " ".join(parts)}


# ---------- ratings (the only place ratings are read: swap here to use economy SkillRating) ----------
def _med(scores):
    return round(statistics.median(scores), 2) if scores else None


def skill_scores_by_id(user) -> dict[int, list[int]]:
    out = defaultdict(list)
    for sid, score in WorkRating.objects.filter(tag__owner=user).values_list("tag__skill_id", "score"):
        out[sid].append(score)
    return out


def skill_summary(us: UserSkill, today: date | None = None) -> dict:
    tags = (WorkSkillTag.objects.filter(owner=us.user, skill=us.skill)
            .prefetch_related("ratings").order_by("-created_at"))
    works, allscores = [], []
    for t in tags:
        s = [r.score for r in t.ratings.all()]
        allscores += s
        works.append({"tag_id": t.id, "work_type": t.work_type, "work_id": t.work_id,
                      "title": t.title, "median": _med(s), "ratings": len(s)})
    return {
        "skill": {"id": us.skill_id, "slug": us.skill.slug, "name": us.skill.name},
        "learned_at": us.learned_at.isoformat(),
        "experience": experience(us.learned_at, today),
        "median": _med(allscores),
        "ratings": len(allscores),
        "provisional": len(allscores) < MIN_RATINGS,
        "gauge": gauge(experience(us.learned_at, today)["total_months"], _med(allscores), len(allscores)),
        "price_cents": us.effective_price,
        "works": works,
    }


def profile_skills(user, today: date | None = None) -> list[dict]:
    qs = UserSkill.objects.filter(user=user).select_related("skill")
    return [skill_summary(us, today) for us in qs]


def augment_public_profile(d: dict, user) -> dict:
    """One-line hook for publicz.public_profile_dict: d = augment_public_profile(d, user)."""
    d["skillz_registry"] = profile_skills(user)
    return d


# ---------- gauge: experience AND rating, per skill ----------
LEVELS = ["Novice", "Developing", "Proficient", "Advanced", "Expert"]
EXP_CUTS = [6, 24, 60, 120]      # months
RATE_CUTS = [4, 6, 8, 9]         # median 0-10


def _tier(v, cuts):
    return sum(1 for c in cuts if v >= c)


def gauge(months: int, median, n: int) -> dict:
    """Level = the LOWER of experience tier and rating tier, so neither alone can inflate it.
    Under MIN_RATINGS the skill is unrated: level is None (shown as experience only)."""
    et = _tier(months, EXP_CUTS)
    if median is None or n < MIN_RATINGS:
        return {"tier": None, "label": f"{LEVELS[et]} (unrated)", "exp_tier": et, "rating_tier": None}
    rt = _tier(median, RATE_CUTS)
    t = min(et, rt)
    return {"tier": t, "label": LEVELS[t], "exp_tier": et, "rating_tier": rt}


def _overlap(lo, hi, want_lo, want_hi):
    """Do [lo,hi] (None=open) and [want_lo,want_hi] overlap?"""
    a1, a2 = (-math.inf if lo is None else lo), (math.inf if hi is None else hi)
    b1, b2 = (-math.inf if want_lo is None else want_lo), (math.inf if want_hi is None else want_hi)
    return a1 <= b2 and b1 <= a2


# ---------- registry-only choices ----------
def choices_for(user):
    return UserSkill.objects.filter(user=user, skill__active=True).select_related("skill")


def validate_skill_ids(user, skill_ids) -> list[Skill]:
    """Uploads may only use skills on the uploader's registry list."""
    ids = list(dict.fromkeys(skill_ids))
    if not ids:
        raise ValidationError("Pick at least one skill from your list.")
    held = {us.skill_id: us.skill for us in choices_for(user)}
    bad = [i for i in ids if i not in held]
    if bad:
        raise ValidationError(f"Skills not on your list: {bad}")
    return [held[i] for i in ids]


def post_cost_cents(user, skills) -> int:
    """Blueprint rule: post cost = combined price of skills used, in cents."""
    prices = {us.skill_id: us.effective_price for us in UserSkill.objects.filter(
        user=user, skill__in=skills)}
    return sum(prices.values())


# ---------- facets / gates ----------
def facet_of(user) -> MemberFacet:
    return MemberFacet.objects.filter(user=user).first() or MemberFacet(user=user)


def age_of(facet: MemberFacet, today: date | None = None):
    b = facet.birth_date
    if not b:
        return None
    t = today or date.today()
    return t.year - b.year - ((t.month, t.day) < (b.month, b.day))


def haversine_km(a_lat, a_lon, b_lat, b_lon) -> float:
    r = 6371.0088
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _in(v, lo, hi):
    return v is not None and (lo is None or v >= lo) and (hi is None or v <= hi)


def clamp_age_range(owner_age, age_min, age_max):
    """Child safety: an adult's age range can never reach under 18, a minor's never 18+."""
    if owner_age is None:
        return age_min, age_max
    if owner_age >= ADULT_AGE:
        return max(age_min or ADULT_AGE, ADULT_AGE), age_max
    return age_min, min(age_max if age_max is not None else ADULT_AGE - 1, ADULT_AGE - 1)


def validate_ranges(g) -> None:
    for lo, hi, name in [("exp_min_months", "exp_max_months", "experience"),
                         ("gauge_min", "gauge_max", "gauge"),
                         ("rating_min", "rating_max", "rating"), ("price_min", "price_max", "price"),
                         ("attr_min", "attr_max", "attractiveness"), ("age_min", "age_max", "age"),
                         ("distance_min_km", "distance_max_km", "distance")]:
        a, b = getattr(g, lo), getattr(g, hi)
        if a is not None and b is not None and a > b:
            raise ValidationError(f"{name} range min is above max")
    for f in ("rating_min", "rating_max", "attr_min", "attr_max"):
        v = getattr(g, f)
        if v is not None and not 0 <= v <= 10:
            raise ValidationError(f"{f} must be 0-10")


REQ_FIELDS = ("rating_min", "rating_max", "exp_min_months", "exp_max_months", "gauge_min", "gauge_max")
FAM = "f:"   # unit key prefix: a requirement unit is a skill id (int) or a family ("f:Rapping")


def gate_reqs(gate: SkillGate) -> dict:
    if not gate.pk:
        return {}
    return {(r.skill_id if r.skill_id else FAM + r.family): {f: getattr(r, f) for f in REQ_FIELDS}
            for r in gate.reqs.all()}


def eff(gate, req, f):
    """Per-unit requirement if set, else the gate-level range."""
    v = (req or {}).get(f)
    return getattr(gate, f) if v is None else v


def unit_level(unit, held: dict, scores: dict, today):
    """Member's level in a unit: (months, ratings, prices) or None if they don't have it.
    Skill: that skill. Family: longest experience of any held skill in the family, ratings pooled
    across all of them, so 'any rapping experience' counts every rap skill."""
    now = today or date.today()
    if isinstance(unit, int):
        us = held.get(unit)
        return None if not us else (months_between(us.learned_at, now), scores.get(unit, []),
                                    [us.effective_price])
    fam = unit[len(FAM):]
    inf = [us for us in held.values() if us.skill.family == fam]
    if not inf:
        return None
    return (max(months_between(us.learned_at, now) for us in inf),
            [x for us in inf for x in scores.get(us.skill_id, [])],
            [us.effective_price for us in inf])


def unit_fails(gate, req, months, s, prices) -> list[str]:
    """Why the member does NOT meet the post's bounds for this unit (empty = meets)."""
    why = []
    rl, rh = eff(gate, req, "rating_min"), eff(gate, req, "rating_max")
    if (rl is not None or rh is not None) and (len(s) < MIN_RATINGS or not _in(_med(s), rl, rh)):
        why.append("rating")
    el, eh = eff(gate, req, "exp_min_months"), eff(gate, req, "exp_max_months")
    if (el is not None or eh is not None) and not _in(months, el, eh):
        why.append("experience")
    gl, gh = eff(gate, req, "gauge_min"), eff(gate, req, "gauge_max")
    if (gl is not None or gh is not None) and not _in(gauge(months, _med(s), len(s))["tier"], gl, gh):
        why.append("gauge")
    if (gate.price_min is not None or gate.price_max is not None) and not any(
            _in(p, gate.price_min, gate.price_max) for p in prices):
        why.append("price")
    return why


def evaluate_gate(gate: SkillGate, cand, today: date | None = None,
                  gate_ids: set | None = None, reqs: dict | None = None) -> tuple[bool, list[str]]:
    """Exclusive gating: every bound that is set must hold; missing data fails a set bound.
    Units = required skills and/or skill families. match 'any' = at least one unit fully meets its
    bounds; 'all' = every unit does."""
    why = []
    if cand.pk == gate.owner_id:
        return False, ["self"]
    of, cf = facet_of(gate.owner), facet_of(cand)
    oa, ca = age_of(of, today), age_of(cf, today)

    # age line: never match across 18 when both ages are known
    if oa is not None and ca is not None and (oa < ADULT_AGE) != (ca < ADULT_AGE):
        why.append("age_line")
    age_set = gate.age_min is not None or gate.age_max is not None
    if gate.adults_only and (ca is None or ca < ADULT_AGE):
        why.append("adults_only")
    if age_set and not _in(ca, gate.age_min, gate.age_max):
        why.append("age")

    if gate.attr_min is not None or gate.attr_max is not None:
        ok = (ca is not None and ca >= ADULT_AGE and cf.attractiveness_opt_in
              and _in(cf.attractiveness_score, gate.attr_min, gate.attr_max))
        if not ok:
            why.append("attractiveness")

    if gate.distance_min_km is not None or gate.distance_max_km is not None:
        if None in (of.lat, of.lon, cf.lat, cf.lon):
            why.append("distance")
        elif not _in(haversine_km(of.lat, of.lon, cf.lat, cf.lon),
                     gate.distance_min_km, gate.distance_max_km):
            why.append("distance")

    held = {us.skill_id: us for us in UserSkill.objects.filter(user=cand).select_related("skill")}
    if gate_ids is None:
        gate_ids = set(gate.skills.values_list("id", flat=True)) if gate.pk else set()
    reqs = gate_reqs(gate) if reqs is None else reqs
    units = set(gate_ids) | set(reqs)
    skill_bounds_set = any(getattr(gate, f) is not None for f in REQ_FIELDS + ("price_min", "price_max")) \
        or any(v is not None for r in reqs.values() for v in r.values())
    if units or skill_bounds_set:
        need = units or set(held)       # no required units: any skill the member holds may satisfy it
        scores = skill_scores_by_id(cand)
        results = {}
        for u in need:
            lvl = unit_level(u, held, scores, today)
            results[u] = ["skills"] if lvl is None else unit_fails(gate, reqs.get(u), *lvl)
        passed = [u for u, f in results.items() if not f]
        ok = (len(passed) == len(need) and bool(need)) if (
            gate.skill_match == SkillGate.MATCH_ALL and units) else bool(passed)
        if not ok:
            why += sorted({r for f in results.values() for r in f}) or ["skills"]
    return (not why), why


def assert_passes_gate(post_type: str, post_id: int, user) -> bool:
    """Call from collabz/venuez/battlez/social join & apply views. No gate = open."""
    gate = SkillGate.objects.filter(post_type=post_type, post_id=post_id).first()
    return True if gate is None else evaluate_gate(gate, user)[0]


def search_candidates(gate: SkillGate, limit: int = 50, gate_ids=None, reqs=None) -> list:
    """Same gates drive search. Candidates = members holding any required skill or family skill."""
    from django.contrib.auth import get_user_model
    U = get_user_model()
    qs = U.objects.filter(skillreg_skills__isnull=False).exclude(pk=gate.owner_id).distinct()
    if gate_ids is None:
        gate_ids = list(gate.skills.values_list("id", flat=True)) if gate.pk else []
    if reqs is None:
        reqs = gate_reqs(gate)
    ids = set(gate_ids) | {k for k in reqs if isinstance(k, int)}
    fams = {k[len(FAM):] for k in reqs if isinstance(k, str)}
    if ids or fams:
        qs = qs.filter(Q(skillreg_skills__skill_id__in=ids) | Q(skillreg_skills__skill__family__in=fams)).distinct()
    out = []
    for u in qs[:500]:
        ok, _ = evaluate_gate(gate, u, gate_ids=gate_ids, reqs=reqs)
        if ok:
            meds = [m for m in (_med(v) for v in skill_scores_by_id(u).values()) if m is not None]
            out.append((statistics.median(meds) if meds else 0, u))
    out.sort(key=lambda t: -t[0])
    return [u for _, u in out[:limit]]


# ---------- collab / socialize split by rating ----------
def participant_weights(work_type: str, work_id: int) -> dict[int, float]:
    """Each contributor's weight = median of their skill medians for skills tagged on this work."""
    weights = {}
    tags = WorkSkillTag.objects.filter(work_type=work_type, work_id=work_id)
    by_owner = defaultdict(list)
    for t in tags:
        by_owner[t.owner_id].append(t.skill_id)
    for uid, sids in by_owner.items():
        scores = defaultdict(list)
        for sid, sc in WorkRating.objects.filter(tag__owner_id=uid, tag__skill_id__in=sids
                                                 ).values_list("tag__skill_id", "score"):
            scores[sid].append(sc)
        meds = [_med(v) for v in scores.values() if v]
        weights[uid] = statistics.median(meds) if meds else 0.0
    return weights


def split_by_rating(gross_cents: int, weights: dict, tax_bps: int | None = None) -> dict:
    """Developer tax off the top, remainder split pro-rata by rating (largest remainder,
    so shares always sum exactly to net). All-zero weights split equally."""
    if not weights:
        raise ValidationError("No participants to split between.")
    bps = DEV_TAX_BPS if tax_bps is None else tax_bps
    tax = gross_cents * bps // 10000
    net = gross_cents - tax
    w = {k: Decimal(str(v)) for k, v in weights.items()}
    total = sum(w.values())
    if total == 0:
        w = {k: Decimal(1) for k in w}
        total = Decimal(len(w))
    raw = {k: Decimal(net) * v / total for k, v in w.items()}
    cents = {k: int(r) for k, r in raw.items()}
    left = net - sum(cents.values())
    for k in sorted(raw, key=lambda k: (raw[k] - cents[k], str(k)), reverse=True)[:left]:
        cents[k] += 1
    shares = {k: {"cents": c, "pct": float(round(Decimal(c) * 100 / net, 2)) if net else 0.0}
              for k, c in cents.items()}
    return {"gross_cents": gross_cents, "tax_cents": tax, "net_cents": net, "shares": shares}


def distribute(work_type: str, work_id: int, gross_cents: int) -> dict:
    """Collab / Socialize payout entry point."""
    return split_by_rating(gross_cents, participant_weights(work_type, work_id))


# ---------- reverse direction: members browsing posts / content ----------
def browse_posts(user, post_type=None, skill_ids=None, families=None, rating=(None, None),
                 exp_months=(None, None), gauge_range=(None, None), only_qualified=True, limit=50) -> list[dict]:
    """Members looking for posts. Skill/family filters match what the POST requires (a post asking for
    the Rapping family matches a Triplet Flow filter, and vice versa); range filters must overlap the
    post's bounds; only_qualified also requires that the member passes the post's gates."""
    qs = SkillGate.objects.exclude(owner=user).select_related("owner").prefetch_related("skills", "reqs")
    if post_type:
        qs = qs.filter(post_type=post_type)
    wanted_ids = set(skill_ids or [])
    wanted_fams = set(families or []) | set(
        Skill.objects.filter(pk__in=wanted_ids).exclude(family="").values_list("family", flat=True))
    out = []
    for g in qs.order_by("-created_at")[:1000]:
        skills = list(g.skills.all())
        gids = {s.id for s in skills}
        rq = {(r.skill_id if r.skill_id else FAM + r.family): {f: getattr(r, f) for f in REQ_FIELDS}
              for r in g.reqs.all()}
        post_fams = {s.family for s in skills if s.family} | {k[len(FAM):] for k in rq if isinstance(k, str)}
        if (wanted_ids or wanted_fams) and not ((gids & wanted_ids) or (post_fams & wanted_fams)):
            continue
        units = gids | set(rq)

        def asks_overlap(u):
            q = rq.get(u)
            return (_overlap(eff(g, q, "rating_min"), eff(g, q, "rating_max"), *rating)
                    and _overlap(eff(g, q, "exp_min_months"), eff(g, q, "exp_max_months"), *exp_months)
                    and _overlap(eff(g, q, "gauge_min"), eff(g, q, "gauge_max"), *gauge_range))
        if not (any(asks_overlap(u) for u in units) if units else asks_overlap(None)):
            continue
        ok = evaluate_gate(g, user, gate_ids=gids, reqs=rq)[0]
        if only_qualified and not ok:
            continue
        out.append({"post_type": g.post_type, "post_id": g.post_id, "owner": g.owner.get_username(),
                    "skills": [s.name for s in skills] + [f"Any {f}" for f in sorted(post_fams - {s.family for s in skills})],
                    "qualified": ok,
                    "asks": {"rating": [g.rating_min, g.rating_max],
                             "experience_months": [g.exp_min_months, g.exp_max_months],
                             "gauge": [g.gauge_min, g.gauge_max]}})
        if len(out) >= limit:
            break
    return out


def search_works(skill_ids=None, families=None, work_type=None, creator_rating=(None, None),
                 creator_exp=(None, None), creator_gauge=(None, None), work_rating=(None, None),
                 limit=100) -> list[dict]:
    """Browse content by skill or whole family ('any rapping'), gated on the creator's experience and
    median rating in that skill/family and on the work's own median. Exclusive ranges; creators with
    too few ratings fail rating/gauge bounds."""
    ids, fams = set(skill_ids or []), set(families or [])
    tags = (WorkSkillTag.objects.filter(Q(skill_id__in=ids) | Q(skill__family__in=fams))
            .select_related("owner", "skill").prefetch_related("ratings").order_by("-created_at"))
    if work_type:
        tags = tags.filter(work_type=work_type)
    owners = {t.owner_id: t.owner for t in tags[:2000]}
    held_by, score_by = {}, {}
    for us in UserSkill.objects.filter(user_id__in=owners).select_related("skill"):
        held_by.setdefault(us.user_id, {})[us.skill_id] = us
    out, seen = [], set()
    for t in tags[:2000]:
        unit = (FAM + t.skill.family) if (t.skill.family in fams and t.skill_id not in ids) else t.skill_id
        lvl_key = (t.owner_id, unit)
        if t.owner_id not in score_by:
            score_by[t.owner_id] = skill_scores_by_id(owners[t.owner_id])
        lvl = unit_level(unit, held_by.get(t.owner_id, {}), score_by[t.owner_id], None)
        if lvl is None:
            continue
        months, sc, _prices = lvl
        med, n = _med(sc), len(sc)
        g = gauge(months, med, n)
        wm = _med([r.score for r in t.ratings.all()])
        if any(v is not None for v in creator_exp) and not _in(months, *creator_exp):
            continue
        if any(v is not None for v in creator_rating) and (n < MIN_RATINGS or not _in(med, *creator_rating)):
            continue
        if any(v is not None for v in creator_gauge) and not _in(g["tier"], *creator_gauge):
            continue
        if any(v is not None for v in work_rating) and not _in(wm, *work_rating):
            continue
        out.append({"work_type": t.work_type, "work_id": t.work_id, "title": t.title,
                    "creator": t.owner.get_username(), "skill": t.skill.name, "family": t.skill.family,
                    "work_median": wm, "creator_median": med, "creator_experience_months": months,
                    "gauge": g["label"]})
        if len(out) >= limit:
            break
    return out
