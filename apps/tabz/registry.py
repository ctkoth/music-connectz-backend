"""The tab + modal map, transcribed from Corey's spec.

Two shapes, exactly as written:

    =Name 🙂  a TAB    — gets its own URL
    +Name 🙂  a MODAL  — lives inside a tab, opens when its icon is tapped

Every tab's URL is the name lowercased with a trailing "Z" dropped, per the
spec: BattleZ -> /battle, CollabZ -> /collab, SingZ -> /sing. `url_for` does
that transformation rather than each row hardcoding it, so a renamed tab can't
drift from its route.

`icon` is the emoji Corey supplied. Where he didn't supply one it is None and
`audit()` reports it — that list is the answer to "what icons am I missing",
computed rather than eyeballed.

`blurb` is Corey's own description, kept close to his words. The frontend shows
it in the modal that the icon opens.
"""

# Tier keys reused from the economy so a gate here can't drift from a gate there.
FREE, PREMIUM, STATZ = "free", "premium", "statz"


def url_for(name):
    """BattleZ -> battle. SingZ -> sing. Social ConnectZ -> socialconnect.

    The spec's rule is "named after the tab, -Z at the end". Applied literally:
    strip a trailing Z, drop spaces, lowercase.
    """
    slug = name.strip()
    if slug.lower().endswith("z") and len(slug) > 1:
        slug = slug[:-1]
    return "".join(ch for ch in slug.lower() if ch.isalnum())


def tab(name, icon, blurb, modals=(), tier=FREE, note="", url=None):
    """`url` overrides the derived slug for the few names where the literal
    rule reads badly — RoyaltieZ would otherwise be /royaltie."""
    return {"kind": "tab", "name": name, "icon": icon, "blurb": blurb,
            "url": url or ("/" + url_for(name)), "tier": tier, "note": note,
            "modals": [dict(m, kind="modal") for m in modals]}


def modal(name, icon, blurb, tier=FREE, note=""):
    return {"name": name, "icon": icon, "blurb": blurb, "tier": tier, "note": note}


