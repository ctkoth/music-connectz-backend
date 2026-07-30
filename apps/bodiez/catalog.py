"""BodieZ reference data — equipment, muscles, movement patterns, exercises.

Jefit's metrics, in this platform's vocabulary. A routine is built by toggling
the equipment you actually have, then the muscle groups you're training, then
picking exercises that survive both filters — which is the flow the blueprint
asks for and the one every serious training app converges on.

The equipment and muscle lists are deliberately the SAME vocabulary the
`weightlifter` PersonaZ uses (apps/economy/personaz.py). One list, so "what I can
lift" and "what this gym has" can never drift into two lists that almost match.

Everything here is data, not I/O — importable from anywhere and trivially
testable. `seed_bodiez` writes the exercises into the database.
"""

# ---------------------------------------------------------------- equipment
# Ordered roughly by how likely a room is to have it, so a picker's first screen
# is the stuff in a garage and a hotel gym rather than a sled and a landmine.
EQUIPMENT = [
    ("bodyweight", "Bodyweight", "🧍"),
    ("dumbbell", "Dumbbell", "💪"),
    ("barbell", "Barbell", "🏋️"),
    ("weight-plates", "Weight Plates", "⚫"),
    ("ez-bar", "EZ Bar", "〰️"),
    ("trap-bar", "Trap Bar", "⬡"),
    ("kettlebell", "Kettlebell", "🔔"),
    ("flat-bench", "Flat Bench", "🛏️"),
    ("incline-bench", "Incline Bench", "📐"),
    ("decline-bench", "Decline Bench", "📉"),
    ("squat-rack", "Squat Rack", "🔲"),
    ("power-cage", "Power Cage", "🗄️"),
    ("smith-machine", "Smith Machine", "🚇"),
    ("cable", "Pulleys / Cables", "🔗"),
    ("machine", "Weight Machines", "⚙️"),
    ("leg-press", "Leg Press", "🦵"),
    ("pull-up-bar", "Pull-Up Bar", "🙌"),
    ("dip-station", "Dip Station", "⬇️"),
    ("bands", "Resistance Bands", "🎗️"),
    ("suspension", "Suspension Trainer", "🪢"),
    ("medicine-ball", "Medicine Ball", "🏐"),
    ("landmine", "Landmine", "💣"),
    ("sled", "Sled", "🛷"),
    ("battle-ropes", "Battle Ropes", "🪢"),
    ("jump-rope", "Jump Rope", "➰"),
    ("foam-roller", "Foam Roller", "🧻"),
    ("cardio-machine", "Cardio Machine", "🏃"),
]
EQUIPMENT_KEYS = [k for k, _n, _e in EQUIPMENT]

# ---------------------------------------------------------------- muscles
# Exactly the groups the blueprint names, in its order, plus glutes and full-body
# — glutes because leaving the largest muscle in the body inside "upper leg"
# makes a posterior-chain routine impossible to filter for.
MUSCLE_GROUPS = [
    ("neck", "Neck", "🦒", "upper"),
    ("shoulder", "Shoulder", "🤷", "upper"),
    ("chest", "Chest", "🫁", "upper"),
    ("bicep", "Bicep", "💪", "arms"),
    ("tricep", "Tricep", "🔺", "arms"),
    ("forearm", "Forearm", "🦾", "arms"),
    ("wrist", "Wrist", "⌚", "arms"),
    ("back", "Back", "🔙", "upper"),
    ("trapz", "TrapZ", "🗻", "upper"),
    ("abz", "AbZ", "🧊", "core"),
    ("upper-leg", "Upper Leg", "🦵", "lower"),
    ("lower-leg", "Lower Leg", "🦶", "lower"),
    ("glutes", "Glutes", "🍑", "lower"),
    ("full-body", "Full Body", "🧍", "full"),
]
MUSCLE_KEYS = [k for k, _n, _e, _r in MUSCLE_GROUPS]

MOVEMENT_PATTERNS = [
    ("push", "Push", "⬆️"),
    ("pull", "Pull", "⬇️"),
    ("squat", "Squat", "🪑"),
    ("hinge", "Hinge", "🌉"),
    ("lunge", "Lunge", "🚶"),
    ("carry", "Carry", "🧳"),
    ("rotation", "Rotation", "🌀"),
    ("isolation", "Isolation", "🎯"),
    ("cardio", "Cardio", "❤️"),
]
PATTERN_KEYS = [k for k, _n, _e in MOVEMENT_PATTERNS]

DIFFICULTIES = [("beginner", "Beginner", "🌱"), ("intermediate", "Intermediate", "🔥"),
                ("advanced", "Advanced", "🏆")]
