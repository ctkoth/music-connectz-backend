# Generated migration to enhance FunnelEvent for detailed funnel analytics

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("economy", "0109_preferences_substances"),
    ]

    operations = [
        migrations.AddField(
            model_name="funnelevent",
            name="age",
            field=models.IntegerField(null=True, blank=True, db_index=True),
        ),
        migrations.AddField(
            model_name="funnelevent",
            name="gender",
            field=models.CharField(
                max_length=16,
                choices=[
                    ("male", "Male"),
                    ("female", "Female"),
                    ("non_binary", "Non-binary"),
                    ("other", "Other"),
                    ("prefer_not", "Prefer not to say"),
                ],
                null=True,
                blank=True,
                db_index=True,
            ),
        ),
        migrations.AddField(
            model_name="funnelevent",
            name="source",
            field=models.CharField(
                max_length=32,
                choices=[
                    ("organic", "Organic Search"),
                    ("paid_ads", "Paid Ads"),
                    ("social", "Social Media"),
                    ("referral", "Referral"),
                    ("direct", "Direct"),
                    ("other", "Other"),
                ],
                null=True,
                blank=True,
                db_index=True,
            ),
        ),
        migrations.AddField(
            model_name="funnelevent",
            name="device",
            field=models.CharField(
                max_length=16,
                choices=[
                    ("mobile", "Mobile"),
                    ("tablet", "Tablet"),
                    ("desktop", "Desktop"),
                    ("other", "Other"),
                ],
                null=True,
                blank=True,
                db_index=True,
            ),
        ),
        migrations.AddField(
            model_name="funnelevent",
            name="retention_days",
            field=models.IntegerField(null=True, blank=True, db_index=True,
                                    help_text="Days between landing and first return visit"),
        ),
    ]
