"""OCC — Ocular Code ConnectZ: the tab registry, the tiers, the taxonomy.

One place, served to the client, so a tab's name, emoji, description and TIER
GATE can never drift between the menu that offers it and the endpoint that
refuses it. Every other gate in this app already works that way; OCC has more
surfaces than anything else here, so it needs it most.

WHAT OCC IS NOT — stated here because the difference decides what can be built:

  OCC edits, tracks, explains and version-controls code. It does not EXECUTE
  it. Running, building or compiling a member's project needs a sandboxed
  container per user — real infrastructure, real cost, and the security problem
  of running strangers' code on your machines. Nothing in this file pretends
  otherwise, and any tab that would need execution says so rather than shipping
  a button that lies.
"""
from .features import required_tier
from .models import TIER_DEBUG, TIER_FREE, TIER_PREMIUM, TIER_STATZ

# Tier ladder — a member at or above the named tier passes. Matches
# features.can_use: a ladder, not an equality test.
TIER_ORDER = [TIER_FREE, TIER_PREMIUM, TIER_STATZ, TIER_DEBUG]


def tier_at_least(tier, needed):
    try:
        return TIER_ORDER.index(tier) >= TIER_ORDER.index(needed)
    except ValueError:
        return False


# The tabs, in the order the spec lists them. `needs` is the tier gate;
# `builds` says honestly what stands behind the tab today, because a menu that
# offers twenty tabs and delivers three is worse than a menu that offers three.
#
# `icon` names the platform artwork a tab wants; `emoji` is what it falls back
# to. Both are always sent, and that is the point — the client uses the icon
# only if its own registry actually has that file, so a tab whose art hasn't
# shipped to the frontend yet shows its emoji rather than a generic logo. (The
# frontend deploys itself and the backend does not, so the two WILL be out of
# step, and the failure has to degrade to something that still means the right
# thing.)
#
# Every tab names the art that belongs to IT — never a neighbour's. BugZ's bug
# on MistakeZ or PersonaZ's face on CharacterZ would be a picture of the wrong
# thing, which is worse than the emoji it replaced.
#
# Eight of these names are RESERVED: the artwork doesn't exist yet, and naming
# it here is what makes dropping the file into the frontend's public/icons/ the
# entire job. Until the file lands it 404s and the client shows the emoji, so
# reserving a name costs a member nothing and saves a code change later.
#
# `built` says whether a SCREEN stands behind the tab today, and `open_in` +
# `target` say where it opens — an app's tab key and the data-tour anchor to
# land on inside it (what `goToSpot(tab, target)` takes). The first version of
# this table named seven screens OCC does not have (an editor, a console, FileZ,
# Welcome…) and the client rendered each as a card with "Not built yet" and no
# button, and sent every "Open →" to an anchor (`occ:<key>`) that exists
# nowhere. A tab that is not built is still listed — it is the spec, and
# `builds` is what stands behind it — but it carries `built: False` and no door,
# and the client does not draw it.
#
# `open_in` must be a tab the client actually mounts. `test_occ_routes` holds
# the allow-list; the frontend's `occRoutes.test.mjs` checks it against
# App.jsx's TABS, so adding a door to a tab that is not there fails a test
# instead of playing a sound and going nowhere.
#
# Gates come from features.py wherever a feature exists, never typed a second
# time: LogZ was typed as Premium here while features.py (and its own test)
# say it is free, so the tab grid told a Free member to upgrade for the one
# screen that answers "what took my ⚡".
OCC_TABS = [
    {"key": "editor", "built": False, "icon": "editor.png", "name": "Code editor", "emoji": "👁️‍🗨️", "needs": TIER_FREE,
     "desc": "Write and edit your files.", "builds": "editor"},
    {"key": "taskz", "built": True, "open_in": "occ", "target": "occ-taskz", "icon": "taskz.png", "name": "TaskZ", "emoji": "📑", "needs": TIER_FREE,
     "desc": "Your to-do list for OCC work — suggestions, sandbox runs and anything you add.",
     "builds": "taskz"},
    # Not in the original list of twenty-one: added because an OCC result that
    # can't be shown, rated or carried anywhere is a dead end, and nothing here
    # is allowed to be one. WorkZ is where what you gave OCC and what it gave
    # back are kept, in the PostZ format, ready to post.
    {"key": "workz", "built": True, "open_in": "occ", "target": "occ-workz", "icon": "workz.png", "name": "WorkZ", "emoji": "🧾", "needs": TIER_FREE,
     "desc": "What you gave OCC and what it gave back — post it, rate it, or take it "
             "into another app.", "builds": "workz"},
    {"key": "codez", "built": True, "open_in": "habitz", "target": "", "icon": "codez.png", "name": "CodeZ", "emoji": "🧩", "needs": TIER_FREE,
     "desc": "Your acronyms, typos and slang — what you meant, and how often you've typed it.",
     "builds": "codez"},
    {"key": "pathz", "built": True, "open_in": "habitz", "target": "", "icon": "pathz.png", "name": "PathZ", "emoji": "🛤️", "needs": TIER_PREMIUM,
     "desc": "Your paths across devices.", "builds": "pathz"},
    {"key": "mistakez", "built": True, "open_in": "habitz", "target": "", "icon": "mistakez.png", "name": "MistakeZ", "emoji": "❌", "needs": TIER_FREE,
     "desc": "Errors the AI made here, kept so it doesn't make them twice.",
     "builds": "mistakez"},
    {"key": "habitz", "built": True, "open_in": "habitz", "target": "", "icon": "habitz.png", "name": "HabitZ", "emoji": "🎂", "needs": TIER_FREE,
     "desc": "Something you repeat, noticed and kept.", "builds": "habitz"},
    # Built: CharacterZ is a mounted tab now (and MangaZ draws with its cast), so
    # "not built" here was the LogicZ failure — a stale flag telling members not
    # to look for something that is right there.
    {"key": "characterz", "built": True, "open_in": "characterz", "target": "", "icon": "characterz.png", "name": "CharacterZ", "emoji": "🤔", "needs": TIER_PREMIUM,
     # Not "MBTI characters". This dict is served to members by `tabs_for`,
     # so it was the second place on the platform publishing somebody else's
     # trademark — while `personalityz.py`'s own docstring says in as many
     # words that we deliberately do not call it that. The four axes are ours
     # to describe; the name is not ours to use.
     "desc": "Characters built on the four PersonalitieZ axes, attached to a "
             "FaceZ face, with a story and a voice.",
     "builds": "characterz"},
    {"key": "settings", "built": True, "open_in": "occ", "target": "occ-settings", "icon": "preferencez.png", "name": "Settings", "emoji": "⚙️", "needs": TIER_FREE,
     "desc": "AutomationZ and SuggestionZ live here.", "builds": "settings"},
    {"key": "console", "built": False, "icon": "console.png", "name": "Output / Console", "emoji": "🖥️", "needs": TIER_FREE,
     "desc": "What OCC printed.", "builds": "console"},
    {"key": "callz", "built": True, "open_in": "callz", "target": "", "icon": "callz.png", "name": "CallZ", "emoji": "📞", "needs": TIER_STATZ,
     "desc": "Talk it through.", "builds": "callz"},
    {"key": "search", "built": False, "icon": "search.png", "name": "Search", "emoji": "🔍", "needs": TIER_FREE,
     "desc": "Across every tab.", "builds": "search"},
    {"key": "tellz", "built": False, "icon": "tellz.png", "name": "TellZ", "emoji": "🗣️", "needs": required_tier("tellz"),
     "desc": "What you prompted or posted, per tab or across all of them.",
     "builds": "tellz"},
    {"key": "logz", "built": True, "open_in": "logz", "target": "", "icon": "logz.png", "name": "LogZ", "emoji": "🪵", "needs": required_tier("logz"),
     "desc": "What was DONE, by day, week, month or a range you pick.",
     "builds": "logz"},
    {"key": "pickconnectz", "built": False, "icon": "pickconz.png", "name": "Pick ConnectZ", "emoji": "📌", "needs": TIER_FREE,
     "desc": "Pin your favourites to the footer.", "builds": "pickconnectz"},
    # Built: FileZ is a mounted tab (every upload, with its storage), so this door opens it.
    {"key": "filez", "built": True, "open_in": "filez", "target": "", "icon": "filez.png", "name": "FileZ", "emoji": "📁", "needs": TIER_FREE,
     "desc": "Files and uploads.", "builds": "filez"},
    {"key": "gitz", "built": False, "icon": "gitz.png", "name": "GitZ", "emoji": "🔀", "needs": required_tier("gitz"),
     "desc": "Branches, commits and pushes — every one of them a TaskZ task.",
     "builds": "gitz"},
    {"key": "gamez", "built": True, "open_in": "gamez", "target": "", "icon": "gamez.png", "name": "GameZ", "emoji": "🎮", "needs": required_tier("occ_games"),
     "desc": "Games you built here, by genre.", "builds": "gamez"},
    {"key": "spinaz", "built": True, "open_in": "logz", "target": "", "icon": "spinaz.png", "name": "SpinaZ", "emoji": "🍥", "needs": TIER_FREE,
     "desc": "How you earned and spent it.", "builds": "spinaz"},
    {"key": "energy", "built": True, "open_in": "logz", "target": "", "icon": "energy.png", "name": "Energy", "emoji": "⚡", "needs": TIER_FREE,
     "desc": "How you earned and spent it.", "builds": "energy"},
    {"key": "facez", "built": True, "open_in": "facez", "target": "", "icon": "facez.png", "name": "FaceZ", "emoji": "🙄", "needs": TIER_FREE,
     "desc": "Faces available to AI images and video, taggable to a profile.",
     "builds": "facez"},
    {"key": "welcome", "built": True, "open_in": "onboardz", "target": "", "icon": "welcome.png", "name": "Welcome", "emoji": "👋", "needs": TIER_FREE,
     "desc": "Start here.", "builds": "welcome"},
]

