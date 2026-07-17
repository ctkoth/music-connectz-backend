from django.urls import path

from .views import AddFundsView, MembershipView, WalletView

urlpatterns = [
    path("wallet/", WalletView.as_view(), name="economy-wallet"),
    path("wallet/add/", AddFundsView.as_view(), name="economy-wallet-add"),
    path("membership/", MembershipView.as_view(), name="economy-membership"),
]
