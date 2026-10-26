"""What a member can pick, and what an interest tends to go with — as DATA.

Pure tables, no imports, so `personaz` (which cleans a persona on every read and
write) and `interestz` (which scans and suggests) can both load it without a cycle.

Nothing here measures anybody. Interests and brands are things a member says they
like; a strength is a thing a member says about themselves, offered as a suggestion
FIRST. `RULES` is the whole of the "intuition": every suggestion is one of these
rows, with its reason written out, so it can be read, argued with and changed by a
person. A model guessing a trait from a pile of interests would be a number with no
reason behind it, which is the failure this codebase already knows by name.

Sensitive territory is absent on purpose. Health, faith, politics, orientation and
the like are not in `INTERESTS`, so the scanner cannot pick them out of what a
member said — a closed list can only find what is on it.
"""

# key -> (label, emoji, aliases). Aliases are lowercase and matched as whole words.
INTERESTS = {
    "drawing":      ("Drawing", "✏️", ("drawing", "sketching", "sketch", "doodling", "doodle")),
    "painting":     ("Painting", "🖌️", ("painting", "watercolour", "watercolor")),
    "illustration": ("Illustration", "🖍️", ("illustration", "illustrating", "illustrate")),
    "cover_art":    ("Cover art", "💿", ("cover art", "album art", "album cover", "album covers",
                                         "song cover", "song covers", "single cover", "cover design")),
    "photography":  ("Photography", "📷", ("photography", "taking photos")),
    "filmmaking":   ("Filmmaking", "🎬", ("filmmaking", "making films", "short films")),
    "gaming":       ("Gaming", "🎮", ("gaming", "video games")),
    "reading":      ("Reading", "📚", ("reading", "books", "novels")),
    "writing":      ("Writing", "📝", ("writing", "poetry", "journaling")),
    "sampling":     ("Sampling", "🎚️", ("sampling", "crate digging", "digging for samples", "record collecting")),
    "gear":         ("Gear", "🎛️", ("gear", "pedals", "synths", "synthesizers", "tinkering", "modding")),
    "dance":        ("Dance", "💃", ("dancing",)),
    "travel":       ("Travel", "✈️", ("travelling", "traveling", "travel")),
    "fitness":      ("Fitness", "🏋️", ("working out", "gym", "lifting", "running")),
}

# key -> (label, category, aliases). Tools and instrument/gear makers a creative
# person actually names. A brand is something a member likes, never a partner: it
# unlocks nothing, is not sold to anyone and is not an ad-targeting profile.
BRANDS = {
    "fender":   ("Fender", "gear", ("fender",)),
    "gibson":   ("Gibson", "gear", ("gibson",)),
    "ibanez":   ("Ibanez", "gear", ("ibanez",)),
    "yamaha":   ("Yamaha", "gear", ("yamaha",)),
    "roland":   ("Roland", "gear", ("roland",)),
    "korg":     ("Korg", "gear", ("korg",)),
    "moog":     ("Moog", "gear", ("moog",)),
    "akai":     ("Akai", "gear", ("akai", "mpc")),
    "shure":    ("Shure", "gear", ("shure",)),
    "focusrite": ("Focusrite", "gear", ("focusrite",)),
    "ni":       ("Native Instruments", "software", ("native instruments", "maschine", "kontakt")),
    "ableton":  ("Ableton", "software", ("ableton", "ableton live")),
    "flstudio": ("FL Studio", "software", ("fl studio", "fruity loops", "fruityloops")),
    "logic":    ("Logic Pro", "software", ("logic pro", "logic x")),
    "protools": ("Pro Tools", "software", ("pro tools", "protools")),
    "splice":   ("Splice", "software", ("splice",)),
    "adobe":    ("Adobe", "design", ("adobe",)),
    "photoshop": ("Photoshop", "design", ("photoshop",)),
    "illustrator": ("Illustrator", "design", ("illustrator",)),
    "aftereffects": ("After Effects", "design", ("after effects",)),
    "premiere": ("Premiere Pro", "design", ("premiere pro", "premiere")),
    "procreate": ("Procreate", "design", ("procreate",)),
    "figma":    ("Figma", "design", ("figma",)),
    "canva":    ("Canva", "design", ("canva",)),
    "blender":  ("Blender", "design", ("blender",)),
    "wacom":    ("Wacom", "design", ("wacom",)),
    "davinci":  ("DaVinci Resolve", "design", ("davinci resolve", "davinci")),
    "sony":     ("Sony", "gear", ("sony",)),
    "canon":    ("Canon", "gear", ("canon",)),
}

# key -> (label, emoji). What a member can DECLARE about themselves.
TRAITS = {
    "dexterous":    ("Dexterous", "🖐️"),
    "creative":     ("Creative", "🎨"),
    "observant":    ("Observant", "👁️"),
    "patient":      ("Patient", "⏳"),
    "technical":    ("Technical", "🔧"),
    "detail_minded": ("Detail-minded", "🔍"),
}

# (who, interests, trait, because). `who` are word STEMS matched against the words
# of the persona's name and its skills; `interests` is "any of". The reason is the
# whole point: it is shown to the member before they decide, and it is written as
# what tends to go with the interest, not as a fact about them.
RULES = (
    (("design", "illustrat", "artist"), ("drawing", "painting", "illustration"), "dexterous",
     "You draw or paint by hand, which takes steady, fine control. People who design and draw tend to be dexterous."),
    (("design", "illustrat"), ("cover_art",), "creative",
     "Cover art turns a song you heard into a picture someone will recognise, which takes imagination."),
    (("design", "illustrat"), ("cover_art",), "observant",
     "A cover that works is built from small details of the music, so cover design goes with noticing them."),
    (("produc", "beat", "engineer", "mix"), ("sampling",), "observant",
     "Sampling is listening closely enough to hear the one second worth keeping."),
    (("produc", "engineer", "guitar", "bass", "key", "synth", "drum"), ("gear",), "technical",
     "Gear and tinkering mean learning how a signal path works, which goes with a technical streak."),
    (("video", "film", "direct", "photograph"), ("photography", "filmmaking"), "observant",
     "Framing a shot means noticing what is in it and what is not."),
    (("write", "lyric", "poet", "ghost"), ("reading", "writing"), "creative",
     "Reading and writing widely feed the lines you can come up with."),
    (("design", "illustrat", "produc", "engineer", "video", "film"), ("drawing", "cover_art", "sampling", "photography"),
     "detail_minded",
     "Work that repeats a small decision many times, like a line, a sample or a frame, tends to go with minding the details."),
)

MAX_PICKS = 20
