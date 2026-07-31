from django.urls import path

from .views import TabDetailView, TabzAuditView, TabzView

urlpatterns = [
    path("", TabzView.as_view(), name="tabz"),
    path("audit/", TabzAuditView.as_view(), name="tabz-audit"),
    path("<str:key>/", TabDetailView.as_view(), name="tabz-detail"),
]
