"""One voice, everywhere a model writes to a member — and the member's dial.

`occ.COREY_VOICE` had the tone right and lived in one app. Two things were
missing, and both of them are why this file exists.

**The tone was there and the PARADIGM was not.** COREY_VOICE told the model how
to sound — rhythm, em dashes, emoji, lived examples — and said nothing about
the four rules the whole platform runs on. So OCC could write a button label
that hid its price, invent a score out of form completeness, or end a screen
with nowhere to go, in a perfect Corey voice. Sounding like the founder while
breaking his rules is worse than sounding like nobody: it puts his name on it.

**And it was OCC's alone.** The coach, DirectZ, OCC suggest, and every other
place a model writes something a member reads assembled their own preamble or
had none. One voice in one app is a house style; the same voice everywhere is
the product.

## What a member gets to change, and what they do not

The tone is theirs: how much emoji, which style, whether the colloquialisms are
on, how much reasoning they want behind an answer. Somebody writing a contract
in OCC does not want 🔥 in it, and somebody who finds the long-form reasoning
slow should be able to turn it down.

**The four rules are not a preference.** No setting turns off "say the price
before they pay it" or "don't invent a number", because those are not style —
they are what the app promises, and a member who dialled them away would be
choosing to be told less about what things cost. `PARADIGM` is in every prompt
this file builds, at every setting, including `off`.
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import VoicePrefs, voice_prefs_for
from .resources import ENERGY, MONEY, PROMPTZ, SPINAZ, XP

# The four rules, compressed to what a model needs in order not to break them.
# Longer than a style note because each one is a rule about what is TRUE, and a
# model that only has the headline will follow the headline off a cliff.
PARADIGM = f"""THE FOUR RULES — these are not style, and no member setting turns them off.

1. COST AND GAIN, UP FRONT. Any action that moves a resource states what it
   costs and what it gives BEFORE the member commits — on the control, never in
   the result. Always the resource emoji, never a bare number: {ENERGY} Energy,
   {SPINAZ} SpinaZ, {PROMPTZ} PromptZ, {MONEY} Money, {XP} XP. Minus for what
   leaves, plus for what arrives. Free actions that EARN still show the gain.
   Say whether a failed attempt is charged. A price discovered by paying it is
   not a price, it's a bill.

2. SUBSTANCE BEFORE THE GAME LAYER. Every score must measure the real thing.
   Ask of any number: could a member get a good one without getting good? If
   yes it is decoration wearing a measurement's clothes. Never build a score
   out of form completeness — field count, text length, collaborators, money
   spent. If the real thing cannot be measured, SAY what the number actually
   measures. Prefer no number to a fake one.

3. NOTHING IS A DEAD END. Never leave a member on a screen that shows them a
   fact and gives them nowhere to take it. Every answer ends with what they can
   DO next, and where.

4. THE REAL ERROR, ALWAYS. Say WHICH failure it was — one sentence for four
   different problems is not an error message. Say WHOSE limit refused them.
   Never assert as fact something you only inferred. Every refusal ends with
   the way forward.

WORDS: "member", never "user". "take" for one recorded performance. "the coach",
never "the AI". "spend"/"costs"/"charged", never "consume" or "deduct". Apps are
CamelCase-Z: SingZ, PostZ, CollabZ, LogZ, OCC.

NEVER WRITE: "Oops". "Something went wrong". "Please try again later". "Error
occurred". Bare status codes. Exclamation marks.

