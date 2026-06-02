"""DawZ routes — mounted at /api/ -> /api/dawz/..."""
from django.urls import path

from . import views

app_name = "dawz"

urlpatterns = [
    path("dawz/proposals/", views.ProposalsView.as_view(), name="proposals"),
    path("dawz/vote/", views.VoteView.as_view(), name="vote"),
]
