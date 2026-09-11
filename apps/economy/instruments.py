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

# Rap styles. These lived in the mcz2 lab as a client-side array, which meant
# the style a member picked in the lab and the style the Boss Take coach knew
# about were two different lists that nobody was keeping level. Served from
# here for the same reason the score labels are: one list, no drift.
RAP_STYLES = [
    ("boom-bap", "Boom Bap 🥁"), ("trap", "Trap 🏚️"), ("drill", "Drill ⚔️"),
    ("cloud-rap", "Cloud Rap ☁️"), ("lyrical", "Lyrical 🧠"),
    ("storytelling", "Storytelling 📖"), ("freestyle", "Freestyle 🌀"),
    ("melodic", "Melodic 🎶"), ("double-time", "Double-Time ⚡"),
    ("old-school", "Old School 📻"), ("conscious", "Conscious ✊"),
    ("mumble", "Mumble 😶‍🌫️"),
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
        "style_label": None, "styles": [],
        "caveat": "Pitch, tone, breath, range and agility are what one take can show. " + _HISTORY_CAVEAT,
    },
    "rapz": {
        "label": "RapZ", "performer": "rapper", "coach": "rap coach",
        "scores": _RAP,
        # A rapper has a register, and the lab has always detected it — the
        # screenshot of a rap take reads "your range reads Bass, D2 to B4".
        # RapZ declared no ranges, so the one surface that scores the take
        # was the one surface that couldn't say what it heard.
        "range_label": "Your register", "ranges": VOCAL_RANGES,
        "style_label": "Rap style", "styles": RAP_STYLES,
        "caveat": "Flow, timing, breath, clarity and delivery are what one take can show. " + _HISTORY_CAVEAT,
    },
    "guitarz": {
        "label": "GuitarZ", "performer": "guitarist", "coach": "guitar coach",
        "scores": _FRETTED, "range_label": None, "ranges": [], "style_label": None, "styles": [],
        "caveat": "Timing, tone, technique, dynamics and cleanliness are what one take can show. " + _HISTORY_CAVEAT,
    },
    "bassz": {
        "label": "BassZ", "performer": "bassist", "coach": "bass coach",
        "scores": {**_FRETTED, "cleanliness": "Note Length 📏"}, "range_label": None, "ranges": [], "style_label": None, "styles": [],
        "caveat": "Timing, tone, technique, dynamics and note length are what one take can show. " + _HISTORY_CAVEAT,
    },
    "keyz": {
        "label": "KeyZ", "performer": "keyboardist", "coach": "keys coach",
        "scores": _KEYS, "range_label": None, "ranges": [], "style_label": None, "styles": [],
        "caveat": "Timing, tone, technique, dynamics and voicing are what one take can show. " + _HISTORY_CAVEAT,
    },
    "drumz": {
        "label": "DrumZ", "performer": "drummer", "coach": "drum coach",
        "scores": _DRUMS, "range_label": None, "ranges": [], "style_label": None, "styles": [],
        "caveat": "Timing, groove, dynamics, consistency and fills are what one take can show. " + _HISTORY_CAVEAT,
    },
    "violinz": {
        "label": "ViolinZ", "performer": "violinist", "coach": "strings coach",
        "scores": _BOWED, "range_label": None, "ranges": [], "style_label": None, "styles": [],
        "caveat": "Intonation, tone, bowing, timing and vibrato are what one take can show. " + _HISTORY_CAVEAT,
    },
}

# Anything mounted without its own entry still gets a coach rather than a 404,
# scored on the dimensions that apply to any instrument.
DEFAULT = {
    "label": "InstrumentZ", "performer": "player", "coach": "coach",
    "scores": {"timing": "Timing ⏱️", "tone": "Tone 🌈", "technique": "Technique 🎯",
               "dynamics": "Dynamics 📊", "cleanliness": "Cleanliness ✨"},
    "range_label": None, "ranges": [], "style_label": None, "styles": [],
    "caveat": "Timing, tone, technique, dynamics and cleanliness are what one take can show. " + _HISTORY_CAVEAT,
}


def profile_for_app(app_key):
    return INSTRUMENTS.get((app_key or "").lower(), DEFAULT)


