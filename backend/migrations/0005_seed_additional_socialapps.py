import os

from django.db import migrations


def _upsert_social_app(apps, provider, name, env_prefix):
    SocialApp = apps.get_model('socialaccount', 'SocialApp')

    client_id = os.environ.get(f'{env_prefix}_CLIENT_ID', '')
    client_secret = os.environ.get(f'{env_prefix}_CLIENT_SECRET', '')

    if not client_id or not client_secret:
        print(f'INFO: Missing credentials for {provider} ({env_prefix}_CLIENT_ID/_SECRET); skipping.')
        return None

    app = SocialApp.objects.filter(provider=provider).order_by('id').first()
    if app is None:
        app = SocialApp.objects.create(
            provider=provider,
            name=name,
            client_id=client_id,
            secret=client_secret,
        )
        print(f'Created SocialApp for {provider}.')
    else:
        app.name = name
        app.client_id = client_id
        app.secret = client_secret
        app.save(update_fields=['name', 'client_id', 'secret'])
        print(f'Updated SocialApp for {provider}.')

    return app


def seed_additional_socialapps(apps, schema_editor):
    Site = apps.get_model('sites', 'Site')
    site = Site.objects.filter(id=1).first()

    providers = [
        ('apple', 'Apple', 'APPLE'),
        ('microsoft', 'Microsoft', 'MICROSOFT'),
        ('facebook', 'Facebook', 'FACEBOOK'),
        ('twitter_oauth2', 'X (Twitter)', 'TWITTER'),
        ('linkedin_oauth2', 'LinkedIn', 'LINKEDIN'),
        ('github', 'GitHub', 'GITHUB'),
        ('google', 'Google', 'GOOGLE'),
        ('spotify', 'Spotify', 'SPOTIFY'),
        ('soundcloud', 'SoundCloud', 'SOUNDCLOUD'),
    ]

    for provider, name, env_prefix in providers:
        app = _upsert_social_app(apps, provider, name, env_prefix)
        if app is not None and site is not None:
            app.sites.add(site)


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0004_seed_google_socialapp'),
        ('socialaccount', '0005_socialtoken_nullable_app'),
        ('sites', '0002_alter_domain_unique'),
    ]

    operations = [
        migrations.RunPython(seed_additional_socialapps, migrations.RunPython.noop),
    ]
