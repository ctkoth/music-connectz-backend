from django.db import migrations


def set_site_domain(apps, schema_editor):
    Site = apps.get_model('sites', 'Site')
    Site.objects.update_or_create(
        id=1,
        defaults={
            'domain': 'music-connectz-backend-2.onrender.com',
            'name': 'Music ConnectZ Backend',
        }
    )


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0002_skill_work_date_uploaded_work_genre_work_price_and_more'),
        ('sites', '0002_alter_domain_unique'),
    ]

    operations = [
        migrations.RunPython(set_site_domain, migrations.RunPython.noop),
    ]
