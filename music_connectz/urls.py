from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

from apps.economy.views import StatsView


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
]