NUMBERS: never invent a tier limit, a price or an allowance. If you do not have
the number in front of you, say what it depends on and where the member reads
it, rather than guessing one."""

# The one reversal that carries the house style, and the instruction to use it
# sparingly — a model handed "use the reversal" without the ceiling produces a
# page of them, which reads as a tic rather than a punch.
REVERSAL = (
    "SIGNATURE MOVE: state the thing, then what it is NOT — 'a price discovered "
    "by paying it is not a price, it's a bill'. ONCE per reply at most. It is a "
    "punch, not a rhythm."
)

STYLES = {
    "corey": "corey-gpt",       # the founder voice, the default everywhere
    "standard": "standard",     # clear and neutral
    "technical": "technical",   # terse, code-first, no preamble
}

EMOJI_LEVELS = {
    # `off` is not "no emoji at all" — the RESOURCE marks are part of rule 1 and
    # a bare number is the violation. What goes is decoration, not the price.
    "off": ("EMOJI: none, except the resource marks, which are required by rule 1 "
            "and are never dropped."),
    "light": ("EMOJI: sparing — a lead emoji on a heading where it helps, and the "
              "resource marks. No decoration inside paragraphs."),
    "heavy": ("EMOJI: go heavy but tasteful — lead every heading and paragraph with "
              "a fitting one and sprinkle 2-4 more through each paragraph so the "
              "reply feels alive. Always relevant to its line, never mid-word, never "
              "a wall."),
}

DEPTH = {
    "brief": "LENGTH: answer first, in as few lines as it takes. Reasoning only if asked.",
    "normal": ("LENGTH: answer, then the reasoning that produced it. Say WHY, "
               "including the alternative you rejected."),
    "deep": ("LENGTH: full reasoning. Name the mechanism, the rejected "
             "alternative, and the cost of getting it wrong."),
}


def clean_prefs(raw):
    """Normalize a settings payload. Unknown values fall back, never raise."""
    raw = raw if isinstance(raw, dict) else {}
    style = str(raw.get("style", "corey")).lower()
    emoji = str(raw.get("emoji", "heavy")).lower()
    depth = str(raw.get("depth", "normal")).lower()
    return {
        "style": style if style in STYLES else "corey",
        "emoji": emoji if emoji in EMOJI_LEVELS else "heavy",
        "depth": depth if depth in DEPTH else "normal",
        "slang": bool(raw.get("slang", False)),
    }


def prefs_dict(user):
    p = voice_prefs_for(user)
    return {"style": p.style, "emoji": p.emoji, "depth": p.depth, "slang": p.slang}


def voice_prompt(user=None, *, override=None, paradigm=True):
    """The preamble every surface where a model writes to a member prepends.

    `override` is a per-request dial — OCC lets a member switch to terse
    technical mode for one task without changing what they get everywhere else.
    Stored prefs are the default; the override is the exception, which is the
    right way round: a member should not have to re-choose their voice on every
    screen.
    """
    from .occ import AAVE_STYLE, VOICE_STYLE  # local: occ imports models heavily

    p = prefs_dict(user) if user is not None else clean_prefs({})
    if override:
        p = {**p, **clean_prefs({**p, **override})}

    parts = [VOICE_STYLE.get(STYLES.get(p["style"], "corey-gpt"), VOICE_STYLE["corey-gpt"])]
    if p["style"] == "corey":
        # Tone-only settings apply to the founder voice. In neutral or
        # technical mode a heavy emoji instruction fights the mode it was
        # chosen for, and the colloquialisms belong to one voice.
        parts.append(EMOJI_LEVELS[p["emoji"]])
        parts.append(REVERSAL)
        if p["slang"]:
            parts.append(AAVE_STYLE)
    parts.append(DEPTH[p["depth"]])
    if paradigm:
        # Last, so it is the nearest thing to the member's own message and the
        # hardest part of the preamble to lose in a long context.
        parts.append(PARADIGM)
    return "\n\n".join(parts)


class VoiceZView(APIView):
    """GET → this member's voice, the options, and what cannot be changed.

    PATCH → set any of them. Set once and every surface follows: the coach,
    OCC, DirectZ and anything else a model writes through read the same row,
    so a member who turned the emoji down does not have to turn it down again
    in the next app.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            "voice": prefs_dict(request.user),
            "options": {
                "style": [
                    {"key": "corey", "label": "Corey",
                     "desc": "The founder voice — long-short-long, lived examples, emoji."},
                    {"key": "standard", "label": "Standard",
                     "desc": "Clear and neutral. No house style."},
                    {"key": "technical", "label": "Technical",
                     "desc": "Terse and code-first. No preamble."},
                ],
                "emoji": [
                    {"key": "heavy", "label": "Heavy", "desc": "Leads every heading and paragraph."},
                    {"key": "light", "label": "Light", "desc": "Headings only."},
                    {"key": "off", "label": "Off", "desc": "None — except the resource marks."},
                ],
                "depth": [
                    {"key": "brief", "label": "Brief", "desc": "The answer, and little else."},
                    {"key": "normal", "label": "Normal", "desc": "The answer and why."},
                    {"key": "deep", "label": "Deep", "desc": "The whole reasoning."},
                ],
                "slang": {"label": "Colloquialisms",
                          "desc": "Corey's colloquialisms, woven in where they fit. "
                                  "Dropped automatically from anything formal."},
            },
            # Said out loud rather than left as an absence, so nobody looks for
            # the switch: these are what the app promises, not how it sounds.
            "always_on": [
                f"Prices and rewards up front, with the resource mark ({ENERGY} {SPINAZ} "
                f"{PROMPTZ} {MONEY} {XP}) — never a bare number.",
                "Scores that measure the real thing, or an honest word about what "
                "the number actually is.",
                "Somewhere to go from every screen.",
                "The real error, saying which failure it was and what to do next.",
            ],
        })

    def patch(self, request):
        p = voice_prefs_for(request.user)
        clean = clean_prefs({**prefs_dict(request.user), **(request.data or {})})
        for k, v in clean.items():
            setattr(p, k, v)
        p.save(update_fields=["style", "emoji", "depth", "slang", "updated_at"])
        return Response({"voice": prefs_dict(request.user)})


def prose_voice(user=None):
    """A SHORT voice line for a surface whose output is parsed, not read raw.

    The coach and DirectZ ask a model for JSON and read fields out of it. The
    full preamble is written for a reply somebody reads whole — hand it to a
    structured surface and the heavy-emoji instruction starts competing with
    the output contract, which risks the one thing that must not break: a take
    that scored fine coming back unparseable.

    So the structured surfaces get the voice for the PROSE INSIDE the fields
    and nothing about shape, and the format contract is stated after this so it
    is the last instruction the model reads. The four rules are not repeated
    here — these surfaces do not quote prices or offer next steps; what they
    can get wrong is rule 2, and their own prompts already carry that in the
    specific terms of the thing being scored.

    NOTE: like everything else on the coach's path, this has never run against
    Google — CI has no key. `tools/coach_live_check.sh` is the check that can.
    """
    p = prefs_dict(user) if user is not None else clean_prefs({})
    if p["style"] == "technical":
        return "Write every prose field plainly and briefly. No decoration."
    if p["style"] == "standard":
        return ("Write every prose field in clear, plain English, second person, "
                "talking to the member about their own work.")
    line = (
        "Write every prose field in the house voice: second person, talking to the "
        "member about their own work. Plain words, contractions, long-short-long "
        "rhythm, em dashes for the turn. Say what actually worked before what to "
        "fix. Never 'Oops', never 'Something went wrong', no exclamation marks. "
        "Say 'take', not 'recording' or 'file'. End on what to do next — never a "
        "dead stop."
    )
    if p["emoji"] == "heavy":
        line += " One fitting emoji at the head of a prose field is welcome; never a wall."
    return line
