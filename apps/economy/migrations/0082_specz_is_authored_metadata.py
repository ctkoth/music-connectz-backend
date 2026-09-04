"""SpecZ stops being a catalog of things nothing produced.

The old row said which of six analytics products you owned — "Audience
Demographics", "Engagement Heatmap" — and NOTHING GENERATED ANY OF THEM.
Nothing read this table either, so the row was the entire purchase. The SpecZ
that was real all along was the one the tab let members write themselves, and
that lived in their browser's localStorage.

Written by hand rather than by `makemigrations`, which wanted an invented
default for each new column. The table is almost certainly empty in production
— the buy endpoint charged money and no client ever called it — but "almost
certainly" is exactly the reasoning that loses somebody's data, so this
migrates rather than drops: an old row keeps its price, and its `item_id`
becomes the label of the SpecZ it turns into, so it stays readable instead of
becoming a blank row nobody can explain.
"""
from django.db import migrations, models


def item_id_becomes_the_label(apps, schema_editor):
    SpecZPurchase = apps.get_model("economy", "SpecZPurchase")
    for p in SpecZPurchase.objects.all():
        p.label = (p.item_id or "SpecZ")[:60]
        p.value = "Bought from the old SpecZ catalog."
        p.save(update_fields=["label", "value"])


class Migration(migrations.Migration):

    dependencies = [
        ("economy", "0081_profile_voice_emoji_profile_voice_explicit_and_more"),
    ]

    operations = [
        # A member may write as many SpecZ as they like now; the old constraint
        # meant "buy each catalog product once".
        migrations.AlterUniqueTogether(name="speczpurchase", unique_together=set()),
        migrations.AddField(
            model_name="speczpurchase", name="app_key",
            field=models.CharField(default="postz", max_length=32),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="speczpurchase", name="label",
            field=models.CharField(default="", max_length=60),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="speczpurchase", name="value",
            field=models.CharField(default="", max_length=200),
            preserve_default=False,
        ),
        migrations.RunPython(item_id_becomes_the_label, migrations.RunPython.noop),
        migrations.RemoveField(model_name="speczpurchase", name="item_id"),
        # A rename, so the number survives. SpinaZ is pegged to cents, so the
        # value means the same thing; the name stops lying about the unit.
        migrations.RenameField(
            model_name="speczpurchase", old_name="price_cents", new_name="price_spinaz",
        ),
        # SpinaZ is never dev-taxed (`split_participants`), so this column
        # could only ever hold 0.
        migrations.RemoveField(model_name="speczpurchase", name="dev_tax_cents"),
    ]
