from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .passwords import ForgotPasswordView, ResetPasswordView
from .views import (LoginView, MeView, OAuthConfigView, OAuthLinkView,
                    OAuthLoginView, OnboardCompleteView, ReferralsView,
                    RegisterView)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="auth-register"),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("password/forgot/", ForgotPasswordView.as_view(), name="auth-password-forgot"),
    path("password/reset/", ResetPasswordView.as_view(), name="auth-password-reset"),
    path("me/", MeView.as_view(), name="auth-me"),
    path("refresh/", TokenRefreshView.as_view(), name="auth-refresh"),
    path("oauth-config/", OAuthConfigView.as_view(), name="auth-oauth-config"),
    # Link/unlink must come first — "<provider>/link/" would otherwise be
    # swallowed by the login route's <str:provider> segment.
    path("oauth/<str:provider>/link/", OAuthLinkView.as_view(), name="auth-oauth-link"),
    path("oauth/<str:provider>/", OAuthLoginView.as_view(), name="auth-oauth"),
    path("referrals/", ReferralsView.as_view(), name="auth-referrals"),
    path("onboard/complete/", OnboardCompleteView.as_view(), name="auth-onboard-complete"),
]
