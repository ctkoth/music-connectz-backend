"""Bad ratings earn less — and the AI coach can count, if the member says so.

Corey's two rules, as one module:

1. **A well-rated track earns its full per-play rate; a badly-rated one earns less.**
   `post_factor(post)` reads the median of what people OUTSIDE the credits scored the
   post. Seven and up earns the full rate (there is no bonus above it — a royalty that
   can be bid up by rating is one rating ring away from printing money); below seven it
   slides down to `FLOOR` at a 1. Never to zero: a play happened, somebody listened, and
   a floor is what stops a brigade of one-star ratings erasing a creator's income.
2. **The skills used on the track are rated too, and they move the share of the person who
   used them.** `skill_haircut(post, user)` is the same curve on that contributor's
   rating in the skill(s) they brought, so a great mix on a weak song and a weak mix on a
   great song are paid differently — the point of rating skills at all.

What this deliberately does not do:

* **Unrated is neutral, never a penalty.** Below `MIN_RATERS` outside raters the factor is
  1.0: "nobody has rated it yet" is an empty measurement, and an empty measurement must not
  cost anybody money (the substance rule: absent is not zero).
* **It never doubles up on a rated collab split.** A post from a deal whose pot was already
  re-cut by contribution rating (`basis == "rating"`) has had each person's rating applied
  once; applying a skill haircut on top would charge a bad rating twice.
* **The AI coach is opt-in and one voice among several.** With
  `Profile.coach_counts_for_skillz` on, a member's coach scores for the matching instrument
  join their listener ratings in `blended_skill_rating` as `COACH_VOTES` votes (the median of
  their recent takes, at least `MIN_COACH_TAKES` of them, so one lucky take cannot carry
  it). It cuts both ways and the opt-in says so before it is pressed. Humans stay the
  majority: with no listener ratings at all the coach alone stands only once those takes
  exist.
"""
from collections import defaultdict

from .models import ItemRating, SkillRating

MIN_RATERS = 5                 # outside raters before a post's rating moves its royalty
FULL_AT = 7                    # a median at or above this earns the full rate
FLOOR = 0.25                   # the lowest the factor goes (a median of 1)

COACH_VOTES = 2                # how many listener votes one coach reading is worth
MIN_COACH_TAKES = 3            # takes the coach median needs behind it
COACH_WINDOW = 10              # the most recent takes it reads

# The persona-skill names a member's work is rated under, per AI coach. Matched
# case-insensitively and by substring so "Lead Vocalist" and "vocals" both land on SingZ.
# One list: add a skill name here and every place that blends reads it.
COACH_SKILLS = {
    "singz": ("sing", "vocal"),
    "rapz": ("rap", "mc", "emcee"),
    "guitarz": ("guitar",),
    "bassz": ("bass",),
    "keyz": ("key", "piano", "synth"),
    "drumz": ("drum", "percussion"),
    "violinz": ("violin", "fiddle", "strings"),
}

RULE = (f"A track rated {FULL_AT}/10 or better earns the full per-play rate. Below that it earns less, "
        f"down to {int(FLOOR * 100)}% at a 1. Until {MIN_RATERS} people outside the credits have rated it, "
        "nothing changes — an unrated track is not a badly-rated one.")


def curve(median):
    """The factor for a median rating. Pure; None → neutral."""
    if median is None:
        return 1.0
    if median >= FULL_AT:
        return 1.0
    m = max(1.0, float(median))
    return round(FLOOR + (1.0 - FLOOR) * (m - 1.0) / (FULL_AT - 1.0), 4)


def _median(values):
    v = sorted(values)
    n = len(v)
    if not n:
        return None
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def post_rating(post):
    """(median, outside raters) of a post — raters not credited on it."""
    credited = {post.author_id}
    for c in (post.contributors or []):
        if isinstance(c, dict) and c.get("username"):
            credited.add(c["username"])
    rows = ItemRating.objects.filter(item_id=f"post:{post.id}").select_related("user")
    scores = [r.score for r in rows if r.user_id not in credited and r.user.username not in credited]
    return _median(scores), len(scores)


def post_factor(post):
    median, n = post_rating(post)
    if n < MIN_RATERS:
        return {"factor": 1.0, "median": median, "raters": n, "applied": False}
    return {"factor": curve(median), "median": median, "raters": n, "applied": True}


def coach_skill_key(skill):
    s = (skill or "").lower()
    for app_key, needles in COACH_SKILLS.items():
        if any(n in s for n in needles):
            return app_key
    return None


def _coach_median(user, app_key):
    from .models import TakeScore
    rows = list(TakeScore.objects.filter(user=user, app_key=app_key, overall__isnull=False)
                .order_by("-created_at").values_list("overall", flat=True)[:COACH_WINDOW])
    return (_median(rows), len(rows)) if len(rows) >= MIN_COACH_TAKES else (None, len(rows))


