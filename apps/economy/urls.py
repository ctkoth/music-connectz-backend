from django.urls import path, re_path

from .directz_app import (DirectZCopyrightView, DirectZWorksView,
                          DirectZRateView)
from .media import MediaFileView
from .questz import QuestBoardView, QuestClaimView
from .journalz import (JournalCostView, JournalEntryView, JournalExportView,
                       JournalLookbackView, JournalShareView, JournalZView)
from .postz import (PostCostView, PostDeleteView, PostOpenView, PostsView,
                    PostJoinView, PostShareView, SubmissionsView, PostProgressionView, DiscoveryFeedView, PostSaleView)
from .publicz import PublicPostView, PublicProfileView
from .links import LinkClickView, LinkTalliesView
from .widgetz import WidgetOpenView, WidgetZView
from .rulez import RulezView
from .personalityz import PersonalityAxesView, PersonalityTestView
from .religionz import ReligionsView
from .languagez import LanguagesView
from .trialdoorz import TrialDoorsView
from .trial import TrialPublicStatsView, PublicTiersView
from .retake import RetakeRemindView, RetakeStopView
from .bodiez_trial import BodieZTrialView
from .offerz_engine import (FunnelCatalogView, FunnelOfferRedeemView,
                            FunnelOffersView)
from .lilith_taskz import (LilithBoardView, LilithRoutineDetailView,
                           LilithRoutineListView, LilithSponsorView,
                           LilithTaskCompleteView, LilithTaskDetailView,
                           LilithTaskListView)
from .karmaz import KarmaRewardsView
from .signbonus import SignBonusView
from .voice import VoiceZView
from .dupez import (DupeZClaimView, DupeZDeleteView, DupeZFlagsView, DupeZVerifyView,
                    DupeZReviewView, DupeZView)
from .callz import CallDetailView, CallRateView, CallsView
from .sharecard import post_card, profile_card
from .scoreshare import ScoreShareView, score_card_png
from .weeklybattle import WeeklyBattleView
from .soundz import SoundZView
from .coachvoice import CoachVoiceView, CoachSpeakView
from .dawz import DawZView
from .attractivenessz_view import AttractivenessZView
from .soundcloud_engagement import SoundCloudEngagementView
from .soundcloud_import import SoundCloudImportView
from .coachz import CoachStudioView, RateStudentTakeView, AddStudentView
from .distributez import TranscodeView, LyricsView
from .adz import AdzView, AdDetailView, AdRewardView
from .rewards import (AdmobConfigView, AdmobSsvView, OfferzView,
                      OfferzCallbackView)
from .translate import TranslateView
from .gemini import GeminiImageView
from .notifications import NotificationsView
from .push import PushPrefsView, PushSubscribeView, PushTestView, PushView
from .earn import EarnView
from .battlez import (BattlesView, BattleChallengeView, BattleDetailView,
                      BattleEnterView, BattleRespondView, BattleSettleView,
                      BattleWagerView, MoneyBattleVoteView)
from .opportunitiez import OpportunitieZView
from .sentencez import SentenceRoyaltyView, SentenceView
from .statz_trial import StatzTrialView
from .viewz import ViewBeatView, ViewCountsView, ViewStartView, ViewTimelineView
from .metricz import HoroscopeView, MetricZView, SubstanceScaleView
from .videoz import VideoDetailView, VideoView
from .instrumentalz import InstrumentalMidiView, InstrumentalMoodView, InstrumentalView
from .intelligence_royalty import IntelligenceTargetsView, IntelligenceUseDetailView, IntelligenceUsesView
from .keyconnectz import (KeyboardView, KeySpeakView, KeyTranscribeView,
                          KeyTranslateView)
from .playlistz import (PlaylistCollaboratorsView, PlaylistDetailView,
                        PlaylistItemDetailView, PlaylistItemsView,
                        PlaylistReorderView, PlaylistsView,
                        MyAppearancesView, PostPlaylistAppearancesView)
from .moderation import ReportView, BlockView
from .account import AccountExportView, AccountDeleteView
from .messages_view import MessagesView
from .logz import FeaturesView, LogZExportView, LogZView
from .observationz import ObservationConsentView, ObservationZView
from .social_verify import SocialReviewQueueView, SocialVerifyView
from .parcel import ParcelCampaignView, ParcelEmailPrefView, ParcelUnsubscribeView
from .reach import ReachGatesView
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
                       ReleaseQueueView, ReleaseSubmitView, ReleasesView)
