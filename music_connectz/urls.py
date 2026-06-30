"""Music ConnectZ — main URL configuration (deployable, self-contained).

Only wires apps that actually exist in this repo, so the project BOOTS cleanly
(the previous merged urls.py imported ~17 apps that weren't present — that is an
ImportError at startup, i.e. the deploy breakage). Add more includes here as you
bring additional apps into this repo.
"""
from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse


def health(_request):
    return JsonResponse({"service": "music-connectz-backend", "status": "ok"})


urlpatterns = [
    path("", health),                      # so / returns 200 (not a scary 404)
    path("healthz/", health),
    path("admin/", admin.site.urls),

    # Auth — JWT register/login/refresh/me + OAuth (Google/GitHub)
    path("api/", include("apps.accounts.urls")),

    # Core surfaces the frontend hits right after login (tolerant/minimal)
    path("api/", include("apps.core.urls")),

    # Age verification + creator manifest + gate utilities
    path("api/", include("apps.common.urls")),

    # Creator apps (DesignZ kept for visual designers; DrawZ intentionally absent)
    path("api/", include("apps.designz.urls")),
    path("api/", include("apps.shotz.urls")),
    path("api/", include("apps.writez.urls")),
    path("api/", include("apps.managez.urls")),    # adult: back office + live manager marketplace
    path("api/", include("apps.developz.urls")),
    path("api/", include("apps.scoutz.urls")),     # adult+premium: A&R CRM + live A&R marketplace
    path("api/", include("apps.producez.urls")),   # training only
    path("api/", include("apps.mixez.urls")),      # training only

    # Shared engines
    path("api/", include("apps.dawz.urls")),       # DawZ proposals + voting
    path("api/", include("apps.gamez.urls")),      # GameZ: build games in OCC
    path("api/", include("apps.skillz.urls")),     # SkillZ progress + capabilities
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
