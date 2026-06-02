"""WriteZ routes — workspace CRUD + SkillZ training (bars/hooks/rhyme/flow).

Mounted at /api/ -> /api/writez/...  Plural segments are Z-ified.
"""
from django.urls import path

from apps.skillz.urls import training_urlpatterns

from . import views

app_name = "writez"

urlpatterns = [
    path("writez/projectz/", views.ProjectListCreateView.as_view(), name="projectz-list"),
    path("writez/projectz/<uuid:pk>/", views.ProjectDetailView.as_view(), name="projectz-detail"),
    path("writez/hookz/", views.HookListCreateView.as_view(), name="hookz-list"),
    path("writez/barz/", views.BarListCreateView.as_view(), name="barz-list"),
    path("writez/rhymez/", views.RhymeListCreateView.as_view(), name="rhymez-list"),
    path("writez/referencez/", views.ReferenceListCreateView.as_view(), name="referencez-list"),
    path("writez/briefz/", views.BriefListCreateView.as_view(), name="briefz-list"),
    path("writez/versionz/", views.VersionListCreateView.as_view(), name="versionz-list"),
] + training_urlpatterns("writez")  # adds /api/writez/train/{tracks,drills,daily,progress,leaderboard,attempt}/
