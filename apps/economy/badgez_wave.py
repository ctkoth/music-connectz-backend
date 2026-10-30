"""BadgeZ, wave one — a badge for every coach, and royalties said out loud.

Named in Corey's voice: a Z where an s would be (High NoteZ, Hot BarZ, Royal
RatingZ), except Thorough, which he wants plain. The emoji are his placeholders
and ride in the neon icon until his art lands.

The rule this file answers to is `badgez.py`'s: a badge that only looks nice is
a sticker. So every badge here either CHANGES a number some other system reads,
or REFLECTS a number that is already moving money and says so — never a second
copy of one (the Founding Fifty lesson in `models.BADGES`).

THE COACH BADGES. One per coach, earned by `HOT_TAKES` takes that coach scored
`HOT_SCORE`+ inside `HOT_DAYS`. The score is the coach LISTENING, so this is the
substance rule's good side: nobody gets one without the takes getting good. It
is TEMPORARY — the window rolls, so a member who stops performing at that level
watches it go. The perk is `ai_energy_off_pct`: the ⚡ an AI run takes is cut,
read by `models.ai_energy_cost`, which is also what prices the run on screen, so
the price shown and the price taken stay the same number. Eleven at 10% would be
70%, so the total is capped at `AI_ENERGY_OFF_CAP` there.

THE ROYALTY PAIR. `royaltyfactor.curve` already moves what a track earns per
play by (median − 5) × 10% once five people outside the credits have rated it.
Royal RatingZ 💰 is held while a track earns a boost of at least `ROYAL_FACTOR`,
and Cut RoyaltieZ ✂️ while one earns under the base rate. Neither pays or takes
anything of its own: the formula does that, and the badge is where a member
finds out it is happening rather than reading it off a payout.

PENALTIES are TEMPORARY and HIDDEN BY DEFAULT (`penalty: True`). A penalty must
come out of a record somebody ELSE settled — here, five-plus outside raters —
never out of one member's say-so, or it is a weapon one member aims at another.
That is also why no-show and dispute penalties are not here: nothing in the
codebase records a no-show, and a dispute is opened by one side of a deal.
"""
from datetime import timedelta

HOT_TAKES = 3
HOT_SCORE = 8
HOT_DAYS = 30
COACH_ENERGY_OFF = 10      # % off the ⚡ an AI run takes, per coach badge
AI_ENERGY_OFF_CAP = 50     # however many coach badges stack
ROYAL_FACTOR = 1.2         # a track earning +20% per play or more
ROYALTY_POSTS = 50         # the most recent posts the royalty pair reads

# app_key -> (badge key, name, emoji). One per coach in `instruments.INSTRUMENTS`;
# test_badgez_wave fails if a coach exists with no badge.
COACH_BADGES = {
    "singz": ("high_notez", "High NoteZ", "🎤"),
    "rapz": ("hot_barz", "Hot BarZ", "🎙️"),
    "guitarz": ("six_stringz", "Six StringZ", "🎸"),
    "bassz": ("low_endz", "Low EndZ", "🔊"),
    "keyz": ("ivory_keyz", "Ivory KeyZ", "🎹"),
    "drumz": ("deep_pocketz", "Deep PocketZ", "🥁"),
    "violinz": ("golden_bowz", "Golden BowZ", "🎻"),
    "flutez": ("silver_flutez", "Silver FluteZ", "🪈"),
    "saxz": ("smooth_saxz", "Smooth SaxZ", "🎷"),
    "clarinetz": ("reed_tonez", "Reed ToneZ", "🎼"),
    "trumpetz": ("brass_blastz", "Brass BlastZ", "🎺"),
}
COACH_LABEL = {"singz": "SingZ", "rapz": "RapZ", "guitarz": "GuitarZ", "bassz": "BassZ",
               "keyz": "KeyZ", "drumz": "DrumZ", "violinz": "ViolinZ",
               "flutez": "FluteZ", "saxz": "SaxZ", "clarinetz": "ClarinetZ", "trumpetz": "TrumpetZ"}


def _cached(user, attr, compute):
    """One reading per user object per recheck: `recheck_badges` asks every
    check in turn, and seven coach badges must not be seven queries."""
    got = getattr(user, attr, None)
    if got is None:
        got = compute()
        try:
            setattr(user, attr, got)
        except Exception:
            pass
    return got