from .collab_files import CollabFileDetailView, CollabFilesView
from .venuez import (VenueBookView, VenueBookingCancelView, VenueQuoteView,
                     VenueBookingRespondView, VenueDetailView, VenueListView,
                     VenueRateView)
from .collab_post import CollabNeedsView, CollabPostView
from .payouts import PayoutConnectView, PayoutRefreshView, PayoutsView
from .ai_models import AiModelView
from .badgez import BadgeGiftView, BadgezView
from .bugz import BugTriageView, BugzView
from .logicz import LogicZView
from .ratez import RateQueueView, RatezView, RatingKindsView
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
    PostEmbedsView,
    PromptzBuyView,
    PromptzConvertView,
    RoyaltiesView,
    RoyaltyAccrueView,
    RoyaltyCashoutView,
    SpecZView,
    UploadDetailView,
    UploadsView,
    WalletView,
    PracticeSessionView,
    DrumPatternView,
    DrumPatternDetailView,
    PublicDrumPatternView,
    ToolPreferenceView,
    PatternShareView,
    DrillTakeView,
    CoachObservationsView,
    TakeAnalysisView,
    LeaderboardsView,
    InstrumentLeaderboardView,
)
from .habits import HabitCreateView, HabitCompleteView
from .bodiez import (
    BodieZAccessView, BodieZBoardView, BodieZCustomDaysView, BodieZStepsView, BodieZCustomExerciseView, BodieZCustomExerciseDetailView, BodieZPastSessionView, BodieZStepCoachView, BodieZCustomDayDetailView, BodieZBodyMapView, BodieZCoachView, BodieZExerciseHistoryView, BodieZExercisesView,
    BodieZGoalDetailView, BodieZGoalsView, BodieZRecoveryView, BodieZRoutinesView,
    BodieZRoutineDetailView, BodieZRoutineCopyView, BodieZSessionRoutineView, BodieZSessionsView, BodieZSessionDetailView, BodieZSessionSummaryView, BodieZSetsView, BodieZLbFixView,
    BodieZProgressView, BodieZWeightLogView,
)
from .lessonz import (
    CoachProfileView, CoachReviewsView, StudentReviewView, coaches_list_view,
)
from .improvementz import (
    GoalListView, GoalDetailView, DrillPrescriptionListView,
    DrillPrescriptionDetailView, AccountabilityGroupListView,
    AccountabilityGroupDetailView,
)
from .beatz import (
    BeatListView, BeatDetailView, BeatPurchaseView, BeatUsageReportView,
    BeatEarningsView, ProducerBeatsView,
)
from .sonday import SondayBoardViewSet, SondayCardViewSet, SondayMetaView

