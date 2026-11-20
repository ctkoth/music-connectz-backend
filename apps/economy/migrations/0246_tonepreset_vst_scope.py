from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """A plugin preset (kind "vst") is named within its plugin, so the one-name-per-kind rule no longer
    covers it. Additive in effect: every existing row is another kind and keeps the same guarantee."""

    dependencies = [("economy", "0245_health_link_step_day")]

    operations = [
        migrations.RemoveConstraint(model_name="tonepreset", name="tonepreset_owner_kind_name"),
        migrations.AddConstraint(
            model_name="tonepreset",
            constraint=models.UniqueConstraint(fields=("owner", "kind", "name"), condition=models.Q(("kind", "vst"), _negated=True),
                                               name="tonepreset_owner_kind_name"),
        ),
    ]