# The two toggles the spec puts front and centre.
OCC_TOGGLES = [
    {"key": "automation", "name": "AutomationZ", "emoji": "🤖", "needs": required_tier("automationz"),
     "desc": "Does the safe suggestions itself, without asking, and tells you as it happens. "
             "Anything that publishes, spends or other members can see still asks."},
    {"key": "suggestionz", "name": "SuggestionZ", "emoji": "💭", "needs": required_tier("suggestionz"),
     "desc": "Reads your account and proposes work, explaining what, why and how before anything runs."},
]

# Languages you may build a game in. Unreal/C++ is the StatZ reservation.
# The tiers are features.py's (`occ_games`, `occ_cpp`), read once here rather
# than typed on seventeen rows — a second copy of a gate is how the tab grid
# came to call LogZ Premium.
_GAMES = required_tier("occ_games")
_CPP = required_tier("occ_cpp")
OCC_LANGUAGES = [
    {"key": "python", "name": "Python", "needs": _GAMES},
    {"key": "javascript", "name": "JavaScript", "needs": _GAMES},
    {"key": "typescript", "name": "TypeScript", "needs": _GAMES},
    {"key": "csharp", "name": "C# (Unity)", "needs": _GAMES},
    {"key": "gdscript", "name": "GDScript (Godot)", "needs": _GAMES},
    {"key": "lua", "name": "Lua", "needs": _GAMES},
    {"key": "java", "name": "Java", "needs": _GAMES},
    {"key": "kotlin", "name": "Kotlin", "needs": _GAMES},
    {"key": "swift", "name": "Swift", "needs": _GAMES},
    {"key": "go", "name": "Go", "needs": _GAMES},
    {"key": "rust", "name": "Rust", "needs": _GAMES},
    {"key": "ruby", "name": "Ruby", "needs": _GAMES},
    {"key": "php", "name": "PHP", "needs": _GAMES},
    {"key": "haxe", "name": "Haxe", "needs": _GAMES},
    {"key": "gml", "name": "GML (GameMaker)", "needs": _GAMES},
    # Unreal is reserved for StatZ, which is what makes C++ the StatZ language.
    {"key": "cpp", "name": "C++ (Unreal)", "needs": _CPP},
    {"key": "c", "name": "C", "needs": _CPP},
]

