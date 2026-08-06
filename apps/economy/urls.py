from django.urls import path

from .directz_app import DirectZWorksView, DirectZRateView
from .postz import PostsView, PostJoinView, PostShareView, SubmissionsView
from .publicz import PublicPostView, PublicProfileView
from .links import LinkClickView, LinkTalliesView
from .distributez import TranscodeView, LyricsView
from .adz import AdzView, AdDetailView, AdRewardView
from .rewards import (AdmobConfigView, AdmobSsvView, OfferzView,
                      OfferzCallbackView)
from .translate import TranslateView
from .gemini import GeminiImageView, GeminiVideoView, GeminiVideoStatusView
from .notifications import NotificationsView
from .earn import EarnView
from .battlez import BattlesView, BattleDetailView, BattleEnterView
from .keyconnectz import KeyboardView, KeyTranslateView
from .playlistz import (PlaylistCollaboratorsView, PlaylistDetailView,
                        PlaylistItemDetailView, PlaylistItemsView,
                        PlaylistReorderView, PlaylistsView,
                        MyAppearancesView, PostPlaylistAppearancesView)
from .moderation import ReportView, BlockView
from .account import AccountExportView, AccountDeleteView
from .messages_view import MessagesView
from .logz import FeaturesView, LogZView
from .observationz import ObservationConsentView, ObservationZView
from .social_verify import SocialVerifyView
from .parcel import ParcelCampaignView
from .autotopup import AutoTopUpView, AutoTopUpCancelView
from .identity import IdentityView
from .collab import (
    PostCollabsView,
    CollabDealsView,
    CollabDetailView,
    CollabFundView,
    CollabDeliverView,
    CollabReleaseView,
    CollabDisputeView,
    CollabRefundView,
)
from .merch import MerchBuyView, MerchDetailView, MerchView
from .occ import OccChatView
from .payments import (
    CheckoutConfigView,
    MembershipRefundView,
    FoundingCheckoutView,
    PremiumCheckoutView,
    StatZCheckoutView,
    FoundingClaimView,
    FoundingView,
    PaypalCaptureView,
    PaypalCreateView,
    PaypalWebhookView,
    StripeCheckoutView,
    StripeWebhookView,
)
from .social import (
    MemberProfileView,
    MembersView,
    ProfileView,
    ProfileAvatarView,
    ProfileLocationView,
    ProfileRateView,
    FollowView,
    SocialView,
    AttractivenessRateView,
    AttractivenessView,
    FaceDetailView,
    FaceRateView,
    FaceZView,
    VenueJoinView,
    VenuesView,
)
from .views import (
    AddFundsView,
    AIChargeView,
    LimitsView,
    MembershipView,
    OwnerClaimView,
    PromptzBuyView,
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
    path("earn/", EarnView.as_view(), name="economy-earn"),
    # BattleZ — a challenge, gated by the same five ranges as everything else.
    path("battlez/", BattlesView.as_view(), name="economy-battlez"),
    path("battlez/<int:pk>/", BattleDetailView.as_view(), name="economy-battle"),
    path("battlez/<int:pk>/enter/", BattleEnterView.as_view(), name="economy-battle-enter"),
    # KeyConnectZ — the keyboard. Wallpaper is Premium; translate is free.
    path("keyz/", KeyboardView.as_view(), name="economy-keyz"),
    path("keyz/translate/", KeyTranslateView.as_view(), name="economy-keyz-translate"),
    path("wallet/add/", AddFundsView.as_view(), name="economy-wallet-add"),
    path("membership/", MembershipView.as_view(), name="economy-membership"),
    path("membership/refund/", MembershipRefundView.as_view(), name="economy-membership-refund"),
    path("owner/claim/", OwnerClaimView.as_view(), name="economy-owner-claim"),
    path("limits/", LimitsView.as_view(), name="economy-limits"),
    path("ai/charge/", AIChargeView.as_view(), name="economy-ai-charge"),
    path("promptz/buy/", PromptzBuyView.as_view(), name="economy-promptz-buy"),
    path("ai/occ/", OccChatView.as_view(), name="economy-ai-occ"),
    path("translate/", TranslateView.as_view(), name="economy-translate"),
    path("gemini/image/", GeminiImageView.as_view(), name="economy-gemini-image"),
    path("gemini/video/", GeminiVideoView.as_view(), name="economy-gemini-video"),
    path("gemini/video/status/", GeminiVideoStatusView.as_view(), name="economy-gemini-video-status"),
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
    path("webhooks/paypal/", PaypalWebhookView.as_view(), name="economy-webhook-paypal"),
    path("founding/", FoundingView.as_view(), name="economy-founding"),
    path("founding/claim/", FoundingClaimView.as_view(), name="economy-founding-claim"),
    path("founding/checkout/", FoundingCheckoutView.as_view(), name="economy-founding-checkout"),
    path("premium/checkout/", PremiumCheckoutView.as_view(), name="economy-premium-checkout"),
    path("statz/checkout/", StatZCheckoutView.as_view(), name="economy-statz-checkout"),
    path("venues/", VenuesView.as_view(), name="economy-venues"),
    path("venues/<int:pk>/join/", VenueJoinView.as_view(), name="economy-venue-join"),
    path("attractiveness/", AttractivenessView.as_view(), name="economy-attractiveness"),
    path("attractiveness/rate/", AttractivenessRateView.as_view(), name="economy-attractiveness-rate"),
    path("facez/", FaceZView.as_view(), name="economy-facez"),
    path("facez/<int:pk>/", FaceDetailView.as_view(), name="economy-face-detail"),
    path("facez/<int:pk>/rate/", FaceRateView.as_view(), name="economy-face-rate"),
    path("profile/", ProfileView.as_view(), name="economy-profile"),
    path("profile/avatar/", ProfileAvatarView.as_view(), name="economy-profile-avatar"),
    path("profile/rate/", ProfileRateView.as_view(), name="economy-profile-rate"),
    path("profile/location/", ProfileLocationView.as_view(), name="economy-profile-location"),
    path("follow/", FollowView.as_view(), name="economy-follow"),
    path("notifications/", NotificationsView.as_view(), name="economy-notifications"),
    path("messages/", MessagesView.as_view(), name="economy-messages"),
    path("logz/", LogZView.as_view(), name="economy-logz"),
    path("features/", FeaturesView.as_view(), name="economy-features"),
    path("observationz/", ObservationZView.as_view(), name="economy-observationz"),
    path("observationz/consent/", ObservationConsentView.as_view(), name="economy-observationz-consent"),
    path("report/", ReportView.as_view(), name="economy-report"),
    path("block/", BlockView.as_view(), name="economy-block"),
    path("account/export/", AccountExportView.as_view(), name="economy-account-export"),
    path("account/delete/", AccountDeleteView.as_view(), name="economy-account-delete"),
    path("social/", SocialView.as_view(), name="economy-social"),
    path("social/react/", SocialView.as_view(), {"action": "react"}, name="economy-social-react"),
    path("social/comment/", SocialView.as_view(), {"action": "comment"}, name="economy-social-comment"),
    path("social/rate/", SocialView.as_view(), {"action": "rate"}, name="economy-social-rate"),
    path("social/verify/", SocialVerifyView.as_view(), name="economy-social-verify"),
    path("members/", MembersView.as_view(), name="economy-members"),
    path("members/<str:username>/", MemberProfileView.as_view(), name="economy-member"),
    path("postz/", PostsView.as_view(), name="economy-postz"),
    # No account needed — a public post by link, and the author behind it.
    path("postz/<int:pk>/", PublicPostView.as_view(), name="economy-postz-public"),
    path("public/members/<str:username>/", PublicProfileView.as_view(), name="economy-public-member"),
    path("postz/<int:pk>/join/", PostJoinView.as_view(), name="economy-postz-join"),
    path("postz/<int:pk>/playlists/", PostPlaylistAppearancesView.as_view(), name="economy-postz-playlists"),
    path("postz/<int:pk>/collabs/", PostCollabsView.as_view(), name="economy-postz-collabs"),
    path("postz/<int:pk>/share/", PostShareView.as_view(), name="economy-postz-share"),
    path("submissions/", SubmissionsView.as_view(), name="economy-submissions"),
    # PlaylistZ — Music ConnectZ posts and outside distro links in one order.
    path("playlistz/", PlaylistsView.as_view(), name="economy-playlistz"),
    path("playlistz/appearances/", MyAppearancesView.as_view(), name="economy-playlist-appearances"),
    path("playlistz/<int:pk>/", PlaylistDetailView.as_view(), name="economy-playlist"),
    path("playlistz/<int:pk>/items/", PlaylistItemsView.as_view(), name="economy-playlist-items"),
    path("playlistz/<int:pk>/items/<int:item_pk>/", PlaylistItemDetailView.as_view(), name="economy-playlist-item"),
    path("playlistz/<int:pk>/reorder/", PlaylistReorderView.as_view(), name="economy-playlist-reorder"),
    path("playlistz/<int:pk>/collaborators/", PlaylistCollaboratorsView.as_view(), name="economy-playlist-collaborators"),
    path("link/click/", LinkClickView.as_view(), name="economy-link-click"),
    path("link/tallies/", LinkTalliesView.as_view(), name="economy-link-tallies"),
    path("distributez/transcode/", TranscodeView.as_view(), name="economy-distributez-transcode"),
    path("distributez/lyrics/", LyricsView.as_view(), name="economy-distributez-lyrics"),
    path("adz/", AdzView.as_view(), name="economy-adz"),
    path("adz/<int:pk>/", AdDetailView.as_view(), name="economy-adz-detail"),
    path("adz/<int:pk>/reward/", AdRewardView.as_view(), name="economy-adz-reward"),
    path("adz/admob-config/", AdmobConfigView.as_view(), name="economy-admob-config"),
    path("adz/admob-ssv/", AdmobSsvView.as_view(), name="economy-admob-ssv"),
    path("offerz/", OfferzView.as_view(), name="economy-offerz"),
    path("offerz/callback/", OfferzCallbackView.as_view(), name="economy-offerz-callback"),
    path("directz/", DirectZWorksView.as_view(), name="economy-directz"),
    path("directz/<int:pk>/rate/", DirectZRateView.as_view(), name="economy-directz-rate"),
    path("merch/", MerchView.as_view(), name="economy-merch"),
    path("merch/<int:pk>/", MerchDetailView.as_view(), name="economy-merch-detail"),
    path("merch/<int:pk>/buy/", MerchBuyView.as_view(), name="economy-merch-buy"),
    path("collab/", CollabDealsView.as_view(), name="economy-collab"),
    path("collab/<int:pk>/", CollabDetailView.as_view(), name="economy-collab-detail"),
    path("collab/<int:pk>/fund/", CollabFundView.as_view(), name="economy-collab-fund"),
    path("collab/<int:pk>/deliver/", CollabDeliverView.as_view(), name="economy-collab-deliver"),
    path("collab/<int:pk>/release/", CollabReleaseView.as_view(), name="economy-collab-release"),
    path("collab/<int:pk>/dispute/", CollabDisputeView.as_view(), name="economy-collab-dispute"),
    path("collab/<int:pk>/refund/", CollabRefundView.as_view(), name="economy-collab-refund"),
    path("parcel/", ParcelCampaignView.as_view(), name="economy-parcel"),
    path("autotopup/", AutoTopUpView.as_view(), name="economy-autotopup"),
    path("autotopup/<int:pk>/cancel/", AutoTopUpCancelView.as_view(), name="economy-autotopup-cancel"),
    path("identity/", IdentityView.as_view(), name="economy-identity"),
]
