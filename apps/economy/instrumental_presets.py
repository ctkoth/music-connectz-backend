"""Instrumental ConnectZ starting points by RAP STYLE, by SINGING RANGE and by GENRE — a form filled in, nothing more.

A preset is the form's own fields (genre, instruments, BPM, key, bars, a one-line brief) and the reason for each choice.
Nothing is generated here and nothing is charged: the member presses Compose as before, at the same price, and can change any
field first. Keyed by the coaches' own slugs (instruments.RAP_STYLES / VOCAL_RANGES, held equal by a test) so a take scored
as Drill, or a voice sung as a Baritone, can offer its own backing.

What decides what, and why (the reasons are served beside each preset):
  * A RAP STYLE decides the tempo, the groove and the parts. Tempo is the defining trait of the style (drill is not boom-bap at
    another speed), and the brief says where to leave the pocket open for the verse.
  * A SINGING RANGE decides the KEY and the register of the accompaniment. A key sets where the tune's home note is; the tonic
    here sits a few notes above the bottom of that range, so a singer has room to go down and up from it. Key names carry no
    octave, so this is a starting point — a singer can take any key an octave away — and the brief keeps the accompaniment OUT
    of the voice's own register (airy pads above a low voice, warm low parts under a high one) so it doesn't mask the singer.
Every choice is a suggestion with its reason on screen, never a rule.
"""
from .instrumentalz import BARS, BPM_MAX, BPM_MIN, INSTRUMENTS, KEY_NAMES


def _preset(group, key, label, emoji, genre, instruments, bpm, tonic, bars, brief, why):
    return {"key": key, "group": group, "label": label, "emoji": emoji, "genre": genre, "instruments": instruments,
            "bpm": bpm, "key_name": tonic, "bars": bars, "brief": brief, "why": why}


RAP_STYLE_PRESETS = [
    _preset("Rap style", "boom-bap", "Boom Bap", "🥁", "Hip-hop", ["drums", "epiano", "bass", "strings"], 90, "A minor", 4,
            "Dusty swung drums with the snare on 2 and 4, a looped electric-piano figure, a round bass. Leave bars of space for the verse.",
            "Boom bap lives around 85-95 BPM on a swung, sampled-feel groove; the loop stays simple so the lyrics carry."),
    _preset("Rap style", "trap", "Trap", "🏚️", "Trap", ["drums", "synth_bass", "pad", "lead"], 140, "F minor", 4,
            "Half-time snare, rolling hi-hats, a sliding 808-style bass, a dark pad and one sparse lead line.",
            "Trap is written at 130-150 BPM but felt at half time; the 808 carries the weight, so the pad stays out of the low end."),
    _preset("Rap style", "drill", "Drill", "⚔️", "Drill", ["drums", "synth_bass", "pad", "strings"], 142, "G minor", 4,
            "Sliding bass, triplet hi-hats, a sparse dark string line, a cold pad. Leave the midrange empty for the vocal.",
            "Drill sits near 140-144 BPM with gliding bass notes; the arrangement stays thin so the vocal and bass can both be heard."),
    _preset("Rap style", "cloud-rap", "Cloud Rap", "☁️", "Cloud rap", ["pad", "epiano", "synth_bass", "drums"], 75, "Db major", 8,
            "Washed, slow pads, a soft electric piano, a quiet bass and light, loose drums. Dreamy, nothing sharp.",
            "Cloud rap is slow and hazy (70-80 BPM), built on pads and space; eight bars lets the wash develop."),
    _preset("Rap style", "lyrical", "Lyrical", "🧠", "Hip-hop", ["piano", "bass", "drums", "strings"], 88, "D minor", 8,
            "Restrained and steady: a repeating piano phrase, a simple bass, a plain pocket. Nothing busy in the vocal's range.",
            "Dense verses need a plain bed: a steady 85-92 BPM pocket and a small arrangement so no word competes with a part."),
    _preset("Rap style", "storytelling", "Storytelling", "📖", "Hip-hop", ["acoustic_guitar", "piano", "bass", "drums"], 82, "G minor", 8,
            "A sparse acoustic guitar figure under a soft piano, a quiet bass, brushed-feel drums. It should feel like a scene.",
            "A story needs room and a gentle bed, so it is slow (about 80-85 BPM) and mostly acoustic."),
    _preset("Rap style", "freestyle", "Freestyle", "🌀", "Hip-hop", ["drums", "bass", "piano"], 92, "C minor", 4,
            "A loop-friendly beat with a clear downbeat: kick and snare, a steady bass, a simple piano loop. Easy to rap over for minutes.",
            "A freestyle needs a loop you can ride without it changing under you: short, steady, the same every pass."),
    _preset("Rap style", "melodic", "Melodic", "🎶", "Melodic rap", ["pad", "lead", "synth_bass", "drums"], 128, "Eb major", 4,
            "Open, bright chords with a singable lead hook, a rolling bass, crisp drums. Leave the hook's register clear for the vocal.",
            "Melodic rap sings over open chords, so the key is major and bright and the tempo is mid-fast (120-135 BPM)."),
    _preset("Rap style", "double-time", "Double-Time", "⚡", "Hip-hop", ["drums", "bass", "piano"], 150, "B minor", 4,
            "Fast and tight: a hard, even kick-snare pocket, a staccato bass, a spare piano stab. Keep the midrange clear for fast syllables.",
            "Double-time flows want a fast, clean pocket (145-155 BPM) and an empty midrange, because fast syllables smear in a busy mix."),
    _preset("Rap style", "old-school", "Old School", "📻", "Hip-hop", ["drums", "bass", "brass", "organ"], 96, "G minor", 4,
            "A punchy breakbeat-style kick and snare, a walking bass, brass stabs and an organ chord. Direct and bouncy.",
            "Old school is built on a drum break and a bassline with a hook stab on top, around 92-100 BPM."),
    _preset("Rap style", "conscious", "Conscious", "✊", "Hip-hop", ["piano", "bass", "drums", "strings"], 86, "F major", 8,
            "Warm and spacious: a hopeful piano progression, a round bass, easy drums, a gentle string pad underneath.",
            "A conscious record wants the words to lead, so the bed is warm and open and the key is major (F)."),
    _preset("Rap style", "mumble", "Mumble", "😶‍🌫️", "Trap", ["drums", "synth_bass", "pad", "lead"], 138, "G# minor", 4,
            "Dark, hazy and minimal: a heavy 808-style bass, slow drifting pads, a detuned lead. Space, not detail.",
            "Mumble rap rides texture, so the beat is heavy and murky (135-145 BPM) and the arrangement is deliberately thin."),
]

