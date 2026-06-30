"""Reusable training routes. Each creator app mounts these under its own prefix:

    # apps/mixez/urls.py
    from apps.skillz.urls import training_urlpatterns
    app_name = "mixez"
    urlpatterns = training_urlpatterns("mixez")
"""
from django.urls import path

from . import views


def training_urlpatterns(app_key):
    p = app_key  # url prefix == app key, e.g. /api/mixez/...
    from . import submit as submit_views
    return [
        path(f"{p}/train/tracks/",       views.TracksView.as_view(app_key=app_key),      name="tracks"),
        path(f"{p}/train/drills/",       views.DrillsView.as_view(app_key=app_key),      name="drills"),
        path(f"{p}/train/daily/",        views.DailyView.as_view(app_key=app_key),       name="daily"),
        path(f"{p}/train/progress/",     views.ProgressView.as_view(app_key=app_key),    name="progress"),
        path(f"{p}/train/leaderboard/",  views.LeaderboardView.as_view(app_key=app_key), name="leaderboard"),
        path(f"{p}/train/attempt/",      views.AttemptView.as_view(app_key=app_key),     name="attempt"),
        path(f"{p}/train/badges/",       views.BadgesView.as_view(app_key=app_key),      name="badges"),
        path(f"{p}/train/submit/",       submit_views.SubmitChallengeView.as_view(app_key=app_key),  name="submit"),
        path(f"{p}/train/submissionz/",  submit_views.SubmissionListView.as_view(app_key=app_key),   name="submissionz"),
    ]


app_name = "skillz"

# Mounted via:  path("api/", include("apps.skillz.urls"))  in main urls.py
urlpatterns = [
    path("skillz/progress/<int:user_id>/", views.PublicProgressView.as_view(), name="public-progress"),
    path("skillz/capabilities/", views.CapabilitiesView.as_view(), name="capabilities"),
]
