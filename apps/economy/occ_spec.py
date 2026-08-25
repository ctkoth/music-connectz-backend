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
# `open_in` says which APP a tab opens; `target` says which CONTROL inside it.
# The client used to build that second half itself, from `occ:<key>`, and
# nothing in the frontend has ever carried an `occ:` anchor — so every Open →
# switched tabs, hunted for an anchor that could not exist, and dropped the
# member at the top of the destination. That is the tab switch wearing a
# handoff's clothes that `goto.js` was written to stop.
#
# So the target is named HERE, next to the app it belongs to, and it is a real
# `data-tour="…"` anchor the destination renders. Two of them (occ-run,
# occ-workz) already existed for the guided tour; the rest were added with this
# field, one anchor serving the tour and this list both so they can't drift.
#
# A tab with nothing behind it yet gets NEITHER field and renders as "Not built
# yet" — which is why Pick ConnectZ gained both: the dock ships, so saying it
# doesn't was the list being wrong about its own app.
OCC_TABS = [
    {"key": "editor", "open_in": "occ", "target": "occ-run", "icon": "editor.png", "name": "Code editor", "emoji": "👁️‍🗨️", "needs": TIER_FREE,
     "desc": "Write and edit your files.", "builds": "editor"},
    {"key": "taskz", "open_in": "occ", "target": "occ-taskz", "icon": "taskz.png", "name": "TaskZ", "emoji": "📑", "needs": TIER_FREE,
     "desc": "Tasks OCC has been set, with live status, an ETA, and an undo window.",
     "builds": "taskz"},
    # Not in the original list of twenty-one: added because an OCC result that
    # can't be shown, rated or carried anywhere is a dead end, and nothing here
    # is allowed to be one. WorkZ is where what you gave OCC and what it gave
    # back are kept, in the PostZ format, ready to post.
    {"key": "workz", "open_in": "occ", "target": "occ-workz", "icon": "workz.png", "name": "WorkZ", "emoji": "🧾", "needs": TIER_FREE,
     "desc": "What you gave OCC and what it gave back — post it, rate it, or take it "
             "into another app.", "builds": "workz"},
    {"key": "codez", "open_in": "habitz", "target": "habitz-kind-code", "icon": "codez.png", "name": "CodeZ", "emoji": "🧩", "needs": TIER_FREE,
     "desc": "Your acronyms, typos and slang — what you meant, and how often you've typed it.",
     "builds": "codez"},
    {"key": "pathz", "open_in": "habitz", "target": "habitz-kind-path", "icon": "pathz.png", "name": "PathZ", "emoji": "🛤️", "needs": TIER_PREMIUM,
     "desc": "Your paths across devices.", "builds": "pathz"},
    {"key": "mistakez", "open_in": "habitz", "target": "habitz-kind-mistake", "icon": "mistakez.png", "name": "MistakeZ", "emoji": "❌", "needs": TIER_FREE,
     "desc": "Errors the AI made here, kept so it doesn't make them twice.",
     "builds": "mistakez"},
    {"key": "habitz", "open_in": "habitz", "target": "habitz-kind-habit", "icon": "habitz.png", "name": "HabitZ", "emoji": "🎂", "needs": TIER_FREE,
     "desc": "Something you repeat, noticed and kept.", "builds": "habitz"},
    {"key": "characterz", "icon": "characterz.png", "name": "CharacterZ", "emoji": "🤔", "needs": TIER_PREMIUM,
     "desc": "MBTI characters attached to a FaceZ face, with a story and a voice.",
     "builds": "characterz"},
    {"key": "settings", "open_in": "occ", "target": "occ-settings", "icon": "preferencez.png", "name": "Settings", "emoji": "⚙️", "needs": TIER_FREE,
     "desc": "AutomationZ and SuggestionZ live here.", "builds": "settings"},
    {"key": "console", "open_in": "occ", "target": "occ-console", "icon": "console.png", "name": "Output / Console", "emoji": "🖥️", "needs": TIER_FREE,
     "desc": "What OCC printed.", "builds": "console"},
    {"key": "callz", "icon": "callz.png", "name": "CallZ", "emoji": "📞", "needs": TIER_STATZ,
     "desc": "Talk it through.", "builds": "callz"},
    {"key": "search", "open_in": "social", "target": "social-search", "icon": "search.png", "name": "Search", "emoji": "🔍", "needs": TIER_FREE,
     "desc": "Across every tab.", "builds": "search"},
    {"key": "tellz", "icon": "tellz.png", "name": "TellZ", "emoji": "🗣️", "needs": TIER_PREMIUM,
     "desc": "What you prompted or posted, per tab or across all of them.",
     "builds": "tellz"},
    {"key": "logz", "open_in": "logz", "target": "logz-entries", "icon": "logz.png", "name": "LogZ", "emoji": "🪵", "needs": TIER_PREMIUM,
     "desc": "What was DONE, by day, week, month or a range you pick.",
     "builds": "logz"},
    {"key": "pickconnectz", "open_in": "occ", "target": "occ-pickconnectz", "icon": "pickconz.png", "name": "Pick ConnectZ", "emoji": "📌", "needs": TIER_FREE,
     "desc": "Pin your favourites to the footer.", "builds": "pickconnectz"},
    {"key": "filez", "open_in": "occ", "target": "occ-filez", "icon": "filez.png", "name": "FileZ", "emoji": "📁", "needs": TIER_FREE,
     "desc": "Files and uploads.", "builds": "filez"},
    {"key": "gitz", "icon": "gitz.png", "name": "GitZ", "emoji": "🔀", "needs": TIER_STATZ,
     "desc": "Branches, commits and pushes — every one of them a TaskZ task.",
     "builds": "gitz"},
    {"key": "gamez", "icon": "gamez.png", "name": "GameZ", "emoji": "🎮", "needs": TIER_PREMIUM,
     "desc": "Games you built here, by genre.", "builds": "gamez"},
    {"key": "spinaz", "open_in": "logz", "target": "logz-resource-spinaz", "icon": "spinaz.png", "name": "SpinaZ", "emoji": "🍥", "needs": TIER_FREE,
     "desc": "How you earned and spent it.", "builds": "spinaz"},
    {"key": "energy", "open_in": "logz", "target": "logz-resource-energy", "icon": "energy.png", "name": "Energy", "emoji": "⚡", "needs": TIER_FREE,
     "desc": "How you earned and spent it.", "builds": "energy"},
    {"key": "facez", "open_in": "profilez", "target": "profilez-facez", "icon": "facez.png", "name": "FaceZ", "emoji": "🙄", "needs": TIER_FREE,
     "desc": "Faces available to AI images and video, taggable to a profile.",
     "builds": "facez"},
    {"key": "welcome", "open_in": "occ", "target": "occ-welcome", "icon": "welcome.png", "name": "Welcome", "emoji": "👋", "needs": TIER_FREE,
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
    # one layer up. It is read now, alongside `open_in` and `target`, so the
    # list says what stands behind a tab, where that tab opens, and which
    # control it opens ON.
    return [{**tab, "allowed": tier_at_least(tier, tab["needs"])} for tab in OCC_TABS]
