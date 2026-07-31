from django.urls import path

from .views import (CatalogView, MembersView, ProjectDetailView, ProjectsView)

urlpatterns = [
    path("catalog/", CatalogView.as_view(), name="collabz-catalog"),
    path("projects/", ProjectsView.as_view(), name="collabz-projects"),
    path("projects/<int:pk>/", ProjectDetailView.as_view(), name="collabz-project"),
    path("projects/<int:pk>/members/", MembersView.as_view(), name="collabz-members"),
]