DIFFICULTY_KEYS = [k for k, _n, _e in DIFFICULTIES]

# Training goals — same vocabulary as the weightlifter PersonaZ.
GOALS = [
    ("hypertrophy", "Hypertrophy", "📈"),
    ("strength", "Strength", "🏋️"),
    ("powerlifting", "Powerlifting", "🥇"),
    ("olympic", "Olympic Lifting", "🏅"),
    ("bodybuilding", "Bodybuilding", "🏆"),
    ("fat-loss", "Fat Loss", "🔥"),
    ("endurance", "Endurance", "🏃"),
    ("calisthenics", "Calisthenics", "🤸"),
    ("mobility", "Mobility", "🧘"),
    ("athletic", "Athletic Performance", "⚡"),
    ("rehab", "Rehab / Prehab", "🩹"),
    ("general", "General Fitness", "✅"),
]
GOAL_KEYS = [k for k, _n, _e in GOALS]

# Common split templates a routine can declare.
SPLITS = ["push-pull-legs", "upper-lower", "full-body", "bro-split", "arnold",
          "phul", "strength", "home", "custom"]


# ---------------------------------------------------------------- exercises
# (key, name, primary muscle, [secondary], [requirements], pattern, difficulty)
#
# A requirement is either a string (you need this) or a TUPLE (any one of these
# will do). Both cases are real and the difference matters: a bench press needs a
# barbell AND a bench, while a goblet squat needs a kettlebell OR a dumbbell.
# Modelling everything as "needs all" quietly hides half the library from anyone
# who owns dumbbells but not a barbell.
EXERCISES = [
    # ---- chest
    ("bench-press", "Barbell Bench Press", "chest", ["tricep", "shoulder"],
     ["barbell", "flat-bench", "weight-plates"], "push", "intermediate"),
    ("incline-bench-press", "Incline Barbell Press", "chest", ["shoulder", "tricep"],
     ["barbell", "incline-bench", "weight-plates"], "push", "intermediate"),
    ("decline-bench-press", "Decline Barbell Press", "chest", ["tricep"],
     ["barbell", "decline-bench", "weight-plates"], "push", "intermediate"),
    ("db-bench-press", "Dumbbell Bench Press", "chest", ["tricep", "shoulder"],
     ["dumbbell", "flat-bench"], "push", "beginner"),
    ("db-incline-press", "Incline Dumbbell Press", "chest", ["shoulder"],
     ["dumbbell", "incline-bench"], "push", "beginner"),
    ("db-fly", "Dumbbell Fly", "chest", [],
     ["dumbbell", "flat-bench"], "isolation", "beginner"),
    ("cable-crossover", "Cable Crossover", "chest", ["shoulder"],
     ["cable"], "isolation", "beginner"),
    ("pec-deck", "Pec Deck Machine", "chest", [],
     ["machine"], "isolation", "beginner"),
    ("push-up", "Push-Up", "chest", ["tricep", "abz"],
     ["bodyweight"], "push", "beginner"),
    ("chest-dip", "Chest Dip", "chest", ["tricep", "shoulder"],
     ["dip-station"], "push", "intermediate"),
    ("smith-bench", "Smith Machine Bench Press", "chest", ["tricep"],
     ["smith-machine", "flat-bench"], "push", "beginner"),

    # ---- back
    ("deadlift", "Barbell Deadlift", "back", ["glutes", "upper-leg", "trapz", "forearm"],
     ["barbell", "weight-plates"], "hinge", "advanced"),
    ("trap-bar-deadlift", "Trap Bar Deadlift", "back", ["upper-leg", "glutes"],
     ["trap-bar", "weight-plates"], "hinge", "intermediate"),
    ("barbell-row", "Bent-Over Barbell Row", "back", ["bicep", "trapz"],
     ["barbell", "weight-plates"], "pull", "intermediate"),
    ("db-row", "One-Arm Dumbbell Row", "back", ["bicep"],
     ["dumbbell", "flat-bench"], "pull", "beginner"),
    ("pull-up", "Pull-Up", "back", ["bicep", "forearm"],
     ["pull-up-bar"], "pull", "intermediate"),
    ("chin-up", "Chin-Up", "back", ["bicep"],
     ["pull-up-bar"], "pull", "intermediate"),
    ("lat-pulldown", "Lat Pulldown", "back", ["bicep"],
     [("cable", "machine")], "pull", "beginner"),
    ("seated-row", "Seated Cable Row", "back", ["bicep", "trapz"],
     [("cable", "machine")], "pull", "beginner"),
    ("t-bar-row", "T-Bar Row", "back", ["bicep", "trapz"],
     ["landmine", "weight-plates"], "pull", "intermediate"),
    ("face-pull", "Face Pull", "back", ["shoulder", "trapz"],
     ["cable"], "pull", "beginner"),
    ("band-pull-apart", "Band Pull-Apart", "back", ["shoulder"],
     ["bands"], "pull", "beginner"),
    ("inverted-row", "Inverted Row", "back", ["bicep"],
     [("suspension", "bodyweight")], "pull", "beginner"),

    # ---- shoulder
    ("overhead-press", "Standing Overhead Press", "shoulder", ["tricep", "abz"],
     ["barbell", "weight-plates"], "push", "intermediate"),
    ("db-shoulder-press", "Dumbbell Shoulder Press", "shoulder", ["tricep"],
     ["dumbbell", "flat-bench"], "push", "beginner"),
    ("arnold-press", "Arnold Press", "shoulder", ["tricep"],
     ["dumbbell"], "push", "intermediate"),
    ("lateral-raise", "Lateral Raise", "shoulder", [],
     ["dumbbell"], "isolation", "beginner"),
    ("front-raise", "Front Raise", "shoulder", [],
     [("dumbbell", "weight-plates")], "isolation", "beginner"),
    ("rear-delt-fly", "Rear Delt Fly", "shoulder", ["back"],
     [("dumbbell", "cable")], "isolation", "beginner"),
    ("upright-row", "Upright Row", "shoulder", ["trapz", "bicep"],
     [("barbell", "ez-bar")], "pull", "intermediate"),
    ("landmine-press", "Landmine Press", "shoulder", ["chest", "tricep"],
     ["landmine", "weight-plates"], "push", "beginner"),

    # ---- trapz
    ("barbell-shrug", "Barbell Shrug", "trapz", ["forearm"],
     ["barbell", "weight-plates"], "isolation", "beginner"),
    ("db-shrug", "Dumbbell Shrug", "trapz", ["forearm"],
     ["dumbbell"], "isolation", "beginner"),
    ("farmers-carry", "Farmer's Carry", "trapz", ["forearm", "abz", "glutes"],
     [("dumbbell", "kettlebell")], "carry", "beginner"),

    # ---- bicep
    ("barbell-curl", "Barbell Curl", "bicep", ["forearm"],
     [("barbell", "ez-bar")], "isolation", "beginner"),
    ("db-curl", "Dumbbell Curl", "bicep", ["forearm"],
     ["dumbbell"], "isolation", "beginner"),
    ("hammer-curl", "Hammer Curl", "bicep", ["forearm"],
     ["dumbbell"], "isolation", "beginner"),
    ("preacher-curl", "Preacher Curl", "bicep", [],
     [("ez-bar", "machine"), ("incline-bench", "machine")], "isolation", "beginner"),
    ("cable-curl", "Cable Curl", "bicep", ["forearm"],
     ["cable"], "isolation", "beginner"),
    ("concentration-curl", "Concentration Curl", "bicep", [],
     ["dumbbell", "flat-bench"], "isolation", "beginner"),

    # ---- tricep
    ("close-grip-bench", "Close-Grip Bench Press", "tricep", ["chest", "shoulder"],
     ["barbell", "flat-bench", "weight-plates"], "push", "intermediate"),
    ("skull-crusher", "Skull Crusher", "tricep", [],
     ["ez-bar", "flat-bench"], "isolation", "intermediate"),
    ("tricep-pushdown", "Tricep Pushdown", "tricep", [],
     ["cable"], "isolation", "beginner"),
    ("overhead-extension", "Overhead Tricep Extension", "tricep", [],
     [("dumbbell", "cable")], "isolation", "beginner"),
    ("tricep-dip", "Tricep Dip", "tricep", ["chest"],
     [("dip-station", "bodyweight")], "push", "intermediate"),
    ("diamond-push-up", "Diamond Push-Up", "tricep", ["chest"],
     ["bodyweight"], "push", "beginner"),

    # ---- forearm & wrist
    ("wrist-curl", "Wrist Curl", "wrist", ["forearm"],
     [("dumbbell", "barbell"), ("flat-bench",)], "isolation", "beginner"),
    ("reverse-wrist-curl", "Reverse Wrist Curl", "wrist", ["forearm"],
     [("dumbbell", "barbell")], "isolation", "beginner"),
    ("reverse-curl", "Reverse Curl", "forearm", ["bicep"],
     [("ez-bar", "barbell")], "isolation", "beginner"),
    ("dead-hang", "Dead Hang", "forearm", ["back", "wrist"],
     ["pull-up-bar"], "carry", "beginner"),
    ("plate-pinch", "Plate Pinch Hold", "forearm", ["wrist"],
     ["weight-plates"], "carry", "beginner"),

    # ---- neck
    ("neck-flexion", "Neck Flexion", "neck", [],
     [("bodyweight", "weight-plates")], "isolation", "beginner"),
    ("neck-extension", "Neck Extension", "neck", ["trapz"],
     [("bodyweight", "bands")], "isolation", "beginner"),
    ("neck-side-flexion", "Neck Side Flexion", "neck", [],
     ["bodyweight"], "isolation", "beginner"),

    # ---- abz
    ("plank", "Plank", "abz", ["shoulder"],
     ["bodyweight"], "isolation", "beginner"),
    ("hanging-leg-raise", "Hanging Leg Raise", "abz", ["forearm"],
     ["pull-up-bar"], "isolation", "intermediate"),
    ("cable-crunch", "Cable Crunch", "abz", [],
     ["cable"], "isolation", "beginner"),
    ("russian-twist", "Russian Twist", "abz", [],
     [("medicine-ball", "weight-plates")], "rotation", "beginner"),
    ("ab-wheel", "Ab Wheel Rollout", "abz", ["shoulder"],
     ["bodyweight"], "isolation", "advanced"),
    ("sit-up", "Sit-Up", "abz", [],
     [("bodyweight", "decline-bench")], "isolation", "beginner"),
    ("woodchopper", "Cable Woodchopper", "abz", ["shoulder"],
     ["cable"], "rotation", "beginner"),

    # ---- upper leg
    ("back-squat", "Barbell Back Squat", "upper-leg", ["glutes", "abz"],
     ["barbell", "squat-rack", "weight-plates"], "squat", "intermediate"),
    ("front-squat", "Front Squat", "upper-leg", ["glutes", "abz"],
     ["barbell", "squat-rack", "weight-plates"], "squat", "advanced"),
    ("goblet-squat", "Goblet Squat", "upper-leg", ["glutes"],
     [("kettlebell", "dumbbell")], "squat", "beginner"),
    ("leg-press-ex", "Leg Press", "upper-leg", ["glutes"],
     [("leg-press", "machine")], "squat", "beginner"),
    ("leg-extension", "Leg Extension", "upper-leg", [],
     ["machine"], "isolation", "beginner"),
    ("leg-curl", "Lying Leg Curl", "upper-leg", ["glutes"],
     ["machine"], "isolation", "beginner"),
    ("romanian-deadlift", "Romanian Deadlift", "upper-leg", ["glutes", "back"],
     [("barbell", "dumbbell")], "hinge", "intermediate"),
    ("bulgarian-split-squat", "Bulgarian Split Squat", "upper-leg", ["glutes"],
     ["dumbbell", "flat-bench"], "lunge", "intermediate"),
    ("walking-lunge", "Walking Lunge", "upper-leg", ["glutes"],
     [("dumbbell", "bodyweight")], "lunge", "beginner"),
    ("hack-squat", "Hack Squat", "upper-leg", ["glutes"],
     ["machine"], "squat", "intermediate"),

    # ---- glutes
    ("hip-thrust", "Barbell Hip Thrust", "glutes", ["upper-leg"],
     ["barbell", "flat-bench", "weight-plates"], "hinge", "beginner"),
    ("glute-bridge", "Glute Bridge", "glutes", ["upper-leg"],
     [("bodyweight", "barbell")], "hinge", "beginner"),
    ("cable-kickback", "Cable Glute Kickback", "glutes", [],
     ["cable"], "isolation", "beginner"),
    ("sled-push", "Sled Push", "glutes", ["upper-leg", "lower-leg"],
     ["sled"], "carry", "intermediate"),

    # ---- lower leg
    ("standing-calf-raise", "Standing Calf Raise", "lower-leg", [],
     [("machine", "smith-machine", "bodyweight")], "isolation", "beginner"),
    ("seated-calf-raise", "Seated Calf Raise", "lower-leg", [],
     ["machine"], "isolation", "beginner"),
    ("jump-rope-ex", "Jump Rope", "lower-leg", ["abz"],
     ["jump-rope"], "cardio", "beginner"),
    ("tibialis-raise", "Tibialis Raise", "lower-leg", [],
     [("bodyweight", "bands")], "isolation", "beginner"),

    # ---- bodyweight (the hotel room / no-equipment case, which is the most
    # common "I can't train today" excuse and the easiest one to remove)
    ("air-squat", "Air Squat", "upper-leg", ["glutes"],
     ["bodyweight"], "squat", "beginner"),
    ("bodyweight-lunge", "Bodyweight Lunge", "upper-leg", ["glutes"],
     ["bodyweight"], "lunge", "beginner"),
    ("pike-push-up", "Pike Push-Up", "shoulder", ["tricep"],
     ["bodyweight"], "push", "intermediate"),
    ("mountain-climber", "Mountain Climber", "abz", ["shoulder", "upper-leg"],
     ["bodyweight"], "cardio", "beginner"),
    ("bicycle-crunch", "Bicycle Crunch", "abz", [],
     ["bodyweight"], "rotation", "beginner"),
    ("superman", "Superman", "back", ["glutes"],
     ["bodyweight"], "isolation", "beginner"),
    ("wall-sit", "Wall Sit", "upper-leg", [],
     ["bodyweight"], "squat", "beginner"),
    ("bird-dog", "Bird Dog", "abz", ["back", "glutes"],
     ["bodyweight"], "isolation", "beginner"),
    ("side-plank", "Side Plank", "abz", ["shoulder"],
     ["bodyweight"], "isolation", "beginner"),
    ("bodyweight-calf-raise", "Bodyweight Calf Raise", "lower-leg", [],
     ["bodyweight"], "isolation", "beginner"),

    # ---- full body / cardio
    ("clean-and-jerk", "Clean & Jerk", "full-body", ["shoulder", "upper-leg", "trapz"],
     ["barbell", "weight-plates"], "hinge", "advanced"),
    ("snatch", "Barbell Snatch", "full-body", ["shoulder", "upper-leg"],
     ["barbell", "weight-plates"], "hinge", "advanced"),
    ("kb-swing", "Kettlebell Swing", "full-body", ["glutes", "back"],
     ["kettlebell"], "hinge", "beginner"),
    ("thruster", "Thruster", "full-body", ["shoulder", "upper-leg"],
     [("barbell", "dumbbell")], "squat", "intermediate"),
    ("burpee", "Burpee", "full-body", ["chest", "upper-leg"],
     ["bodyweight"], "cardio", "beginner"),
    ("battle-rope-waves", "Battle Rope Waves", "full-body", ["shoulder", "abz"],
     ["battle-ropes"], "cardio", "beginner"),
    ("treadmill-run", "Treadmill Run", "full-body", ["lower-leg"],
     ["cardio-machine"], "cardio", "beginner"),
    ("rowing-machine", "Rowing Machine", "full-body", ["back", "upper-leg"],
     ["cardio-machine"], "cardio", "beginner"),
    ("foam-roll", "Foam Rolling", "full-body", [],
     ["foam-roller"], "isolation", "beginner"),
]