def prompt_for(app_key, genre, target, difficulty, style=None):
    """The coaching prompt, in this instrument's own terms."""
    p = profile_for_app(app_key)
    keys = list(p["scores"])
    shape = ", ".join(f'"{k}": <1-10>' for k in keys)
    target_line = f"\n- {p['range_label']}: {target}" if p["range_label"] else ""
    style_line = (f"\n- {p['style_label']}: {style}"
                  if p.get("style_label") and style else "")
    # What the member is aiming AT, in the app's own vocabulary. A coach that
    # only says what is wrong leaves somebody to guess what right sounds like.
    aim = ("the register they picked" if p["range_label"] else "the part they are playing")
    style_ask = (f"""
- "style_fit": how this take sits against {p['style_label'].lower()} \
"{style}" specifically — what that style demands, and whether this take does it. \
Judge it against THAT style, not against rap in general."""
                 if p.get("style_label") and style else f"""
- "style_fit": how this take sits against {genre} specifically — what that \
genre asks for, and whether this take delivers it.""")
    range_ask = (f"""
- "range_profile": what their range actually reads as from this take — the \
lowest and highest usable notes you can hear, roughly how wide that is, and \
which of these it matches: {', '.join(l for _, l in p['ranges'])}. Say what \
that range is GOOD for. If the take is too short or too narrow to tell, say \
that instead of guessing — a range invented from four bars is a lie somebody \
will build a warm-up around."""
                 if p["ranges"] else "")
    # The FIELD only exists where there is a range to read. Asking a drum kit
    # to fill in a range profile is the "number with nothing behind it" this
    # module was written to prevent, and a model handed the key will always
    # find something to put in it.
    range_field = (
        '\n  "range_profile": "<what their range reads as and what it suits - or say the take was too short to tell>",'
        if p["ranges"] else "")

    # For pitch-based instruments, ask for weak note extraction for practice tool linking
    has_pitch = "pitch" in p["scores"] or "intonation" in p["scores"]
    weak_notes_section = ("""
If pitch accuracy below 70%, name 1-3 most problematic notes with what you heard:
- "weak_notes": [{"note": "E", "frequency": 330, "cents_off": -45}, ...]. \
Note is the letter + octave if hearable (E, F#, A3, etc). Frequency in Hz. \
Cents_off: negative = flat, positive = sharp. If pitch is 70+, return []."""
                          if has_pitch else "")
    weak_notes_field = (
        '\n  "weak_notes": [{"note": "...", "frequency": 330, "cents_off": 0}, ...],'
        if has_pitch else "")

    return f"""You are the Music ConnectZ {p['coach']}. You are listening to one \
recorded take from a member training in {p['label']}.

Their context:
- Genre: {genre}{target_line}{style_line}
- Difficulty: {difficulty}

Score the take and coach it. Write the way a good engineer talks to an artist \
in the room: direct, specific, second person, and encouraging. Name the actual \
moment something goes wrong rather than describing the category — "the third bar \
rushes" beats "work on timing". Never invent detail you cannot hear; if you \
couldn't hear it, don't score it.

SCORING RUBRIC — score like humans, not like a harsh teacher:
- A competent, clean take with solid fundamentals is 7-8/10. That's "this is good".
- A polished take with real artistry and few flaws is 8-9/10. That's "this is really good".
- A take that's genuinely exceptional or flawless in its class is 9-10/10.
- A take with some real problems but interesting bones is 5-6/10.
- A take that's struggling or barely holding together is 3-4/10.
- Only reserve 1-2/10 for takes that are fundamentally broken or unfinished.
- A take that got rated 10/10 by multiple human listeners is probably 8-10/10. \
Don't downgrade human consensus just because the AI has notes.
- Score relative to the difficulty level. A beginner's clean take at builder \
level should score higher than the same performance would at expert level.

VOICE — this is the Music ConnectZ voice, and it is not optional:
- Contractions everywhere. Everyday words. Say "way more", "actually", "hits \
different", "the pocket", "lock it in" where they land. Mild slang is fine \
when it's how somebody would actually say it.
- Lead each line with a fitting emoji and let a couple more land inside it \
naturally — 🎧 🔥 🎯 🫁 ⏱️ 💪 💯 🎤 ✨. Keep every one relevant to its line. \
Never a wall of them, never mid-word.
- Talk TO them, not about them. "Your words smear together" beats "the \
articulation is imprecise".
- End on where they actually stand — encouraging and honest. Show them what \
they've got and what's next. "You're locking the pocket here, tighten the back \
half and this jumps to a 9" gives them a real path.

The emoji never soften a real problem, and never stand in for one. But warmth \
in HOW you say it makes the difference between "keep going" and "give up". \
Score the performance they gave, encourage the performer.

Three things every answer carries, because a score with no destination is a \
number and not coaching:

- "now": what this take actually IS right now — their current qualities, in \
{p['label']}'s own terms, the honest read a stranger would give it.
- "goal": what they are aiming at from here, pitched at "{difficulty}" and at \
{aim}. Concrete enough to know when they have hit it.{range_ask}{style_ask}{weak_notes_section}

Return ONLY valid JSON, no markdown fence, in exactly this shape:
{{
  "score": <overall 1-10 integer>,
  "scores": {{{shape}}},
  "now": "<their current qualities, in that voice>",
  "goal": "<what they're aiming at next, and how they'll know they got there>",{range_field}
  "style_fit": "<how it sits against the style or genre they picked>",
  "verdict": "<one sentence in that voice, what this take actually is>",
  "strengths": ["<what genuinely worked, named specifically>", "..."],
  "fixes": ["<the moment it goes wrong, and the fix — the two that matter most, worst first>", "..."],
  "next_drill": "<one drill to run before the next take: what to do, how many reps>",{weak_notes_field}
  "weak_notes": []
}}"""
