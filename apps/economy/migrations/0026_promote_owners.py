"""Promote platform owner(s) to staff/superuser + StatZ on every deploy.

Runs the same logic as the `make_owner` command and the login self-heal, but as
a migration so it applies automatically the moment this ships to Render — the
reliable path that doesn't depend on the owner logging in after deploy. Matches
by email (OWNER_EMAILS) OR username (OWNER_USERNAMES). Idempotent and safe: a
missing user is a no-op, and it never demotes anyone.
"""
from django.conf import settings
from django.db import migrations


def promote_owners(apps, schema_editor):
    User = apps.get_model(settings.AUTH_USER_MODEL.split(".")[0], settings.AUTH_USER_MODEL.split(".")[1])
    Membership = apps.get_model("economy", "Membership")

    emails = [e.strip().lower() for e in (getattr(settings, "OWNER_EMAILS", []) or []) if e.strip()]
    usernames = [u.strip().lower() for u in (getattr(settings, "OWNER_USERNAMES", []) or []) if u.strip()]
    if not emails and not usernames:
        return

    qs = User.objects.all()
    for user in qs:
        email = (user.email or "").lower()
        uname = (user.username or "").lower()
        if (email and email in emails) or (uname and uname in usernames):
            changed = False
            if not user.is_staff or not user.is_superuser:
                user.is_staff = True
                user.is_superuser = True
                changed = True
            if changed:
                user.save(update_fields=["is_staff", "is_superuser"])
            m, _ = Membership.objects.get_or_create(user=user, defaults={"tier": "statz"})
            if m.tier in ("free", "premium"):
                m.tier = "statz"
                m.save(update_fields=["tier", "updated_at"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("economy", "0025_collabdeal"),
    ]

    operations = [
        migrations.RunPython(promote_owners, noop),
    ]