# --------------------------------------------------------------------- tabs --
# Ordered the way Corey listed them, not alphabetically — the order is the
# product's opinion about what matters.
TABS = [
    tab("Home", None, "Where you land. Your feed, your balances, what's moving.",
        note="No emoji supplied — only the URL /home was given."),

    tab("CollabZ", "🤝",
        "Collaborate with other users, manage collab projects.",
        modals=[
            modal("OriginalZ", None, "Unique songz — collaborate on something "
                                     "that isn't a cover or a remix.",
                  note="Revealed by the artwork you sent; it has no line in the "
                       "written spec, so it has no emoji or description yet."),
            modal("CoverZ", "🫴🏼", "Covers of songs, or redraw existing art."),
            modal("RemixeZ", "🔄", "Remixing posts and songz."),
        ]),

    tab("BattleZ", "🪖",
        "One post vs another post. Contestants verified 18+ can bet money on "
        "themselves; everyone else bets spinaz.",
        modals=[
            modal("Freestyle", "🆓", "Live sporadic battles."),
            modal("1v1", "1️⃣", "One artist versus one artist, regardless of "
                                "other personas helping."),
            modal("Battle Cypher", "🧑‍🤝‍🧑",
                  "More than one artist vs more than one artist, with other "
                  "personas helping."),
        ]),

    tab("Social ConnectZ", "💓", "Meet people — to date, or to work with.",
        url="/social",
        modals=[
            modal("VibeZ", "♥️", "Plenty-of-fish style dating/collab, with a "
                                 "clear indication of what you're looking for: "
                                 "romance, or a partnership."),
            modal("Inferno", "❤️‍🔥", "Tinder style dating/collab, with a clear "
                                     "indication of romance or a quick collab."),
            modal("BoardZ", "🪧", "Message boards."),
            modal("PersonalitieZ", "😶", "MBTI tests, simple and complex."),
        ]),

    tab("MessageZ", "📨", "Your mail.",
        modals=[
            modal("Inbox", None, "What came in.",
                  note="No emoji supplied."),
            modal("Outbox", None, "What you sent.",
                  note="No emoji supplied."),
        ]),

    tab("CallZ", "📞",
        "Calling. Needs a cash balance — spinaz say \"coming soon\" and offer "
        "to top up.", tier=STATZ,
        modals=[
            modal("AI", "🤖", "Costs whatever the model you pick costs."),
            modal("User", "🗣️", "Costs the other member's skill rate per hour."),
        ]),

    tab("BugZ", "🐞",
        "Submit a bug as a post. Only admins move it to In progress 💭 or "
        "Squashed 🪦 — squashed pays the reporter 200 spinaz."),

    tab("DistributeZ", "🎶",
        "Distribution built out of your posts: audio becomes the track, an "
        "image becomes the cover, text becomes the lyrics. Free gets one "
        "submission a month; Premium and StatZ are unlimited, and StatZ can "
        "submit for licensing."),

    tab("RoyaltieZ", "👑",
        "Current balance and logz, every source timestamped. The developer "
        "takes 5% on all transactions as developer tax.", url="/royalties"),

    tab("GroupZ", "👥",
        "Posts that combine other members into editable groups, local to you: "
        "Friends 🙂, Fans 👋🏽, Partners 👏🏽, Blocked 🤚🏽, and Custom ❓."),

    tab("LabelZ", "🏷️",
        "Public groups. Needs a Premium A&R Scout or Manager persona to create "
        "or edit. Gives advances with terms, and e-signed contracts.",
        tier=PREMIUM),

    tab("ToolZ", "💡", "The apps you work in.",
        modals=[
            modal("Key ConnectZ", "⌨️",
                  "System keyboard on mobile, floating on desktop — ctrl+shift+K "
                  "opens it. Custom background image, speech-to-text, and "
                  "translation into whatever language you want out."),
            modal("SentenceZ", "📃", "Word knockoff. All text media opens here."),
            modal("ImageZ", "🖼️", "Photoshop knockoff. All image media opens here."),
            modal("VideoZ", "📹", "Sony Vegas knockoff. All video media opens here."),
            modal("Lilith", "💃🏽", "Things-style project management."),
            modal("SingZ", "👩🏼‍🎤", "Vocal training, organised like Lilith."),
            modal("RapZ", "👨🏼‍🎤", "Rap training, organised like Lilith."),
            modal("BodieZ", "💪🏽", "Jefit metrics behind Lilith's organisation."),
            modal("Parcel Primate", "🐵", "Mailchimp knockoff."),
            modal("Builder", "🏗️", "Buffer knockoff — post management."),
            modal("Sonday", "🌞", "Monday.com knockoff."),
            modal("Clean ConnectZ", "🧹",
                  "Device cleaner. StatZ points it at a device or a path, sets a "
                  "target percent ❇️ or target size ⚖️, and it picks what to "
                  "delete by priority ‼️, size 📐, or frequency ☢️.", tier=STATZ),
        ]),

    tab("Intelligence", "🧠",
        "Everything AI-made. Corey Knap is credited in the applicable role, "
        "output stays inside posts, and the splits are shown up front.",
        modals=[
            modal("Sentence ConnectZ", "📃",
                  "Documents, LyricZ, EssayZ ⌨️, ContractZ 🤝, guitar tabs and "
                  "sheet music."),
            modal("Image ConnectZ", "👨🏽‍🎨",
                  "Song covers, album covers, portraits, profile and promo pictures."),
            modal("Instrumental ConnectZ", "🎹", "Beats and instrumentals."),
            modal("Mix ConnectZ", "🎚️", "Mixes."),
            modal("Video ConnectZ", "📺", "Music videoz and introduction videoz."),
            modal("ReelZ", "⏪", "Short cuts — up to 3 minutes."),
            modal("EpisodeZ", "📺", "Series, episode by episode. 60 minute limit."),
            modal("MovieZ", "🎥", "Features. 1–3 hours."),
            modal("MangaZ", "📚",
                  "Design manga with your CharacterZ — write by hand, paste a "
                  "script for the AI to lay out, or let it write from a "
                  "character's bio and MBTI. Any age can collab; rooms with "
                  "under-18s have a verified adult supervising. AI-made "
                  "MangaZ pays an extra 10% developer royalty."),
            modal("CharacterZ", "🐆",
                  "FaceZ with personalitieZ — bio, MBTI, traits and voice, so "
                  "the AI writes them the same way twice."),
            modal("Ocular Code ConnectZ", "👁️‍🗨️",
                  "Visual Studio knockoff — OCC with its own tab map."),
            modal("Rate ConnectZ", "📨🤔",
                  "Rates images on artistic value or attractiveness, text on wit, "
                  "audio on mix and performance, video on performance and artistry. "
                  "Raters get 1 energy per rating."),
        ]),

    tab("VenueZ", "🏛️", "Host or join events — collaborative or performance."),

    tab("VSTZ", "🔌",
        "The plugins you own. Toggle your rack, then find members who have what "
        "your session needs. Native plugins can't run in a browser — this is for "
        "matching, and the desktop app is what loads them."),

    tab("DawZ", "🎛️", "Digital audio workstations, filtered by the VSTs you own.",
        modals=[
            modal("Fruity Möbius", "🍑", "FL Studio knockoff."),
            modal("Arsenal", "⚔️", "Avid Pro Tools knockoff."),
            modal("Witchcraft", "🔮", "Acoustica Mixcraft knockoff."),
            modal("Trump Toupee", "🤵🏼‍♂️", "Bitwig knockoff."),
            modal("Azrael", "☠️", "Reaper knockoff."),
            modal("Intuition", "🤔", "Logic knockoff."),
            modal("FormulaWon", "🚦", "GarageBand knockoff.",
                  note="Written without a leading + in the spec; treated as a "
                       "DawZ modal like its siblings."),
        ]),

    tab("GameZ", "👾",
        "Games members built in OCC, sorted by genre and subgenre. StatZ can "
        "use any language including C++ for Unreal; Premium gets every language "
        "except C++."),

    tab("SpinaZ", "🍥",
        "Logz of how spinaz were earned and spent. Buy at 80% — 100 costs $80. "
        "Streaming another member's media pays (seconds played − 30)."),

    tab("Energy", "⚡", "Logz of how energy was earned and spent. Buy at 80%."),

    tab("FaceZ", "🙄",
        "Faces available for AI-generated images and videos, taggable by profile."),

    tab("Pick ConnectZ", "📌",
        "Footer customisation — pin your favourite features. Free picks 2 and "
        "AI fills the rest; Premium and StatZ pick as many as they like."),

    tab("FileZ", "📁", "File management and uploads."),

    tab("Analytics", "📈", "Deep dive into usage and performance."),

    tab("Onboarding", "🛂", "Account setup and verification."),

    tab("Profile", "👤",
        "Username, first/middle/last name. Birthday, email, phone and location "
        "are required.",
        modals=[
            modal("SocialZ", "🌐",
                  "Linked OAuth and distribution accounts — Google, Apple, "
                  "Spotify and the rest."),
        ]),

    tab("PersonaZ", "🎭",
        "Your creative personas, and the skills they carry, dated from when you "
        "started."),

    tab("CodeZ", "🧩",
        "Acronyms, typos and slang you type that mean something else, with a "
        "tally of how often, sortable either way."),

    tab("PathZ", "🛤️", "Your paths on every device, CRUD across all of them."),

    tab("MistakeZ", "😢", "Errors the AI made, kept so it doesn't repeat them."),

    tab("HabitZ", "🫠",
        "Something you repeat, noted for what it says about you. Detected by AI."),

    tab("SettingZ", "⚙️", "Your preferences.",
        modals=[
            modal("Default Language", "🗺️",
                  "Transcreates the whole site, posts and apps into your "
                  "language, split by region, with a flag for everything."),
            modal("Incognito", "🕵️‍♂️",
                  "Privacy and anonymous mode, toggleable per post, per tab, or "
                  "globally.", tier=PREMIUM),
            modal("Theme", None, "Theme colour and emoji, editable by Premium "
                                 "and StatZ.", tier=PREMIUM,
                  note="No emoji supplied."),
            modal("2FA / Security", "🔒", "Two-factor authentication and security."),
        ]),

    tab("TellZ", "🗣️",
        "Logs of what you prompted or posted, per tab or across all of them."),

    tab("MoodZ", "😅", "Your mood when you posted."),

    tab("LogZ", "🪵",
        "What was done, by day, week, month, or a range you pick. Detailed 🖇️ "
        "word-for-word, or Summary 📎."),

    tab("PostZ", "🪧",
        "Everything you put out. Visibility 👁️ is Public 👀, Restricted 🛑, "
        "Private 🔏, or GroupZ 👥."),

    tab("Welcome", "👋", "The front door."),
]


