from django.urls import path

from .directz_app import DirectZWorksView, DirectZRateView
from .postz import (PostCostView, PostDeleteView, PostOpenView, PostsView,
                    PostJoinView, PostShareView, SubmissionsView)
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
from .battlez import (BattlesView, BattleChallengeView, BattleDetailView,
                      BattleEnterView, BattleRespondView, BattleSettleView,
                      BattleWagerView, MoneyBattleVoteView)
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
from .social_verify import SocialReviewQueueView, SocialVerifyView
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
from .occ_taskz import (OccSettingsView, OccSpecView, OccTaskDetailView,
                        OccTaskUndoView, OccTasksView)
from .occ_run import OccRunView
from .occ_agent_view import OccAgentView
from .gamez import GameAssetView, GameDetailView, GamezView
from .gamez_build import GameBuildView, GamePlayView
from .occ_suggest import OccSuggestView
from .releasez import (CollabDistributeView, PostDistributeView, ReleaseDetailView,
                       ReleaseSubmitView, ReleasesView)
from .collab_files import CollabFileDetailView, CollabFilesView
from .collab_post import CollabNeedsView, CollabPostView
from .ai_models import AiModelView
from .badgez import BadgeGiftView, BadgezView
from .bugz import BugTriageView, BugzView
from .logicz import LogicZView
from .ratez import RatezView, RatingKindsView
from .occ_workz import (OccWorkDetailView, OccWorkShareView, OccWorkUnshareView,
                        OccWorkzView, PostOccWorkView)
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
    OwnerRevenueView,
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
    path("battlez/challenge/", BattleChallengeView.as_view(), name="economy-battle-challenge"),
    path("battlez/moneyvote/", MoneyBattleVoteView.as_view(), name="economy-battle-moneyvote"),
    path("battlez/<int:pk>/", BattleDetailView.as_view(), name="economy-battle"),
    path("battlez/<int:pk>/respond/", BattleRespondView.as_view(), name="economy-battle-respond"),
    path("battlez/<int:pk>/wager/", BattleWagerView.as_view(), name="economy-battle-wager"),
    path("battlez/<int:pk>/settle/", BattleSettleView.as_view(), name="economy-battle-settle"),
    path("battlez/<int:pk>/enter/", BattleEnterView.as_view(), name="economy-battle-enter"),
    # KeyConnectZ — the keyboard. Wallpaper is Premium; translate is free.
    path("keyz/", KeyboardView.as_view(), name="economy-keyz"),
    path("keyz/translate/", KeyTranslateView.as_view(), name="economy-keyz-translate"),
    path("wallet/add/", AddFundsView.as_view(), name="economy-wallet-add"),
    path("owner/revenue/", OwnerRevenueView.as_view(), name="economy-owner-revenue"),
    path("membership/", MembershipView.as_view(), name="economy-membership"),
    path("membership/refund/", MembershipRefundView.as_view(), name="economy-membership-refund"),
    path("owner/claim/", OwnerClaimView.as_view(), name="economy-owner-claim"),
    path("limits/", LimitsView.as_view(), name="economy-limits"),
    path("ai/charge/", AIChargeView.as_view(), name="economy-ai-charge"),
    path("promptz/buy/", PromptzBuyView.as_view(), name="economy-promptz-buy"),
    path("ai/occ/", OccChatView.as_view(), name="economy-ai-occ"),
    # OCC — Ocular Code ConnectZ.
    path("occ/spec/", OccSpecView.as_view(), name="economy-occ-spec"),
    path("occ/settings/", OccSettingsView.as_view(), name="economy-occ-settings"),
    path("occ/taskz/", OccTasksView.as_view(), name="economy-occ-taskz"),
    path("occ/taskz/<int:pk>/", OccTaskDetailView.as_view(), name="economy-occ-task"),
    path("occ/taskz/<int:pk>/undo/", OccTaskUndoView.as_view(), name="economy-occ-task-undo"),
    # WorkZ — what went into OCC, what came out, and where it goes next.
    # The sandbox. Off, and saying why, until the Modal tokens are set.
    path("occ/run/", OccRunView.as_view(), name="economy-occ-run"),
    # The agent loop — OCC reading and changing a project, not describing it.
    # GET states the ceiling before POST spends anything.
    path("occ/agent/", OccAgentView.as_view(), name="economy-occ-agent"),
    # GameZ — the tab occ_spec has advertised, and EXPORT_ROUTES has pointed
    # at, since before anything served either.
    path("gamez/", GamezView.as_view(), name="economy-gamez"),
    path("gamez/<int:pk>/", GameDetailView.as_view(), name="economy-game"),
    path("gamez/<int:pk>/assets/", GameAssetView.as_view(), name="economy-game-assets"),
    path("gamez/<int:pk>/build/", GameBuildView.as_view(), name="economy-game-build"),
    # The bundle. Every response carries a CSP sandbox — see gamez_build.py.
    path("gamez/<int:pk>/play/", GamePlayView.as_view(), name="economy-game-play"),
    path("gamez/<int:pk>/play/<path:path>", GamePlayView.as_view(),
         name="economy-game-play-file"),
    # SuggestionZ proposes and waits; AutomationZ drops the tap on what's safe.
    path("occ/suggest/", OccSuggestView.as_view(), name="economy-occ-suggest"),
    path("occ/workz/", OccWorkzView.as_view(), name="economy-occ-workz"),
    path("occ/workz/<int:pk>/", OccWorkDetailView.as_view(), name="economy-occ-work"),
    path("occ/workz/<int:pk>/share/", OccWorkShareView.as_view(), name="economy-occ-work-share"),
    path("occ/workz/<int:pk>/unshare/", OccWorkUnshareView.as_view(), name="economy-occ-work-unshare"),
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
    # What the AI couldn't confirm goes to a person, not to a wall.
    path("social/reviews/", SocialReviewQueueView.as_view(), name="economy-social-reviews"),
    path("members/", MembersView.as_view(), name="economy-members"),
    path("members/<str:username>/", MemberProfileView.as_view(), name="economy-member"),
    # RateZ — every rating, classified for what it actually measures.
    # BadgeZ — a title you wear and an effect you feel.
    # LogicZ — every tab has an address, an icon, and something it says.
    path("logicz/", LogicZView.as_view(), name="economy-logicz"),
    path("ai/models/", AiModelView.as_view(), name="economy-ai-models"),
    path("badgez/", BadgezView.as_view(), name="economy-badgez"),
    path("bugz/", BugzView.as_view(), name="economy-bugz"),
    path("bugz/<int:pk>/", BugTriageView.as_view(), name="economy-bugz-triage"),
    path("badgez/gift/", BadgeGiftView.as_view(), name="economy-badgez-gift"),
    path("ratez/", RatezView.as_view(), name="economy-ratez"),
    path("ratez/kinds/", RatingKindsView.as_view(), name="economy-ratez-kinds"),
    path("postz/", PostsView.as_view(), name="economy-postz"),
    # The price before the button, never after it.
    path("postz/cost/", PostCostView.as_view(), name="economy-postz-cost"),
    # No account needed — a public post by link, and the author behind it.
    path("postz/<int:pk>/", PublicPostView.as_view(), name="economy-postz-public"),
    path("public/members/<str:username>/", PublicProfileView.as_view(), name="economy-public-member"),
    # Nothing is a dead end: every app this post can open in, and the price of
    # each before it is spent.
    path("postz/<int:pk>/open/", PostOpenView.as_view(), name="economy-postz-open"),
    path("postz/<int:pk>/join/", PostJoinView.as_view(), name="economy-postz-join"),
    path("postz/<int:pk>/playlists/", PostPlaylistAppearancesView.as_view(), name="economy-postz-playlists"),
    path("postz/<int:pk>/collabs/", PostCollabsView.as_view(), name="economy-postz-collabs"),
    # The return leg: a post made in OCC opens back in OCC with its prompt.
    path("postz/<int:pk>/occ/", PostOccWorkView.as_view(), name="economy-postz-occ"),
    # A post populates a release: the song, the video, the cover and the lyrics
    # are already the four assets a distributor asks for.
    path("postz/<int:pk>/distribute/", PostDistributeView.as_view(), name="economy-postz-distribute"),
    path("postz/<int:pk>/share/", PostShareView.as_view(), name="economy-postz-share"),
    path("postz/<int:pk>/delete/", PostDeleteView.as_view(), name="economy-postz-delete"),
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
    # A collab is where the finished master usually lands, so it releases too.
    path("collab/<int:pk>/distribute/", CollabDistributeView.as_view(), name="economy-collab-distribute"),
    # The work going back and forth: v1 down, v2 up.
    # A finished collab becomes ONE post, owned by everyone who made it.
    path("collab/<int:pk>/post/", CollabPostView.as_view(), name="economy-collab-post"),
    # What the deal is looking for, so the right person can find it.
    path("collab/<int:pk>/needs/", CollabNeedsView.as_view(), name="economy-collab-needs"),
    path("collab/<int:pk>/files/", CollabFilesView.as_view(), name="economy-collab-files"),
    path("collab/<int:pk>/files/<int:file_id>/", CollabFileDetailView.as_view(), name="economy-collab-file"),
    path("distributez/releases/", ReleasesView.as_view(), name="economy-releases"),
    path("distributez/releases/<int:pk>/", ReleaseDetailView.as_view(), name="economy-release"),
    path("distributez/releases/<int:pk>/submit/", ReleaseSubmitView.as_view(), name="economy-release-submit"),
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
