"""One address, one account — enforced by the database rather than by hope.

`RegisterSerializer.validate_email` checks `email__iexact` and then inserts,
which is a check-then-act with a gap in the middle: two signups on the same
address at the same time both pass the check and both commit. The OAuth path
has the same shape — it looks for a match, decides to create, then inserts
without looking again. Neither is common, both are possible, and the whole
point of the one-account rule is that it holds when somebody is trying.

`auth.User` is Django's own model, so this cannot be a `Meta.constraints`
entry — it is a partial expression index, created here.

Two things about its shape are load-bearing:

* **LOWER(email)**, because the application matches with `__iexact` and an
  index that disagreed with the lookup would let through exactly the rows the
  lookup thinks it excluded.
* **WHERE email <> ''**, because `email` is `blank=True` and a real population
  of members has no address at all — every account made through a provider
  that does not hand one over (Twitter gives none) is stored with `''`. Without
  the partial clause the second such member collides with the first, and the
  constraint meant to stop duplicates would instead stop signups.

Collisions are resolved BEFORE the index is created, in the same migration, in
order. `build.sh` runs `migrate --no-input` on every deploy unattended, so an
index that failed on existing data would fail the deploy — and the whole site
would sit on the previous version until somebody noticed why.
"""
from django.db import migrations


def resolve_collisions(apps, schema_editor):
    """Blank the address on all but the OLDEST account holding it.

    Nothing is deleted. An account whose email is blanked keeps its posts, its
    wallet and its uploads, and can still sign in by username or through any
    provider already linked to it — it just no longer answers to that address,
    which is the thing that has to become unique.

    Oldest wins because it is the one explainable rule: it is the account that
    registered the address, and every later one is the duplicate the rule
    exists to stop. Members who end up on the wrong side of it can re-add the
    address to the account they actually use, and DupeZ is already the place
    where "this other one is mine" gets said.

    Printed, not silent: a member losing the address they log in with is worth
    seeing in the deploy log rather than discovering from a support message.
    """
    User = apps.get_model("auth", "User")
    seen, cleared = {}, 0
    # Oldest first, so the first time an address is seen is the one that keeps
    # it. `id` rather than `date_joined`: it cannot be null and cannot tie.
    for uid, email in (User.objects.exclude(email="")
                       .order_by("id").values_list("id", "email")):
        key = (email or "").strip().lower()
        if not key:
            continue
        if key in seen:
            User.objects.filter(pk=uid).update(email="")
            cleared += 1
            print(f"  · {key}: kept #{seen[key]}, cleared it from #{uid}")
        else:
            seen[key] = uid
    if cleared:
        print(f"  · {cleared} duplicate address(es) cleared before the unique index")


def noop(apps, schema_editor):
    """Nothing to undo — a blanked address cannot be un-blanked from here.

    Deliberately not an error: reversing this migration should drop the index
    (below) rather than refuse, and the data step has no inverse to offer.
    """


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(resolve_collisions, noop),
        migrations.RunSQL(
            sql=(
                "CREATE UNIQUE INDEX IF NOT EXISTS accounts_user_email_ci_uniq "
                "ON auth_user (LOWER(email)) WHERE email <> '';"
            ),
            reverse_sql="DROP INDEX IF EXISTS accounts_user_email_ci_uniq;",
        ),
    ]
