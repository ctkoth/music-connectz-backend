"""List BodieZ exercises that have no demo clip, seated/lying ones first.

Read-only. The list of what still needs recording is derived from the library
every time it is asked for, never kept by hand: a "still needed" list nobody
re-checks sends the next reader to record something twice (this repo has been
bitten by exactly that). BODIEZ_VIDEOS.md is a dated snapshot of this output.

    python manage.py bodiez_video_audit            # everything missing
    python manage.py bodiez_video_audit --seated   # only seated/lying ones

Clips live in ctkoth/mcz-media, never in this repo. Dropping a file there does
not wire it: `demo_url` is set by a data migration (see 0177/0178), so a new
clip needs a one-line migration that points its exercise at it.
"""
import re

from django.core.management.base import BaseCommand

from apps.economy.models import BodieZExercise


def suggested_filename(name):
    """kebab-case, matching the clips that are already wired (barbell-row.mp4)."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{slug}.mp4"


def missing(seated_only=False):
    rows = BodieZExercise.objects.library().filter(demo_url="")
    out = []
    for ex in rows:
        sit = bool({"seated", "lying"} & set(ex.position_list))
        if seated_only and not sit:
            continue
        out.append((ex, sit))
    # seated/lying first, then by muscle and name
    out.sort(key=lambda t: (not t[1], t[0].muscle_group, t[0].name))
    return out


class Command(BaseCommand):
    help = "List BodieZ exercises with no demo clip (seated/lying first)."

    def add_arguments(self, parser):
        parser.add_argument("--seated", action="store_true",
                            help="Only exercises that can be done seated or lying.")

    def handle(self, *args, **opts):
        total = BodieZExercise.objects.library().count()
        rows = missing(opts["seated"])
        have = BodieZExercise.objects.library().exclude(demo_url="").count()
        self.stdout.write(f"{have} of {total} exercises have a clip; {len(rows)} listed below.\n")
        section = None
        for ex, sit in rows:
            if sit != section:
                section = sit
                self.stdout.write("\nSeated / lying (the ones a member who can't stand is offered):"
                                  if sit else "\nStanding / floor / kneeling:")
            limbs = ", ".join(l for l, need in (("arms", ex.needs_arms), ("legs", ex.needs_legs)) if need) or "neither limb required"
            self.stdout.write(f"  {ex.muscle_group:<11} {ex.name:<34} {ex.equipment:<10} "
                              f"{'/'.join(ex.position_list):<16} needs {limbs:<22} -> {suggested_filename(ex.name)}")
