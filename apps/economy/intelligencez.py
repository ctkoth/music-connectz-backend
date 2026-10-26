"""IntelligenceZ — the hub that holds every IntelligenceZ app.

Sentence ConnectZ, OCC, Instrumental ConnectZ, Mix ConnectZ, Video ConnectZ,
FaceZ and Image ConnectZ each had a screen (or not) and no front door: nothing
said, in one place, which of them exist, which are switched on, and what each
costs. This is that place, and it is the cost/gain rule applied to a menu — the
price of every app is on its tile BEFORE it is opened, from the same functions
each app's own GET uses, so the hub can never quote a number the app then
contradicts.

It decides nothing and charges nothing. Every price is read from where the app
already states it; `configured` is the same key check the app's own screen uses;
`count` and `recent` are the member's own rows. A shelf of recent pieces across
all of them is the cross-pollination rule: something made in one app is one tap
from being opened in it (`tab` + `target`, landed on by `goToSpot`).

The cost of this endpoint is a fixed handful of queries, however many pieces a
member has made: each count is one aggregate, each shelf is sliced in SQL
before it is merged in Python. `test_intelligencez` pins the number, because
this is the screen every IntelligenceZ visit starts on.
"""
import os

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import videoz
from .catalog import ai_cost, ai_model_for
from .gemini import _key
from .models import (Face, GeneratedImage, InstrumentalWork, MasterWork, OccOutput, SentenceWork, VideoWork,
                     daily_prompt_covers, daily_prompt_state, membership_for, profile_for)
from .sentencez import KINDS as SENTENCE_KINDS

RECENT_MAX = 12
SNIPPET = 48


def _snippet(text, n=SNIPPET):
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _anthropic_configured():
    """OCC's chat builds `anthropic.Anthropic()`, which reads this variable, and
    answers 503 when it is missing or the package is not installed. There is no
    separate settings flag to read, so this is the same check made up front."""
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


# Which apps the standalone IntelligenceZ app carries (`in_app`, also served as
# `standalone`). The standalone is a shell with sign-in and no MembershipZ, no
# wallet screen and nothing it may sell, so an app is in it only if it can be
# used there WITHOUT a purchase:
#
# * Sentence, OCC and Instrumental ConnectZ run on the free daily allowance.
# * Mix ConnectZ runs on the member's own device and costs nothing at all.
# * Video ConnectZ is a fixed price with no free tier — inside an app that
#   cannot sell anything it would be a wall, a tile that says "$4" and has no
#   way to pay it. It stays on the main site, where it can.
# * FaceZ exists to hold the photos Video ConnectZ starts from, so without
#   Video it is a room with nothing to do in it.
# * Image ConnectZ is not built.
IN_APP = {"sentenceconnectz", "occ", "instrumentalconnectz", "mixconnectz"}

# (key, label, emoji, icon, desc, built). Order is the order the hub shows them.
APPS = [
    ("sentenceconnectz", "Sentence ConnectZ", "✍️", "sentencez.png",
     "Resumes, cover letters, lyrics, poems, bios, posts and essays, written from what you tell it.", True),
    ("occ", "OCC", "👁️", "occ.png",
     "Chat with Claude about what you're building — code, plans, copy.", True),
    ("instrumentalconnectz", "Instrumental ConnectZ", "🎹", "instrumentalconnectz.png",
     "AI-composed MIDI loops by genre, instruments, BPM and key.", True),
    ("mixconnectz", "Mix ConnectZ", "🎚️", "mixconnectz.png",
     "Master a finished song on your device — loudness, tone, width and peaks, measured.", True),
    ("videoconnectz", "Video ConnectZ", "🎬", "videoconnectz.png",
     "Short AI video clips from a prompt, with an optional photo as the first frame.", True),
    ("facez", "FaceZ", "🙂", "facez.png",
     "The photos Video ConnectZ can start from.", True),
    ("imageconnectz", "Image ConnectZ", "🖼️", "imageconnectz.png",
     "Profile pictures, avatars, song and album covers, banners, wallpapers, thumbnails and flyers — pick what it's for.", True),
]

# The data-tour anchor each shelf row lands on in its own app.
TARGETS = {
    "sentenceconnectz": "sentencez-recent",
    "instrumentalconnectz": "instrumental-recent",
    "mixconnectz": "mixz-recent",
    "videoconnectz": "videoz-recent",
    "occ": "occ-workz",
}


def _prompt_price(cost, daily_left):
    return {"kind": "prompt", "cost_cents": cost,
            "free_today": daily_left > 0 and daily_prompt_covers(cost),
            "daily_remaining": daily_left}


