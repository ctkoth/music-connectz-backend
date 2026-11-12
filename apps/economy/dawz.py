"""DawZ — eight DAW knockoffs on one engine; a built one opens, an unbuilt one takes a vote.

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
        "emoji": "💭",
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
    {
        "id": "studio_dragon",
        "name": "Studio Dragon",
        "emoji": "🐉",
        "icon": "",
        "knockoff": "Studio One",
        "desc": ("One window, drag-and-drop everything — drop a sound on a "
                 "track, an effect on a channel, a song section where it "
                 "goes. Songwriting and mastering live in the same room, so "
                 "the record you build is the record you finish. Our "
                 "knockoff of Studio One."),
    },
]

DAW_IDS = {d["id"] for d in DAWS}

# The DAWs that exist, and the tab each one opens. All of them run on ONE engine in the frontend
# (src/daw/): a DAW here is a workflow — which windows, which edit modes, which way a track is
# laid out — not a second codebase. A DAW joins this map when its workflow ships, never before:
# a "built" flag on something that isn't is the LogicZ failure in reverse.
BUILT = {"arsenal": "arsenal", "fruity_mobius": "fruitymobius"}

# Said beside every DAW, because "VST" is the word people arrive with and the answer is not a
# yes. A VST is a native desktop program; no web page can load one, and the Android app is a web
# page. What a browser can run is a plugin written for the web (Web Audio Modules), and third-party
# plugin code would run with the member's own sign-in — so only the built-in effects ship now.
PLUGIN_NOTE = ("Effects are built in: EQ, compressor, delay, reverb, filter and gain, on every "
               "track, free. VST plugins can't run in a browser or the phone app — they are "
               "desktop programs. Loading outside plugins is planned for the Windows app, where "
               "they can run safely.")


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
        {**d, "built": d["id"] in BUILT, "tab": BUILT.get(d["id"], ""),
         "votes": counts.get(d["id"], 0), "my_vote": d["id"] in mine}
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
        return Response({"daws": daw_catalog(request.user), "plugin_note": PLUGIN_NOTE})

    def post(self, request):
        daw_id = str(request.data.get("daw_id") or "").strip()
        if daw_id not in DAW_IDS:
            return Response({"detail": "not a real DAW id"}, status=400)
        existing = DawVote.objects.filter(user=request.user, daw_id=daw_id).first()
        if existing:
            existing.delete()
        else:
            DawVote.objects.create(user=request.user, daw_id=daw_id)
        return Response({"daws": daw_catalog(request.user), "plugin_note": PLUGIN_NOTE})
