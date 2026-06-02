from django.core.management.base import BaseCommand

from apps.skillz.seed import seed_skillz


class Command(BaseCommand):
    help = "Seed SkillZ tracks + drills for the training apps (idempotent)."

    def handle(self, *args, **opts):
        c = seed_skillz()
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {c['tracks']} new tracks, {c['drills']} new drills."))
