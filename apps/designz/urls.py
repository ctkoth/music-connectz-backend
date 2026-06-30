"""DesignZ routes. Mounted at /api/ -> everything under /api/designz/.

Built (real CRUD): projectz, assetz, templatez, brand-kitz, palettez,
commentz, versionz, dashboard. Remaining sub-tabs respond via TabView until built.
"""
from django.urls import path

from apps.skillz.urls import training_urlpatterns

from . import views

app_name = "designz"

urlpatterns = [
    path("designz/dashboard/", views.DashboardView.as_view(), name="dashboard"),

    path("designz/projectz/", views.ProjectListCreateView.as_view(), name="projectz-list"),
    path("designz/projectz/<uuid:pk>/", views.ProjectDetailView.as_view(), name="projectz-detail"),

    path("designz/assetz/", views.AssetListCreateView.as_view(), name="assetz-list"),
    path("designz/assetz/<uuid:pk>/", views.AssetDetailView.as_view(), name="assetz-detail"),

    path("designz/templatez/", views.TemplateListCreateView.as_view(), name="templatez-list"),
    path("designz/brand-kitz/", views.BrandKitListCreateView.as_view(), name="brandkitz-list"),
    path("designz/palettez/", views.PaletteListCreateView.as_view(), name="palettez-list"),

    path("designz/commentz/", views.CommentListCreateView.as_view(), name="commentz-list"),
    path("designz/versionz/", views.VersionListCreateView.as_view(), name="versionz-list"),

    # Not yet built — respond 200 so the UI never dead-ends:
    path("designz/fontz/", views.TabView.as_view(tab="fontz"), name="fontz"),
    path("designz/layerz/", views.TabView.as_view(tab="layerz"), name="layerz"),
    path("designz/exportz/", views.TabView.as_view(tab="exportz"), name="exportz"),
    path("designz/mockupz/", views.TabView.as_view(tab="mockupz"), name="mockupz"),
    path("designz/moodboardz/", views.TabView.as_view(tab="moodboardz"), name="moodboardz"),
    path("designz/collaboratorz/", views.TabView.as_view(tab="collaboratorz"), name="collaboratorz"),
    path("designz/inspiration/", views.TabView.as_view(tab="inspiration"), name="inspiration"),
    path("designz/marketplace/", views.TabView.as_view(tab="marketplace"), name="marketplace"),
    path("designz/analytics/", views.TabView.as_view(tab="analytics"), name="analytics"),
    path("designz/settingz/", views.TabView.as_view(tab="settingz"), name="settingz"),
    path("designz/challenge/submit/", views.SubmitChallengeView.as_view(), name="challenge-submit"),
    path("designz/challenge/submissionz/", views.SubmissionListView.as_view(), name="challenge-submissionz"),
] + training_urlpatterns("designz")
