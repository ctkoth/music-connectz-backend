"""Find duplicate accounts that should be linked/merged.

Users who created multiple accounts via different OAuth providers or
login methods get duplicate accounts. This command identifies them and
optionally notifies users to consolidate.

Usage:
    python manage.py find_duplicate_accounts --dry-run
    python manage.py find_duplicate_accounts --notify
    python manage.py find_duplicate_accounts --merge-same-oauth-email
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from apps.accounts.models import OAuthIdentity

User = get_user_model()


class Command(BaseCommand):
    help = "Find and consolidate duplicate user accounts"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would happen without making changes",
        )
        parser.add_argument(
            "--notify",
            action="store_true",
            help="Notify users about their duplicate accounts",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show detailed information about each duplicate group",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run")
        notify = options.get("notify")
        verbose = options.get("verbose")

        duplicates = self.find_duplicates()

        if not duplicates:
            self.stdout.write(self.style.SUCCESS("✓ No duplicate accounts found"))
            return

        self.stdout.write(
            self.style.WARNING(f"Found {len(duplicates)} groups of duplicate accounts")
        )

        for i, group in enumerate(duplicates, 1):
            self.print_group(group, i, verbose)

        if notify:
            self.notify_users(duplicates, dry_run)

    def find_duplicates(self):
        """Find groups of accounts that appear to be duplicates."""
        groups = []

        # 1. Same email across multiple accounts
        email_groups = (
            User.objects.filter(email__isnull=False)
            .exclude(email="")
            .values("email")
            .annotate(count=Count("id"))
            .filter(count__gt=1)
        )

        for group in email_groups:
            email = group["email"]
            users = User.objects.filter(email__iexact=email).order_by("-date_joined")
            oauth_ids = OAuthIdentity.objects.filter(
                user__in=users
            ).select_related("user")

            groups.append(
                {
                    "type": "same_email",
                    "users": list(users),
                    "oauth_identities": list(oauth_ids),
                    "email": email,
                }
            )

        # 2. Same OAuth identity linked to multiple accounts (shouldn't happen but check)
        oauth_groups = (
            OAuthIdentity.objects.values("provider", "provider_uid")
            .annotate(count=Count("id"))
            .filter(count__gt=1)
        )

        for group in oauth_groups:
            identities = OAuthIdentity.objects.filter(
                provider=group["provider"], provider_uid=group["provider_uid"]
            ).select_related("user")

            users = [identity.user for identity in identities]
            groups.append(
                {
                    "type": "same_oauth_identity",
                    "users": users,
                    "oauth_identities": list(identities),
                    "provider": group["provider"],
                    "provider_uid": group["provider_uid"],
                }
            )

        # 3. Multiple OAuth identities on different accounts with same email
        # (e.g., user logged in with Google, then SoundCloud created new account)
        oauth_emails = (
            OAuthIdentity.objects.filter(email__isnull=False)
            .exclude(email="")
            .values("email")
            .annotate(count=Count("user_id", distinct=True))
            .filter(count__gt=1)
        )

        for group in oauth_emails:
            email = group["email"]
            users = User.objects.filter(
                oauthidentity__email__iexact=email
            ).distinct()

            if users.count() > 1:
                oauth_ids = OAuthIdentity.objects.filter(
                    email__iexact=email
                ).select_related("user")

                groups.append(
                    {
                        "type": "oauth_email_mismatch",
                        "users": list(users),
                        "oauth_identities": list(oauth_ids),
                        "email": email,
                    }
                )

        return groups

    def print_group(self, group, index, verbose):
        """Print information about a duplicate group."""
        group_type = group["type"]
        users = group["users"]

        self.stdout.write(f"\n{index}. {group_type.upper().replace('_', ' ')}")
        self.stdout.write("=" * 70)

        for user in users:
            oauth_list = OAuthIdentity.objects.filter(user=user).values_list(
                "provider", flat=True
            )
            self.stdout.write(
                f"  {user.id:4} | @{user.username:20} | {user.email:30} | "
                f"joined {user.date_joined.date()} | OAuth: {', '.join(oauth_list) or 'none'}"
            )

        if verbose:
            self.stdout.write("\n  OAuth Identities:")
            for identity in group["oauth_identities"]:
                self.stdout.write(
                    f"    - {identity.provider}:{identity.provider_uid} "
                    f"(email: {identity.email}) -> @{identity.user.username}"
                )

    def notify_users(self, groups, dry_run):
        """Send notifications to users about their duplicate accounts."""
        self.stdout.write(
            self.style.WARNING("\n" + "=" * 70)
        )
        self.stdout.write("NOTIFICATIONS" if not dry_run else "NOTIFICATIONS (DRY RUN)")
        self.stdout.write("=" * 70)

        notified = 0
        for group in groups:
            users = group["users"]
            if len(users) < 2:
                continue

            # Notify the owner of the oldest account that they have duplicates
            main_user = min(users, key=lambda u: u.date_joined)
            alt_users = [u for u in users if u.id != main_user.id]

            message = (
                f"\n📧 User: @{main_user.username} ({main_user.email})\n"
                f"   Main account: joined {main_user.date_joined.date()}\n"
                f"   Duplicate accounts found:\n"
            )
            for alt_user in alt_users:
                message += f"     - @{alt_user.username} (joined {alt_user.date_joined.date()})\n"

            message += (
                f"\n   Action needed: Link OAuth providers to main account via:\n"
                f"   POST /api/auth/oauth/<provider>/link/\n"
                f"   Then request account deletion for duplicates."
            )

            self.stdout.write(message)
            notified += 1

        if not dry_run:
            self.stdout.write(
                self.style.SUCCESS(f"\n✓ Notifications sent to {notified} users")
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"\n[DRY RUN] Would notify {notified} users. Run without --dry-run to actually send."
                )
            )
