"""Send the day-3 and day-7 retake reminders that have come due.

Hourly from the same cron service as habit reminders. Idempotent: a reminder
advances a stage only when its email actually went, so a run that dies halfway
is finished by the next one. See apps/economy/retake.py.
"""
from django.core.management.base import BaseCommand

from apps.economy import retake


class Command(BaseCommand):
    help = "Send retake reminder emails that are due."

    def handle(self, *args, **opts):
        if not retake.ready():
            # Not an error, and not "0 sent": nothing was attempted.
            self.stdout.write("EMAIL_HOST is not set — no reminders attempted.")
            return
        sent, failed = retake.run_due()
        self.stdout.write(f"retake reminders: {sent} sent, {failed} failed")
