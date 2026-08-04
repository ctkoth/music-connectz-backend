"""Tell members whose skills still show elapsed time to add their end dates.

    python manage.py nudge_skills --dry-run     # who would get it, and the text
    python manage.py nudge_skills               # send
    python manage.py nudge_skills steve515      # one member
    python manage.py nudge_skills --again       # re-send to people already nudged

Experience used to be `today - start`, so a member who played 1999-2013 and
stopped read 26 years instead of 14. The model is fixed, but their data is not:
a skill still holding a bare `start` keeps showing elapsed time until its owner
adds an end date. Their profile is overstating them right now and they have no
idea the option exists — which is the whole reason to reach out rather than
wait.

Only members who would actually benefit are contacted. Somebody whose skills
are already stinted, or who has none, is skipped rather than mailed noise.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.economy.models import Notification, Profile, notify
from apps.economy.social import _skill_years

User = get_user_model()

# Doubles as the idempotency key: a member carrying this notification has been
# nudged. Stored on the notification itself, so no migration and no second
# place to keep in sync.
NUDGE_KEY = "nudge:skills"


def legacy_skills(profile):
    """Skills still on the start-only shape — the ones showing elapsed time.

    A skill with `periods` has been answered, whatever the answer was. A skill
    with neither is undated and has no number to overstate.
    """
    out = []
    for persona in (profile.personas or []):
        if not isinstance(persona, dict):
            continue
        for s in (persona.get("skills") or []):
            if isinstance(s, dict) and s.get("start") and not s.get("periods"):
                out.append(s)
    return out


def worst_offender(skills):
    """The skill claiming the most years — the one worth naming in the text."""
    best, best_yrs = None, None
    for s in skills:
        yrs = _skill_years(s)
        if yrs is not None and (best_yrs is None or yrs > best_yrs):
            best, best_yrs = s, yrs
    return best, best_yrs


def message_for(skill, years):
    """Say what is wrong with THEIR number, not 'please update your profile'.

    Notification.text is 280 chars and notify() truncates, so this stays short
    enough to survive intact.
    """
    name = str(skill.get("name", "that skill"))[:40]
    since = str(skill.get("start", ""))[:4]
    return (
        f"Your {name} shows {years} yrs — counted from {since}, not the years you actually played. "
        f"If you ever stopped, open ProfileZ → Skills, add the end date, and it'll show the time you served."
    )


class Command(BaseCommand):
    help = "Notify members whose skills still show elapsed time instead of time served."

    def add_arguments(self, parser):
        parser.add_argument("identifier", nargs="?", help="username or email; omit for everyone eligible")
        parser.add_argument("--dry-run", action="store_true",
                            help="list who would be contacted and change nothing")
        parser.add_argument("--again", action="store_true",
                            help="re-send to members already nudged")

    def handle(self, *args, **options):
        profiles = Profile.objects.select_related("user").all()
        ident = options.get("identifier")
        if ident:
            user = (User.objects.filter(username__iexact=ident).first()
                    or User.objects.filter(email__iexact=ident).first())
            if not user:
                self.stderr.write(self.style.ERROR(f"No member matches '{ident}'."))
                return
            profiles = profiles.filter(user=user)

        sent = skipped_done = skipped_clean = 0
        for p in profiles:
            skills = legacy_skills(p)
            if not skills:
                skipped_clean += 1
                continue
            skill, years = worst_offender(skills)
            if skill is None:
                skipped_clean += 1
                continue

            already = Notification.objects.filter(user=p.user, item_id=NUDGE_KEY).exists()
            if already and not options["again"]:
                skipped_done += 1
                self.stdout.write(f"  · {p.user.username} — already nudged, skipping")
                continue

            text = message_for(skill, years)
            if options["dry_run"]:
                self.stdout.write(f"  → {p.user.username}: {text}")
            else:
                notify(p.user, "system", text, item_id=NUDGE_KEY)
                self.stdout.write(self.style.SUCCESS(f"  ✓ {p.user.username} ({len(skills)} skill(s), worst {years} yrs)"))
            sent += 1

        verb = "would notify" if options["dry_run"] else "notified"
        self.stdout.write(self.style.SUCCESS(
            f"\n{verb} {sent} · {skipped_done} already nudged · {skipped_clean} nothing to fix"))
        if options["dry_run"] and sent:
            self.stdout.write("Nothing was sent. Re-run without --dry-run to send.")
