"""What a score points at: teach it, or learn it from someone.

Corey's rule: a take at 6 or above is a prompt to coach or teach in LessonZ; below 5 it is
advice plus teachers and coaches with the SAME skill. 5 to under 6 is the middle of the
scale and gets neither — nothing is said that the number does not support.

Honesty rules, because this sits on the most-read screen in the app:

* **One take is an invitation, not a qualification.** LessonZ already says who may teach
  (`MIN_TEACH_RATING`, the member's rating in that skill — RateZ, a stored rating, or their
  SkillZ level, highest wins). The CTA states that rating next to the take's score and says
  what is still needed, instead of promising a door the server will then refuse.
* **Teachers are real offers** (`LessonOffer`, active, same skill), never invented, shown
  with the price BEFORE anything is booked, best-rated first. No offers means the screen
  says nobody teaches it yet.
* **Adults only.** LessonZ teaching and live lessons are adult-only on this platform, so a
  minor gets neither CTA (their own free drills and the coach's fixes are untouched).
* **Never a dead end and never a risk to the take**: every caller wraps this, because a
  recommendation failing must not turn a scored take the member paid for into an error.
"""
from .models import is_minor

TEACH_AT = 6          # == apps.lessonz.models.MIN_TEACH_RATING (asserted by the tests)
LEARN_BELOW = 5
MAX_TEACHERS = 3


def zone(score):
    """'teach' at 6 or more, 'learn' below 5, else None. None for an unscored take."""
    if score is None:
        return None
    if score >= TEACH_AT:
        return "teach"
    if score < LEARN_BELOW:
        return "learn"
    return None


def skill_names(app_key):
    """The names a teacher might have filed the same skill under: the coach's key
    ('guitarz'), without the Z ('guitar'), and its label ('GuitarZ')."""
    from .instruments import profile_for_app
    names = {app_key.lower(), profile_for_app(app_key)["label"].lower()}
    if app_key.lower().endswith("z"):
        names.add(app_key.lower()[:-1])
    return names


def context(user, app_key, memo=None):
    """What does not change from take to take, read once per request. `memo` is the
    caller's own dict (the history screen shares one across its whole list)."""
    memo = memo if memo is not None else {}
    key = ("lessons", user.pk, app_key)
    if key not in memo:
        memo[key] = {"user": user, "app_key": app_key, "adult": not is_minor(user), "memo": memo}
    return memo[key]


def _rating(ctx):
    if "rating" not in ctx:
        from apps.lessonz.models import get_skill_rating
        ctx["rating"] = int(get_skill_rating(ctx["user"], ctx["app_key"]) or 0)
    return ctx["rating"]


def _teachers(ctx):
    """Up to MAX_TEACHERS active offers for this skill, best-rated first. Read once per
    context, so a list of forty low takes costs one query, not forty."""
    if "teachers" not in ctx:
        from apps.lessonz.models import LessonOffer
        from .models import blocked_user_ids
        user = ctx["user"]
        names = skill_names(ctx["app_key"])
        hidden = set(blocked_user_ids(user)) | {user.pk}
        rows = []
        # LessonZ stores a skill lower-cased and stripped, and `names` is lower-case, so a plain
        # `in` matches. Over-fetch a little: a minor's offer is skipped below, not served.
        qs = (LessonOffer.objects.filter(is_active=True, skill__in=list(names))
              .exclude(teacher_id__in=hidden).select_related("teacher")
              .order_by("-rating_snapshot", "-id"))
        for o in qs[:MAX_TEACHERS * 4]:
            if is_minor(o.teacher):
                continue
            rows.append({
                "id": o.pk, "teacher": o.teacher.username, "title": o.title, "skill": o.skill,
                "rating": o.rating_snapshot, "price": str(o.price), "currency": o.currency,
                "mode": o.pricing_mode, "remote_ok": o.remote_ok, "callz_ok": o.callz_ok,
                "city": o.city,
            })
            if len(rows) >= MAX_TEACHERS:
                break
        ctx["teachers"] = rows
    return ctx["teachers"]


