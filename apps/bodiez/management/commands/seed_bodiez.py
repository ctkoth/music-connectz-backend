"""Seed the BodieZ exercise library. Idempotent — safe on every deploy.

    python manage.py seed_bodiez

Updates catalog exercises in place (owner=None), so re-running after editing
apps/bodiez/catalog.py corrects the library without touching a member's own
custom movements or any routine that references one.
"""
from django.core.management.base import BaseCommand

from apps.bodiez.catalog import (EQUIPMENT, EXERCISES, MUSCLE_GROUPS,
                                 equipment_used, requirement_groups)
from apps.bodiez.models import Exercise


class Command(BaseCommand):
    help = "Create or update the BodieZ catalog exercises."

    def handle(self, *args, **options):
        created = 0
        for key, name, muscle, secondary, equipment, pattern, difficulty in EXERCISES:
            _, made = Exercise.objects.update_or_create(
                key=key, owner=None,
                defaults={"name": name, "muscle": muscle, "secondary": list(secondary),
                          "equipment": equipment_used(equipment),
                          "requires": [list(g) for g in requirement_groups(equipment)],
                          "pattern": pattern, "difficulty": difficulty, "active": True},
            )
            created += 1 if made else 0

        total = Exercise.objects.filter(owner__isnull=True).count()
        self.stdout.write(self.style.MIGRATE_HEADING("\nBodieZ library"))
        by_muscle = {}
        for e in Exercise.objects.filter(owner__isnull=True):
            by_muscle[e.muscle] = by_muscle.get(e.muscle, 0) + 1
        for key, name, emoji, _region in MUSCLE_GROUPS:
            self.stdout.write(f"  {emoji} {name:<12} {by_muscle.get(key, 0):>3} exercises")
        self.stdout.write(
            f"\n  {total} catalog exercises ({created} new), "
            f"{len(EQUIPMENT)} equipment types, {len(MUSCLE_GROUPS)} muscle groups."
        )
