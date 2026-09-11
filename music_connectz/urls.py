import os

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path, re_path
from django.views.static import serve as static_serve

from apps.economy.views import (
    AllMembersView,
    FunnelEventView,
    FunnelSummaryView,
    PublicStatsView,
    StatsView,
)
from apps.economy.groupz import GroupMemberView, GroupZView
from apps.economy.labelz import (LabelContractRespondView, LabelContractsView,
                                 LabelZView)
from apps.omviardz.wellknown import AssetLinksView

# SkillZ training is generated per app_key. MimeZ/DirectZ/LessonZ mount their own
# inside their urls.py; the InstrumentZ apps have no Django app of their own, so
# their trees are mounted here. The frontend's <InstrumentZ appKey="…"> builds
# basePath as /api/<appKey>, so every key below must match an appKey it renders
# or that app's SkillZ panel 404s.
try:
    from apps.skillz.training import training_urlpatterns
except Exception:  # pragma: no cover - never let this take the deploy down
    def training_urlpatterns(app_key):
        return []

# guitarz/bassz/keyz/drumz/violinz have had a scored profile in
# apps/economy/instruments.py (dimensions, caveat, prompt_for) since it was
# written — `prompt_for("drumz", ...)` is tested and has worked the whole
# time. What they never had was a route: this list is the only thing that
# turns a profile into `/api/<key>/coach/`, `/api/<key>/trial/` and a SkillZ
# tree, so five fully-scoreable instruments 404'd behind a tab the frontend
# never had reason to build. One line.
INSTRUMENT_APP_KEYS = ["singz", "rapz", "guitarz", "bassz", "keyz", "drumz", "violinz"]

# Boss Take — the blueprint's scored final take, coached by the StatZ AI coach.
# Mounted for EVERY instrument app beside the SkillZ tree, because a take is a
# take whichever app you train in. The scored dimensions differ per instrument
# (a guitar take has no "breath") — see apps/economy/instruments.py.
try:
    from apps.economy.vocalcoach import SingZCoachView
except Exception:  # pragma: no cover - never take the deploy down
    SingZCoachView = None

# The no-account trial take, and the public share endpoint the client has been
# calling at this exact path since before it existed.
try:
    from apps.economy.playlistz import PublicPlaylistView
    from apps.economy.publicz import PublicPostView
    from apps.economy.trial import TrialCoachView, TrialTakeDetailView
except Exception:  # pragma: no cover - never take the deploy down
    PublicPostView = TrialCoachView = TrialTakeDetailView = PublicPlaylistView = None


def health(_request):
    # Whether member uploads are actually being kept. Reported here because it
    # is the one place the answer can be read without a Render login — and
    # because a service that is "ok" while quietly deleting everyone's music
    # on the next deploy is not telling the whole truth about itself.
    try:
        from apps.economy.storage_health import upload_storage_state
        uploads = upload_storage_state()
    except Exception:                                    # pragma: no cover
        uploads = {"durable": None, "detail": "could not be determined"}
    # Whether money can move, for the same reason uploads are here. A missing
    # STRIPE_WEBHOOK_SECRET is the quiet one: checkout works, Stripe takes the
    # money, and the delivery that credits the wallet is refused — the member
    # is charged and nothing arrives, and nothing inside the app can see it.
    try:
        from apps.economy.payments_health import payments_state
        payments = payments_state()
    except Exception:                                    # pragma: no cover
        payments = {"ready": None, "problems": ["could not be determined"]}
    # Whether the AI surfaces can actually run, for the same reason uploads
    # are reported here: it is a fact about the deployment that decides
    # whether a headline feature works, and until now the only way to learn
    # it was to open the Render dashboard or to press the button and get a
    # 503. The coach, OCC, DirectZ craft and KeyConnectZ all hang off this
    # one key.
    #
    # A BOOLEAN, never the key and never its length. This endpoint is open to
    # anybody, and "configured" is the whole question — any detail beyond it
    # is a fact about a secret, published.
    #
    # And it says CONFIGURED, not working: a key that is set can still be
    # revoked, out of quota or restricted to the wrong API, and this cannot
    # see any of that. tools/coach_live_check.sh is the only thing that can.
    try:
        from apps.economy.gemini import _key
        ai_configured = bool(_key())
    except Exception:                                    # pragma: no cover
        ai_configured = None
    # Whether a submission can be checked against commercial recordings at
    # all. Same argument as the AI key: it decides whether a whole surface
    # works, and readiness() already names which half is missing.
    try:
        from apps.economy.copyrightz import readiness
        copyright_state = readiness()
    except Exception:                                    # pragma: no cover
        copyright_state = {"ready": None, "why": "could not be determined"}
    return JsonResponse(
        {
            "service": "music-connectz-backend",
            "status": "ok",
            "uploads": uploads,
            "payments": payments,
            "copyright": copyright_state,
            "ai": {
                "configured": ai_configured,
                "detail": (
                    "GEMINI_API_KEY is set — surfaces will attempt a real call. "
                    "Set does not mean working; run tools/coach_live_check.sh."
                    if ai_configured else
                    "GEMINI_API_KEY is NOT set — the coach, OCC, DirectZ craft "
                    "and KeyConnectZ voice all 503 until it is."
                    if ai_configured is False else
                    "could not be determined"
                ),
            },
            "endpoints": [
                "/api/auth/register/",
                "/api/auth/login/",
                "/api/auth/oauth/{google|github|apple}/",
                "/api/mimez/skillz/...",
                "/api/directz/skillz/...",
                "/admin/",
            ],
        }
    )


