"""Age-verification routes. Mounted at /api/ -> /api/me/age/..."""
from django.urls import path
from . import views

app_name = "common"
urlpatterns = [
    path("me/age/", views.AgeStateView.as_view(), name="age-state"),
    path("me/age/declare/", views.AgeDeclareView.as_view(), name="age-declare"),
    path("me/age/parental-consent/", views.ParentalConsentView.as_view(), name="age-consent"),
    path("me/age/verify-adult/", views.VerifyAdultView.as_view(), name="age-verify-adult"),
    path("me/age/stripe-identity/start/", views.StripeIdentityStartView.as_view(), name="stripe-identity-start"),
    path("webhooks/stripe-identity/", views.StripeIdentityWebhookView.as_view(), name="stripe-identity-webhook"),
    path("creator-manifest/", views.CreatorManifestView.as_view(), name="creator-manifest"),
]