def languages_with_run_status():
    """OCC_LANGUAGES, each marked with whether the sandbox can actually run it.

    Seventeen languages are advertised and twelve have a runner — C# (Unity),
    GDScript (Godot), Swift, Haxe and GML have none. That is not a lie (OCC can
    WRITE Unity C# perfectly well without executing it) but nothing on screen
    drew the line, and the pills sit directly above a Run panel offering twelve.

    Derived from RUNNERS rather than typed twice, so adding a runner updates the
    list by itself and the two can never disagree again.
    """
    from .modal_sandbox import RUNNERS
    return [{**lang, "runs": lang["key"] in RUNNERS} for lang in OCC_LANGUAGES]


# Every image type OCC exports, .ico included as the spec calls out.
OCC_IMAGE_EXPORTS = [
    "png", "jpg", "jpeg", "webp", "gif", "bmp", "tiff", "svg", "ico",
    "heic", "avif", "psd", "tga", "exr",
]

# Which app an export is handed to, by media type. An export that lands nowhere
# is a dead end; this is the routing table that stops that.
#
# `app` is a tab the client MOUNTS, and `target` is a data-tour anchor inside
# it (or "" to land at the top — an anchor that does not exist makes the jump
# a tab switch that pretends to be a landing). The first version named
# `imagez` and `writez`, which are not tabs anywhere, and sent code to `occ`
# itself, so every one of those pills played the open-in sound and went
# nowhere. A media type with no real destination says so with an empty `app`
# and gets no "Open in" row — WorkZ's "Share to PostZ" is the door for those,
# and an honest absence beats a button onto nothing.
#
#   audio    -> DistributeZ  (a release is built from a track)
#   video    -> DirectZ      (the releases list)
#   document -> Sentence ConnectZ (the writer — a document goes to be rewritten)
#   game     -> GameZ
#   image    -> nothing mounted takes an image yet
#   code     -> nothing: OCC IS where code lives, and "open in OCC" from OCC
#               is the dead button
EXPORT_ROUTES = {
    "image": {"app": "", "target": "", "label": ""},
    "video": {"app": "directz", "target": "directz-releases", "label": "DirectZ"},
    "audio": {"app": "distributez", "target": "distributez-releases", "label": "DistributeZ"},
    "document": {"app": "sentenceconnectz", "target": "sentencez-write", "label": "Sentence ConnectZ"},
    "code": {"app": "", "target": "", "label": ""},
    "game": {"app": "gamez", "target": "", "label": "GameZ"},
}


