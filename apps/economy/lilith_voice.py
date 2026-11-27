"""Lilith's voice: how she talks to a member when she makes a suggestion.

Everyone hears her as she is by default: the INFJ voice, the same letter styles VoiceZ gives her character
(`voicez.LETTER_STYLE`: inward and says less, reaches for the bigger picture, says why it matters to you, then
makes one clear call). Choosing another way of talking is StatZ's, the way every customisation is: a tier decides
who may choose, never whether a member hears her. A StatZ member who chose a voice and then lapsed keeps the
choice; it rests until StatZ is back, and the default is what they hear meanwhile.

Every line states the record the suggestion stands on first (`why`, from `lilith_suggest`), so a voice changes how
a fact is said and never what it is. No model is called: a voice costs nothing per message, so the lines are
written here, not generated.
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

DEFAULT = "lilith"

# style → what it is, the line it adds for each kind of suggestion (`*` for every kind), and its closing call.
STYLES = {
    "lilith": {
        "label": "Lilith (the default)",
        "about": "Quiet and sure of herself. Says less and means it, reaches for the bigger picture, says why it "
                 "matters to you, then makes one clear call.",
        "feel": {
            "persona": "Who you say you are is where the work starts to show.",
            "instrument": "It's the thread you keep returning to. Build on it.",
            "habit": "You're already doing it, and a habit is just that, kept.",
            "gap": "It's the quiet part of the work that makes the rest land.",
            "activity": "A step from what you just did is easier than starting over.",
            "profile": "Small details like this are what people trust first.",
            "start": "Every practice begins with one small place.",
        },
        "call": "I'd start with this one. Want it on your board?",
    },
    "plain": {
        "label": "Plain",
        "about": "Direct and practical. The record, then the one thing to do. No feelings, no build-up.",
        "feel": {},
        "call": "Do this one first. Add it?",
    },
    "warm": {
        "label": "Warm",
        "about": "Talks it through with you. Says 'we', brings some energy, and asks you a question back.",
        "feel": {"*": "This is a good one to do with someone."},
        "call": "Shall we start with this one? Want to try it together?",
    },
    "quiet": {
        "label": "Quiet",
        "about": "Says as little as it can: the record, and an open door.",
        "feel": {},
        "call": "Whenever you're ready.",
    },
}

# The sentence a voice is shown with on the picker. It is an example, labelled as one on the screen.
EXAMPLE_WHY = "You've sent four takes this month and posted none."


# Some suggestions close on a sentence of their own, in each voice: a routine that keeps a member on track says so
# in the way each voice would. Keyed by the suggestion's key, then by the voice.
CALL_FOR = {
    "weak_spot": {
        "lilith": "Want a weekly routine for it, so we can keep on track?",
        "plain": "Make it a weekly routine. Add it?",
        "warm": "Shall we make it a weekly routine and keep on track together?",
        "quiet": "A weekly routine, if you want one.",
    },
}


def say(style, kind, why, key=""):
    """The conversational line for one suggestion: the record first, what it means to the member, then one call.
    `kind` is the suggestion's `because` (persona, instrument, habit, gap, activity, profile, start); `key` is the
    suggestion's own key, so a routine can close on a sentence of its own."""
    s = STYLES.get(style) or STYLES[DEFAULT]
    feel = s["feel"].get(kind) or s["feel"].get("*") or ""
    call = CALL_FOR.get(key, {}).get(style, s["call"]) if key else s["call"]
    return " ".join(part for part in (str(why or "").strip(), feel, call) if part)


def style_for(user):
    """The way she talks to this member now. Only a StatZ member can have another; anyone else hears the default."""
    from .models import LilithVoice
    from .statz_trial import has_statz
    if not has_statz(user):
        return DEFAULT
    row = LilithVoice.objects.filter(user=user).first()
    return row.style if row and row.style in STYLES else DEFAULT


def state(user):
    """The voices on offer, and which one she uses with this member. The lock sentence is the server's."""
    from .models import LilithVoice
    from .statz_trial import has_statz
    ok = has_statz(user)
    row = LilithVoice.objects.filter(user=user).first()
    return {
        "allowed": ok,
        "style": style_for(user),
        "chosen": row.style if row and row.style in STYLES else DEFAULT,
        "styles": [{"key": k, "label": v["label"], "about": v["about"],
                    "sample": say(k, "gap", EXAMPLE_WHY)} for k, v in STYLES.items()],
        "locked": "" if ok else "Choosing Lilith's voice is a StatZ feature. Everyone hears her as she is by default.",
    }


class LilithVoiceView(APIView):
    """GET /api/economy/lilith/voice/ — the voices on offer, and the one she uses with this member.
    POST {style} — choose one. Only StatZ may choose; anyone else is told why, and nothing changes."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(state(request.user))

    def post(self, request):
        from .models import LilithVoice
        from .statz_trial import has_statz
        if not has_statz(request.user):
            return Response({"detail": state(request.user)["locked"], **state(request.user)},
                            status=status.HTTP_403_FORBIDDEN)
        style = str((request.data or {}).get("style") or "")
        if style not in STYLES:
            return Response({"detail": "Pick one of the four voices."}, status=status.HTTP_400_BAD_REQUEST)
        LilithVoice.objects.update_or_create(user=request.user, defaults={"style": style})
        return Response(state(request.user))
