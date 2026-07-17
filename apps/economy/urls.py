from django.urls import path

from .views import (
    AddFundsView,
    LimitsView,
    MembershipView,
    RoyaltiesView,
    RoyaltyAccrueView,
    RoyaltyCashoutView,
    SpecZView,
    WalletView,
)

urlpatterns = [
    path("wallet/", WalletView.as_view(), name="economy-wallet"),
    path("wallet/add/", AddFundsView.as_view(), name="economy-wallet-add"),
    path("membership/", MembershipView.as_view(), name="economy-membership"),
    path("limits/", LimitsView.as_view(), name="economy-limits"),
    path("specz/", SpecZView.as_view(), name="economy-specz"),
    path("specz/buy/", SpecZView.as_view(), name="economy-specz-buy"),
    path("royalties/", RoyaltiesView.as_view(), name="economy-royalties"),
    path("royalties/accrue/", RoyaltyAccrueView.as_view(), name="economy-royalties-accrue"),
    path("royalties/cashout/", RoyaltyCashoutView.as_view(), name="economy-royalties-cashout"),
]
