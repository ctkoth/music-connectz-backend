import os
from django.apps import AppConfig


PROVIDER_ENV_MAP = {
    'google':         ('GOOGLE_CLIENT_ID',     'GOOGLE_CLIENT_SECRET'),
    'spotify':        ('SPOTIFY_CLIENT_ID',    'SPOTIFY_CLIENT_SECRET'),
    'soundcloud':     ('SOUNDCLOUD_CLIENT_ID', 'SOUNDCLOUD_CLIENT_SECRET'),
    'apple':          ('APPLE_CLIENT_ID',      'APPLE_CLIENT_SECRET'),
    'microsoft':      ('MICROSOFT_CLIENT_ID',  'MICROSOFT_CLIENT_SECRET'),
    'facebook':       ('FACEBOOK_CLIENT_ID',   'FACEBOOK_CLIENT_SECRET'),
    'twitter_oauth2': ('TWITTER_CLIENT_ID',    'TWITTER_CLIENT_SECRET'),
    'linkedin_oauth2':('LINKEDIN_CLIENT_ID',   'LINKEDIN_CLIENT_SECRET'),
    'github':         ('GITHUB_CLIENT_ID',     'GITHUB_CLIENT_SECRET'),
}


class BackendConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'backend'

    def ready(self):
        # Fix SoundCloud provider: API may return 'id' instead of 'urn'
        try:
            from allauth.socialaccount.providers.soundcloud.provider import SoundCloudProvider
            def _patched_extract_uid(self, data):
                return str(data.get('urn') or data.get('id') or data.get('permalink'))
            SoundCloudProvider.extract_uid = _patched_extract_uid
        except Exception:
            pass

        # Import signals to ensure UserProfile is created on signup
        try:
            import backend.signals
        except Exception:
            pass

        try:
            from allauth.socialaccount.models import SocialApp
            from django.contrib.sites.models import Site

            site, _ = Site.objects.get_or_create(
                id=1,
                defaults={'domain': 'musicconnectz.net', 'name': 'Music ConnectZ'},
            )

            for provider, (id_var, secret_var) in PROVIDER_ENV_MAP.items():
                client_id = os.environ.get(id_var, '')
                secret = os.environ.get(secret_var, '')
                if not client_id or not secret:
                    continue
                app, _ = SocialApp.objects.update_or_create(
                    provider=provider,
                    defaults={
                        'name': provider.replace('_oauth2', '').capitalize(),
                        'client_id': client_id,
                        'secret': secret,
                    },
                )
                if site not in app.sites.all():
                    app.sites.add(site)
        except Exception:
            pass  # DB not ready on first run (e.g. before migrations)