# ---- The games taxonomy ----
#
# Verbatim from the spec, unabridged: 17 genres, 99 subgenres. Two entries in
# the source were written without their subgenre marker — "Tactical RPG" under
# Role-Playing and "Artillery" under Strategy — and both are plainly subgenres
# of the genre above them, so they are kept there rather than dropped or
# promoted. "Shoot 'Em Up" was marked as a genre in the middle of Shooter's
# subgenres; it is a genre in its own right in common use, so it stays one.
GAME_GENRES = [
    ("action", "Action", "🗡️", [
        "Platformer", "Hack and Slash", "Beat 'Em Up", "Roguelike / Roguelite",
        "Survival", "Flight Combat", "Vehicular Combat", "Run and Gun",
    ]),
    ("action_adventure", "Action-Adventure", "🧭", [
        "Open World / Sandbox", "Metroidvania", "Stealth", "Linear Action-Adventure",
    ]),
    ("adventure", "Adventure", "🗺️", [
        "Point-and-Click / Graphic Adventure", "Visual Novel", "Walking Simulator",
        "Narrative / Interactive Movie", "Text-Based / Interactive Fiction", "Escape Room",
    ]),
    ("shooter", "Shooter", "🔫", [
        "First-Person Shooter (FPS)", "Third-Person Shooter (TPS)", "Tactical Shooter",
        "Arena Shooter", "Hero Shooter", "Light Gun",
    ]),
    ("shmup", "Shoot 'Em Up (Shmup)", "🚀", [
        "Top-Down Shooter", "Battle Royale",
    ]),
    ("rpg", "Role-Playing (RPG)", "⚔️", [
        "Action RPG", "Turn-Based RPG", "JRPG", "MMORPG", "Tactical RPG",
        "Dungeon Crawler", "Soulslike", "Sandbox / Open World RPG",
    ]),
    ("strategy", "Strategy", "♟️", [
        "Real-Time Strategy (RTS)", "Real-Time Tactics (RTT)", "Turn-Based Strategy (TBS)",
        "Turn-Based Tactics (TBT)", "Tower Defense", "4X", "Grand Strategy / Wargame",
        "MOBA", "Auto-Battler / Auto Chess", "Artillery",
    ]),
    ("simulation", "Simulation", "🏗️", [
        "Life / Social Simulation", "City Builder / Construction", "Vehicle Simulation",
        "Flight Simulation", "Management / Business", "Farming Simulation", "Pet Raising",
    ]),
    ("sports", "Sports", "🏆", [
        "Football / Soccer", "American Football", "Basketball", "Baseball", "Golf",
        "Tennis", "Hockey", "Boxing / Combat Sports", "MMA / Wrestling",
        "Extreme Sports", "Olympic / Mixed Sports",
    ]),
    ("racing", "Racing", "🏎️", [
        "Arcade Racing", "Simulation Racing", "Kart Racing", "Futuristic Racing",
        "Combat Racing",
    ]),
    ("fighting", "Fighting", "🥊", [
        "Traditional 2D Fighter", "3D Fighter", "Arena Brawler / Party Fighter",
        "Hack and Slash Fighter",
    ]),
    ("puzzle", "Puzzle", "🧩", [
        "Logic Puzzle", "Physics-Based Puzzle", "Match-Three / Tile Matching",
        "Exploration Puzzle", "Word Construction", "Trivia / Quiz",
        "Falling Block (Tetris-style)",
    ]),
    ("horror", "Horror / Survival Horror", "👻", [
        "Psychological Horror", "Survival Horror", "Stealth Horror",
    ]),
    ("rhythm", "Rhythm / Music", "🎵", [
        "Peripheral-Based", "Rhythm Action", "Music Sandbox",
    ]),
    ("sandbox", "Sandbox / Open World", "🧱", [
        "Creative Sandbox", "Survival Sandbox", "Open World Survival Craft",
    ]),
    ("casual", "Casual / Idle", "🎲", [
        "Idle / Incremental", "Clicker", "Hyper-Casual", "Party Games",
        "Mini-Games", "Exergames",
    ]),
    ("other", "Other", "✨", [
        "Pinball", "Board Game / Card Game", "Dating Simulation",
        "Educational / Edutainment", "Programming Games", "Hidden Object",
    ]),
]

