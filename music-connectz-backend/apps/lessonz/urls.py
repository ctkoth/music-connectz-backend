from django.urls import path

from .posts import PostListCreateView, PostUnlockView
from .views import BookingActionView, BookingListCreateView, EligibilityView, OfferListCreateView

# SkillZ wiring for consistency with other creator apps (defensive).
try:
    from apps.common.training import training_urlpatterns  # noqa
except Exception:  # pragma: no cover
    try:
        from apps.skillz.training import training_urlpatterns  # noqa
    except Exception:  # pragma: no cover
        def training_urlpatterns(app_key):
            return []

urlpatterns = [
    path("eligibility/", EligibilityView.as_view(), name="lessonz-eligibility"),
    path("offers/", OfferListCreateView.as_view(), name="lessonz-offers"),
    path("bookings/", BookingListCreateView.as_view(), name="lessonz-bookings"),
    path("bookings/<int:pk>/<str:action>/", BookingActionView.as_view(), name="lessonz-booking-action"),
    path("posts/", PostListCreateView.as_view(), name="lessonz-posts"),
    path("posts/<int:pk>/unlock/", PostUnlockView.as_view(), name="lessonz-post-unlock"),
] + training_urlpatterns("lessonz")
