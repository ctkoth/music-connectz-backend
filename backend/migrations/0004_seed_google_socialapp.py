import os
from django.db import migrations


def seed_google_socialapp(apps, schema_editor):
    client_id = os.environ.get('GOOGLE_CLIENT_ID', '')
    client_secret = os.environ.get('GOOGLE_CLIENT_SECRET', '')

    if not client_id or not client_secret:
        print('WARNING: GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET not set — skipping Google SocialApp seed.')
        return

    SocialApp = apps.get_model('socialaccount', 'SocialApp')
    Site = apps.get_model('sites', 'Site')

    app, created = SocialApp.objects.update_or_create(
        provider='google',
        defaults={
            'name': 'Google',
            'client_id': client_id,
            'secret': client_secret,
        }
    )

    site = Site.objects.filter(id=1).first()
    if site:
        app.sites.add(site)

    action = 'Created' if created else 'Updated'
    print(f'{action} Google SocialApp (client_id={client_id[:20]}...)')


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0003_set_site_domain'),
        ('socialaccount', '0005_socialtoken_nullable_app'),
        ('sites', '0002_alter_domain_unique'),
    ]

    operations = [
        migrations.RunPython(seed_google_socialapp, migrations.RunPython.noop),
    ]
