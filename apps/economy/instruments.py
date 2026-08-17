"""What each InstrumentZ app is scored on.

A take is a take, but the dimensions are not transferable. Pitch / tone /
breath / range / agility describe a voice; scoring a guitar take on "breath"
would be a number with nothing behind it, which is the whole failure mode the
Boss Take was built to avoid. So every app declares its own.

`range_label` is None for anything that has no range to target — the picker is
hidden rather than asking a drummer which soprano they are.

The client renders from this, served by the coach's GET, so the labels can
never drift from the dimensions the model is actually asked to score.
"""

# Blueprint difficulty ladder — the same four rungs everywhere.
DIFFICULTIES = ["starter", "builder", "performer", "stageboss"]

# The blueprint's eight vocal range classes.
VOCAL_RANGES = [
    ("bass", "Bass 🧔‍♂️"), ("baritone", "Baritone 🎙️"), ("tenor", "Tenor 🎤"),
    ("countertenor", "Countertenor 🕊️"), ("contralto", "Contralto 🎻"),
    ("alto", "Alto 🎶"), ("mezzo-soprano", "Mezzo-Soprano 🌊"), ("soprano", "Soprano ☀️"),
]

# score key -> label shown to the member.
_VOCAL = {"pitch": "Pitch 🎯", "tone": "Tone 🌈", "breath": "Breath 🫁",
          "range": "Range 📏", "agility": "Agility 🌪️"}
_RAP = {"flow": "Flow 🌊", "timing": "Timing ⏱️", "breath": "Breath 🫁",
        "clarity": "Clarity 🔍", "delivery": "Delivery 🔥"}
_FRETTED = {"timing": "Timing ⏱️", "tone": "Tone 🌈", "technique": "Technique 🎯",
            "dynamics": "Dynamics 📊", "cleanliness": "Cleanliness ✨"}
_KEYS = {"timing": "Timing ⏱️", "tone": "Tone 🌈", "technique": "Technique 🎯",
         "dynamics": "Dynamics 📊", "voicing": "Voicing 🎹"}
_DRUMS = {"timing": "Timing ⏱️", "groove": "Groove 🕺", "dynamics": "Dynamics 📊",
          "consistency": "Consistency 📐", "fills": "Fills 🥁"}
_BOWED = {"intonation": "Intonation 🎯", "tone": "Tone 🌈", "bowing": "Bowing 🏹",
          "timing": "Timing ⏱️", "vibrato": "Vibrato 〰️"}

# What a single take genuinely cannot show, said out loud rather than scored.
_HISTORY_CAVEAT = ("Consistency, health and goal match come from your history, "
                   "not a single clip.")

INSTRUMENTS = {
    "singz": {
        "label": "SingZ", "performer": "vocalist", "coach": "vocal coach",
        "scores": _VOCAL, "range_label": "Target range", "ranges": VOCAL_RANGES,
        "caveat": "Pitch, tone, breath, range and agility are what one take can show. " + _HISTORY_CAVEAT,
    },
    "rapz": {
        "label": "RapZ", "performer": "rapper", "coach": "rap coach",
        "scores": _RAP, "range_label": None, "ranges": [],
        "caveat": "Flow, timing, breath, clarity and delivery are what one take can show. " + _HISTORY_CAVEAT,
    },
    "guitarz": {
        "label": "GuitarZ", "performer": "guitarist", "coach": "guitar coach",
        "scores": _FRETTED, "range_label": None, "ranges": [],
        "caveat": "Timing, tone, technique, dynamics and cleanliness are what one take can show. " + _HISTORY_CAVEAT,
    },
    "bassz": {
        "label": "BassZ", "performer": "bassist", "coach": "bass coach",
        "scores": {**_FRETTED, "cleanliness": "Note Length 📏"}, "range_label": None, "ranges": [],
        "caveat": "Timing, tone, technique, dynamics and note length are what one take can show. " + _HISTORY_CAVEAT,
    },
    "keyz": {
        "label": "KeyZ", "performer": "keyboardist", "coach": "keys coach",
        "scores": _KEYS, "range_label": None, "ranges": [],
        "caveat": "Timing, tone, technique, dynamics and voicing are what one take can show. " + _HISTORY_CAVEAT,
    },
    "drumz": {
        "label": "DrumZ", "performer": "drummer", "coach": "drum coach",
        "scores": _DRUMS, "range_label": None, "ranges": [],
        "caveat": "Timing, groove, dynamics, consistency and fills are what one take can show. " + _HISTORY_CAVEAT,
    },
    "violinz": {
        "label": "ViolinZ", "performer": "violinist", "coach": "strings coach",
        "scores": _BOWED, "range_label": None, "ranges": [],
        "caveat": "Intonation, tone, bowing, timing and vibrato are what one take can show. " + _HISTORY_CAVEAT,
    },
}

