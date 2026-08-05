"""Range gates — one spec, one evaluation, every surface.

Five ranges decide who can see or join a thing: skill rating, skill price,
attractiveness, age and distance. They were written inline in MembersView and
nowhere else, so a CollabZ or VenueZ post could not require any of them.

Gates are EXCLUSIVE by design: when a min or max is set, a member with no value
for that metric is out. A rating gate that lets unrated members through is not
a rating gate — it is a suggestion.
"""
GATE_KEYS = ("rating", "price", "attract", "age", "km")

LABEL = {
    "rating": "skill rating", "price": "skill price", "attract": "attractiveness",
    "age": "age", "km": "distance",
}


def clean_gates(raw):
    """Normalize {key: [min, max]} from a client. Absent or null = no gate.

    `km` is a max only — "within N km" has no floor worth expressing.
    """
    out = {}
    if not isinstance(raw, dict):
        return out
    for key in GATE_KEYS:
        v = raw.get(key)
        if v is None:
            continue
        if key == "km":
            try:
                out[key] = [None, max(0.0, float(v[1] if isinstance(v, (list, tuple)) else v))]
            except (TypeError, ValueError):
                pass
            continue
        if not isinstance(v, (list, tuple)) or len(v) != 2:
            continue
        pair = []
        for x in v:
            try:
                pair.append(None if x is None or x == "" else float(x))
            except (TypeError, ValueError):
                pair.append(None)
        if pair[0] is not None or pair[1] is not None:
            out[key] = pair
    return out


class MemberMetrics:
    """The numbers a gate is checked against, computed on first ask.

    Lazy on purpose: `rating` and `attract` are a query each, and member search
    walks up to 500 profiles. Computing all five for everybody would put a
    thousand queries behind a search that set no gates at all.

    None means "no value", which an active gate excludes.
    """

    def __init__(self, profile, origin=(None, None)):
        self.profile = profile
        self.origin = origin
        self._cache = {}

    def get(self, key, default=None):
        if key not in self._cache:
            self._cache[key] = self._compute(key)
        value = self._cache[key]
        return default if value is None else value

    __getitem__ = get

    def _compute(self, key):
        from .models import (attractiveness_median, haversine_km,
                             overall_median, profile_age)
        from .social import profile_max_experience, profile_skill_rate
        p = self.profile
        if key == "rating":
            return overall_median(p.user)
        if key == "price":
            return profile_skill_rate(p)
        if key == "attract":
            return attractiveness_median(p.user)
        if key == "age":
            return profile_age(p)
        if key == "exp":
            return profile_max_experience(p)
        if key == "km":
            if self.origin[0] is None or not p.share_location or p.lat is None:
                return None
            return haversine_km(self.origin[0], self.origin[1], p.lat, p.lng)
        return None


def member_metrics(profile, origin=(None, None)):
    return MemberMetrics(profile, origin)


def failing_gate(metrics, gates):
    """The first gate this member fails, or None. Named rather than boolean so
    a refusal can say which range excluded them instead of just "no"."""
    for key, pair in (gates or {}).items():
        if key not in GATE_KEYS:
            continue
        lo, hi = (pair + [None, None])[:2] if isinstance(pair, list) else (None, None)
        if lo is None and hi is None:
            continue
        value = metrics.get(key)
        if value is None:
            return key                      # exclusive: no value, no entry
        if lo is not None and value < lo:
            return key
        if hi is not None and value > hi:
            return key
    return None


def describe(key, gates):
    lo, hi = (gates.get(key) or [None, None])[:2]
    label = LABEL.get(key, key)
    if key == "km":
        return f"within {hi:g} km"
    if lo is not None and hi is not None:
        return f"{label} {lo:g}–{hi:g}"
    return f"{label} {'at least' if lo is not None else 'at most'} {lo if lo is not None else hi:g}"


def refusal(key, gates):
    return {"detail": f"This one is gated on {describe(key, gates)} — you're outside it.",
            "gate": key, "gates": gates}