def opted_in(user):
    from .models import profile_for
    return bool(getattr(profile_for(user), "coach_counts_for_skillz", False))


def blended_skill_rating(user, skill):
    """(rating, detail) — listener ratings, plus the coach's reading when the member opted in
    and the skill has a coach. `detail` says what went into the number, so a screen never
    shows a rating it cannot explain."""
    human = list(SkillRating.objects.filter(subject=user, skill=skill).values_list("score", flat=True))
    detail = {"listeners": len(human), "coach": None}
    app_key = coach_skill_key(skill)
    coach = None
    if app_key and opted_in(user):
        med, n = _coach_median(user, app_key)
        detail["coach"] = {"app_key": app_key, "takes": n, "median": med, "used": med is not None}
        coach = med
    if coach is None:
        return (_median(human) if human else None), detail
    total = sum(human) + coach * COACH_VOTES
    return round(total / (len(human) + COACH_VOTES), 1), detail


def skill_haircut(post, user):
    """The factor on one contributor's share from the skills they brought, or 1.0.
    Averaged over those skills so bringing five does not multiply a bad one five times."""
    from .models import skills_for_post
    mine = [skill for u, skill in skills_for_post(post) if u.id == user.id]
    if not mine:
        return 1.0
    factors = []
    for skill in set(mine):
        n = SkillRating.objects.filter(subject=user, skill=skill).count()
        if n < MIN_RATERS and not (coach_skill_key(skill) and opted_in(user)):
            factors.append(1.0)
            continue
        rating, _ = blended_skill_rating(user, skill)
        factors.append(curve(rating) if rating is not None else 1.0)
    return round(sum(factors) / len(factors), 4)


# ----------------------------------------------------------------------- the API
from rest_framework import status                                   # noqa: E402
from rest_framework.permissions import IsAuthenticated              # noqa: E402
from rest_framework.response import Response                        # noqa: E402
from rest_framework.views import APIView                            # noqa: E402

COACH_OPT_IN_NOTE = (
    f"Your AI coach scores for an instrument can count toward the matching skill rating, as {COACH_VOTES} "
    f"votes beside the ratings listeners give your tracks (the median of your last {COACH_WINDOW} takes, "
    f"once you have {MIN_COACH_TAKES}). That rating moves what your share of a track's royalties is. "
    "It cuts both ways: a strong run of takes can raise it and a weak one can lower it. Listener ratings "
    "stay the majority, and you can switch it off any time.")


class SkillzCoachView(APIView):
    """GET → the choice, what it does and what is behind each coach skill; POST {enabled}."""
    permission_classes = [IsAuthenticated]

    def _state(self, request):
        from .instruments import profile_for_app
        on = opted_in(request.user)
        rows = []
        for app_key in COACH_SKILLS:
            med, n = _coach_median(request.user, app_key)
            rows.append({"app_key": app_key, "label": profile_for_app(app_key)["label"],
                         "takes": n, "median": med, "enough": med is not None})
        return {"enabled": on, "note": COACH_OPT_IN_NOTE, "coach_votes": COACH_VOTES,
                "min_takes": MIN_COACH_TAKES, "window": COACH_WINDOW, "coaches": rows}

    def get(self, request):
        return Response(self._state(request))

    def post(self, request):
        from .models import profile_for
        enabled = (request.data or {}).get("enabled")
        if not isinstance(enabled, bool):
            return Response({"detail": "Say yes or no."}, status=status.HTTP_400_BAD_REQUEST)
        p = profile_for(request.user)
        p.coach_counts_for_skillz = enabled
        p.save(update_fields=["coach_counts_for_skillz", "updated_at"])
        return Response(self._state(request))


class RoyaltyRatingsView(APIView):
    """GET → the rule, and what each of MY posts' rating does to what it earns — said
    before the track earns it, not found out in a payout."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import Post
        out = []
        for post in Post.objects.filter(author=request.user).order_by("-created_at")[:30]:
            pf = post_factor(post)
            out.append({"post_id": post.id, "title": post.title, "median": pf["median"],
                        "raters": pf["raters"], "factor": pf["factor"], "applied": pf["applied"],
                        "pct": round(pf["factor"] * 100),
                        "why": (f"{pf['raters']} outside ratings, median {pf['median']:g}/10." if pf["applied"] else
                                f"{pf['raters']} of {MIN_RATERS} outside ratings so far — full rate until then.")})
        return Response({"rule": RULE, "min_raters": MIN_RATERS, "full_at": FULL_AT,
                         "floor_pct": int(FLOOR * 100), "posts": out})
