"""Who is already over the username rule — report only, never rewrite.

CLAUDE.md: "Never lower a live limit without a plan for the members already
over it." The handle rule was written down in `check-username/` and applied by
nothing that creates accounts, so anything at all could be registered — and
tightening it now leaves whoever got in under the old non-rule on the wrong
side of the new one.

This names them. Dry by default, like `reconcile_uploads` and
`repair_profiles`, and unlike those it has no `--write` at all: a username is
the address other members type and the `?ref=` invite they share, so renaming
somebody without asking breaks every link anybody ever made to them. The fix
for a bad handle is a conversation, not a sweep.

    python manage.py audit_usernames
    python manage.py audit_usernames --broken-only
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.accounts.usernames import RESERVED, USERNAME_RE, USERNAME_RULE


class Command(BaseCommand):
    help = "List accounts whose username would not be allowed today."

    def add_arguments(self, parser):
        parser.add_argument(
            "--broken-only", action="store_true",
            help="Only handles that break a URL or a referral link (/ ? # space).")

    def handle(self, *args, **opts):
        User = get_user_model()
        # The characters that do real damage rather than merely failing the
        # rule: a `/` makes the public profile unaddressable, and `?` or `#`
        # truncate the member's own invite link.
        URL_BREAKING = set("/?# \t")

        rows = []
        for u in User.objects.order_by("id").iterator():
            name = u.username or ""
            breaks_url = any(c in URL_BREAKING for c in name)
            if USERNAME_RE.match(name) and name.lower() not in RESERVED:
                continue
            if opts["broken_only"] and not breaks_url:
                continue
            rows.append((u.id, name, breaks_url))

        total = User.objects.count()
        self.stdout.write(f"Rule today: {USERNAME_RULE}")
        self.stdout.write(f"{len(rows)} of {total} accounts would not be allowed today.\n")
        for uid, name, breaks_url in rows:
            mark = "URL-BREAKING" if breaks_url else "would not pass"
            self.stdout.write(f"  #{uid:<6} {name!r:30} {mark}")
        if rows:
            self.stdout.write(
                "\nNothing was changed. A handle is the address other members "
                "type and the ?ref= link they share, so renaming one breaks "
                "every link made to it — talk to them first.")
