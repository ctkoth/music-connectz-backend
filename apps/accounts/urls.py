"""Auth routes — mounted at /api/ -> /api/auth/..."""
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

app_name = "accounts"

urlpatterns = [
    path("auth/register/", views.RegisterView.as_view(), name="register"),
    path("auth/login/", views.LoginView.as_view(), name="login"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="refresh"),
    path("auth/me/", views.MeView.as_view(), name="me"),

    # OAuth
    path("auth/oauth/google/start/", views.OAuthStartView.as_view(provider="google"), name="google-start"),
    path("auth/oauth/google/callback/", views.OAuthCallbackView.as_view(provider="google"), name="google-callback"),
    path("auth/oauth/github/start/", views.OAuthStartView.as_view(provider="github"), name="github-start"),
    path("auth/oauth/github/callback/", views.OAuthCallbackView.as_view(provider="github"), name="github-callback"),
]