def hot_counts(user):
    """{app_key: takes scored HOT_SCORE+ in the last HOT_DAYS}, in one query."""
    def compute():
        from django.db.models import Count
        from django.utils import timezone
        from .models import TakeScore
        since = timezone.now() - timedelta(days=HOT_DAYS)
        rows = (TakeScore.objects.filter(user=user, overall__gte=HOT_SCORE, created_at__gte=since)
                .values("app_key").annotate(n=Count("id")))
        return {r["app_key"]: r["n"] for r in rows}
    return _cached(user, "_hot_counts", compute)


def is_hot(user, app_key):
    return hot_counts(user).get(app_key, 0) >= HOT_TAKES


def royalty_reading(user):
    """{"best": factor, "worst": factor} over the member's recent posts whose
    factor is APPLIED (five-plus outside raters). Two queries."""
    def compute():
        from .models import ItemRating, Post
        from .royaltyfactor import MIN_RATERS, _median, curve
        posts = list(Post.objects.filter(author=user).order_by("-created_at")
                     .values("id", "contributors")[:ROYALTY_POSTS])
        if not posts:
            return {"best": None, "worst": None}
        keys = {f"post:{p['id']}": p for p in posts}
        scores = {}
        for item, rater_id, rater_name, score in (ItemRating.objects.filter(item_id__in=keys)
                                                  .values_list("item_id", "user_id", "user__username", "score")):
            credited = {c.get("username") for c in (keys[item]["contributors"] or []) if isinstance(c, dict)}
            if rater_id == user.id or rater_name in credited:
                continue
            scores.setdefault(item, []).append(score)
        factors = [curve(_median(v)) for v in scores.values() if len(v) >= MIN_RATERS]
        if not factors:
            return {"best": None, "worst": None}
        return {"best": max(factors), "worst": min(factors)}
    return _cached(user, "_royalty_reading", compute)


def is_royal(user):
    best = royalty_reading(user)["best"]
    return best is not None and best >= ROYAL_FACTOR


def is_cut(user):
    worst = royalty_reading(user)["worst"]
    return worst is not None and worst < 1.0


def specs():
    """The wave's entries for `models.BADGES`. Checks import lazily — this module
    is read while models.py is still being built."""
    out = {}
    for app_key, (key, name, emoji) in COACH_BADGES.items():
        coach = COACH_LABEL[app_key]
        out[key] = {
            "name": name, "emoji": emoji, "title": name, "gifted": False, "temporary": True,
            "icon": f"badge_{key}.png", "app": app_key,
            "desc": f"Your {coach} takes are landing: {HOT_TAKES} scored {HOT_SCORE}+ by the coach in {HOT_DAYS} days.",
            "how": (f"Have the {coach} coach score {HOT_TAKES} of your takes {HOT_SCORE} or higher inside "
                    f"{HOT_DAYS} days. It lapses when the window does — keep the takes coming."),
            "effects": {"ai_energy_off_pct": COACH_ENERGY_OFF},
            "effect_note": (f"−{COACH_ENERGY_OFF}% ⚡ on every AI run while you hold it — stacks with the other "
                            f"coach badges up to −{AI_ENERGY_OFF_CAP}%."),
            "check": (lambda a: (lambda u: is_hot(u, a)))(app_key),
        }
    boost = round((ROYAL_FACTOR - 1) * 100)
    out["royal_ratingz"] = {
        "name": "Royal RatingZ", "emoji": "💰", "title": "Royal RatingZ", "gifted": False, "temporary": True,
        "icon": "badge_royal_ratingz.png", "app": "royaltiez",
        "desc": f"A track of yours earns +{boost}% or more per play because the room rates it.",
        "how": ("Get a track to a median of 7 or more from five-plus members outside its credits. "
                "It lapses if the median drops."),
        "effects": {"achievement": True},
        "effect_note": ("No extra payout — the rating already moves your royalty by (median − 5) × 10%. "
                        "This badge is where you see it happening. The numbers are in RoyaltieZ."),
        "check": lambda u: is_royal(u),
    }
    out["cut_royaltiez"] = {
        "name": "Cut RoyaltieZ", "emoji": "✂️", "title": "", "gifted": False, "temporary": True,
        "penalty": True, "icon": "badge_cut_royaltiez.png", "app": "royaltiez",
        "desc": "A track of yours earns under the base rate per play because the room rates it under 5.",
        "how": ("Five-plus members outside the credits rated a track of yours under 5. It lifts by itself "
                "when that median climbs back to 5 — a new take or a better mix is the way back."),
        "effects": {"achievement": True},
        "effect_note": ("No extra penalty — the rating already cuts that track's royalty by (5 − median) × 10%. "
                        "Hidden from other members unless you choose to show it."),
        "check": lambda u: is_cut(u),
    }
    return out
