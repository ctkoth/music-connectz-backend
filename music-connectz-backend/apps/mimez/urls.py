from django.urls import path

from .views import MimeZOverviewView, MimeZSubmitView

# Defensive: prefer the canonical shared SkillZ engine; fall back to the bundled
# skillz app; never let Render ImportError take the deploy down.
try:
    from apps.common.training import training_urlpatterns  # noqa
except Exception:  # pragma: no cover
    try:
        from apps.skillz.training import training_urlpatterns  # noqa
    except Exception:  # pragma: no cover
        def training_urlpatterns(app_key):
            return []

urlpatterns = [
    path("overview/", MimeZOverviewView.as_view(), name="mimez-overview"),
    path("submit/", MimeZSubmitView.as_view(), name="mimez-submit"),
] + training_urlpatterns("mimez")