urlpatterns = [
    path("", health, name="health"),
    path("admin/", admin.site.urls),
    path("api/auth/stats/", StatsView.as_view(), name="auth-stats"),
    path("api/auth/stats/all/", AllMembersView.as_view(), name="auth-stats-all"),
    # No session required — the landing page's real member/online count.
    path("api/auth/public-stats/", PublicStatsView.as_view(), name="auth-public-stats"),
    # No session required — a step on the join funnel, logged by a visitor
    # who may never have had one. Owner-only summary sits behind it.
    path("api/auth/funnel/", FunnelEventView.as_view(), name="auth-funnel"),
    path("api/auth/funnel/summary/", FunnelSummaryView.as_view(), name="auth-funnel-summary"),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/economy/", include("apps.economy.urls")),
    # GroupZ and LabelZ answer at the root because that is where the shipped
    # client asks for them — both screens were in the nav calling these paths
    # before either backend existed.
    path("api/groupz/", GroupZView.as_view(), name="groupz"),
    path("api/groupz/<str:gid>/<str:action>/", GroupMemberView.as_view(), name="groupz-member"),
    path("api/labelz/", LabelZView.as_view(), name="labelz"),
    path("api/labelz/contracts/", LabelContractsView.as_view(), name="labelz-contracts"),
    path("api/labelz/contracts/<int:pk>/<str:action>/", LabelContractRespondView.as_view(),
         name="labelz-contract-respond"),
    path("api/mimez/", include("apps.mimez.urls")),
    path("api/directz/", include("apps.directz.urls")),
    path("api/lessonz/", include("apps.lessonz.urls")),
    path("api/omviardz/", include("apps.omviardz.urls")),
    # Android app <-> site link verification. Must sit at the domain root, not
    # under /api/ — Google fetches this exact path over https.
    path(".well-known/assetlinks.json", AssetLinksView.as_view(), name="assetlinks"),
] + ([
    # `/p/<id>` share links resolve here without a session. Mounted at the root
    # because that is where the shipped client asks for it; the same view is
    # also reachable at /api/economy/postz/<id>/ with the rest of PostZ.
    path("api/postz/<int:pk>/", PublicPostView.as_view(), name="postz-public"),
] if PublicPostView else []) + ([
    # A shared playlist opens for anyone, same rule as a shared post.
    path("api/playlistz/<int:pk>/", PublicPlaylistView.as_view(), name="playlistz-public"),
] if PublicPlaylistView else []) + ([
    path("api/trial/<str:token>/", TrialTakeDetailView.as_view(), name="trial-take"),
] if TrialTakeDetailView else []) + [
    path(f"api/{key}/", include((training_urlpatterns(key), key)))
    for key in INSTRUMENT_APP_KEYS
] + ([
    path(f"api/{key}/trial/", TrialCoachView.as_view(app_key=key), name=f"{key}-trial")
    for key in INSTRUMENT_APP_KEYS
] if TrialCoachView else []) + ([
    path(f"api/{key}/coach/", SingZCoachView.as_view(app_key=key), name=f"{key}-coach")
    for key in INSTRUMENT_APP_KEYS
] if SingZCoachView else [])

# Serve user uploads. When S3/R2 is configured (S3_BUCKET_NAME), django-storages
# serves media from the bucket and these URLs are absolute — this route isn't hit.
# Without a bucket, files live on the local disk and must be served by the app in
# BOTH dev and prod (else every uploaded preview 404s). NOTE: Render's disk is
# ephemeral, so set S3_BUCKET_NAME + keys for media that survives redeploys.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
elif not os.environ.get("S3_BUCKET_NAME"):
    urlpatterns += [
        re_path(r"^media/(?P<path>.*)$", static_serve, {"document_root": settings.MEDIA_ROOT}),
    ]