def equipment_payload():
    return [{"key": k, "name": n, "emoji": e} for k, n, e in EQUIPMENT]


def muscle_payload():
    return [{"key": k, "name": n, "emoji": e, "region": r} for k, n, e, r in MUSCLE_GROUPS]


def simple_payload(rows):
    return [{"key": k, "name": n, "emoji": e} for k, n, e in rows]


def requirement_groups(requirements):
    """Normalise a row's requirements into a list of any-of tuples."""
    return [(r,) if isinstance(r, str) else tuple(r) for r in requirements]


def equipment_used(requirements):
    """Flat list of every piece a movement might use, for display."""
    out = []
    for group in requirement_groups(requirements):
        for item in group:
            if item not in out:
                out.append(item)
    return out


def can_perform(requirements, have):
    """True when every requirement group is satisfied by something owned."""
    return all(set(group) & have for group in requirement_groups(requirements))


def exercises_for(equipment=None, muscles=None):
    """Filter the seed library the way the routine builder does.

    `equipment` is what the member HAS. An exercise qualifies when every
    requirement group is satisfied — a bench press with no bench is not a bench
    press, but a goblet squat is fine with either a kettlebell or a dumbbell.
    """
    # Bodyweight is ALWAYS available. A member who owns only a barbell can still
    # do a push-up, and a gym-coverage report that says "you can't train chest
    # here" because nobody ticked a box for their own body is just wrong.
    have = set(equipment or [])
    if have:
        have.add("bodyweight")
    want = set(muscles or [])
    out = []
    for key, name, primary, secondary, needs, pattern, difficulty in EXERCISES:
        if have and not can_perform(needs, have):
            continue
        if want and primary not in want and not want.intersection(secondary):
            continue
        out.append({
            "key": key, "name": name, "muscle": primary, "secondary": secondary,
            "equipment": equipment_used(needs),
            "requires": [list(g) for g in requirement_groups(needs)],
            "pattern": pattern, "difficulty": difficulty,
        })
    return out
