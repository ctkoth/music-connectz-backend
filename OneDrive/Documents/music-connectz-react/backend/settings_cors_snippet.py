# Add this to your Django settings.py
INSTALLED_APPS += ['corsheaders']
MIDDLEWARE = ['corsheaders.middleware.CorsMiddleware'] + MIDDLEWARE
CORS_ALLOWED_ORIGINS = [
    "https://musicconnectz.net",
    "https://www.musicconnectz.net",
]# Add this to your Django settings.py
INSTALLED_APPS += ['corsheaders']
MIDDLEWARE = ['corsheaders.middleware.CorsMiddleware'] + MIDDLEWARE
CORS_ALLOWED_ORIGINS = [
    "https://musicconnectz.net",
    "https://www.musicconnectz.net",
]