GAME_GENRE_KEYS = {key for key, _, _, _ in GAME_GENRES}
GAME_SUBGENRES = {sub for _, _, _, subs in GAME_GENRES for sub in subs}


def genre_of(subgenre):
    """Which genre a subgenre belongs to, or "" — so a game can be filed by
    subgenre alone and still appear under the right heading."""
    for key, _, _, subs in GAME_GENRES:
        if subgenre in subs:
            return key
    return ""


def languages_for(tier):
    """The languages this member may build in, and the ones they can see but
    not use — stated rather than hidden, so the upgrade has a reason."""
    allowed, locked = [], []
    # Carries `runs` so the client can say which of these the sandbox actually
    # executes — five of the seventeen it can only write.
    for lang in languages_with_run_status():
        (allowed if tier_at_least(tier, lang["needs"]) else locked).append(lang)
    return allowed, locked


def tabs_for(tier):
    """Every tab, each marked with whether this member may open it. The locked
    ones are RETURNED, not filtered out: a member should know what the tier
    above them has, and a menu that silently shrinks teaches nothing."""
    # `builds` stays in the response. It was put there on purpose — "a menu that
    # offers twenty tabs and delivers three is worse than a menu that offers
    # three" — and the client simply never read it, which is the same failure
    # one layer up. It is read now, alongside `open_in`, so the list says both
    # what stands behind a tab and where that tab opens.
    return [{**tab, "allowed": tier_at_least(tier, tab["needs"])} for tab in OCC_TABS]
