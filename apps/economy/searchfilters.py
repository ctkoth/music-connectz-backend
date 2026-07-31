"""Search range gates — shared by CollabZ, VenueZ, BattleZ and Social ConnectZ.

Five ranges, and they are **exclusive gates**: outside the range means excluded,
not ranked lower. A gate that quietly lets people through isn't a gate, and a
member who set "18–30" and got a 45-year-old would stop trusting the filter.

    Skill rating ⭐   0–10    the member's overall rating median
    Skill price 💲    cents   what they charge for the skill
    Attractiveness 🙂 1–10    their attractiveness median (opt-in only)
    Age 🎂            years   from a verified-format birthday
    Distance 🗺️       km      great-circle, needs both parties sharing location

**Unknown values are excluded, and counted.** If somebody has no rating yet, a
rating gate cannot prove they're inside it, so they don't pass — but they're
reported in `unknown` so the UI can offer "and 12 more with no rating yet"
rather than pretending they don't exist. Silently dropping them would make a
new member invisible forever, which is how a marketplace fails to bootstrap.

One range parses from either shape, because clients disagree:

    ?age=18-30          ?age_min=18&age_max=30
"""
from .models import (attractiveness_median, haversine_km, overall_median,
                     profile_age, profile_for)

# key -> (label, emoji, hard floor, hard ceiling, unit)
RANGES = {
    "skill_rating": ("Skill rating", "⭐", 0, 10, "score"),
    "skill_price": ("Skill price", "💲", 0, None, "cents"),
    "attractiveness": ("Attractiveness", "🙂", 1, 10, "score"),
    "age": ("Age", "🎂", 13, 120, "years"),
    "distance": ("Distance", "🗺️", 0, None, "km"),
}


class Range:
    """One low–high gate. Either end may be open."""

    __slots__ = ("key", "low", "high")

    def __init__(self, key, low=None, high=None):
        self.key = key
        floor, ceiling = RANGES[key][2], RANGES[key][3]
        self.low = None if low is None else max(float(low), float(floor))
        self.high = high if high is None else (
            float(high) if ceiling is None else min(float(high), float(ceiling)))
        # A reversed range is a typo, not an empty result. Swapping is kinder
        # than returning nothing and letting them wonder why.
        if self.low is not None and self.high is not None and self.low > self.high:
            self.low, self.high = self.high, self.low

    @property
    def active(self):
        return self.low is not None or self.high is not None

    def contains(self, value):
        """None means 'we don't know', which never satisfies a gate."""
        if value is None:
            return False
        value = float(value)
        if self.low is not None and value < self.low:
            return False
        if self.high is not None and value > self.high:
            return False
        return True

    def payload(self):
        label, emoji, floor, ceiling, unit = RANGES[self.key]
        return {"key": self.key, "label": label, "emoji": emoji, "unit": unit,
                "min": self.low, "max": self.high,
                "limit_min": floor, "limit_max": ceiling}


def _number(raw):
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return None


def parse(params):
    """Read every range out of a query dict. Returns {key: Range}."""
    out = {}
    for key in RANGES:
        low = high = None
        combined = (params.get(key) or "").strip() if hasattr(params, "get") else ""
        if combined and "-" in combined:
            left, _, right = combined.partition("-")
            low, high = _number(left), _number(right)
        elif combined:
            low = _number(combined)
        if low is None:
            low = _number(params.get(f"{key}_min"))
        if high is None:
            high = _number(params.get(f"{key}_max"))
        rng = Range(key, low, high)
        if rng.active:
            out[key] = rng
    return out


# --- how each range reads its value off a member ----------------------------

def skill_rating_of(user, **_):
    return overall_median(user)


def attractiveness_of(user, **_):
    """Only counts when the member opted in to public attractiveness. A gate
    must never expose a score somebody chose to keep off their profile."""
    p = profile_for(user)
    if not getattr(p, "attractiveness_public", False):
        return None
    return attractiveness_median(user)


def age_of(user, **_):
    return profile_age(profile_for(user))


def skill_price_of(user, **_):
    """What they charge, in cents. Zero is a real answer — plenty of members
    collaborate for free — so it is not treated as missing."""
    p = profile_for(user)
    value = getattr(p, "skill_price_cents", None)
    return value if value is not None else 0


def distance_of(user, viewer=None, **_):
    """Great-circle km. Needs BOTH parties sharing a location — one-sided
    coordinates would let a search reveal where somebody is."""
    if viewer is None:
        return None
    mine, theirs = profile_for(viewer), profile_for(user)
    for p in (mine, theirs):
        if not getattr(p, "share_location", False):
            return None
    return haversine_km(mine.lat, mine.lng, theirs.lat, theirs.lng)


RESOLVERS = {
    "skill_rating": skill_rating_of,
    "skill_price": skill_price_of,
    "attractiveness": attractiveness_of,
    "age": age_of,
    "distance": distance_of,
}


def evaluate(user, ranges, viewer=None):
    """(passes, detail). `detail` says which gate rejected them and why."""
    detail = {}
    passes = True
    for key, rng in ranges.items():
        value = RESOLVERS[key](user, viewer=viewer)
        ok = rng.contains(value)
        detail[key] = {"value": value, "ok": ok,
                       "reason": None if ok else ("unknown" if value is None
                                                  else "out_of_range")}
        if not ok:
            passes = False
    return passes, detail


def apply(users, ranges, viewer=None):
    """Split a list of members into those inside every gate and those outside.

    Returns {"matches", "excluded", "unknown"}. `unknown` is separate on
    purpose: excluded-because-out-of-range and excluded-because-we-have-no-data
    are different answers, and only one of them is worth showing the searcher.
    """
    matches, excluded, unknown = [], [], []
    for user in users:
        if not ranges:
            matches.append(user)
            continue
        ok, detail = evaluate(user, ranges, viewer=viewer)
        if ok:
            matches.append(user)
        elif any(d["reason"] == "unknown" for d in detail.values()):
            unknown.append(user)
        else:
            excluded.append(user)
    return {"matches": matches, "excluded": excluded, "unknown": unknown}


def catalog():
    """What the filter UI needs to draw the five sliders."""
    return {
        "ranges": [
            {"key": k, "label": label, "emoji": emoji,
             "limit_min": floor, "limit_max": ceiling, "unit": unit}
            for k, (label, emoji, floor, ceiling, unit) in RANGES.items()
        ],
        "rules": {
            "exclusive": True,
            "unknown_excluded": True,
            "accepts": ["age=18-30", "age_min=18&age_max=30"],
            "note": ("Ranges are exclusive gates — outside means excluded, not "
                     "ranked lower. Members with no value for a gated range are "
                     "reported separately as `unknown` rather than dropped."),
        },
        "applies_to": ["collabz", "venuez", "battlez", "social"],
    }
