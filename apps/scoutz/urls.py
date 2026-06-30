"""ScoutZ routes — /api/scoutz/...

Two layers:
  • Private CRM (Premium + adult): prospectz, reportz, taskz, dashboard.
  • LIVE A&R marketplace (adult-gated both sides): talent listings + scout openings
    + interest. Browsing only ever returns adult-verified, open records.
Plus SkillZ training (A&R skill-building) — gamified like SingZ/RapZ.
"""
from django.urls import path

from apps.skillz.urls import training_urlpatterns

from . import views

app_name = "scoutz"

urlpatterns = [
    # Private scouting CRM
    path("scoutz/dashboard/", views.DashboardView.as_view(), name="dashboard"),
    path("scoutz/prospectz/", views.ProspectListCreateView.as_view(), name="prospectz-list"),
    path("scoutz/prospectz/<uuid:pk>/", views.ProspectDetailView.as_view(), name="prospectz-detail"),
    path("scoutz/reportz/", views.ReportListCreateView.as_view(), name="reportz-list"),
    path("scoutz/taskz/", views.TaskListCreateView.as_view(), name="taskz-list"),

    # LIVE A&R marketplace — artist side
    path("scoutz/my-listing/", views.MyTalentListingView.as_view(), name="my-listing"),
    path("scoutz/my-listing/<uuid:pk>/", views.MyTalentListingDetailView.as_view(), name="my-listing-detail"),
    path("scoutz/openingz/", views.BrowseOpeningsView.as_view(), name="browse-openingz"),

    # LIVE A&R marketplace — scout side
    path("scoutz/talent/", views.BrowseTalentView.as_view(), name="browse-talent"),
    path("scoutz/my-openingz/", views.MyScoutOpeningView.as_view(), name="my-openingz"),
    path("scoutz/my-openingz/<uuid:pk>/", views.MyScoutOpeningDetailView.as_view(), name="my-openingz-detail"),
    path("scoutz/interestz/", views.MyInterestView.as_view(), name="interestz"),
] + training_urlpatterns("scoutz")