# [key, label, emoji, tonic, mode-key, tempo, instruments, brief-about-the-register, why]
_RANGES = [
    ("bass", "Bass", "🧔‍♂️", "A minor", 80, ["piano", "pad", "strings", "drums"],
     "Keep the low register to a quiet bass only; put airy pads and a light piano above the voice so it is not masked."),
    ("baritone", "Baritone", "🎙️", "D minor", 84, ["piano", "acoustic_guitar", "bass", "drums"],
     "Warm mid-register guitar and piano, a restrained bass; leave the low-mid where this voice sits clear."),
    ("tenor", "Tenor", "🎤", "F major", 96, ["piano", "electric_guitar", "bass", "drums"],
     "A balanced band; keep guitar and piano chords below the tenor's line so the voice stays on top."),
    ("countertenor", "Countertenor", "🕊️", "A major", 90, ["epiano", "acoustic_guitar", "pad", "bass"],
     "Soft low-to-mid parts and a gentle pad; nothing bright in the upper register the voice occupies."),
    ("contralto", "Contralto", "🎻", "Bb minor", 80, ["piano", "strings", "bass", "drums"],
     "Strings and piano kept above and below the voice, a warm bass; the low-mid is left open."),
    ("alto", "Alto", "🎶", "C major", 100, ["acoustic_guitar", "piano", "bass", "drums"],
     "A balanced band with guitar and piano under the alto's range, bass and drums steady."),
    ("mezzo-soprano", "Mezzo-Soprano", "🌊", "D major", 104, ["piano", "acoustic_guitar", "strings", "drums"],
     "Warm low and mid parts with a light string bed; keep the high register free for the melody."),
    ("soprano", "Soprano", "☀️", "F major", 108, ["piano", "acoustic_guitar", "bass", "drums"],
     "Warm low and mid instruments only; no bright lead or high strings, so nothing sits where the soprano sings."),
]

RANGE_PRESETS = [
    _preset("Singing range", key, f"{label} backing", emoji, "Singer-songwriter", insts, bpm, tonic, 4, brief,
            f"The home note ({tonic.split()[0]}) is placed a few notes above the bottom of the {label.lower()} range, so there is room to sing "
            "up and down from it; the parts are chosen to stay out of the voice's own register. A starting key: an octave either way works too.")
    for key, label, emoji, tonic, bpm, insts, brief in _RANGES
]

PRESETS = RAP_STYLE_PRESETS + RANGE_PRESETS


def presets_payload():
    return PRESETS


def validate():
    """Every field a preset fills must be one the form accepts. Called by the test, so a preset cannot ship broken."""
    bad = []
    for p in PRESETS:
        if p["key_name"] not in KEY_NAMES:
            bad.append((p["key"], "key", p["key_name"]))
        if not BPM_MIN <= p["bpm"] <= BPM_MAX:
            bad.append((p["key"], "bpm", p["bpm"]))
        if p["bars"] not in BARS:
            bad.append((p["key"], "bars", p["bars"]))
        for i in p["instruments"]:
            if i not in INSTRUMENTS:
                bad.append((p["key"], "instrument", i))
    return bad
