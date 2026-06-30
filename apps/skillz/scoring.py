"""Shared scoring/award logic for the SkillZ engine.

Both the generic training AttemptView and app-specific challenge submissions
(e.g. DesignZ "submit my design for a score") funnel through record_attempt, so
XP, levels, streaks, badges, and the leaderboard all behave identically no matter
how the work was produced — drilled in-app, edited in ImageZ, or imported.
"""
import datetime

from . import badges as badge_engine
from .models import Attempt, SkillProgress
from .utils import level_for_xp


def record_attempt(user, drill, score):
    """Record an attempt for `drill` by `user` at `score` (0-100). Returns the
    result payload (passed, xp, level, streak, new badges)."""
    score = max(0, min(100, int(score)))
    passed = score >= 60
    xp = round(drill.xp_reward * (score / 100.0)) if passed else 0

    prog, _ = SkillProgress.objects.get_or_create(user=user, track=drill.track)
    before_level = level_for_xp(prog.total_xp)[0]
    prog.total_xp += xp

    today = datetime.date.today()
    if prog.last_practiced == today:
        pass
    elif prog.last_practiced == today - datetime.timedelta(days=1):
        prog.streak_days += 1
    else:
        prog.streak_days = 1
    prog.last_practiced = today
    prog.save()

    after_level = level_for_xp(prog.total_xp)[0]
    Attempt.objects.create(user=user, drill=drill, score=score, xp_earned=xp, passed=passed)
    new_badges = badge_engine.award(user, drill.track.app_key, {
        "score": score, "track_level": after_level,
        "streak": prog.streak_days, "leveled_up": after_level > before_level,
    })
    return {
        "passed": passed, "xp_earned": xp,
        "total_xp": prog.total_xp, "level": after_level,
        "leveled_up": after_level > before_level,
        "streak_days": prog.streak_days,
        "new_badges": [{"code": c, **badge_engine.BADGE_CATALOG.get(c, {})} for c in new_badges],
    }
