"""Find accounts that look like the same person, from the command line.

The screen is `GET /api/economy/dupez/` and it is the one anybody should use.
This is the same detection with no web in the way — for a look at production
over SSH, and for the case where the screen itself is what is broken.

**It reports and it stops.** It does not delete, it does not merge, and the
`--notify` flag it used to carry is gone: it printed a summary to stdout and
then said "✓ Notifications sent to N users" without sending anything. A flag
that reports having done something it did not do is worse than a missing
feature, because the person who ran it stops looking.

Two things it used to get wrong, both of which meant it could not find the case
it existed for:

* It queried ``oauthidentity__email``. The reverse name is ``oauth_identities``,
  so that branch raised FieldError the moment a real cross-email duplicate
  existed — i.e. it only ever "worked" on a platform that had none.
* It looked for one OAuth identity on two accounts, which
  ``unique_together = ("provider", "provider_uid")`` makes impossible. It was
  checking for something the database forbids.

Both are gone: detection lives in ``apps.economy.dupez`` now, so the command
and the screen cannot disagree about what a duplicate is.

Usage:
    python manage.py find_duplicate_accounts
    python manage.py find_duplicate_accounts --verbose
"""
from django.core.management.base import BaseCommand

from apps.economy.dupez import duplicate_groups


class Command(BaseCommand):
    help = "Report accounts that share a strong identity signal. Reports only."

    def add_arguments(self, parser):
        parser.add_argument("--verbose", action="store_true",
                            help="Show the signals behind every pair.")

    def handle(self, *args, **options):
        groups = duplicate_groups()
        if not groups:
            self.stdout.write(self.style.SUCCESS("No duplicate accounts found."))
            return

        self.stdout.write(self.style.WARNING(
            f"{len(groups)} group(s) of accounts share a strong identity signal.\n"
            f"Nothing has been changed. Resolve them in DupeZ."))

        for i, g in enumerate(groups, 1):
            self.stdout.write(f"\n{i}. suggested keep: @{g['suggested_keep']}")
            self.stdout.write("-" * 70)
            for a in g["accounts"]:
                # Money first among the numbers: it is the one that makes a
                # delete unrecoverable rather than merely irreversible.
                self.stdout.write(
                    f"  @{a['username']:<20} {a['email']:<30} {a['tier']:<8} "
                    f"joined {(a['joined'] or '')[:10]}  "
                    f"{a['posts']}p {a['uploads']}u  "
                    f"money {a['money_cents'] / 100:.2f} "
                    f"royalties {a['royalties_cents'] / 100:.2f}"
                    + (f"  sign-ins: {', '.join(a['sign_ins'])}" if a["sign_ins"] else ""))
            if options.get("verbose"):
                for p in g["pairs"]:
                    for s in p["signals"]:
                        self.stdout.write(
                            f"    @{p['a']} ~ @{p['b']}: {s['label']}"
                            + (f" ({s['detail']})" if s["detail"] else "")
                            + f" [{s['weight']}]")