# Anything mounted without its own entry still gets a coach rather than a 404,
# scored on the dimensions that apply to any instrument.
DEFAULT = {
    "label": "InstrumentZ", "performer": "player", "coach": "coach",
    "scores": {"timing": "Timing ⏱️", "tone": "Tone 🌈", "technique": "Technique 🎯",
               "dynamics": "Dynamics 📊", "cleanliness": "Cleanliness ✨"},
    "range_label": None, "ranges": [],
    "caveat": "Timing, tone, technique, dynamics and cleanliness are what one take can show. " + _HISTORY_CAVEAT,
}


def profile_for_app(app_key):
    return INSTRUMENTS.get((app_key or "").lower(), DEFAULT)


def prompt_for(app_key, genre, target, difficulty):
    """The coaching prompt, in this instrument's own terms."""
    p = profile_for_app(app_key)
    keys = list(p["scores"])
    shape = ", ".join(f'"{k}": <1-10>' for k in keys)
    target_line = f"\n- {p['range_label']}: {target}" if p["range_label"] else ""
    return f"""You are the Music ConnectZ {p['coach']}. You are listening to one \
recorded take from a member training in {p['label']}.

Their context:
- Genre: {genre}{target_line}
- Difficulty: {difficulty}

Score the take and coach it. Write the way a good engineer talks to an artist \
in the room: direct, specific, second person, no hedging and no flattery. Name \
the actual moment something goes wrong rather than describing the category — \
"the third bar rushes" beats "work on timing". Never invent detail you cannot \
hear; if you couldn't hear it, don't score it.

VOICE — this is the Music ConnectZ voice, and it is not optional:
- Contractions everywhere. Everyday words. Say "way more", "actually", "hits \
different", "the pocket", "lock it in" where they land. Mild slang is fine \
when it's how somebody would actually say it.
- Lead each line with a fitting emoji and let a couple more land inside it \
naturally — 🎧 🔥 🎯 🫁 ⏱️ 💪 💯 🎤 ✨. Keep every one relevant to its line. \
Never a wall of them, never mid-word.
- Talk TO them, not about them. "Your words smear together" beats "the \
articulation is imprecise".
- End on where they actually stand — earned, not cheerful. A weak take gets \
"you've got the bones, tighten these two and it levels up fast"; a strong one \
gets told it's strong.

The emoji never soften a real problem, and never stand in for one. A 3/10 with \
a 🔥 on it is a lie that costs somebody a month of practising the wrong thing. \
Warmth in HOW you say it; the number and the fix stay honest.

Return ONLY valid JSON, no markdown fence, in exactly this shape:
{{
  "score": <overall 1-10 integer>,
  "scores": {{{shape}}},
  "verdict": "<one sentence in that voice, what this take actually is>",
  "strengths": ["<what genuinely worked, named specifically>", "..."],
  "fixes": ["<the moment it goes wrong, and the fix — the two that matter most, worst first>", "..."],
  "next_drill": "<one drill to run before the next take: what to do, how many reps>"
}}"""
