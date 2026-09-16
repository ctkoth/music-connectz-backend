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
#
# It used to end there, which made it an honest refusal with nothing behind it:
# no score was kept, so the history it deferred to did not exist. `TakeScore`
# and `takescorez` are that history now, and the three deferred dimensions are
# served from it at `/api/<key>/progress/` — so the caveat says where they went
# rather than only that they are not here.
_HISTORY_CAVEAT = ("Consistency, health and goal match come from your history, "
                   "not a single clip — they're on your progress screen.")

INSTRUMENTS = {
    "singz": {
        "label": "SingZ", "performer": "vocalist", "coach": "vocal coach",
        # There are words in a vocal take, so the writing CAN be judged — but
        # only when the member asks. A singer working on range does not want
        # their lyrics marked, and scoring somebody on something they did not
        # submit for scoring is how a coach stops being trusted.
        "lyrics": True,
        "scores": _VOCAL, "range_label": "Target range", "ranges": VOCAL_RANGES,
        "style_label": None, "styles": [],
        "caveat": "Pitch, tone, breath, range and agility are what one take can show. " + _HISTORY_CAVEAT,
    },
    "rapz": {
        "label": "RapZ", "performer": "rapper", "coach": "rap coach",
        # The blueprint lists "Writing Score 📝 — rhyme density, structure,
        # originality, punchlines, storytelling depending on style" as one of
        # RapZ's core scores, and it was never implemented. This is it, opt-in.
        "lyrics": True,
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


# The optional sixth dimension. Kept OUT of every profile's `scores` and added
# only when asked for, because the five in a profile are the promise the app
# makes about what one take shows — a member who opened SingZ to work on breath
# should not find their writing marked.
# The blueprint's Writing score, broken into the things it actually names:
# "rhyme density, structure, originality, punchlines, or storytelling —
# DEPENDING ON STYLE". One number called "Writing" would have averaged five
# different judgements into something nobody can act on; "your writing is a 6"
# tells a member nothing about what to go and practise.
#
# Every one of these is answerable from the words themselves, which is the test
# that kept the list to five. What was left out and why:
#
#   * "Originality" as such — nobody can judge it without knowing everything
#     ever written, and a model asked for it will confidently invent an
#     opinion. `freshness` asks the answerable half instead: how much of this
#     is stock phrasing you have heard a hundred times. Clichés are
#     recognisable; novelty is not.
#   * "Flow" and "cadence" — already scored, as performance. How the words SIT
#     is delivery; what the words ARE is writing, and scoring the same thing
#     twice would let one weakness sink two numbers.
#   * Subject matter, opinions, swearing. Not craft. See the prompt.
LYRIC_SCORE = {
    "rhyme": "Rhyme Scheme 🔗",
    "punchlines": "Punchlines 🥊",
    "story": "Story & Structure 📖",
    "imagery": "Imagery 🖼️",
    "freshness": "Freshness 💡",
}

# Style Match 🎭 — the blueprint lists it among RapZ's CORE scores and it has
# only ever been served as prose (`style_fit`), so nothing could trend it, no
# drill could be recommended from it, and the history could not say whether
# somebody was getting closer to the style they picked.
#
# It is added for EVERY instrument rather than just RapZ, because every take
# carries a genre even when the app has no style picker: "does this drum take
# sound like the drill record it is aiming at" is the same question as "does
# this verse sound like drill", and it is one a take can honestly answer.
#
# The prose stays. The number says how close; the sentence says in what way,
# and a number with no explanation is the thing this file keeps refusing to
# ship.
STYLE_SCORE = {"style_match": "Style Match 🎭"}

# Mix 🎚️ — opt-in, like lyricism, and for the same reason: it is a DIFFERENT
# SKILL from the one the five dimensions measure, and scoring somebody on a
# craft they did not submit is the complaint that produced the lyrics toggle.
#
# The default has to be off. Most takes here are a phone in a bedroom, and a
# performance coach that quietly marks those down for room tone is measuring
# the room instead of the singer — the substance rule inverted, since a member
# could raise that number by buying an interface rather than by getting better.
# Somebody mixing on purpose wants to know; everybody else is being graded on
# equipment.
#
# It is also why the performance dimensions must IGNORE production entirely:
# with this off, a rough recording of a great take is a great take, and the
# prompt says so in as many words.
MIX_SCORE = {
    "clarity_mix": "Balance 🎚️",
    "low_end": "Low End 🔊",
    "space": "Space & Depth 🌌",
    "loudness": "Level 📶",
}


def rates_mix(app_key):
    """Every instrument — any recording has a mix, including a drum take.

    A function rather than a per-profile flag because there is nothing to vary:
    unlike lyrics, which need words, there is no instrument whose recording
    cannot be listened to as a recording. It exists so the caller reads the
    same shape for both toggles.
    """
    return True


def profile_for_app(app_key):
    return INSTRUMENTS.get((app_key or "").lower(), DEFAULT)


def rates_lyrics(app_key):
    """Can this instrument's coach judge writing? Only where there are words.

    A drum take has no lyrics, and a toggle offered on a screen that cannot
    honour it is the switch-that-changes-nothing this codebase already has a
    note about.
    """
    return bool(profile_for_app(app_key).get("lyrics"))


def scores_for(app_key, *, lyrics=False, mix=False):
    """The dimensions this take will be scored on. One place, so the prompt,
    the whitelist that filters the model's answer, and the row that stores it
    can never disagree about how many there are."""
    p = profile_for_app(app_key)
    return {**p["scores"], **STYLE_SCORE,
            **(LYRIC_SCORE if (lyrics and rates_lyrics(app_key)) else {}),
            **(MIX_SCORE if (mix and rates_mix(app_key)) else {})}


def prompt_for(app_key, genre, target, difficulty, style=None, lyrics=False, mix=False):
    """The coaching prompt, in this instrument's own terms."""
    p = profile_for_app(app_key)
    lyrics = bool(lyrics) and rates_lyrics(app_key)
    mix = bool(mix) and rates_mix(app_key)
    keys = list(scores_for(app_key, lyrics=lyrics, mix=mix))
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
    # The number behind that sentence. Said explicitly because "style match" is
    # the easiest score in the set to turn into a quality judgement by
    # accident: a brilliant take of the WRONG style is a low style match and a
    # high everything else, and flattening that into "bad" would tell somebody
    # to stop doing the thing they are good at.
    style_scale = f"""
"style_match" scores ONLY how close this take is to {('the ' + str(style)) if style else genre} \
— not how good it is. A superb take of a different style is a LOW style match \
and high everything else, and that is the correct answer: it tells them they \
nailed something, just not the thing they picked. If they did not pick a \
style, score it against {genre}."""
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

    # What the writing is judged on, and — just as importantly — what it is
    # NOT. A lyric score is the easiest place in this app to start marking
    # somebody's opinions, their subject matter or their swearing, none of
    # which is craft. It is also the easiest place to invent: a model that
    # cannot make the words out will happily review lyrics it imagined.
    lyric_ask = ("""
- "lyrics_read": the words you could actually make out, and how much of the \
take that was. If the delivery is too buried or unclear to catch the writing, \
SAY SO, score every lyric dimension null, and do not review words you did not \
hear — that is the worst thing you can do on this screen.
- "lyrics_note": what the WRITING does, quoting the actual line you mean.

Scoring the writing, dimension by dimension:
- "rhyme": the scheme itself — density, where the rhymes land, internal \
rhymes, multis, whether it stays interesting or settles into the same slot \
every bar.
- "punchlines": wordplay, double meanings, the line somebody would rewind. \
Quote the best one and say why it works.
- "story": does the verse GO somewhere and is it built — setup, turn, \
payoff, or a clear through-line.
- "imagery": concrete and specific against vague and general. "The kitchen \
light still on at 4am" over "things were hard".
- "freshness": how much of this is stock phrasing anybody could have written. \
You are judging CLICHÉ DENSITY, which you can hear, not originality, which \
you cannot — never claim something is unprecedented.

**WEIGHT THESE BY THE STYLE THEY PICKED, and score null for one the style \
genuinely does not ask for.** The blueprint is explicit that good writing means \
different things in different styles: Boom Bap lives on punchlines and internal \
rhymes, Conscious on story and message, Cloud Rap on imagery and space, Drill on \
tension. A ballad with no punchlines is not a ballad with a writing problem — \
score "punchlines" null and say in the note that the style is not asking for \
them. A null is an honest "not what this is for"; a 3 is an accusation.

Judging the writing means the CRAFT and nothing else. Not what they are \
talking about, not their opinions, not whether you would say it, not swearing \
or subject matter. A song about something you find unpleasant, written well, \
is written well. You are a coach, not a censor.""" if lyrics else "")
    lyric_fields = ('\n  "lyrics_read": "<the words you caught, and roughly how much of it - or say you could not make them out>",'
                    '\n  "lyrics_note": "<what the writing does, quoting the line you mean>",'
                    if lyrics else "")

    # Production, only when they asked for it. Deliberately the LAST section so
    # it cannot colour the performance judgement above it.
    mix_ask = ("""

**THE MIX — they asked for this, so judge the RECORDING as a recording.**
- "clarity_mix": is everything audible in its own space, or are parts masking \
each other? Can you hear the vocal against the instrumental?
- "low_end": is the bottom controlled — present without booming, tight without \
being thin? Say what you hear, not what gear you think they used.
- "space": reverb, width and depth. Is it placed in a room on purpose, or dry \
and flat, or drowned?
- "loudness": is the level consistent and appropriate, without clipping or \
pumping? Judge the LEVEL, never the loudness war.

Judge what is ON the recording, never the equipment behind it. "Get a better \
mic" is not coaching — it is a shopping list, and most people sending this are \
on a phone. Say what to change in the mix they have.""" if mix else "")
    mix_fields = ('\n  "mix_note": "<what the mix does, and the one change that would help most>",'
                  if mix else "")
    # Sits right under "score the PERFORMANCE, not the recording", because
    # turning the mix scores on is the one thing that could be read as
    # cancelling that rule. It doesn't: the mix block is the ONLY place
    # production counts, and a rough recording of a great take is still great.
    mix_caveat = ("""

That holds even though they asked for a mix rating. The mix scores below are \
the ONLY place production may count — a rough recording of a great performance \
is still a great performance and must score as one.""" if mix else "")

    # For pitch-based instruments, ask for weak note extraction for practice tool linking
    has_pitch = "pitch" in p["scores"] or "intonation" in p["scores"]
    weak_notes_section = ("""
If pitch accuracy below 70%, name 1-3 most problematic notes with what you heard:
- "weak_notes": [{"note": "E", "frequency": 330, "cents_off": -45}, ...]. \
Note is the letter + octave if hearable (E, F#, A3, etc). Frequency in Hz. \
Cents_off: negative = flat, positive = sharp. If pitch is 70+, return []."""
                          if has_pitch else "")
    # A JSON object with the SAME KEY TWICE is what this used to ask for: the
    # template ended with a hardcoded `"weak_notes": []` and this field added
    # another one above it. Whichever the model honoured, the other was
    # ignored — and on a pitched instrument the empty one came last, which is
    # the one a parser keeps. So the weak notes that drive the TunerZ drill
    # links were being asked for and thrown away.
    #
    # It is the last key now, exactly once, and it carries its own comma.
    weak_notes_field = (
        ',\n  "weak_notes": [{"note": "...", "frequency": 330, "cents_off": 0}, ...]'
        if has_pitch else "")

    return f"""You are the Music ConnectZ {p['coach']}. You are listening to one \
recorded take from a member training in {p['label']}.

Their context:
- Genre: {genre}{target_line}{style_line}
- Difficulty: {difficulty}

Score the take and coach it. Write the way a good engineer talks to an artist \
in the room: direct, specific, second person, no hedging and no flattery. Name \
the actual moment something goes wrong rather than describing the category — \
"the third bar rushes" beats "work on timing". Never invent detail you cannot \
hear; if you couldn't hear it, don't score it.

THE SCALE — read this before you pick a number.
You are scoring a DEVELOPING ARTIST'S PRACTICE TAKE at the "{difficulty}" \
level, recorded on whatever they had to hand. You are NOT scoring it against a \
released record, a session professional, or a studio mix. Those are the wrong \
reference and using them makes every honest take a 2, which tells the member \
nothing except to stop.

FIRST, IS THERE A PERFORMANCE AT ALL? Silence, a few seconds of room noise, \
talking, a TV in the background, a voice memo of an idea, or plainly the wrong \
file — where there is essentially no performance to score, that is not a weak \
take, it is not a take. Set "unscorable" to a short plain sentence saying what \
you actually heard and what to send instead, set "score" and every entry in \
"scores" to null, and stop. Do NOT score it low instead: a 2 tells somebody \
their performance was bad when the truth is you never heard one, and those two \
need opposite answers — one is what to fix, the other is what to send. If you \
can hear them performing at all, however roughly, this is not that: leave \
"unscorable" null and score it properly below.

What the numbers mean, at "{difficulty}":
- 1-2: they are performing, but it barely holds together — the take is mostly \
getting away from them. This is the floor for a REAL attempt, not the bin for \
a clip with nothing in it; that one is "unscorable" above.
- 3-4: real attempt, but the fundamentals come apart often enough that it is \
the first thing to fix.
- 5-6: a solid, ordinary take from somebody at this level. Things to fix, \
nothing broken. **Most takes belong here** — 5 is normal, not a failure.
- 7-8: clearly good for this level; the fixes are refinements.
- 9-10: exceptional at this level. Rare, and worth saying so when it happens.

THE OVERALL is not an average of the dimensions below it, and it is never the \
weakest one. A real listener does not grade each facet and divide — they \
remember what landed. If the hook is real, the emotion reads, or the energy \
connects, one rough facet (diction smearing on the fast bars, a pitchy note, a \
rushed line) does not cap the whole take at that facet's level. Let what's \
working carry the overall the way an actual audience would, and put the weak \
facet in "fixes" rather than in the number. Only let the overall sit low when \
the weaknesses run through the whole take — score it down for a take that is \
shaky throughout, never for a strong one with a single fixable habit.

Score the PERFORMANCE, not the recording. Room noise, phone microphones, no \
mixing, a backing track that is too loud — none of that is their singing, \
playing or writing, and none of it may pull a score down. If the recording \
genuinely gets in the way of hearing something, say so in the fixes and don't \
score that dimension harshly for it.{mix_caveat}

Harshness is not honesty. A number lower than the take deserves is just as \
wrong as one higher, and it is the one that makes somebody quit.

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

"strengths" always has at least one real entry. Every take that contains a \
performance has something working — the pocket on one line, the tone on one \
note, the fact they went for it. Finding it is the job. An empty strengths list \
is a failure of listening, not an honest verdict, and it is what turns coaching \
into a list of complaints somebody closes.

Three things every answer carries, because a score with no destination is a \
number and not coaching:

- "now": what this take actually IS right now — their current qualities, in \
{p['label']}'s own terms, the honest read a stranger would give it.
- "goal": what they are aiming at from here, pitched at "{difficulty}" and at \
{aim}. Concrete enough to know when they have hit it.{range_ask}{style_ask}{style_scale}{lyric_ask}{mix_ask}{weak_notes_section}

Return ONLY valid JSON, no markdown fence, in exactly this shape:
{{
  "unscorable": <null, or a short sentence: what you heard, and what to send instead>,
  "score": <overall 1-10 integer, or null if unscorable>,
  "scores": {{{shape}}},
  "now": "<their current qualities, in that voice>",
  "goal": "<what they're aiming at next, and how they'll know they got there>",{range_field}
  "style_fit": "<how it sits against the style or genre they picked>",{lyric_fields}{mix_fields}
  "verdict": "<one sentence in that voice, what this take actually is>",
  "strengths": ["<what genuinely worked, named specifically - AT LEAST ONE, always>", "..."],
  "fixes": ["<the moment it goes wrong, and the fix — the two that matter most, worst first>", "..."],
  "next_drill": "<one drill to run before the next take: what to do, how many reps>"{weak_notes_field}
}}"""