# ------------------------------------------------- OCC's own internal tabs --
# Ocular Code ConnectZ is a modal that contains a whole tab map of its own.
OCC_TABS = [
    tab("Code Editor", "👁️‍🗨️", "Where the code is."),
    tab("TaskZ", "📑",
        "Defined tasks OCC has already done, with live updates and an ETA on "
        "each, undoable inside your edit window."),
    tab("CodeZ", "🧩", "Acronyms, typos and slang, tallied."),
    tab("PathZ", "🛤️", "Your paths across devices."),
    tab("MistakeZ", "😢", "Errors to not repeat."),
    tab("HabitZ", "🫠", "What you repeat, and why it matters."),
    tab("Settings", "⚙️", "OCC's own switches.",
        modals=[
            modal("Automated", "🤖",
                  "Performs taskz with no confirmation, updating you live in "
                  "logz.", tier=STATZ),
            modal("SuggestionZ", "💭",
                  "Adds taskz explaining what, why and how.", tier=STATZ),
        ]),
    tab("Output", "🖥️", "The console."),
    tab("CallZ", "📞", "Calls from inside OCC.", tier=STATZ),
    tab("Search", "🔍", "Find anything."),
    tab("TellZ", "🗣️", "What you prompted, per tab or across all.", tier=STATZ),
    tab("LogZ", "🪵", "What got done, by range."),
]


