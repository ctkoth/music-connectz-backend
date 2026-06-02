"""ScoutZ routes — /api/scoutz/...  Premium + adult only."""
from django.urls import path
from . import views

app_name = "scoutz"
urlpatterns = [
    path("scoutz/dashboard/", views.DashboardView.as_view(), name="dashboard"),
    path("scoutz/prospectz/", views.ProspectListCreateView.as_view(), name="prospectz-list"),
    path("scoutz/prospectz/<uuid:pk>/", views.ProspectDetailView.as_view(), name="prospectz-detail"),
    path("scoutz/reportz/", views.ReportListCreateView.as_view(), name="reportz-list"),
    path("scoutz/taskz/", views.TaskListCreateView.as_view(), name="taskz-list"),
]
