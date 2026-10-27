"""What a member values most in the piece they are about to make — IntelligenceZ's dials.

Corey: when users make media in IntelligenceZ they rate how much value they place in each
variable, and that affects the production. This is the one list of variables per medium and the
one place a rating becomes words for the model.

* **A closed list.** Each medium has a fixed set of variables with a one-line meaning. The member
  sets a number 0-5 on any of them; nothing they TYPE reaches the prompt, only a whitelisted key,
  a clamped integer and the server's own label. So a priority cannot carry an instruction.
* **Unset is "no preference", not zero.** 0 means "I don't care about this here" (spend nothing on
  it, never make it worse on purpose); a variable they leave alone is simply not mentioned.
* **It steers emphasis and nothing else.** It is appended after the brief, says so, and does not
  touch price, rating, royalty or what gets scored. A dial is a preference, never a measurement.
* **Mainstream appeal is a dial like the rest.** It is reach, not quality, and turning it up is a
  choice about the audience — never a better piece.
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

MIN, MAX = 0, 5
SCALE = {"min": MIN, "max": MAX,
         "labels": {"0": "Don't care", "1": "A little", "3": "Matters", "5": "Matters most"}}

# medium -> {key: (label, what turning it up means)}
VARIABLES = {
    "writing": {
        "rhyme": ("Rhyme scheme", "dense, interesting rhymes - internal and multisyllabic, not one slot every bar"),
        "wordplay": ("Wordplay", "puns, double meanings and switch-ups"),
        "imagery": ("Imagery", "concrete, specific lines the listener can see, hear or touch"),
        "metaphor": ("Metaphors", "comparisons that carry meaning, fresh and consistent"),
        "wit": ("Wit", "cleverness of the turn - the line that makes you grin or rewind"),
        "depth": ("Depth", "specific, true moments instead of general feelings"),
        "lyric_clarity": ("Clarity", "the meaning is easy to follow from the words alone"),
        "story": ("Story & structure", "a clear arc and sections that build"),
        "mainstream": ("Mainstream appeal", "broad, familiar, easy to take in on a first hearing"),
    },
    "instrumental": {
        "groove": ("Groove", "the pocket and feel of the rhythm"),
        "melody": ("Melody", "a memorable line you could hum"),
        "harmony": ("Harmony", "richer, more interesting chords"),
        "space": ("Space & simplicity", "fewer notes, room to breathe"),
        "energy": ("Energy", "drive and intensity"),
        "sound_imagery": ("Sound imagery", "a scene or mood you can picture"),
        "mainstream": ("Mainstream appeal", "familiar, accessible, easy to enjoy first time"),
    },
    "video": {
        "imagery": ("Imagery", "striking, specific images and symbols that earn their place"),
        "story": ("Story", "a clear beginning, middle and end"),
        "pacing": ("Pacing", "rhythm of the cuts and the shots"),
        "lighting": ("Light & colour", "a deliberate look"),
        "mainstream": ("Mainstream appeal", "broad, familiar, easy to take in"),
    },
    "image": {
        "imagery": ("Imagery", "specific, memorable things in the picture"),
        "mood": ("Mood", "a strong, consistent feeling"),
        "detail": ("Detail", "richness and texture"),
        "simplicity": ("Simplicity", "a clean, uncluttered picture"),
        "mainstream": ("Mainstream appeal", "broad, familiar, easy to take in"),
    },
}


def clean(medium, raw):
    """{key: 0-5} for the keys this medium has, in the list's order. Junk is dropped, never an error."""
    table = VARIABLES.get(medium) or {}
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key in table:
        if key not in raw:
            continue
        try:
            v = int(float(raw[key]))
        except (TypeError, ValueError):
            continue
        out[key] = max(MIN, min(MAX, v))
    return out


def clause(medium, raw):
    """The words that go on the end of a prompt, or "" when the member set nothing."""
    weights = clean(medium, raw)
    if not weights:
        return ""
    table = VARIABLES[medium]
    lines = [f"- {table[k][0]}: {v} ({table[k][1]})" for k, v in
             sorted(weights.items(), key=lambda kv: (-kv[1], list(table).index(kv[0])))]
    return (
        "\n\nWhat the author values in THIS piece (0 = they do not care, 5 = matters most; anything "
        "not listed they have no preference about):\n" + "\n".join(lines) +
        "\nSpend your effort in that order. Where two of these pull against each other, favour the "
        "higher number, and do not give up a 4-5 to improve a 1-2. A 0 means spend no effort there, "
        "but never make it worse on purpose. These only steer emphasis: keep to the brief and every "
        "other instruction above.")


class PrioritiesView(APIView):
    """GET /api/economy/priorities/ — the variables per medium and the scale. Read, never retyped."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"scale": SCALE, "media": {
            m: [{"key": k, "label": lab, "means": means} for k, (lab, means) in t.items()]
            for m, t in VARIABLES.items()}})
