from django.urls import path

from .views import DirectZOverviewView, DirectZSubmitView

# Defensive SkillZ wiring (Render-safe).
try:
    from apps.common.training import training_urlpatterns  # noqa
except Exception:  # pragma: no cover
    try:
        from apps.skillz.training import training_urlpatterns  # noqa
    except Exception:  # pragma: no cover
        def training_urlpatterns(app_key):
            return []

urlpatterns = [
    path("overview/", DirectZOverviewView.as_view(), name="directz-overview"),
    path("submit/", DirectZSubmitView.as_view(), name="directz-submit"),
] + training_urlpatterns("directz")
