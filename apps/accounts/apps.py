from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"
    verbose_name = "Accounts & Auth"

    def ready(self):
        # Auto-fix corsheaders.E013 at startup, BEFORE the system check runs.
        # Cleans CORS_ALLOWED_ORIGINS / CSRF_TRUSTED_ORIGINS no matter where the
        # value came from (hardcoded list OR a Render env var). Wrapped so it can
        # never crash boot. This is why no settings.py edit is required.
        self._sanitize_cors_origins()

    @staticmethod
    def _sanitize_cors_origins():
        try:
            from urllib.parse import urlparse
            from django.conf import settings

            def _clean(seq):
                out = []
                for v in (seq or []):
                    v = (v or "").strip().rstrip("/")
                    if not v:
                        continue
                    if "://" not in v:          # bare host -> add scheme
                        v = "https://" + v
                    p = urlparse(v)
                    if p.scheme and p.netloc:    # drop "://host" / malformed
                        origin = f"{p.scheme}://{p.netloc}"
                        if origin not in out:
                            out.append(origin)
                return out

            for key in ("CORS_ALLOWED_ORIGINS", "CSRF_TRUSTED_ORIGINS"):
                if hasattr(settings, key):
                    setattr(settings, key, _clean(getattr(settings, key)))
        except Exception:
            # Never let the sanitizer take down the process.
            pass
