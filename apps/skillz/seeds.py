"""Idempotent seeding helpers so each app can register its own drills/badges."""
from .models import Badge, Drill


def seed_app(app_key, drills=None, badges=None):
    """Upsert drills + badges for an app_key. Safe to run repeatedly."""
    created = {"drills": 0, "badges": 0}

    for i, d in enumerate(drills or []):
        _, was_created = Drill.objects.update_or_create(
            app_key=app_key,
            key=d["key"],
            defaults={
                "title": d.get("title", d["key"]),
                "description": d.get("description", ""),
                "category": d.get("category", ""),
                "xp": d.get("xp", 50),
                "icon": d.get("icon", ""),
                "order": d.get("order", i),
                "is_active": d.get("is_active", True),
            },
        )
        created["drills"] += int(was_created)

    for i, b in enumerate(badges or []):
        _, was_created = Badge.objects.update_or_create(
            app_key=app_key,
            code=b["code"],
            defaults={
                "name": b.get("name", b["code"]),
                "description": b.get("description", ""),
                "icon": b.get("icon", ""),
                "rule": b.get("rule", Badge.RULE_XP),
                "threshold": b.get("threshold", 100),
                "order": b.get("order", i),
            },
        )
        created["badges"] += int(was_created)

    return created
