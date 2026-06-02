"""ShotZ routes — workspace CRUD + SkillZ training. /api/shotz/..."""
from django.urls import path
from apps.skillz.urls import training_urlpatterns
from . import views

app_name = "shotz"
urlpatterns = [
    path("shotz/projectz/", views.ProjectListCreateView.as_view(), name="projectz-list"),
    path("shotz/projectz/<uuid:pk>/", views.ProjectDetailView.as_view(), name="projectz-detail"),
    path("shotz/clipz/", views.ClipListCreateView.as_view(), name="clipz-list"),
    path("shotz/footage/", views.FootageListCreateView.as_view(), name="footage-list"),
    path("shotz/storyboardz/", views.StoryboardListCreateView.as_view(), name="storyboardz-list"),
    path("shotz/shotlistz/", views.ShotListView.as_view(), name="shotlistz-list"),
    path("shotz/locationz/", views.LocationListCreateView.as_view(), name="locationz-list"),
    path("shotz/renderz/", views.RenderListCreateView.as_view(), name="renderz-list"),
] + training_urlpatterns("shotz")
