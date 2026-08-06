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
OCC_TABS = [
    {"key": "editor", "name": "Code editor", "emoji": "👁️‍🗨️", "needs": TIER_FREE,
     "desc": "Write and edit your files.", "builds": "editor"},
    {"key": "taskz", "name": "TaskZ", "emoji": "📑", "needs": TIER_FREE,
     "desc": "Tasks OCC has been set, with live status, an ETA, and an undo window.",
     "builds": "taskz"},
    {"key": "codez", "name": "CodeZ", "emoji": "🧩", "needs": TIER_FREE,
     "desc": "Your acronyms, typos and slang — what you meant, and how often you've typed it.",
     "builds": "codez"},
    {"key": "pathz", "name": "PathZ", "emoji": "🛤️", "needs": TIER_PREMIUM,
     "desc": "Your paths across devices.", "builds": "pathz"},
    {"key": "mistakez", "name": "MistakeZ", "emoji": "❌", "needs": TIER_FREE,
     "desc": "Errors the AI made here, kept so it doesn't make them twice.",
     "builds": "mistakez"},
    {"key": "habitz", "name": "HabitZ", "emoji": "🎂", "needs": TIER_FREE,
     "desc": "Something you repeat, noticed and kept.", "builds": "habitz"},
    {"key": "characterz", "name": "CharacterZ", "emoji": "🤔", "needs": TIER_PREMIUM,
     "desc": "MBTI characters attached to a FaceZ face, with a story and a voice.",
     "builds": "characterz"},
    {"key": "settings", "name": "Settings", "emoji": "⚙️", "needs": TIER_FREE,
     "desc": "AutomationZ and SuggestionZ live here.", "builds": "settings"},
    {"key": "console", "name": "Output / Console", "emoji": "🖥️", "needs": TIER_FREE,
     "desc": "What OCC printed.", "builds": "console"},
    {"key": "callz", "name": "CallZ", "emoji": "📞", "needs": TIER_STATZ,
     "desc": "Talk it through.", "builds": "callz"},
    {"key": "search", "name": "Search", "emoji": "🔍", "needs": TIER_FREE,
     "desc": "Across every tab.", "builds": "search"},
    {"key": "tellz", "name": "TellZ", "emoji": "🗣️", "needs": TIER_PREMIUM,
     "desc": "What you prompted or posted, per tab or across all of them.",
     "builds": "tellz"},
    {"key": "logz", "name": "LogZ", "emoji": "🪵", "needs": TIER_PREMIUM,
     "desc": "What was DONE, by day, week, month or a range you pick.",
     "builds": "logz"},
    {"key": "pickconnectz", "name": "Pick ConnectZ", "emoji": "📌", "needs": TIER_FREE,
     "desc": "Pin your favourites to the footer.", "builds": "pickconnectz"},
    {"key": "filez", "name": "FileZ", "emoji": "📁", "needs": TIER_FREE,
     "desc": "Files and uploads.", "builds": "filez"},
    {"key": "gitz", "name": "GitZ", "emoji": "🔀", "needs": TIER_STATZ,
     "desc": "Branches, commits and pushes — every one of them a TaskZ task.",
     "builds": "gitz"},
    {"key": "gamez", "name": "GameZ", "emoji": "🎮", "needs": TIER_PREMIUM,
     "desc": "Games you built here, by genre.", "builds": "gamez"},
    {"key": "spinaz", "name": "SpinaZ", "emoji": "🍥", "needs": TIER_FREE,
     "desc": "How you earned and spent it.", "builds": "spinaz"},
    {"key": "energy", "name": "Energy", "emoji": "⚡", "needs": TIER_FREE,
     "desc": "How you earned and spent it.", "builds": "energy"},
    {"key": "facez", "name": "FaceZ", "emoji": "🙄", "needs": TIER_FREE,
     "desc": "Faces available to AI images and video, taggable to a profile.",
     "builds": "facez"},
    {"key": "welcome", "name": "Welcome", "emoji": "👋", "needs": TIER_FREE,
     "desc": "Start here.", "builds": "welcome"},
]

# The two toggles the spec puts front and centre.
OCC_TOGGLES = [
    {"key": "automation", "name": "AutomationZ", "emoji": "🤖", "needs": TIER_STATZ,
     "desc": "Performs tasks with no confirmation. You're told in LogZ as it happens."},
    {"key": "suggestionz", "name": "SuggestionZ", "emoji": "💭", "needs": TIER_PREMIUM,
     "desc": "Adds tasks and explains what, why and how before anything runs."},
]

# Languages you may build a game in. Unreal/C++ is the StatZ reservation.
OCC_LANGUAGES = [
    {"key": "python", "name": "Python", "needs": TIER_PREMIUM},
    {"key": "javascript", "name": "JavaScript", "needs": TIER_PREMIUM},
    {"key": "typescript", "name": "TypeScript", "needs": TIER_PREMIUM},
    {"key": "csharp", "name": "C# (Unity)", "needs": TIER_PREMIUM},
    {"key": "gdscript", "name": "GDScript (Godot)", "needs": TIER_PREMIUM},
    {"key": "lua", "name": "Lua", "needs": TIER_PREMIUM},
    {"key": "java", "name": "Java", "needs": TIER_PREMIUM},
    {"key": "kotlin", "name": "Kotlin", "needs": TIER_PREMIUM},
    {"key": "swift", "name": "Swift", "needs": TIER_PREMIUM},
    {"key": "go", "name": "Go", "needs": TIER_PREMIUM},
    {"key": "rust", "name": "Rust", "needs": TIER_PREMIUM},
    {"key": "ruby", "name": "Ruby", "needs": TIER_PREMIUM},
    {"key": "php", "name": "PHP", "needs": TIER_PREMIUM},
    {"key": "haxe", "name": "Haxe", "needs": TIER_PREMIUM},
    {"key": "gml", "name": "GML (GameMaker)", "needs": TIER_PREMIUM},
    # Unreal is reserved for StatZ, which is what makes C++ the StatZ language.
    {"key": "cpp", "name": "C++ (Unreal)", "needs": TIER_STATZ},
    {"key": "c", "name": "C", "needs": TIER_STATZ},
]

# Every image type OCC exports, .ico included as the spec calls out.
OCC_IMAGE_EXPORTS = [
    "png", "jpg", "jpeg", "webp", "gif", "bmp", "tiff", "svg", "ico",
    "heic", "avif", "psd", "tga", "exr",
]

# Which intelligence app an export is handed to, by media type. An export that
# lands nowhere is a dead end; this is the routing table that stops that.
EXPORT_ROUTES = {
    "image": {"app": "imagez", "target": "imagez:library"},
    "video": {"app": "directz", "target": "directz:works"},
    "audio": {"app": "distributez", "target": "distributez:tracks"},
    "document": {"app": "writez", "target": "writez:docs"},
    "code": {"app": "occ", "target": "occ:filez"},
    "game": {"app": "gamez", "target": "gamez:mine"},
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
    for lang in OCC_LANGUAGES:
        (allowed if tier_at_least(tier, lang["needs"]) else locked).append(lang)
    return allowed, locked


def tabs_for(tier):
    """Every tab, each marked with whether this member may open it. The locked
    ones are RETURNED, not filtered out: a member should know what the tier
    above them has, and a menu that silently shrinks teaches nothing."""
    return [{**tab, "allowed": tier_at_least(tier, tab["needs"])} for tab in OCC_TABS]
