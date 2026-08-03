"""Credit a referral that happened off-link.

    python manage.py grant_referral K-Oth steve515
    python manage.py grant_referral K-Oth steve515 --dry-run

Someone joins because you told them to, but never touches your invite link —
so nothing records it and neither side gets paid. This credits it after the
fact, through the same `record_referral()` the link uses, so both people are
paid exactly what they'd have been paid at signup: the referrer earns
REFERRAL_REWARD_REFERRER_SPINAZ, the joinee their welcome bonus.

Deliberately a management command and not an admin action or an API route:
creating a Referral row by hand in /admin/ links the two accounts but pays
nobody, because the payout lives in record_referral() rather than in a model
signal. That silent half-fix is the trap this exists to avoid.

Idempotent and non-destructive. A member can only ever be referred once, so a
second run reports the existing link and pays nothing.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.economy.models import (
    REFERRAL_REWARD_JOINEE_SPINAZ,
    REFERRAL_REWARD_REFERRER_SPINAZ,
    Referral,
    record_referral,
    wallet_for,
)

User = get_user_model()


def _find(ident):
    """Resolve a user by username or email, case-insensitively."""
    return (
        User.objects.filter(username__iexact=ident).first()
        or User.objects.filter(email__iexact=ident).first()
    )


class Command(BaseCommand):
    help = "Credit a referral that was never recorded, paying both sides."

    def add_arguments(self, parser):
        parser.add_argument("referrer", help="who did the referring — username or email")
        parser.add_argument("joinee", help="who joined — username or email")
        parser.add_argument("--dry-run", action="store_true",
                            help="say what would happen and change nothing")

    def handle(self, *args, **options):
        referrer = _find(options["referrer"])
        joinee = _find(options["joinee"])

        for label, ident, user in (("referrer", options["referrer"], referrer),
                                   ("joinee", options["joinee"], joinee)):
            if not user:
                self.stderr.write(self.style.ERROR(f"No {label} matches '{ident}'."))
                return

        if referrer.id == joinee.id:
            self.stderr.write(self.style.ERROR("Nobody can refer themselves."))
            return

        existing = Referral.objects.filter(joinee=joinee).select_related("referrer").first()
        if existing:
            who = existing.referrer.username
            if existing.referrer_id == referrer.id:
                self.stdout.write(self.style.WARNING(
                    f"Already credited — {who} → {joinee.username} on "
                    f"{existing.created_at:%Y-%m-%d}. Nothing paid."))
            else:
                self.stderr.write(self.style.ERROR(
                    f"{joinee.username} was already referred by {who}. A member is only "
                    f"ever referred once, so this was not changed."))
            return

        if options["dry_run"]:
            self.stdout.write(
                f"Would credit {referrer.username} → {joinee.username}: "
                f"+{REFERRAL_REWARD_REFERRER_SPINAZ} 🍥 to {referrer.username}, "
                f"+{REFERRAL_REWARD_JOINEE_SPINAZ} 🍥 to {joinee.username}.")
            return

        if not record_referral(referrer, joinee):
            self.stderr.write(self.style.ERROR("Could not record that referral."))
            return

        self.stdout.write(self.style.SUCCESS(
            f"✓ {referrer.username} → {joinee.username}\n"
            f"  {referrer.username}: +{REFERRAL_REWARD_REFERRER_SPINAZ} 🍥 "
            f"(now {wallet_for(referrer).spinaz})\n"
            f"  {joinee.username}: +{REFERRAL_REWARD_JOINEE_SPINAZ} 🍥 "
            f"(now {wallet_for(joinee).spinaz})"))
