"""Badge catalog + award rules. Badges are earned from training (scores, levels,
streaks, XP). Catalog metadata lives here; earned rows live in UserAchievement.
"""
from django.db.models import Count, Sum

BADGE_CATALOG = {
    "first_step":  {"title": "First Step",   "emoji": "🌱", "desc": "Completed your first drill."},
    "passed_5":    {"title": "Getting Reps",  "emoji": "💪", "desc": "Passed 5 drills in this app."},
    "perfect":     {"title": "Flawless",      "emoji": "💯", "desc": "Scored 100 on a drill."},
    "level_5":     {"title": "Rising",        "emoji": "⭐", "desc": "Reached level 5 in a track."},
    "level_10":    {"title": "Specialist",    "emoji": "🏅", "desc": "Reached level 10 in a track."},
    "streak_7":    {"title": "Locked In",     "emoji": "🔥", "desc": "7-day training streak."},
    "xp_1000":     {"title": "Grinder",       "emoji": "🏆", "desc": "Earned 1,000 XP in this app."},
}


def _level_from_xp(xp):
    from .utils import level_for_xp
    return level_for_xp(xp)[0]


def evaluate(user, app_key, ctx):
    """Return badge codes the user now qualifies for in this app.
    ctx: {score, leveled_up, track_level, streak}
    """
    from .models import Attempt, SkillProgress
    earned = set()

    earned.add("first_step")
    if ctx.get("score") == 100:
        earned.add("perfect")
    if ctx.get("track_level", 0) >= 5:
        earned.add("level_5")
    if ctx.get("track_level", 0) >= 10:
        earned.add("level_10")
    if ctx.get("streak", 0) >= 7:
        earned.add("streak_7")

    passed = Attempt.objects.filter(user=user, passed=True, drill__track__app_key=app_key).count()
    if passed >= 5:
        earned.add("passed_5")

    app_xp = SkillProgress.objects.filter(user=user, track__app_key=app_key).aggregate(s=Sum("total_xp"))["s"] or 0
    if app_xp >= 1000:
        earned.add("xp_1000")

    return earned


def award(user, app_key, ctx):
    """Create any newly-earned UserAchievement rows; return list of NEW codes."""
    from .models import UserAchievement
    qualifies = evaluate(user, app_key, ctx)
    have = set(UserAchievement.objects.filter(user=user, app_key=app_key, code__in=qualifies)
               .values_list("code", flat=True))
    new = qualifies - have
    UserAchievement.objects.bulk_create(
        [UserAchievement(user=user, app_key=app_key, code=c) for c in new], ignore_conflicts=True)
    return sorted(new)


def hydrate(rows):
    """Attach catalog metadata to UserAchievement rows -> list of dicts."""
    out = []
    for r in rows:
        meta = BADGE_CATALOG.get(r.code, {"title": r.code, "emoji": "🎖️", "desc": ""})
        out.append({"code": r.code, "app": r.app_key, "earned_at": r.earned_at,
                    **meta})
    return out
