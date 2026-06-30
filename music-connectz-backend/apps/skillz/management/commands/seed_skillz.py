"""Seed SkillZ drills + badges for every creator app that ships a seeder.

    python manage.py seed_skillz

Each creator app may expose `seed()` in its `seed` module (e.g. apps.mimez.seed).
This command discovers and runs the ones bundled here; it's idempotent.
"""
from importlib import import_module

from django.core.management.base import BaseCommand

# Apps that ship a `seed()` callable in apps.<app>.seed
SEEDABLE_APPS = ["mimez", "directz"]


class Command(BaseCommand):
    help = "Seed SkillZ drills and badges for creator apps."

    def handle(self, *args, **options):
        for app in SEEDABLE_APPS:
            try:
                mod = import_module(f"apps.{app}.seed")
            except Exception as exc:  # pragma: no cover - defensive
                self.stderr.write(self.style.WARNING(f"skip {app}: {exc}"))
                continue
            seed = getattr(mod, "seed", None)
            if not callable(seed):
                self.stderr.write(self.style.WARNING(f"skip {app}: no seed()"))
                continue
            result = seed()
            self.stdout.write(
                self.style.SUCCESS(
                    f"{app}: +{result.get('drills', 0)} drills, "
                    f"+{result.get('badges', 0)} badges"
                )
            )
        self.stdout.write(self.style.SUCCESS("SkillZ seed complete."))