def _prices(user, tier, daily_left):
    standard = ai_cost("standard")
    engine_key, engine = ai_model_for(profile_for(user).ai_model, tier)
    occ = _prompt_price(engine["cost_cents"], daily_left)
    # The engine the member picked, because on OCC the engine IS the price.
    occ["engine"] = engine["name"]
    occ["engine_key"] = engine_key
    return {
        "sentenceconnectz": _prompt_price(standard, daily_left),
        "occ": occ,
        "instrumentalconnectz": _prompt_price(standard, daily_left),
        "mixconnectz": {"kind": "device"},
        "videoconnectz": {"kind": "fixed", "cost_cents": videoz.price_cents()},
        "facez": {"kind": "free"},
        # A picture runs a dearer model than the daily allowance is priced for, so it
        # is never covered by it (gemini._bill, count_daily=False) — a fixed price.
        "imageconnectz": {"kind": "fixed", "cost_cents": standard},
    }


def _configured():
    gemini = bool(_key())
    return {
        "sentenceconnectz": gemini,
        "occ": _anthropic_configured(),
        "instrumentalconnectz": gemini,
        # Runs in the member's browser; there is no key to be missing.
        "mixconnectz": True,
        "videoconnectz": gemini,
        # Photos are stored, not generated.
        "facez": True,
        "imageconnectz": gemini,
    }


def _counts(user):
    return {
        "sentenceconnectz": SentenceWork.objects.filter(user=user).count(),
        "occ": OccOutput.objects.filter(user=user).count(),
        "instrumentalconnectz": InstrumentalWork.objects.filter(user=user).count(),
        "mixconnectz": MasterWork.objects.filter(user=user).count(),
        "videoconnectz": VideoWork.objects.filter(user=user).count(),
        "facez": Face.objects.filter(owner=user).count(),
        "imageconnectz": GeneratedImage.objects.filter(user=user).count(),
    }


def _row(app, pk, label, created_at):
    return (created_at, app, pk, label)


def recent_for(user, limit=RECENT_MAX):
    """The newest pieces across every app, newest first.

    Each app is sliced to `limit` in SQL (a piece outside its own app's newest
    twelve cannot be in the overall newest twelve), narrowed to the columns the
    label needs — a Sentence ConnectZ `text` can be a resume — and merged here.
    Five queries however much anyone has made.
    """
    rows = []
    for w in SentenceWork.objects.filter(user=user).only("id", "kind", "topic", "created_at")[:limit]:
        kind = SENTENCE_KINDS.get(w.kind, {}).get("label", w.kind.replace("_", " ").title())
        rows.append(_row("sentenceconnectz", w.id, f"{kind} · {_snippet(w.topic)}", w.created_at))
    for w in InstrumentalWork.objects.filter(user=user).only("id", "genre", "key", "bpm", "created_at")[:limit]:
        rows.append(_row("instrumentalconnectz", w.id,
                         f"{w.genre or 'Loop'} · {w.key} · {w.bpm} BPM", w.created_at))
    for w in MasterWork.objects.filter(user=user).only("id", "title", "created_at")[:limit]:
        rows.append(_row("mixconnectz", w.id, w.title, w.created_at))
    # Finished only: a pending render has nothing to open and a failed one was
    # handed back in full; neither belongs on a shelf of what somebody made.
    for w in (VideoWork.objects.filter(user=user, status=VideoWork.STATUS_DONE)
              .only("id", "kind", "prompt", "created_at")[:limit]):
        kind = videoz.KINDS.get(w.kind, {}).get("label", w.kind.title())
        rows.append(_row("videoconnectz", w.id, f"{kind} · {_snippet(w.prompt)}", w.created_at))
    for w in OccOutput.objects.filter(user=user).only("id", "title", "created_at")[:limit]:
        rows.append(_row("occ", w.id, _snippet(w.title) or "OCC work", w.created_at))
    # Ties (same microsecond is rare, same second is not on a bulk import) break
    # on the app then id so the shelf never reorders between two reads.
    rows.sort(reverse=True)
    return [{"app": app, "id": pk, "label": label, "created_at": at.isoformat(),
             "tab": app, "target": TARGETS[app]}
            for at, app, pk, label in rows[:limit]]


class IntelligenceHubView(APIView):
    """GET /api/economy/intelligencez/ — the apps, their price and state before
    any is opened, and the newest things the member has made in them."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        tier = membership_for(user).tier
        allowance, used, remaining = daily_prompt_state(user)
        prices, configured, counts = _prices(user, tier, remaining), _configured(), _counts(user)
        apps = []
        for key, label, emoji, icon, desc, built in APPS:
            apps.append({
                "key": key, "label": label, "emoji": emoji, "icon": icon, "desc": desc,
                "built": built,
                # A tab to go to only if there is one: a door to a screen that
                # cannot do the thing is worse than no door.
                "tab": key if built else "",
                "configured": configured[key],
                "in_app": key in IN_APP,
                "standalone": key in IN_APP,
                "price": prices[key],
                "count": counts[key],
            })
        return Response({
            "tier": tier,
            "apps": apps,
            "recent": recent_for(user),
            "daily": {"allowance": allowance, "used": used, "remaining": remaining},
        })
