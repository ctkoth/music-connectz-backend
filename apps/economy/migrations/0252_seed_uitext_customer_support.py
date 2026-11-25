"""Seed the shared UI-translation table with the Customer Support dialog in 50 languages.

Data only: `UiString` rows read by `uitext.py`, keyed by a hash of the English. Never
overwrites a row that is already there (`ignore_conflicts`), and the reverse removes only
the rows this wrote, matched on both language and the exact text.
"""
import hashlib
import json
import os

from django.db import migrations

SEED = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uitext_seed", "customer_support.json")


def _load():
    with open(SEED, encoding="utf-8") as f:
        return json.load(f)


def forwards(apps, schema_editor):
    UiString = apps.get_model("economy", "UiString")
    data = _load()
    rows = []
    for lang, texts in data["translations"].items():
        for src, text in zip(data["source"], texts):
            rows.append(UiString(lang=lang, key=hashlib.sha1(src.encode("utf-8")).hexdigest(), source=src, text=text))
    UiString.objects.bulk_create(rows, ignore_conflicts=True)


def backwards(apps, schema_editor):
    UiString = apps.get_model("economy", "UiString")
    data = _load()
    for lang, texts in data["translations"].items():
        for src, text in zip(data["source"], texts):
            UiString.objects.filter(lang=lang, key=hashlib.sha1(src.encode("utf-8")).hexdigest(), text=text).delete()


class Migration(migrations.Migration):
    dependencies = [("economy", "0251_print_design")]
    operations = [migrations.RunPython(forwards, backwards)]
