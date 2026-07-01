"""MimeZ SkillZ content — drills and badges. Idempotent.

    python manage.py seed_skillz
"""
try:
    from apps.common.training_seed import seed_app  # canonical, if present
except Exception:  # pragma: no cover
    from apps.skillz.seeds import seed_app

APP_KEY = "mimez"

DRILLS = [
    # Lipsync
    {"key": "lipsync-warmup", "title": "Lipsync Warm-Up", "category": "lipsync",
     "description": "Mouth a slow 10-second line in perfect time.", "xp": 40, "order": 1},
    {"key": "lipsync-tempo", "title": "Tempo Lock", "category": "lipsync",
     "description": "Hit every beat of an up-tempo verse.", "xp": 60, "order": 2},
    {"key": "lipsync-emotion", "title": "Emotion Pass", "category": "lipsync",
     "description": "Match lyrics with matching facial emotion.", "xp": 80, "order": 3},
    # Selfie expression
    {"key": "selfie-angles", "title": "Find Your Angles", "category": "selfie",
     "description": "Three expressions, three angles, one take.", "xp": 40, "order": 4},
    {"key": "selfie-story", "title": "Selfie Story", "category": "selfie",
     "description": "Tell a mini-story across a 4-shot selfie set.", "xp": 70, "order": 5},
    # Dance
    {"key": "dance-8count", "title": "First 8-Count", "category": "dance",
     "description": "Clean execution of a basic 8-count.", "xp": 50, "order": 6},
    {"key": "dance-combo", "title": "Combo Builder", "category": "dance",
     "description": "Chain two 8-counts into a combo.", "xp": 90, "order": 7},
    {"key": "dance-freestyle", "title": "Freestyle Flow", "category": "dance",
     "description": "16 counts, your moves, on the beat.", "xp": 120, "order": 8},
]

BADGES = [
    {"code": "first-mime", "name": "First Mime", "rule": "drills", "threshold": 1,
     "description": "Completed your first MimeZ drill.", "order": 1},
    {"code": "lip-locked", "name": "Lip Locked", "rule": "xp", "threshold": 300,
     "description": "300 XP of lipsync, selfie, and dance reps.", "order": 2},
    {"code": "week-of-moves", "name": "Week of Moves", "rule": "streak", "threshold": 7,
     "description": "7-day MimeZ training streak.", "order": 3},
    {"code": "mime-machine", "name": "Mime Machine", "rule": "drills", "threshold": 25,
     "description": "25 drills logged.", "order": 4},
    {"code": "stage-ready", "name": "Stage Ready", "rule": "xp", "threshold": 1500,
     "description": "1500 XP — you're stage ready.", "order": 5},
]


def seed():
    return seed_app(APP_KEY, drills=DRILLS, badges=BADGES)
