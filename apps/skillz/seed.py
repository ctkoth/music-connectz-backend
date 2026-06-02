"""Seed SkillZ tracks + drills for MixeZ and ProduceZ. Idempotent."""
from .models import Drill, SkillTrack

DATA = {
    "producez": {
        "color": "#eab308", "emoji": "🎹",
        "tracks": [
            ("drum-programming", "Drum Programming", "🥁", "Beat foundations — groove, swing, velocity.", [
                ("Build a 16-step boom-bap loop", "practice", 1, 20),
                ("Add swing + velocity humanization", "practice", 2, 30),
                ("Program a trap hi-hat roll pattern", "challenge", 3, 40),
            ]),
            ("sound-design", "Sound Design", "🌌", "Make sounds from scratch.", [
                ("Design a supersaw lead", "practice", 2, 30),
                ("Build a sub bass that translates", "practice", 3, 40),
                ("Recreate a sound by ear", "challenge", 4, 60),
            ]),
            ("sampling", "Sampling & Chopping", "✂️", "Flip a sample tastefully + legally.", [
                ("Chop a loop into 8 playable slices", "practice", 1, 20),
                ("Pitch + time-stretch a vocal chop", "practice", 2, 30),
                ("Flip a sample into a new groove", "challenge", 3, 50),
            ]),
            ("arrangement", "Arrangement", "🧱", "Turn a loop into a song.", [
                ("Arrange intro / verse / hook", "practice", 2, 30),
                ("Write a transition + drop", "challenge", 3, 45),
            ]),
            ("genre-studies", "Genre StudieZ", "🗺️", "Boom Bap → Trap → Drill → Cloud.", [
                ("Recreate a boom-bap feel", "practice", 2, 30),
                ("Recreate a drill bounce", "practice", 3, 40),
            ]),
        ],
    },
    "writez": {
        "color": "#a855f7", "emoji": "✍️",
        "tracks": [
            ("flow", "Flow & Cadence", "🌊", "Ride the beat — pocket, switch-ups, breath.", [
                ("Write 4 bars in a steady pocket", "practice", 1, 20),
                ("Switch flow mid-verse cleanly", "challenge", 3, 45),
                ("Match a double-time cadence", "challenge", 4, 60),
            ]),
            ("rhyme", "Rhyme Schemes", "🔁", "Multis, internals, slant rhymes.", [
                ("Build a 5-deep rhyme stack", "practice", 2, 30),
                ("Write 2 bars of internal rhyme", "practice", 3, 40),
                ("Use a multisyllabic chain", "challenge", 4, 60),
            ]),
            ("hooks", "Hook Writing", "🪝", "Catchy, repeatable, on-theme.", [
                ("Write a 4-line hook with a refrain", "practice", 2, 35),
                ("Rewrite a hook 3 different ways", "challenge", 3, 45),
            ]),
            ("bars", "Bar Craft", "🧊", "Punchlines, wordplay, imagery.", [
                ("Write a punchline bar", "practice", 2, 30),
                ("Land a double-meaning bar", "challenge", 4, 55),
            ]),
            ("style-studies", "Style StudieZ", "🗺️", "Boom Bap → Drill → Cloud → Conscious.", [
                ("Write a boom-bap-style verse", "practice", 2, 30),
                ("Write a drill-style verse", "practice", 3, 40),
            ]),
        ],
    },
    "shotz": {
        "color": "#22d3ee", "emoji": "🎥",
        "tracks": [
            ("camera", "Camera & Framing", "🎥", "Composition, movement, exposure.", [
                ("Frame a clean rule-of-thirds shot", "practice", 1, 20),
                ("Pull focus between two subjects", "challenge", 3, 45),
            ]),
            ("editing", "Editing & Pacing", "✂️", "Cut on motion, control rhythm.", [
                ("Cut a 15s sequence on the beat", "practice", 2, 30),
                ("Build a J-cut / L-cut", "challenge", 3, 45),
            ]),
            ("color", "Color Grading", "🎨", "Match shots, set a look.", [
                ("Balance white point across 3 clips", "practice", 2, 35),
                ("Build a cinematic LUT look", "challenge", 4, 60),
            ]),
            ("audio", "Sound for Video", "🔊", "Dialogue, ambience, mix.", [
                ("Clean up dialogue + add room tone", "practice", 2, 35),
            ]),
            ("story", "Story & Shotlist", "🗺️", "Plan coverage that cuts.", [
                ("Storyboard a 4-shot scene", "practice", 1, 25),
            ]),
        ],
    },
    "mixez": {
        "color": "#84cc16", "emoji": "🎚️",
        "tracks": [
            ("gain-staging", "Gain Staging", "📏", "Clean levels from input to master.", [
                ("Set a -18 dBFS gain structure", "practice", 1, 20),
                ("Fix a clipping channel without losing tone", "challenge", 2, 35),
            ]),
            ("eq-frequency", "EQ & Frequency", "🎛️", "Carve space; hear frequencies.", [
                ("Identify the mud frequency by ear", "quiz", 2, 30),
                ("Carve 250Hz buildup on a bus", "practice", 2, 30),
                ("High-pass for clarity without thinning", "practice", 3, 40),
            ]),
            ("compression", "Compression & Dynamics", "🫁", "Control dynamics musically.", [
                ("Dial attack/release on a vocal", "practice", 2, 35),
                ("Parallel-compress a drum bus", "challenge", 3, 50),
            ]),
            ("spatial", "Spatial — Reverb/Delay/Pan", "🌐", "Depth and width.", [
                ("Place 4 elements front-to-back", "practice", 2, 35),
                ("Use delay throws without clutter", "practice", 3, 45),
            ]),
            ("mastering", "Mastering & Loudness", "💿", "Finish loud + clean.", [
                ("Master a mix to -14 LUFS", "challenge", 3, 50),
                ("Reference-match tonal balance", "challenge", 4, 65),
            ]),
        ],
    },
}


def seed_skillz():
    created = {"tracks": 0, "drills": 0}
    for app_key, cfg in DATA.items():
        for ti, (key, title, emoji, desc, drills) in enumerate(cfg["tracks"]):
            track, made = SkillTrack.objects.get_or_create(
                app_key=app_key, key=key,
                defaults={"title": title, "emoji": emoji, "description": desc,
                          "color": cfg["color"], "order": ti, "persona_skill": key})
            created["tracks"] += int(made)
            for di, (dtitle, kind, diff, xp) in enumerate(drills):
                _, dmade = Drill.objects.get_or_create(
                    track=track, title=dtitle,
                    defaults={"kind": kind, "difficulty": diff, "xp_reward": xp, "order": di,
                              "prompt": dtitle})
                created["drills"] += int(dmade)
    return created
