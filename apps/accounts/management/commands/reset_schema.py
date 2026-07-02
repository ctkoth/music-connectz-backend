"""
reset_schema — DROP and recreate the Postgres `public` schema.

DESTRUCTIVE: erases EVERY table and row in the connected database. Use only to
clear a database whose old `django_migrations` history conflicts with this
project (symptom: `relation "auth_user" does not exist` during migrate because
old rows for `accounts`/`skillz`/`auth` make Django skip creating the tables).

Safety: refuses to run unless BOTH --force is passed AND the env var
RESET_DB=1 is set. No-ops on non-Postgres databases.
"""
import os

from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "DROP SCHEMA public CASCADE and recreate it (Postgres only, destructive)."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true")

    def handle(self, *args, **opts):
        if connection.vendor != "postgresql":
            self.stderr.write(self.style.WARNING(
                f"reset_schema only supports Postgres (got '{connection.vendor}'). Skipping."))
            return
        if not opts["force"] or os.environ.get("RESET_DB") != "1":
            self.stderr.write(self.style.ERROR(
                "Refusing: requires --force AND env RESET_DB=1. "
                "This erases ALL data in the connected database."))
            return
        with connection.cursor() as cur:
            cur.execute("DROP SCHEMA public CASCADE;")
            cur.execute("CREATE SCHEMA public;")
            cur.execute("GRANT ALL ON SCHEMA public TO CURRENT_USER;")
            cur.execute("GRANT ALL ON SCHEMA public TO public;")
        self.stdout.write(self.style.SUCCESS(
            "Schema reset. Run migrate to rebuild tables, then REMOVE RESET_DB from env."))
