"""Forget every stored screen translation that kept the word "Energy" in English.

`UiString` is translated once and served to everybody, and "Energy" was on the list of
names the translator was told to keep, so "Energy" is stored as "Energy" in every
language. Taking it off the list fixes new strings only; these rows would go on being
served. Deleting them is safe: a missing row is simply translated again the next time
a screen shows that string (inside the daily cap), and a language whose own word for
energy really is "Energy" just gets the same answer back.

Data only, no schema, and nothing to put back on the way down.
"""
from django.db import migrations


def forget(apps, schema_editor):
    UiString = apps.get_model("economy", "UiString")
    UiString.objects.filter(source__contains="Energy", text__contains="Energy").delete()


class Migration(migrations.Migration):
    dependencies = [("economy", "0237_funnel_try_engage")]
    operations = [migrations.RunPython(forget, migrations.RunPython.noop)]