def lessons_for(score, ctx, weakest_label=""):
    """The CTA for a take scored `score`, or None. Pure of any request."""
    z = zone(score)
    if z is None or not ctx["adult"]:
        return None
    label = _label(ctx["app_key"])
    if z == "teach":
        rating = _rating(ctx)
        can = rating >= TEACH_AT
        return {
            "zone": "teach", "score": score, "skill": ctx["app_key"], "label": label,
            "title": f"This take is at teaching level — share your {label}",
            "text": (f"A {score:g} is the kind of {label} other members learn from. "
                     + ("You can publish a lesson offer now: you set the price and students pay it, you never pay."
                        if can else
                        f"LessonZ opens teaching at a {TEACH_AT}★ rating in the skill itself, and yours is "
                        f"{rating}★ — a single take is a start, so keep training and it opens.")),
            "can_teach": can, "rating": rating, "min_required": TEACH_AT,
            "cta": {"label": "Teach it on LessonZ" if can else "See what teaching needs",
                    "tab": "lessonz", "target": "lessonz-teach", "carry": {"view": "teach", "skill": ctx["app_key"]}},
        }
    teachers = _teachers(ctx)
    return {
        "zone": "learn", "score": score, "skill": ctx["app_key"], "label": label,
        "title": "Learn this from someone who has it",
        "text": ((f"Start with {weakest_label} — it scored lowest. " if weakest_label else "")
                 + ("These members teach " + label + " on LessonZ; the price is shown before you book anything."
                    if teachers else
                    f"Nobody offers {label} lessons on LessonZ yet. The drills below are free, and you can browse "
                    "other teachers there.")),
        "teachers": teachers,
        "cta": {"label": "Find a teacher" if not teachers else "See all " + label + " teachers",
                "tab": "lessonz", "target": "lessonz-browse", "carry": {"view": "browse", "skill": ctx["app_key"]}},
    }


def _label(app_key):
    from .instruments import profile_for_app
    return profile_for_app(app_key)["label"]


def for_take(user, app_key, score, weakest_label="", memo=None):
    """One call for the coach result. Never raises."""
    try:
        return lessons_for(score, context(user, app_key, memo), weakest_label)
    except Exception:                                        # pragma: no cover
        import logging
        logging.getLogger(__name__).exception("take lessons CTA failed")
        return None


def collab_door(app_key, score, *, genre="", weakest_label="", take_id=None):
    """Send this take to CollabZ — offered at EVERY score, to every age (collabs are open
    at any age), because the two ends of the scale want opposite things from it. A weaker
    take wants somebody stronger in the skill it is weak in; a strong one wants a partner
    to finish, produce or release it. Same door, wording by the number. Free to open:
    starting a deal costs the ⚡ price of the skills the starter brings, and CollabZ states
    that before anything is confirmed. Nothing here is a claim about the take beyond the
    number the member was shown."""
    label = _label(app_key)
    seeking_help = score is None or score < TEACH_AT
    if seeking_help:
        door_label = "Find a stronger collaborator"
        note = ((f"Your {weakest_label} scored lowest — " if weakest_label else "")
                + "a collab pairs you with someone better at it. Free to look; starting a deal costs the ⚡ "
                  "price of the skills you bring, shown before you confirm.")
        seek = "help"
    else:
        door_label = "Take it to a collab"
        note = ("Find a partner to finish, produce or release it. Free to look; starting a deal costs the ⚡ "
                "price of the skills you bring, shown before you confirm.")
        seek = "partner"
    title = (f"{label} take — need a stronger hand" + (f" on {weakest_label}" if weakest_label else "")
             if seeking_help else f"{label} take — looking for a partner")[:160]
    return {"key": "collabz", "label": door_label, "tab": "collabz", "target": "collabz-start",
            "carry": {"title": title, "skill": app_key, "genre": genre or "", "seek": seek,
                      **({"take_id": take_id} if take_id else {})},
            "cost": None, "note": note}
