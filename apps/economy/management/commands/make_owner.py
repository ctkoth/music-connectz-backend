"""Promote a user to platform owner (staff + superuser + StatZ) on demand.

    python manage.py make_owner ctkoth@gmail.com
    python manage.py make_owner K-Oth            # by username

With no argument, promotes everyone matching OWNER_EMAILS / OWNER_USERNAMES.
Idempotent; never demotes. The instant manual counterpart to migration
0026_promote_owners and the login self-heal in views.ensure_owner.
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.economy.models import TIER_FREE, TIER_PREMIUM, TIER_STATZ, membership_for

User = get_user_model()


class Command(BaseCommand):
    help = "Promote a user (or all configured owners) to staff/superuser + StatZ."

    def add_arguments(self, parser):
        parser.add_argument("identifier", nargs="?", help="email or username; omit to use OWNER_EMAILS/OWNER_USERNAMES")

    def handle(self, *args, **options):
        ident = options.get("identifier")
        if ident:
            users = list(User.objects.filter(email__iexact=ident)) or list(User.objects.filter(username__iexact=ident))
            if not users:
                self.stderr.write(self.style.ERROR(f"No user matches '{ident}'."))
                return
        else:
            emails = [e.lower() for e in (getattr(settings, "OWNER_EMAILS", []) or [])]
            usernames = [u.lower() for u in (getattr(settings, "OWNER_USERNAMES", []) or [])]
            users = [
                u for u in User.objects.all()
                if (u.email and u.email.lower() in emails) or (u.username and u.username.lower() in usernames)
            ]
            if not users:
                self.stderr.write(self.style.WARNING("No users match OWNER_EMAILS/OWNER_USERNAMES."))
                return

        for user in users:
            if not (user.is_staff and user.is_superuser):
                user.is_staff = True
                user.is_superuser = True
                user.save(update_fields=["is_staff", "is_superuser"])
            m = membership_for(user)
            if m.tier in (TIER_FREE, TIER_PREMIUM):
                m.tier = TIER_STATZ
                m.save(update_fields=["tier", "updated_at"])
            self.stdout.write(self.style.SUCCESS(f"✓ {user.username} <{user.email}> → owner + {m.tier}"))
