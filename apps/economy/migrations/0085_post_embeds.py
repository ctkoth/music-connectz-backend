# Generated migration for post embeds (portfolio showcase)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("economy", "0084_soundz"),
    ]

    operations = [
        migrations.AddField(
            model_name="post",
            name="embeds",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Portfolio showcase: [{type, url, title}] for YouTube/Spotify/SoundCloud"
            ),
        ),
    ]
