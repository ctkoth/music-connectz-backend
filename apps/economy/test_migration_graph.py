"""The migration graph must have exactly one leaf.

Both repos deploy from `main` and `build.sh` runs `migrate` on every deploy.
Two branches that each add "the next" migration are each fine alone and
together leave two leaves, which makes `migrate` refuse with "Conflicting
migrations detected" — so the deploy fails after a green merge. It happened
once (two 0178s); the fix is `makemigrations --merge`, and this is the check
that says so before the deploy does.
"""
from django.db.migrations.loader import MigrationLoader
from django.test import SimpleTestCase


class MigrationGraphTests(SimpleTestCase):
    def test_every_app_has_a_single_leaf(self):
        loader = MigrationLoader(None, ignore_no_migrations=True)
        conflicts = loader.detect_conflicts()
        self.assertEqual(conflicts, {},
                         f"Multiple leaf migrations: {conflicts}. Run `makemigrations --merge`.")