urlpatterns = [
    path("wallet/", WalletView.as_view(), name="economy-wallet"),
    path("earn/", EarnView.as_view(), name="economy-earn"),
    # OpportunitieZ — what other members are seeking, for collaborators to find.
    path("opportunitiez/", OpportunitieZView.as_view(), name="economy-opportunitiez"),
    # BattleZ — a challenge, gated by the same five ranges as everything else.
    path("battlez/weekly/", WeeklyBattleView.as_view(), name="economy-battlez-weekly"),
    path("battlez/", BattlesView.as_view(), name="economy-battlez"),
    path("battlez/challenge/", BattleChallengeView.as_view(), name="economy-battle-challenge"),
    path("battlez/moneyvote/", MoneyBattleVoteView.as_view(), name="economy-battle-moneyvote"),
    path("battlez/<int:pk>/", BattleDetailView.as_view(), name="economy-battle"),
    path("battlez/<int:pk>/respond/", BattleRespondView.as_view(), name="economy-battle-respond"),
    path("battlez/<int:pk>/wager/", BattleWagerView.as_view(), name="economy-battle-wager"),
    path("battlez/<int:pk>/settle/", BattleSettleView.as_view(), name="economy-battle-settle"),
    path("battlez/<int:pk>/enter/", BattleEnterView.as_view(), name="economy-battle-enter"),
    # KeyConnectZ — the keyboard. Wallpaper is Premium; translate is free.
    path("sentencez/", SentenceView.as_view(), name="economy-sentencez"),
    path("statz-trial/", StatzTrialView.as_view(), name="economy-statz-trial"),
    path("views/start/", ViewStartView.as_view(), name="economy-views-start"),
    path("views/beat/", ViewBeatView.as_view(), name="economy-views-beat"),
    path("views/counts/", ViewCountsView.as_view(), name="economy-views-counts"),
    path("views/timeline/", ViewTimelineView.as_view(), name="economy-views-timeline"),
    path("videoz/", VideoView.as_view(), name="economy-videoz"),
    path("videoz/<int:pk>/", VideoDetailView.as_view(), name="economy-videoz-detail"),
    path("substancez/", SubstanceScaleView.as_view(), name="economy-substancez-scale"),
    path("metricz/<str:kind>/", MetricZView.as_view(), name="economy-metricz"),
    path("horoscope/<str:sign>/", HoroscopeView.as_view(), name="economy-horoscope"),
    path("instrumentalz/", InstrumentalView.as_view(), name="economy-instrumentalz"),
    path("instrumentalz/moods/", InstrumentalMoodView.as_view(), name="economy-instrumentalz-moods"),
    path("instrumentalz/<int:pk>/midi/", InstrumentalMidiView.as_view(), name="economy-instrumentalz-midi"),
    path("intelligence/targets/", IntelligenceTargetsView.as_view(), name="economy-intelligence-targets"),
    path("intelligence/uses/", IntelligenceUsesView.as_view(), name="economy-intelligence-uses"),
    path("intelligence/uses/<int:pk>/", IntelligenceUseDetailView.as_view(), name="economy-intelligence-use"),
    path("sentencez/<int:pk>/royalty/", SentenceRoyaltyView.as_view(), name="economy-sentencez-royalty"),
    path("keyz/", KeyboardView.as_view(), name="economy-keyz"),
    path("keyz/translate/", KeyTranslateView.as_view(), name="economy-keyz-translate"),
    # Voice, both directions. Neither is gated by tier — the allowance is, and
    # GET keyz/ publishes it before either button is pressed.
    path("keyz/transcribe/", KeyTranscribeView.as_view(), name="economy-keyz-transcribe"),
    path("keyz/speak/", KeySpeakView.as_view(), name="economy-keyz-speak"),
    path("wallet/add/", AddFundsView.as_view(), name="economy-wallet-add"),
    path("owner/revenue/", OwnerRevenueView.as_view(), name="economy-owner-revenue"),
    path("membership/", MembershipView.as_view(), name="economy-membership"),
    path("membership/refund/", MembershipRefundView.as_view(), name="economy-membership-refund"),
    path("owner/claim/", OwnerClaimView.as_view(), name="economy-owner-claim"),
    path("limits/", LimitsView.as_view(), name="economy-limits"),
    path("ai/charge/", AIChargeView.as_view(), name="economy-ai-charge"),
    path("promptz/buy/", PromptzBuyView.as_view(), name="economy-promptz-buy"),
    path("promptz/convert/", PromptzConvertView.as_view(), name="economy-promptz-convert"),
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
    # CallZ. The rate route is separate and comes FIRST in the flow: a member
    # asks what a call costs before anything rings, which is the whole
    # cost/gain rule for a feature priced by the minute.
    path("callz/rate/<str:username>/", CallRateView.as_view(), name="economy-callz-rate"),
    path("callz/", CallsView.as_view(), name="economy-callz"),
    path("callz/<int:pk>/", CallDetailView.as_view(), name="economy-call"),
    path("callz/<int:pk>/<str:action>/", CallDetailView.as_view(), name="economy-call-action"),
    # Link previews. These are NOT under /api/ on purpose — they are the same
    # addresses a person shares, served as HTML to whatever cannot run
    # JavaScript. See sharecard.py and the vercel.json note in the PR.
    path("share/u/<str:username>", profile_card, name="share-profile"),
    path("share/p/<int:pk>", post_card, name="share-post"),
    # Shareable score cards: JSON for the page + a 1200x630 image for crawlers.
    path("scores/<str:token>/", ScoreShareView.as_view(), name="score-share"),
    path("scores/<str:token>/card.png", score_card_png, name="score-share-card"),
    path("soundz/", SoundZView.as_view(), name="economy-soundz"),
    path("coachvoice/", CoachVoiceView.as_view(), name="economy-coachvoice"),
    path("coachvoice/speak/", CoachSpeakView.as_view(), name="economy-coachvoice-speak"),
    path("dawz/", DawZView.as_view(), name="economy-dawz"),
    path("attractivenessz/", AttractivenessZView.as_view(), name="economy-attractivenessz"),
    path("soundcloud/engagement/", SoundCloudEngagementView.as_view(), name="economy-soundcloud-engagement"),
    path("soundcloud/import/", SoundCloudImportView.as_view(), name="economy-soundcloud-import"),
    path("coachz/studio/", CoachStudioView.as_view(), name="economy-coachz-studio"),
    path("coachz/rate/", RateStudentTakeView.as_view(), name="economy-coachz-rate"),
    path("coachz/add-student/", AddStudentView.as_view(), name="economy-coachz-add-student"),
    path("specz/", SpecZView.as_view(), name="economy-specz"),
    path("specz/buy/", SpecZView.as_view(), name="economy-specz-buy"),
    # Removing one is a DELETE on the thing itself, not a POST to /remove/.
    path("specz/<int:pk>/", SpecZView.as_view(), name="economy-specz-item"),
    path("royalties/", RoyaltiesView.as_view(), name="economy-royalties"),
    path("royalties/accrue/", RoyaltyAccrueView.as_view(), name="economy-royalties-accrue"),
    path("royalties/cashout/", RoyaltyCashoutView.as_view(), name="economy-royalties-cashout"),
    # Taking it OUT — the only path where money leaves the platform.
    path("payouts/", PayoutsView.as_view(), name="economy-payouts"),
    path("payouts/connect/", PayoutConnectView.as_view(), name="economy-payouts-connect"),
    path("payouts/refresh/", PayoutRefreshView.as_view(), name="economy-payouts-refresh"),
    path("uploads/", UploadsView.as_view(), name="economy-uploads"),
    path("uploads/<int:pk>/", UploadDetailView.as_view(), name="economy-upload-detail"),
    # The address an upload is HANDED OUT under, and the only one anything
    # stores. Resolved to wherever the bytes are on every request, so a signed
    # bucket URL is minted fresh instead of being frozen into a post that then
    # goes dead an hour later. No trailing slash, and the filename last —
    # `upload_behind()` finds the take on a post by the tail of its URL.
    re_path(r"^media/(?P<pk>\d+)/(?P<filename>[^/]+)$",
            MediaFileView.as_view(), name="economy-media-file"),
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
    path("push/", PushView.as_view(), name="economy-push"),
    path("push/subscribe/", PushSubscribeView.as_view(), name="economy-push-subscribe"),
    path("push/prefs/", PushPrefsView.as_view(), name="economy-push-prefs"),
    path("push/test/", PushTestView.as_view(), name="economy-push-test"),
    path("messages/", MessagesView.as_view(), name="economy-messages"),
    path("habits/", HabitCreateView.as_view(), name="economy-habits"),
    path("habits/<int:habit_id>/complete/", HabitCompleteView.as_view(), name="economy-habit-complete"),
    path("logz/", LogZView.as_view(), name="economy-logz"),
    # A ledger you can read and not act on is the read-only surface the
    # cross-pollination rule calls unfinished. This is the acting-on.
    path("logz/export/", LogZExportView.as_view(), name="economy-logz-export"),
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
    # The player's heartbeat. Rating a track you never played was possible for
    # every post older than a minute — the age window gated the post, not the
    # listener. See models.ListenProgress.
    path("social/listened/", SocialView.as_view(), {"action": "listened"},
         name="economy-social-listened"),
    path("social/verify/", SocialVerifyView.as_view(), name="economy-social-verify"),
    # What the AI couldn't confirm goes to a person, not to a wall.
    path("social/reviews/", SocialReviewQueueView.as_view(), name="economy-social-reviews"),
    path("members/", MembersView.as_view(), name="economy-members"),
    path("reach/", ReachGatesView.as_view(), name="economy-reach"),
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
    path("ratez/queue/", RateQueueView.as_view(), name="economy-ratez-queue"),
    path("postz/", PostsView.as_view(), name="economy-postz"),
    # Personalized discovery feed based on taste affinity and listening behavior.
    path("postz/discover/", DiscoveryFeedView.as_view(), name="economy-postz-discover"),
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
    # Progress toward BattleZ/CollabZ eligibility: ratings needed and current progress.
    path("postz/<int:pk>/progression/", PostProgressionView.as_view(), name="economy-postz-progression"),
    path("postz/<int:pk>/share/", PostShareView.as_view(), name="economy-postz-share"),
    path("postz/<int:pk>/sale/", PostSaleView.as_view(), name="economy-postz-sale"),
    path("postz/<int:pk>/delete/", PostDeleteView.as_view(), name="economy-postz-delete"),
    path("postz/embeds/", PostEmbedsView.as_view(), name="economy-postz-embeds"),
    path("submissions/", SubmissionsView.as_view(), name="economy-submissions"),
    # JournalZ — the diary. Private by default, which is the one thing here
    # that isn't like PostZ, so the share is its own deliberate endpoint and
    # quotes what it costs and who it tells before it does either.
    path("journalz/", JournalZView.as_view(), name="economy-journalz"),
    path("journalz/cost/", JournalCostView.as_view(), name="economy-journalz-cost"),
    # On This Day and the formatted export — Premium, through the standard gate.
    path("journalz/lookback/", JournalLookbackView.as_view(), name="economy-journalz-lookback"),
    path("journalz/export/", JournalExportView.as_view(), name="economy-journalz-export"),
    path("journalz/<int:pk>/", JournalEntryView.as_view(), name="economy-journalz-entry"),
    path("journalz/<int:pk>/share/", JournalShareView.as_view(), name="economy-journalz-share"),
    # QuestZ — the Energy on-ramp for members who have no reach yet.
    path("questz/", QuestBoardView.as_view(), name="economy-questz"),
    path("questz/<str:quest_id>/claim/", QuestClaimView.as_view(), name="economy-questz-claim"),
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
    # WidgetZ — a link that opens on the screen instead of taking the member
    # off it. GET is the policy (who may frame a page, what a visit pays);
    # POST resolves one link into the widget it becomes.
    path("widgetz/", WidgetZView.as_view(), name="economy-widgetz"),
    path("widgetz/open/", WidgetOpenView.as_view(), name="economy-widgetz-open"),
    # The house rules, in one place so no screen retypes one. Open logged-out:
    # the one about how many accounts a person gets is needed on the signup
    # form, which is the one screen where nobody is signed in yet.
    path("rulez/", RulezView.as_view(), name="economy-rulez"),
    # Logged-out: which coaches a stranger can reach without an account.
    path("trialdoorz/", TrialDoorsView.as_view(), name="economy-trial-doors"),
    # Public funnel headline stats for non-authenticated trial visitors.
    path("trial/public/stats/", TrialPublicStatsView.as_view(), name="economy-trial-public-stats"),
    # Email a trial score and remind them to send another take (retake.py).
    path("trial/remind/", RetakeRemindView.as_view(), name="economy-trial-remind"),
    path("trial/remind/stop/", RetakeStopView.as_view(), name="economy-trial-remind-stop"),
    path("tiers/", PublicTiersView.as_view(), name="economy-public-tiers"),
    # PersonalitieZ axes — one list, read by the profile toggles, every
    # member search filter, and VybeZ.
    path("personalityz/", PersonalityAxesView.as_view(), name="economy-personalityz"),
    # The questionnaire, open logged-out like the trial take.
    path("personalityz/test/", PersonalityTestView.as_view(), name="economy-personalityz-test"),
    # ReligionZ — the closed list of 50, read by the profile picker and every
    # member search filter. Same shape as personalityz above.
    path("religionz/", ReligionsView.as_view(), name="economy-religionz"),
    # LanguageZ — the closed list of 50, grouped by region. Same shape.
    path("languagez/", LanguagesView.as_view(), name="economy-languagez"),
    path("signbonus/", SignBonusView.as_view(), name="economy-signbonus"),
    # What rating, voting, commenting and answering a stranger pay — stated
    # before the act, because none of them cost anything and a reward found
    # out by accident is a coincidence.
    path("karmaz/", KarmaRewardsView.as_view(), name="economy-karmaz"),
    # Lilith — the task manager. One GET builds the whole board because it
    # renders on every open, and the reward table rides with it so every
    # price is on screen before anything is pressed.
    path("lilith/", LilithBoardView.as_view(), name="economy-lilith"),
    path("lilith/tasks/", LilithTaskListView.as_view(), name="economy-lilith-tasks"),
    path("lilith/tasks/<int:task_id>/", LilithTaskDetailView.as_view(),
         name="economy-lilith-task"),
    path("lilith/tasks/<int:task_id>/complete/", LilithTaskCompleteView.as_view(),
         name="economy-lilith-task-complete"),
    path("lilith/routines/", LilithRoutineListView.as_view(),
         name="economy-lilith-routines"),
    path("lilith/routines/<int:routine_id>/", LilithRoutineDetailView.as_view(),
         name="economy-lilith-routine"),
    path("lilith/sponsor/", LilithSponsorView.as_view(), name="economy-lilith-sponsor"),
    # BodieZ — strength training and workout planning. v1: library, routines,
    # session log, and a progress read built from logged sets, not a formula.
    path("bodiez/exercises/", BodieZExercisesView.as_view(), name="economy-bodiez-exercises"),
    path("bodiez/exercises/custom/", BodieZCustomExerciseView.as_view(), name="economy-bodiez-custom-exercise"),
    path("bodiez/exercises/custom/<int:exercise_id>/", BodieZCustomExerciseDetailView.as_view(),
         name="economy-bodiez-custom-exercise-detail"),
    path("bodiez/exercises/<int:exercise_id>/history/", BodieZExerciseHistoryView.as_view(),
         name="economy-bodiez-exercise-history"),
    path("bodiez/custom-days/", BodieZCustomDaysView.as_view(), name="economy-bodiez-custom-days"),
    path("bodiez/custom-days/<int:day_id>/", BodieZCustomDayDetailView.as_view(),
         name="economy-bodiez-custom-day"),
    path("bodiez/routines/", BodieZRoutinesView.as_view(), name="economy-bodiez-routines"),
    path("bodiez/routines/<int:routine_id>/copy/", BodieZRoutineCopyView.as_view(),
         name="economy-bodiez-routine-copy"),
    path("bodiez/sessions/<int:session_id>/routine/", BodieZSessionRoutineView.as_view(),
         name="economy-bodiez-session-routine"),
    path("bodiez/routines/<int:routine_id>/", BodieZRoutineDetailView.as_view(),
         name="economy-bodiez-routine"),
    path("bodiez/sessions/", BodieZSessionsView.as_view(), name="economy-bodiez-sessions"),
    path("bodiez/sessions/past/", BodieZPastSessionView.as_view(), name="economy-bodiez-past-session"),
    path("bodiez/sessions/<int:session_id>/", BodieZSessionDetailView.as_view(),
         name="economy-bodiez-session"),
    path("bodiez/sessions/<int:session_id>/summary/", BodieZSessionSummaryView.as_view(),
         name="economy-bodiez-session-summary"),
    path("bodiez/sessions/<int:session_id>/sets/", BodieZSetsView.as_view(),
         name="economy-bodiez-sets"),
    path("bodiez/lb-fix/", BodieZLbFixView.as_view(), name="economy-bodiez-lb-fix"),
    path("bodiez/progress/", BodieZProgressView.as_view(), name="economy-bodiez-progress"),
    path("bodiez/board/", BodieZBoardView.as_view(), name="economy-bodiez-board"),
    path("bodiez/access/", BodieZAccessView.as_view(), name="economy-bodiez-access"),
    path("bodiez/bodymap/", BodieZBodyMapView.as_view(), name="economy-bodiez-bodymap"),
    path("bodiez/coach/", BodieZCoachView.as_view(), name="economy-bodiez-coach"),
    path("bodiez/goals/", BodieZGoalsView.as_view(), name="economy-bodiez-goals"),
    path("bodiez/goals/<int:goal_id>/", BodieZGoalDetailView.as_view(), name="economy-bodiez-goal"),
    path("bodiez/weightlog/", BodieZWeightLogView.as_view(), name="economy-bodiez-weightlog"),
    path("bodiez/steps/", BodieZStepsView.as_view(), name="economy-bodiez-steps"),
    path("bodiez/stepz/coach/", BodieZStepCoachView.as_view(), name="economy-bodiez-stepz-coach"),
    path("bodiez/recovery/", BodieZRecoveryView.as_view(), name="economy-bodiez-recovery"),
    path("bodiez/trial/", BodieZTrialView.as_view(), name="economy-bodiez-trial"),
    path("offerz/funnel/", FunnelOffersView.as_view(), name="economy-funnel-offers"),
    path("offerz/funnel/redeem/", FunnelOfferRedeemView.as_view(),
         name="economy-funnel-offer-redeem"),
    path("offerz/catalog/", FunnelCatalogView.as_view(),
         name="economy-funnel-catalog"),
    # One voice, set once and followed by every surface a model writes through.
    path("voicez/", VoiceZView.as_view(), name="economy-voicez"),
    # DupeZ — one person, one account. Groups, the member's claim on their own
    # other account, the owner's review queue, and the owner override.
    path("dupez/", DupeZView.as_view(), name="economy-dupez"),
    path("dupez/claim/", DupeZClaimView.as_view(), name="economy-dupez-claim"),
    path("dupez/review/", DupeZReviewView.as_view(), name="economy-dupez-review"),
    # The account being claimed answers for itself — a weak signal is a
    # coincidence as often as a person, and they are the only party that knows.
    path("dupez/verify/", DupeZVerifyView.as_view(), name="economy-dupez-verify"),
    path("dupez/delete/", DupeZDeleteView.as_view(), name="economy-dupez-delete"),
    # The system-raised half of the queue: a new account made from an address
    # another account was made from. A flag, never a block and never a delete.
    path("dupez/flags/", DupeZFlagsView.as_view(), name="economy-dupez-flags"),
    # What was heard in a DirectZ work's audio, and the member's answer to it.
    # A match is named before they publish — never after, and never a block.
    path("directz/<int:pk>/copyright/", DirectZCopyrightView.as_view(),
         name="economy-directz-copyright"),
    # A collab is where the finished master usually lands, so it releases too.
    path("collab/<int:pk>/distribute/", CollabDistributeView.as_view(), name="economy-collab-distribute"),
    # VenueZ — CollabZ when everyone is in the same room. The quote is on the
    # listing, not behind the booking, because the price of turning up has to
    # be readable before anybody agrees to turn up.
    path("venuez/", VenueListView.as_view(), name="economy-venuez"),
    path("venuez/<int:pk>/", VenueDetailView.as_view(), name="economy-venue"),
    path("venuez/<int:pk>/book/", VenueBookView.as_view(), name="economy-venue-book"),
    # The price for the skills and hours actually asked for, before the ask.
    path("venuez/<int:pk>/quote/", VenueQuoteView.as_view(), name="economy-venue-quote"),
    path("venuez/bookings/<int:pk>/respond/", VenueBookingRespondView.as_view(),
         name="economy-venue-respond"),
    path("venuez/bookings/<int:pk>/cancel/", VenueBookingCancelView.as_view(),
         name="economy-venue-cancel"),
    # Attendance-gated, unlike a battle and unlike a collab split. Somebody
    # who was not in the room has nothing to report about it.
    path("venuez/<int:pk>/rate/", VenueRateView.as_view(), name="economy-venue-rate"),
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
    path("distributez/queue/", ReleaseQueueView.as_view(), name="economy-release-queue"),
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
    path("parcel/email-pref/", ParcelEmailPrefView.as_view(), name="economy-parcel-email-pref"),
    path("parcel/unsubscribe/", ParcelUnsubscribeView.as_view(), name="economy-parcel-unsubscribe"),
    path("autotopup/", AutoTopUpView.as_view(), name="economy-autotopup"),
    path("autotopup/<int:pk>/cancel/", AutoTopUpCancelView.as_view(), name="economy-autotopup-cancel"),
    path("identity/", IdentityView.as_view(), name="economy-identity"),
    # MetZ, TunerZ, ChordZ, DrumZ — practice tool tracking and cross-pollination
    path("metz/sessions/", PracticeSessionView.as_view(), name="economy-metz-sessions"),
    path("drumz/patterns/", DrumPatternView.as_view(), name="economy-drumz-patterns"),
    path("drumz/patterns/<int:pattern_id>/", DrumPatternDetailView.as_view(), name="economy-drumz-pattern"),
    path("drumz/patterns/public/", PublicDrumPatternView.as_view(), name="economy-drumz-patterns-public"),
    path("metz/preferences/", ToolPreferenceView.as_view(), name="economy-metz-preferences"),
    path("drumz/share/", PatternShareView.as_view(), name="economy-drumz-share"),
    path("tunerz/drills/", DrillTakeView.as_view(), name="economy-tunerz-drills"),
    path("coach/observations/", CoachObservationsView.as_view(), name="economy-coach-observations"),
    path("takes/<int:upload_id>/analysis/", TakeAnalysisView.as_view(), name="economy-take-analysis"),
    # LeaderboardZ — competition drives conversions. All metrics are substance.
    path("leaderboardz/", LeaderboardsView.as_view(), name="economy-leaderboardz"),
    path("leaderboardz/xp/<str:app_key>/", InstrumentLeaderboardView.as_view(), name="economy-leaderboardz-xp"),
    # LessonZ — Lesson marketplace (Path 3 monetization)
    path("lessonz/profile/", CoachProfileView.as_view(), name="economy-lessonz-profile"),
    path("lessonz/coach/<int:coach_id>/reviews/", CoachReviewsView.as_view(), name="economy-lessonz-coach-reviews"),
    path("lessonz/review/", StudentReviewView.as_view(), name="economy-lessonz-review"),
    path("lessonz/coaches/", coaches_list_view, name="economy-lessonz-coaches"),
    # ImprovemenZ — Gap 3 improvement loop (goals, drill prescriptions, accountability)
    path("improvementz/goals/", GoalListView.as_view(), name="economy-improvementz-goals"),
    path("improvementz/goals/<int:goal_id>/", GoalDetailView.as_view(), name="economy-improvementz-goal-detail"),
    path("improvementz/drills/", DrillPrescriptionListView.as_view(), name="economy-improvementz-drills"),
    path("improvementz/drills/<int:drill_id>/complete/", DrillPrescriptionDetailView.as_view(), name="economy-improvementz-drill-complete"),
    path("improvementz/groups/", AccountabilityGroupListView.as_view(), name="economy-improvementz-groups"),
    path("improvementz/groups/<int:group_id>/", AccountabilityGroupDetailView.as_view(), name="economy-improvementz-group-detail"),
    # BeatZ — Path 4 beat/stem licensing (producers sell, buyers license)
    path("beatz/", BeatListView.as_view(), name="economy-beatz"),
    path("beatz/<int:beat_id>/", BeatDetailView.as_view(), name="economy-beatz-detail"),
    path("beatz/<int:beat_id>/purchase/", BeatPurchaseView.as_view(), name="economy-beatz-purchase"),
    path("beatz/purchases/<int:purchase_id>/report-usage/", BeatUsageReportView.as_view(), name="economy-beatz-report-usage"),
    path("beatz/earnings/", BeatEarningsView.as_view(), name="economy-beatz-earnings"),
    path("beatz/my-beats/", ProducerBeatsView.as_view(), name="economy-beatz-my-beats"),
    # SondayZ — Path 5 Kanban board for creative project management (Premium-only)
    path("sonday/", SondayBoardViewSet.as_view({"get": "list", "post": "create"}), name="economy-sonday-boards"),
    path("sonday/<int:id>/", SondayBoardViewSet.as_view({"get": "retrieve", "patch": "partial_update", "put": "update", "delete": "destroy"}), name="economy-sonday-board"),
    path("sonday/<int:id>/add_column/", SondayBoardViewSet.as_view({"post": "add_column"}), name="economy-sonday-add-column"),
    path("sonday/<int:id>/invite_user/", SondayBoardViewSet.as_view({"post": "invite_user"}), name="economy-sonday-invite-user"),
    path("sonday/<int:id>/permissions/", SondayBoardViewSet.as_view({"get": "permissions"}), name="economy-sonday-permissions"),
    path("sonday/meta/", SondayMetaView.as_view({"get": "retrieve"}), name="economy-sonday-meta"),
    path("sonday/<int:id>/columns/<int:column_id>/", SondayBoardViewSet.as_view({"patch": "column", "delete": "column"}), name="economy-sonday-column"),
    path("sonday/<int:id>/members/<int:user_id>/", SondayBoardViewSet.as_view({"delete": "remove_user"}), name="economy-sonday-remove-user"),
    path("sonday/cards/", SondayCardViewSet.as_view({"get": "list", "post": "create"}), name="economy-sonday-cards"),
    path("sonday/cards/<int:id>/", SondayCardViewSet.as_view({"get": "retrieve", "patch": "partial_update", "put": "update", "delete": "destroy"}), name="economy-sonday-card"),
    path("sonday/cards/<int:id>/move/", SondayCardViewSet.as_view({"post": "move"}), name="economy-sonday-card-move"),
]
