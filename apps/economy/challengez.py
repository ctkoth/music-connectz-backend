"""The weekly challenge — one prompt, the same for everybody, so scores compare.

Wordle spread because everyone played the same puzzle, which made a result
shareable AND comparable. "Beat my score" means little when two takes were made in
different genres at different difficulties; it means something when they answer the
same prompt. So each coach gets one challenge per ISO week — a genre, a tempo to
practise over and a difficulty — derived from the week alone, so there is no table to
maintain and every member (and a logged-out visitor) is shown the same one.

What counts: a take made that week in that genre at that difficulty. A shared card for
such a take carries the week (`payload["challenge"]`), and the top cards of the week
are the shared ones — a member's card only appears because THEY shared it.

It is a prompt, not a rule: nothing is blocked outside it, no score changes because
of it, and a take that doesn't match is scored exactly as any other.
"""
import hashlib
from datetime import timedelta

from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .instruments import INSTRUMENTS

# Genres every coach's picker offers (names must exist in the client's list; the
# screen applies one only if its picker has it). Rap leans rap; the rest are broad.
GENRES = {
    "rapz": ["Trap", "Boom Bap", "Drill", "Hip Hop", "Old School", "Cloud Rap"],
    "singz": ["R&B", "Pop", "Soul", "Rock", "Country", "Singer-Songwriter"],
}
DEFAULT_GENRES = ["Pop", "Rock", "Jazz", "Funk", "Blues", "Lo-Fi"]
BPMS = [70, 80, 90, 100, 110, 120]
DIFFICULTY = "builder"      # the middle rung: the same one for everyone, never the member's own


def week_id(when=None):
    """ISO year-week, e.g. "2026-W42"."""
    y, w, _ = (when or timezone.now()).isocalendar()
    return f"{y}-W{w:02d}"


def _pick(seq, app_key, week, salt):
    h = hashlib.sha256(f"{app_key}:{week}:{salt}".encode()).digest()
    return seq[h[0] % len(seq)]


def challenge_for(app_key, when=None):
    """This week's challenge for one coach: the same for everybody, from the week alone."""
    week = week_id(when)
    genre = _pick(GENRES.get(app_key, DEFAULT_GENRES), app_key, week, "genre")
    bpm = _pick(BPMS, app_key, week, "bpm")
    label = INSTRUMENTS.get(app_key, {}).get("label", app_key)
    return {"week": week, "app_key": app_key, "genre": genre, "bpm": bpm, "difficulty": DIFFICULTY,
            "title": f"{label} · {genre} · {bpm} BPM",
            "rule": ("One prompt for everybody this week, so scores compare. Make a take in this genre "
                     "at this difficulty and share its card — it carries the week. Nothing else changes: "
                     "a take outside it is scored exactly the same.")}


def challenge_tag(app_key, genre, difficulty, when=None):
    """The week id when a take answers that week's challenge, else ''."""
    c = challenge_for(app_key, when)
    ok = str(genre or "") == c["genre"] and str(difficulty or "") == c["difficulty"]
    return c["week"] if ok else ""


def top_cards(app_key, week, limit=10):
    """The week's best SHARED cards, one per member (their best), highest first."""
    from .models import ScoreShare
    rows = (ScoreShare.objects.filter(app_key=app_key, user__isnull=False, payload__challenge=week)
            .select_related("user"))
    best = {}
    for r in rows:
        exact = (r.payload or {}).get("score_exact")
        val = float(exact) if isinstance(exact, (int, float)) else float(r.score)
        if r.user_id not in best or val > best[r.user_id][0]:
            best[r.user_id] = (val, r)
    out = sorted(best.values(), key=lambda t: -t[0])[:limit]
    return [{"token": r.token, "username": r.user.username, "score": r.score,
             "shown": f"{val:.1f}" if val != int(val) else str(int(val)),
             "human": bool((r.payload or {}).get("human"))} for val, r in out]


class ChallengeView(APIView):
    """GET /api/economy/challenge/<app_key>/ — this week's prompt and its top shared
    cards. Public, like the cards themselves: it is the thing a stranger is shown."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, app_key):
        if app_key not in INSTRUMENTS:
            return Response({"detail": "No such coach."}, status=404)
        c = challenge_for(app_key)
        return Response({**c, "top": top_cards(app_key, c["week"])})
