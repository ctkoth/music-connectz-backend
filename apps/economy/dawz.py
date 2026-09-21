"""DawZ — seven DAW knockoffs, none built, clicking one casts a vote.

The descriptions and the seven names already existed — written for
`src/mcz2/dawz.js`, the frontend's 2.2 reference app, which is explicitly
**not mounted** (its own CLAUDE.md says so). So this exact feature has been
sitting finished, in Corey's own voice, on a tab nothing routes to since
before this file existed. That is the LogicZ failure from the frontend's
CLAUDE.md one level up: a built thing nobody can reach reads as unbuilt.

This is the live version. `DAWS` is the one list — the frontend renders it,
never retypes it, the same rule every tier number and instrument profile in
this codebase already follows. `DawVote` follows `MoneyBattleVote` exactly:
one row per member per DAW, a toggle rather than a counter a member cannot
take back, because "cast a vote" has to mean the same thing pressed twice.

Voting is free and earns nothing — the cost/gain rule has nothing to say
about a click that moves no resource, and inventing a reward for it would be
paying for attention while calling it demand. The substance rule's test still
applies to the NUMBER, not the button: `votes` is a straight `.count()`, no
weighting, no multiplier for tier or reach. A StatZ vote and a Free vote are
the same one vote, because "which DAW do people want" is a headcount question
and answering it with anything else is the AI-craft-estimate failure with a
different name on it.
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

DAWS = [
    {
        "id": "fruity_mobius",
        "name": "Fruity Möbius",
        "emoji": "🍑",
        "icon": "fruity_mobius.png",
        "knockoff": "FL Studio",
        "desc": ("Pattern-first beat machine — you loop it, chain it, and it "
                 "never stops looping back on itself, that's the Möbius. Step "
                 "sequencer up top, piano roll that actually feels good, "
                 "lifetime free updates energy. Built for producers who make "
                 "the beat before the song. Our knockoff of FL Studio."),
    },
    {
        "id": "arsenal",
        "name": "Arsenal",
        "emoji": "⚔️",
        "icon": "arsenal.png",
        "knockoff": "Pro Tools",
        "desc": ("The industry-grade weapon. Deep multitrack recording, "
                 "surgical audio editing, mixing that holds up in a real "
                 "studio. This is the one engineers reach for when the "
                 "session has to be bulletproof. Our knockoff of Pro Tools."),
    },
    {
        "id": "witchcraft",
        "name": "Witchcraft",
        "emoji": "🔮",
        "icon": "witchcraft.png",
        "knockoff": "Acoustica Mixcraft",
        "desc": ("Approachable magic — loops, live performance, and video "
                 "scoring without the steep climb. The one you hand a "
                 "beginner that still has real power under the hood. Our "
                 "knockoff of Acoustica Mixcraft."),
    },
    {
        "id": "trump_toupee",
        "name": "Trump Toupee",
        "emoji": "🤵🏼‍♂️",
        "icon": "trump_toupee.png",
        "knockoff": "Bitwig",
        "desc": ("Modular and modern — a clip launcher for jamming plus a "
                 "modulation system you can wire into anything. Made for "
                 "sound designers and live sets. Flashy on top, seriously "
                 "deep underneath. Our knockoff of Bitwig."),
    },
    {
        "id": "azrael",
        "name": "Azrael",
        "emoji": "☠️",
        "icon": "azrael.png",
        "knockoff": "Reaper",
        "desc": ("Lightweight, endlessly customizable, runs on anything. "
                 "Skin it, script it, bend it to your workflow. The "
                 "power-user's DAW that respects your CPU and your wallet. "
                 "Our knockoff of Reaper."),
    },
    {
        "id": "intuition",
        "name": "Intuition",
        "emoji": "🤔",
        "icon": "intuition.png",
        "knockoff": "Logic Pro",
        "desc": ("Polished, all-in-one songwriting powerhouse — stacked "
                 "instruments, smart tempo, a library that makes a full "
                 "arrangement feel effortless. It just knows what you're "
                 "reaching for. Our knockoff of Logic Pro."),
    },
    {
        "id": "formulawon",
        "name": "FormulaWon",
        "emoji": "🚦",
        "icon": "dawz_formulawon.png",
        "knockoff": "GarageBand",
        "desc": ("Zero to a track in minutes. Smart drummer, tap-in loops, "
                 "dead-simple recording — the on-ramp that gets a beginner "
                 "their first W. Our knockoff of GarageBand."),
    },
]

DAW_IDS = {d["id"] for d in DAWS}


class DawVote(models.Model):
    """One member, one DAW, one vote — a toggle, not a counter, the same
    shape `MoneyBattleVote` already is for the same reason: casting a vote
    twice has to mean the same thing as casting it once."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="daw_votes")
    daw_id = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "daw_id")


def daw_catalog(user):
    """Every DAW, its vote count, and whether THIS member has voted for it —
    built off one query for the counts and one for this member's own votes,
    never per-card."""
    counts = {}
    for row in (DawVote.objects.values("daw_id")
                .annotate(n=models.Count("id"))):
        counts[row["daw_id"]] = row["n"]
    mine = set(DawVote.objects.filter(user=user).values_list("daw_id", flat=True))
    return [
        {**d, "built": False, "votes": counts.get(d["id"], 0),
         "my_vote": d["id"] in mine}
        for d in DAWS
    ]


class DawZView(APIView):
    """GET the catalog with tallies; POST {daw_id} toggles my vote.

    None of the seven are built. Clicking a card votes for which gets built
    next — the same "count demand, don't fake a feature" answer
    `MoneyBattleVote` already gives for real-money battles, applied here
    because a DAW is a real build, not a legal question, but the shape of
    "nothing is live yet, so a click means a vote" is identical.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"daws": daw_catalog(request.user)})

    def post(self, request):
        daw_id = str(request.data.get("daw_id") or "").strip()
        if daw_id not in DAW_IDS:
            return Response({"detail": "not a real DAW id"}, status=400)
        existing = DawVote.objects.filter(user=request.user, daw_id=daw_id).first()
        if existing:
            existing.delete()
        else:
            DawVote.objects.create(user=request.user, daw_id=daw_id)
        return Response({"daws": daw_catalog(request.user)})
