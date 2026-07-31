import os

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path, re_path
from django.views.static import serve as static_serve

from apps.economy.views import StatsView
from apps.omviardz.wellknown import AssetLinksView

# SkillZ training is generated per app_key. MimeZ/DirectZ/LessonZ mount their own
# inside their urls.py; the InstrumentZ apps have no Django app of their own, so
# their trees are mounted here. The frontend's <InstrumentZ appKey="…"> builds
# basePath as /api/<appKey>, so every key below must match an appKey it renders
# or that app's SkillZ panel 404s.
try:
    from apps.skillz.training import training_urlpatterns
except Exception:  # pragma: no cover - never let this take the deploy down
    def training_urlpatterns(app_key):
        return []

INSTRUMENT_APP_KEYS = ["singz", "rapz"]


def health(_request):
    return JsonResponse(
        {
            "service": "music-connectz-backend",
            "status": "ok",
            "endpoints": [
                "/api/auth/register/",
                "/api/auth/login/",
                "/api/auth/oauth/{google|github|apple}/",
                "/api/mimez/skillz/...",
                "/api/directz/skillz/...",
                "/admin/",
            ],
        }
    )


urlpatterns = [
    path("", health, name="health"),
    path("admin/", admin.site.urls),
    path("api/auth/stats/", StatsView.as_view(), name="auth-stats"),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/economy/", include("apps.economy.urls")),
    path("api/mimez/", include("apps.mimez.urls")),
    path("api/directz/", include("apps.directz.urls")),
    path("api/lessonz/", include("apps.lessonz.urls")),
    path("api/omviardz/", include("apps.omviardz.urls")),
    path("api/bodiez/", include("apps.bodiez.urls")),
    path("api/battlez/", include("apps.battlez.urls")),
    path("api/collabz/", include("apps.collabz.urls")),
    path("api/tabz/", include("apps.tabz.urls")),
    # Android app <-> site link verification. Must sit at the domain root, not
    # under /api/ — Google fetches this exact path over https.
    path(".well-known/assetlinks.json", AssetLinksView.as_view(), name="assetlinks"),
] + [
    path(f"api/{key}/", include((training_urlpatterns(key), key)))
    for key in INSTRUMENT_APP_KEYS
]

# Serve user uploads. When S3/R2 is configured (S3_BUCKET_NAME), django-storages
# serves media from the bucket and these URLs are absolute — this route isn't hit.
# Without a bucket, files live on the local disk and must be served by the app in
# BOTH dev and prod (else every uploaded preview 404s). NOTE: Render's disk is
# ephemeral, so set S3_BUCKET_NAME + keys for media that survives redeploys.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
elif not os.environ.get("S3_BUCKET_NAME"):
    urlpatterns += [
        re_path(r"^media/(?P<path>.*)$", static_serve, {"document_root": settings.MEDIA_ROOT}),
    ]
