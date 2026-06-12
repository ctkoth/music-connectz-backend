import os, dj_database_url
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get('SECRET_KEY', 'change-me')
DEBUG = False
ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third party
    'rest_framework',
    'corsheaders',
    'rest_framework_simplejwt',
    # Local apps
    'apps.accounts',
    'apps.ai',
    'apps.analytics',
    'apps.designz',
   # 'apps.direct',
    'apps.events',
    'apps.memberships',
    'apps.notifications',
    'apps.personas',
    'apps.profiles',
    'apps.referrals',
    'apps.search',
    'apps.shotz',
    'apps.storage',
    'apps.tasks',
    'apps.transactions',
    'apps.video',
    'apps.votes',
    'apps.writez',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'music_connectz.urls'
WSGI_APPLICATION = 'music_connectz.wsgi.application'

TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [], 'APP_DIRS': True, 'OPTIONS': {'context_processors': ['django.template.context_processors.debug', 'django.template.context_processors.request', 'django.contrib.auth.context_processors.auth', 'django.contrib.messages.context_processors.messages']}}]

DATABASE_URL = os.environ.get('DATABASE_URL')
DATABASES = {
    'default': dj_database_url.parse(DATABASE_URL, conn_max_age=600)
    if DATABASE_URL else
    {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3'}
}

AUTH_USER_MODEL = 'accounts.User'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
}

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
CORS_ALLOW_ALL_ORIGINS = True
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True
# Appended missing apps
INSTALLED_APPS += [
    'apps.skillz',
    'apps.shotz',
    'apps.events',
    'apps.battles',
    'apps.collabs',
    'apps.analytics',
    'apps.ai',
    'apps.dawz',
    'apps.designz',
    'apps.developz',
    'apps.direct',
    'apps.managez',
    'apps.memberships',
    'apps.messages',
    'apps.mixez',
    'apps.notifications',
    'apps.payments',
    'apps.personas',
    'apps.producez',
    'apps.profiles',
    'apps.referrals',
    'apps.releases',
    'apps.scoutz',
    'apps.search',
    'apps.storage',
    'apps.subscriptions',
    'apps.tasks',
    'apps.transactions',
    'apps.video',
    'apps.votes',
    'apps.writez',
    'apps.common',
]

# Appended missing apps
INSTALLED_APPS += [
    'apps.skillz',
    'apps.shotz',
    'apps.events',
    'apps.battles',
    'apps.collabs',
    'apps.analytics',
    'apps.ai',
    'apps.dawz',
    'apps.designz',
    'apps.developz',
    'apps.direct',
    'apps.managez',
    'apps.memberships',
    'apps.messages',
    'apps.mixez',
    'apps.notifications',
    'apps.payments',
    'apps.personas',
    'apps.producez',
    'apps.profiles',
    'apps.referrals',
    'apps.releases',
    'apps.scoutz',
    'apps.search',
    'apps.storage',
    'apps.subscriptions',
    'apps.tasks',
    'apps.transactions',
    'apps.video',
    'apps.votes',
    'apps.writez',
    'apps.common',
]
