from django.urls import path

from .views import AnswerView, ResetView, SkipView, StepView, TourView

urlpatterns = [
    path("tour/", TourView.as_view(), name="omviardz-tour"),
    path("answer/", AnswerView.as_view(), name="omviardz-answer"),
    path("skip/", SkipView.as_view(), name="omviardz-skip"),
    path("reset/", ResetView.as_view(), name="omviardz-reset"),
    # Last: a step key is a free-form slug and would otherwise swallow the
    # fixed routes above.
    path("step/<str:key>/", StepView.as_view(), name="omviardz-step"),
]
