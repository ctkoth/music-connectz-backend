"""Core routes — mounted at /api/."""
from django.urls import path
from . import views

app_name = "core"

urlpatterns = [
    path("membership/", views.MembershipView.as_view(), name="membership"),
    path("notifications/", views.NotificationsView.as_view(), name="notifications"),
    path("notifications/mark-all-read/", views.NotificationsMarkAllReadView.as_view(), name="notifications-read"),
    path("referrals/my-code/", views.MyReferralCodeView.as_view(), name="my-referral-code"),
]
