"""Turn members' open platform TASKS into RoutineZ, where the starter library made them routines.

Dry run by default: it prints what it would do and changes nothing. `--write` does it. One routine per
task: the member's own title and note, the starter's cadence and action, and a streak that starts at
zero. The task is then deleted. A member already keeping that routine keeps the task (nothing is
duplicated), and a member at the routine ceiling keeps the task and is counted. Set-up tasks that stayed
tasks are not touched, finished tasks are history and are never touched, and nothing is paid here.
"""
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Turn open platform tasks into RoutineZ (a dry run unless --write is given)."

    def add_arguments(self, parser):
        parser.add_argument("--write", action="store_true",
                            help="Convert. Without it nothing changes, and the report says what would.")

    def handle(self, *args, **opts):
        from apps.economy import lilith_starters as ST
        from apps.economy.lilith_taskz import LilithRoutine, LilithTask, live_routines, routines_full, tier_limits
        from apps.economy.models import membership_for

        write = opts["write"]
        planned = defaultdict(int)          # routines a member would gain in a dry run (writes count in the DB)
        converted = kept_have = kept_full = 0
        tasks = (LilithTask.objects.filter(done_at__isnull=True).exclude(bucket="trash").exclude(template="")
                 .select_related("user").order_by("user_id", "pk"))
        for t in tasks:
            key = ST.routine_for_retired(t.template)
            spec = ST.routine_by_key(key) if key else None
            if not spec:
                continue                    # still a task on purpose: a set-up step
            if live_routines(t.user).filter(template=key).exists():
                kept_have += 1
                continue
            held = live_routines(t.user).count() + (0 if write else planned[t.user_id])
            if routines_full(held, tier_limits(membership_for(t.user).tier)):
                kept_full += 1
                continue
            planned[t.user_id] += 1
            converted += 1
            if write:
                with transaction.atomic():
                    LilithRoutine.objects.create(
                        user=t.user, title=t.title[:140], note=(t.note or "")[:500],
                        cadence=spec["cadence"], template=key, app_key=spec["app_key"],
                        target=spec["target"], action=spec.get("action", ""), goal=spec.get("goal", 1),
                        source="platform")
                    t.delete()

        verb = "Converted" if write else "Would convert"
        self.stdout.write(f"{verb} {converted} task{'' if converted == 1 else 's'} into RoutineZ.")
        self.stdout.write(f"Kept as tasks: {kept_have} already kept as a routine, "
                          f"{kept_full} at the routine ceiling.")
        if not write:
            self.stdout.write("Dry run: nothing changed. Run again with --write to convert.")
