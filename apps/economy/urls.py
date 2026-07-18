from django.urls import path

from .payments import (
    CheckoutConfigView,
    PaypalCaptureView,
    PaypalCreateView,
    StripeCheckoutView,
    StripeWebhookView,
)
from .social import (
    AttractivenessRateView,
    AttractivenessView,
    VenueJoinView,
    VenuesView,
)
from .views import (
    AddFundsView,
    LimitsView,
    MembershipView,
    RoyaltiesView,
    RoyaltyAccrueView,
    RoyaltyCashoutView,
    SpecZView,
    UploadDetailView,
    UploadsView,
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
    path("uploads/", UploadsView.as_view(), name="economy-uploads"),
    path("uploads/<int:pk>/", UploadDetailView.as_view(), name="economy-upload-detail"),
    path("checkout/config/", CheckoutConfigView.as_view(), name="economy-checkout-config"),
    path("checkout/stripe/", StripeCheckoutView.as_view(), name="economy-checkout-stripe"),
    path("checkout/paypal/", PaypalCreateView.as_view(), name="economy-checkout-paypal"),
    path("checkout/paypal/capture/", PaypalCaptureView.as_view(), name="economy-checkout-paypal-capture"),
    path("webhooks/stripe/", StripeWebhookView.as_view(), name="economy-webhook-stripe"),
    path("venues/", VenuesView.as_view(), name="economy-venues"),
    path("venues/<int:pk>/join/", VenueJoinView.as_view(), name="economy-venue-join"),
    path("attractiveness/", AttractivenessView.as_view(), name="economy-attractiveness"),
    path("attractiveness/rate/", AttractivenessRateView.as_view(), name="economy-attractiveness-rate"),
]
