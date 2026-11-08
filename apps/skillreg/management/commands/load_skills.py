"""manage.py load_skills skills.json  -> upserts the specific-skill catalog.
JSON: [{"slug": "rap-flow-triplet", "name": "Triplet Flow", "family": "Rapping", "app_key": "rapz", "price_cents": 200}]"""
import json

from django.core.management.base import BaseCommand

from apps.skillreg.models import Skill


class Command(BaseCommand):
    def add_arguments(self, p):
        p.add_argument("path")

    def handle(self, *a, path, **kw):
        n = 0
        for row in json.load(open(path)):
            Skill.objects.update_or_create(
                slug=row["slug"],
                defaults={"name": row["name"], "app_key": row.get("app_key", ""), "family": row.get("family", ""),
                          "price_cents": int(row.get("price_cents", 0)), "active": True})
            n += 1
        self.stdout.write(f"loaded {n} skills")
