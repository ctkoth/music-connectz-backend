"""
Django settings for music_connectz — Render-ready scaffold.

This is a clean, working project that wraps the new apps (skillz, accounts,
mimez, directz). It is the FALLBACK to use only if you cannot recover your full
repo from GitHub history (see RECOVER_REPO.md). It will NOT bring back your other
apps (dawz, designz, managez, scoutz, shotz, writez, common) — those live only in
your git history. Your Postgres data is untouched either way.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(name, default="0"):
    return os.environ.get(name, default).lower() in ("1", "true", "yes", "on")


SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-change-me")
DEBUG = _env_bool("DEBUG", "0")

ALLOWED_HOSTS = [
    "admin.musicconnectz.net",
    "musicconnectz.net",
    "www.musicconnectz.net",
    ".onrender.com",
    "localhost",
    "127.0.0.1",
]
_extra_hosts = os.environ.get("ALLOWED_HOSTS", "")
if _extra_hosts:
    ALLOWED_HOSTS += [h.strip() for h in _extra_hosts.split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third-party
    "corsheaders",
    "rest_framework",
    # local — skillz first so its tables migrate before the apps that use it
    "apps.skillz",
    "apps.accounts",
    "apps.economy",
    "apps.mimez",
    "apps.directz",
    "apps.lessonz",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "music_connectz.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "music_connectz.wsgi.application"

# Database — Render Postgres via DATABASE_URL, else sqlite for local dev.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
_db_url = os.environ.get("DATABASE_URL", "")
if _db_url:
    try:
        import dj_database_url

        DATABASES["default"] = dj_database_url.parse(
            _db_url, conn_max_age=600, ssl_require=True
        )
    except Exception:
        pass

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# User uploads. NOTE: Render's web filesystem is ephemeral — swap the default
# storage for S3/R2 (django-storages) in production so files survive deploys.
# Quota enforcement (per-tier upload/storage caps) is storage-backend agnostic.
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# DRF + SimpleJWT (frontend stores access token as `mcz_access`)
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
}

from datetime import timedelta  # noqa: E402

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=14),
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# CORS / CSRF — apps.accounts.ready() also sanitizes these at startup so a
# malformed origin can never trip corsheaders.E013.
CORS_ALLOWED_ORIGINS = [
    "https://musicconnectz.net",
    "https://www.musicconnectz.net",
    "https://ctkoth-music-connectz-frontend-wy3x.vercel.app",
    "http://localhost:5173",
    "https://localhost",
    "capacitor://localhost",
]
CSRF_TRUSTED_ORIGINS = [
    "https://musicconnectz.net",
    "https://www.musicconnectz.net",
    "https://admin.musicconnectz.net",
    "https://ctkoth-music-connectz-frontend-wy3x.vercel.app",
]

# Allow the custom domain (any subdomain) and any Vercel preview deploy of the
# frontend to call the API cross-origin. Regexes are checked in addition to the
# exact-match list above.
CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^https://([a-z0-9-]+\.)*musicconnectz\.net$",
    r"^https://ctkoth-music-connectz-frontend[a-z0-9-]*\.vercel\.app$",
]

# OAuth provider config (set as Render env vars)
GOOGLE_OAUTH_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
GITHUB_OAUTH_CLIENT_ID = os.environ.get("GITHUB_OAUTH_CLIENT_ID", "")
GITHUB_OAUTH_CLIENT_SECRET = os.environ.get("GITHUB_OAUTH_CLIENT_SECRET", "")
APPLE_OAUTH_CLIENT_ID = os.environ.get("APPLE_OAUTH_CLIENT_ID", "")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
