"""WhyZ — why a member uses Music ConnectZ, said back to them with their own proof.

People stay for a reason they can SEE. A platform that never says what it did for
you is one nobody can explain to a friend, and a member who can't explain it won't
share it. So this reads the member's own history and states, per reason, what is
already true for them: a number of takes scored, a climb, a card that was opened,
🍥 earned, a streak.

The rule that keeps it honest is the substance rule's: a reason is only claimed
with proof when there is some. No proof means no number — the reason is shown with
the free way to find out, never "0 shares" or an invented figure. The reasons and
their wording are the server's; the screen renders them.
"""
from django.db.models import Count, Sum
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .instruments import INSTRUMENTS
from .models import Referral, ScoreShare, SentenceWork, TakeScore, Transaction

INSTRUMENT_KEYS = tuple(INSTRUMENTS)   # derived: a coach added there is counted here


def _best_climb(user):
    """The biggest measured improvement across the member's coaches, or None."""
    from .takescorez import coaching
    best = None
    for key in (r["app_key"] for r in TakeScore.objects.filter(user=user).values("app_key").distinct()):
        if key not in INSTRUMENT_KEYS:
            continue
        for w in coaching(user, key).get("wins", []):
            if best is None or w["change"] > best["change"]:
                best = {**w, "app_key": key}
    return best


def reasons_for(user):
    takes = TakeScore.objects.filter(user=user).count()
    climb = _best_climb(user) if takes >= 6 else None
    shares = ScoreShare.objects.filter(user=user)
    opened = shares.aggregate(n=Sum("views"))["n"] or 0
    joined = Referral.objects.filter(referrer=user).count()
    earned = (Transaction.objects.filter(user=user, resource="spinaz", amount__gt=0)
              .aggregate(n=Sum("amount"))["n"] or 0)
    wrote = SentenceWork.objects.filter(user=user).count()
    from apps.skillz.models import TrainingProfile
    breath = TrainingProfile.objects.filter(user=user, app_key="breathz").first()
    streak = breath.current_streak if breath else 0

    def row(key, headline, line, tab, target, proof, try_it):
        return {"key": key, "headline": headline, "line": line, "tab": tab, "target": target,
                "proof": proof or "", "try_it": try_it if not proof else ""}

    return [
        row("fix", "Know exactly what to fix",
            "Every take comes back with a score, why you got it, what worked, what to fix and what to practise.",
            "rapz", "rapz:progress",
            f"{takes} take{'s' if takes != 1 else ''} scored, each with the reasons." if takes else "",
            "Score your first take — the first free one needs no account."),
        row("climb", "See yourself get better",
            "Your history shows what moved — and you can share the climb.",
            "rapz", "rapz-coaching",
            (f"{climb['label']} went {climb['was']} → {climb['now']}." if climb else ""),
            "Six takes in a fortnight and your first measured climb shows up here."),
        row("reach", "Get heard",
            "A shared score is a link anyone can open; anyone who joins from it earns you the referral reward.",
            "postz", "composer",
            (f"Your shared cards were opened {opened} time{'s' if opened != 1 else ''}"
             + (f", and {joined} {'person' if joined == 1 else 'people'} joined from your link." if joined else "."))
            if opened or joined else "",
            "Share a score and this fills in with how many people opened it."),
        row("earn", "Earn from what you make",
            "Ratings, joins and referrals pay 🍥; releases and deals pay real royalties.",
            "logz", "",
            f"{earned:,} 🍥 earned so far." if earned else "",
            "Rate a track or invite a friend — the first 🍥 land in LogZ with the reason."),
        row("write", "Write what you can release",
            "Punchlines, hooks and verses you keep — and if you release one, you earn from it.",
            "sentenceconnectz", "sentencez-write",
            f"{wrote} piece{'s' if wrote != 1 else ''} written and kept." if wrote else "",
            "Pick a weak area on your coach screen and it writes five fixes."),
        row("train", "Train for free",
            "Breath, tuning and tempo practice that costs nothing and shows up in your next score.",
            "breathz", "breathz-pacer",
            f"{streak}-day streak." if streak >= 2 else "",
            "Two minutes of breathing before your next take."),
    ]


class WhyZView(APIView):
    """GET /api/economy/whyz/ — the reasons, each with the member's own proof when
    there is some and the free way to find out when there isn't."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = reasons_for(request.user)
        return Response({"reasons": rows, "proven": sum(1 for r in rows if r["proof"])})
