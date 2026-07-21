from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import LoginView, MeView, OAuthConfigView, OAuthLoginView, RegisterView

urlpatterns = [
    path("register/", RegisterView.as_view(), name="auth-register"),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("me/", MeView.as_view(), name="auth-me"),
    path("refresh/", TokenRefreshView.as_view(), name="auth-refresh"),
    path("oauth-config/", OAuthConfigView.as_view(), name="auth-oauth-config"),
    path("oauth/<str:provider>/", OAuthLoginView.as_view(), name="auth-oauth"),
]
