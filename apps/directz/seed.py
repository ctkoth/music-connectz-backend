"""DirectZ SkillZ content — drills and badges. Idempotent.

    python manage.py seed_skillz
"""
try:
    from apps.common.training_seed import seed_app  # canonical, if present
except Exception:  # pragma: no cover
    from apps.skillz.seeds import seed_app

APP_KEY = "directz"

DRILLS = [
    # Dynamic Scene Creation
    {"key": "scene-blocking", "title": "Block the Scene", "category": "scene",
     "description": "Stage a 3-beat scene with clear blocking.", "xp": 60, "order": 1},
    {"key": "scene-coverage", "title": "Coverage Pass", "category": "scene",
     "description": "Plan wide / medium / close coverage for one moment.", "xp": 80, "order": 2},
    {"key": "scene-dynamic", "title": "Dynamic Motion", "category": "scene",
     "description": "Add a motivated camera move that serves the story.", "xp": 100, "order": 3},
    # Audio-Visual Harmony
    {"key": "av-beatmatch", "title": "Cut to the Beat", "category": "av_harmony",
     "description": "Edit a sequence so cuts land on the track's beats.", "xp": 70, "order": 4},
    {"key": "av-mood", "title": "Mood Match", "category": "av_harmony",
     "description": "Pair visuals with a score that matches the mood.", "xp": 90, "order": 5},
    {"key": "av-sounddesign", "title": "Sound Design Layer", "category": "av_harmony",
     "description": "Layer ambience + FX under a scene.", "xp": 110, "order": 6},
    # Creative Collaborations
    {"key": "collab-brief", "title": "Write the Brief", "category": "collab",
     "description": "Draft a one-page creative brief for a collaborator.", "xp": 60, "order": 7},
    {"key": "collab-session", "title": "Run a Session", "category": "collab",
     "description": "Co-direct a scene with another creator on the platform.", "xp": 130, "order": 8},
]

BADGES = [
    {"code": "first-cut", "name": "First Cut", "rule": "drills", "threshold": 1,
     "description": "Completed your first DirectZ drill.", "order": 1},
    {"code": "scene-smith", "name": "Scene Smith", "rule": "xp", "threshold": 400,
     "description": "400 XP across scene craft.", "order": 2},
    {"code": "in-harmony", "name": "In Harmony", "rule": "xp", "threshold": 900,
     "description": "900 XP — audio and visual locked in.", "order": 3},
    {"code": "showrunner", "name": "Showrunner", "rule": "streak", "threshold": 10,
     "description": "10-day DirectZ training streak.", "order": 4},
    {"code": "auteur", "name": "Auteur", "rule": "xp", "threshold": 2500,
     "description": "2500 XP — a director's vision.", "order": 5},
]


def seed():
    return seed_app(APP_KEY, drills=DRILLS, badges=BADGES)