def all_tabs():
    return TABS


def find(name, tabs=None):
    key = url_for(name)
    for t in (tabs if tabs is not None else TABS):
        if url_for(t["name"]) == key:
            return t
    return None


def audit(tabs=None):
    """Everything the spec left out, computed from the registry itself.

    Returns {"missing_icons": [...], "duplicate_urls": [...], "notes": [...]}.
    A hand-written list of gaps rots the moment a row changes; this can't.
    """
    rows = tabs if tabs is not None else TABS
    missing, notes, seen, dupes = [], [], {}, []

    def visit(entry, parent=None):
        label = f"{parent} → {entry['name']}" if parent else entry["name"]
        if not entry.get("icon"):
            missing.append({"where": label, "kind": entry["kind"],
                            "note": entry.get("note", "")})
        if entry.get("note"):
            notes.append({"where": label, "note": entry["note"]})

    for t in rows:
        visit(t)
        url = t["url"]
        if url in seen:
            dupes.append({"url": url, "tabs": [seen[url], t["name"]]})
        else:
            seen[url] = t["name"]
        for m in t["modals"]:
            visit(m, parent=t["name"])

    return {"missing_icons": missing, "duplicate_urls": dupes, "notes": notes,
            "tab_count": len(rows),
            "modal_count": sum(len(t["modals"]) for t in rows)}


def payload(include_occ=True):
    out = {"tabs": TABS, "audit": audit()}
    if include_occ:
        out["occ_tabs"] = OCC_TABS
        out["occ_audit"] = audit(OCC_TABS)
    return out
