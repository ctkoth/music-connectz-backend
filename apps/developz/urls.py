"""DevelopZ routes — /api/developz/...  Youth-safe. Z-ified plural segments."""
from django.urls import path

from . import views

app_name = "developz"

urlpatterns = [
    path("developz/repoz/", views.RepoListCreateView.as_view(), name="repoz-list"),
    path("developz/repoz/<uuid:pk>/", views.RepoDetailView.as_view(), name="repoz-detail"),
    path("developz/buildz/", views.BuildListCreateView.as_view(), name="buildz-list"),
    path("developz/deploymentz/", views.DeploymentListCreateView.as_view(), name="deploymentz-list"),
    path("developz/environmentz/", views.EnvironmentListCreateView.as_view(), name="environmentz-list"),
    path("developz/api-keyz/", views.ApiKeyListCreateView.as_view(), name="api-keyz-list"),
    path("developz/webhookz/", views.WebhookListCreateView.as_view(), name="webhookz-list"),
    path("developz/snippetz/", views.SnippetListCreateView.as_view(), name="snippetz-list"),
    path("developz/taskz/", views.TaskListCreateView.as_view(), name="taskz-list"),
]
