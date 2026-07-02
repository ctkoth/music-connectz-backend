"""LessonZ SkillZ content — teaching-craft drills. Idempotent."""
try:
    from apps.common.training_seed import seed_app  # canonical, if present
except Exception:  # pragma: no cover
    from apps.skillz.seeds import seed_app

APP_KEY = "lessonz"

DRILLS = [
    {"key": "first-syllabus", "title": "Write a Syllabus", "category": "teaching",
     "description": "Outline a 4-lesson plan for one of your skillz.", "xp": 60, "order": 1},
    {"key": "demo-lesson", "title": "Demo Lesson", "category": "teaching",
     "description": "Record a 5-minute teaching demo.", "xp": 90, "order": 2},
    {"key": "feedback-pass", "title": "Feedback Pass", "category": "teaching",
     "description": "Give structured feedback on a student attempt.", "xp": 80, "order": 3},
    {"key": "first-booking", "title": "First Booking", "category": "business",
     "description": "Publish an offer and complete your first lesson.", "xp": 150, "order": 4},
]

BADGES = [
    {"code": "new-teacher", "name": "New Teacher", "rule": "drills", "threshold": 1,
     "description": "Completed your first LessonZ drill.", "order": 1},
    {"code": "mentor", "name": "Mentor", "rule": "xp", "threshold": 500,
     "description": "500 XP of teaching craft.", "order": 2},
    {"code": "maestro", "name": "Maestro", "rule": "xp", "threshold": 2000,
     "description": "2000 XP — students seek you out.", "order": 3},
]


def seed():
    return seed_app(APP_KEY, drills=DRILLS, badges=BADGES)
