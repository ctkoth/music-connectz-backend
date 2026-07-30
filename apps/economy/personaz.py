"""PersonaZ — the canonical persona and skill catalog.

Until now this lived only in the frontend, as a hand-maintained JavaScript object
(`instrumentDatabase` in the v2.2/2.3 build). Nothing checked it, so it drifted:
persona buttons passed keys the database didn't have, two entries were corrupted
into JavaScript syntax errors, and three personas were named in the UI with no
skills defined at all. Full findings in PERSONAZ_AUDIT.md.

This module is the fix — one source of truth, served over the API, with tests
that re-run the audit on every commit.

THE PARADIGM (every persona follows it, old and new):

    persona key -> categories -> {skill key: "Display Label + emoji"}

* Two or more categories. Convention is a *tools* category (what you work in)
  plus a *craft* category (what you can do) — `artist` instead splits by
  instrument family, which is the same idea one level finer.
* Every category opens with an "Any …" wildcard, so a member can claim a
  category without enumerating it. The client renders these differently (the
  amber `.any-skill` style) and they must stay first.
* The label is what a member sees and what gets stored on their profile; the key
  is the stable identifier. They differ where the brand name is longer than the
  menu entry ("Photoshop" -> "Adobe Photoshop 🎨").

The five 2.2 personas carry their skills **verbatim** from that build — same
keys, same labels, same emoji, same order — because members have already picked
them and stored labels on their profiles. The only edits are the two corrupted
entries, called out inline.
"""

# Skills for the personas that shipped in 2.2, preserved exactly.
_ARTIST = {
    "String Instruments": {
        "Any String": "Any String 🎸",
        "Acoustic Guitar": "Acoustic Guitar 🎸",
        "Electric Guitar": "Electric Guitar 🎸",
        "Bass Guitar": "Bass Guitar 🎸",
        "Ukulele": "Ukulele 🎸",
        "Banjo": "Banjo 🎸",
        "Mandolin": "Mandolin 🎸",
        "Violin": "Violin 🎻",
        "Viola": "Viola 🎻",
        "Cello": "Cello 🎻",
        "Double Bass": "Double Bass 🎻",
        "Harp": "Harp 🎵",
    },
    "Keyboard Instruments": {
        "Any Keyboard": "Any Keyboard 🎹",
        "Acoustic Piano": "Acoustic Piano 🎹",
        "Digital Piano": "Digital Piano 🎹",
        "Synthesizer": "Synthesizer 🎹",
        "Organ": "Organ 🎹",
        "Harpsichord": "Harpsichord 🎹",
        "Accordion": "Accordion 🎹",
    },
    "Percussion Instruments": {
        "Any Percussion": "Any Percussion 🥁",
        "Drums (Snare)": "Drums (Snare) 🥁",
        "Drums (Bass)": "Drums (Bass) 🥁",
        "Drums (Bongo)": "Drums (Bongo) 🥁",
        "Cymbals": "Cymbals 🥁",
        # Added after the 2.2 audit (#12). The 2.2 list had no full kit and no
        # hand percussion, so a drummer could register a snare but not the
        # instrument they actually play. Nothing above was changed or removed.
        "Full Drum Kit": "Full Drum Kit 🥁",
        "Hi-Hat": "Hi-Hat 🥁",
        "Congas": "Congas 🪘",
        "Djembe": "Djembe 🪘",
        "Timbales": "Timbales 🥁",
        "Cajón": "Cajón 🪘",
        "Tambourine": "Tambourine 🎶",
        "Shaker": "Shaker 🎶",
        "Marimba": "Marimba 🎹",
        "Steel Drum": "Steel Drum 🛢️",
        "Electronic Drum Pad": "Electronic Drum Pad 🎛️",
    },
    # Added after the 2.2 audit (#12). 2.2 covered strings, keys, percussion,
    # rapping and singing — so a saxophonist, trumpeter or flautist had nowhere
    # to put their instrument at all. Two new families, same paradigm.
    "Wind & Woodwind": {
        "Any Wind": "Any Wind 🎷",
        "Saxophone (Alto)": "Saxophone (Alto) 🎷",
        "Saxophone (Tenor)": "Saxophone (Tenor) 🎷",
        "Saxophone (Soprano)": "Saxophone (Soprano) 🎷",
        "Saxophone (Baritone)": "Saxophone (Baritone) 🎷",
        "Flute": "Flute 🪈",
        "Piccolo": "Piccolo 🪈",
        "Clarinet": "Clarinet 🎼",
        "Bass Clarinet": "Bass Clarinet 🎼",
        "Oboe": "Oboe 🎼",
        "Bassoon": "Bassoon 🎼",
        "Recorder": "Recorder 🪈",
        "Harmonica": "Harmonica 🎵",
        "Bagpipes": "Bagpipes 🏴",
        "Pan Flute": "Pan Flute 🪈",
    },
    "Brass Instruments": {
        "Any Brass": "Any Brass 🎺",
        "Trumpet": "Trumpet 🎺",
        "Cornet": "Cornet 🎺",
        "Trombone": "Trombone 🎺",
        "Bass Trombone": "Bass Trombone 🎺",
        "French Horn": "French Horn 📯",
        "Tuba": "Tuba 🎺",
        "Euphonium": "Euphonium 🎺",
        "Flugelhorn": "Flugelhorn 🎺",
        "Sousaphone": "Sousaphone 🎺",
    },
    # Producing live is performing. 2.2 had no place for a DJ or a beat-machine
    # player under `artist` at all — they had to claim the producer persona even
    # when the skill in question is a stage skill.
    "Electronic & DJ": {
        "Any Electronic": "Any Electronic 🎛️",
        "DJ Decks": "DJ Decks 🎧",
        "Turntablism": "Turntablism 💿",
        "Beatboxing": "Beatboxing 🎤",
        "Drum Machine": "Drum Machine 🥁",
        "MPC / Sampler": "MPC / Sampler 🎛️",
        "MIDI Controller": "MIDI Controller 🎹",
        "Launchpad": "Launchpad 🟩",
        "Modular Synth": "Modular Synth 🔌",
        "Vocoder / Talkbox": "Vocoder / Talkbox 🗣️",
        "Theremin": "Theremin 📡",
    },
    "Rapping": {
        "Any Rapping": "Any Rapping 🎤",
        "Alternative Rap": "Alternative Rap 🎸",
        "Boom Bap": "Boom Bap 🥁",
        "Chopper": "Chopper 🚁",
        "Cloud Rap": "Cloud Rap ☁️",
        "Conscious Rap": "Conscious Rap 🧠",
        "Crunk": "Crunk 🔥",
        "Drill": "Drill ⚔️",
        "Emo Rap": "Emo Rap 🖤",
        "G-Funk": "G-Funk 🌴",
        "Gangsta Rap": "Gangsta Rap ⛓️",
        "Hardcore Hip Hop": "Hardcore Hip Hop 🎤",
        "Jazz Rap": "Jazz Rap 🎷",
        "Mumble Rap": "Mumble Rap 💤",
        "Old School": "Old School 📻",
        "Snap": "Snap 🫰",
        "Trap": "Trap 🏚️",
    },
    "Singing": {
        "Any Singing": "Any Singing 🎶",
        "Bass": "Bass 🧔‍♂️",
        "Baritone": "Baritone 🎙️",
        "Tenor": "Tenor 🎤",
        "Countertenor": "Countertenor 🕊️",
        "Contralto": "Contralto 🎻",
        "Alto": "Alto 🎶",
        "Mezzo-Soprano": "Mezzo-Soprano 🌊",
        "Soprano": "Soprano ☀️",
    },
}

# Shared by producer and mix-engineer in 2.2 — the same list, so it lives once.
#
# REPAIRED: the mix-engineer copy of this list had `Reaper:'Reaper🪦': 'Azrael☠️'`
# in it, which is not valid JavaScript. It threw a SyntaxError at parse time and
# took the entire app script down with it. The producer copy was intact, so it is
# the one reproduced here. Its "Studio One1⃣ 🎛️" typo is corrected too.
_MUSIC_DAWS = {
    "Any DAW": "Any DAW 🎛️",
    "Ableton Live": "Ableton Live 🎵",
    "Adobe Audition": "Adobe Audition 🎙️",
    "Audacity": "Audacity 🎧",
    "Bitwig Studio": "Bitwig Studio 🎚️",
    "Cakewalk": "Cakewalk 🎼",
    "Cubase": "Cubase 🎛️",
    "FL Studio": "FL Studio 🎚️",
    "GarageBand": "GarageBand 🎵",
    "Logic Pro": "Logic Pro 🎵",
    "Luna": "Luna ☁️",
    "Mixcraft": "Mixcraft 🎚️",
    # NOTE: "PreSonus Studio One" and "Studio One" are the same product. Both are
    # kept because both shipped in 2.2 and members may have picked either.
    # See PERSONAZ_AUDIT.md #6 for the one-line dedupe when you want it.
    "PreSonus Studio One": "PreSonus Studio One 🎛️",
    "Pro Tools": "Pro Tools 🎙️",
    "Reason": "Reason 🎛️",
    "Reaper": "Reaper 🔧",
    "Studio One": "Studio One 🎛️",
    "Waveform Pro": "Waveform Pro 📊",
}


# ---------------------------------------------------------------- the catalog
PERSONAZ = {
    # ------------------------------------------------ shipped in 2.2
    "artist": {
        "name": "Artist",
        "emoji": "🎤",
        "since": "2.2",
        "blurb": "You perform. Instruments, bars, or voice.",
        "categories": _ARTIST,
    },
    "producer": {
        "name": "Beat Producer",
        "emoji": "🎚️",
        "since": "2.2",
        "blurb": "You build the track — beats, sounds, arrangement.",
        "categories": {
            "Music DAWs": _MUSIC_DAWS,
            "Production Techniques": {
                "Any Production": "Any Production 🎚️",
                "Beat Making": "Beat Making 🎚️",
                "Sampling": "Sampling 🎵",
                "Sound Design": "Sound Design 🎛️",
                "Arrangement": "Arrangement 🎼",
                "Synthesis": "Synthesis 🎹",
            },
        },
    },
    "mix-engineer": {
        "name": "Mix Engineer",
        "emoji": "🎛️",
        "since": "2.2",
        "blurb": "You make it sit right — mix, master, the technical ear.",
        "categories": {
            "Music DAWs": _MUSIC_DAWS,
            "Engineering Skills": {
                "Any Engineering": "Any Engineering 🎛️",
                "Mixing": "Mixing 🎛️",
                "Mastering": "Mastering 🎙️",
                "EQ": "EQ 📊",
                "Compression": "Compression 🔧",
                "Reverb/Effects": "Reverb/Effects ✨",
            },
        },
    },
    "designer": {
        "name": "Designer",
        "emoji": "🎨",
        "since": "2.2",
        "blurb": "You make it look like something — covers, brand, layout.",
        "categories": {
            "Design Software": {
                "Any Design Software": "Any Design Software 🎨",
                "Photoshop": "Adobe Photoshop 🎨",
                "Illustrator": "Adobe Illustrator 🖌️",
                "Figma": "Figma 🎯",
                "Canva": "Canva 🌈",
                "Affinity Designer": "Affinity Designer ✨",
                "CorelDRAW": "CorelDRAW 🎨",
                "Sketch": "Sketch 📐",
                "InDesign": "Adobe InDesign 📄",
            },
            "Design Skills": {
                "Any Design Skill": "Any Design Skill 🎨",
                "UI/UX Design": "UI/UX Design 🎯",
                "Graphic Design": "Graphic Design 🖌️",
                "Branding": "Branding 🏷️",
                "Layout Design": "Layout Design 📐",
                "Typography": "Typography 🔤",
                "Color Theory": "Color Theory 🌈",
                "Icon Design": "Icon Design 🎭",
            },
        },
    },
    "videographer": {
        "name": "Videographer",
        "emoji": "🎬",
        "since": "2.2",
        "blurb": "You shoot and cut it — visuals that move.",
        "categories": {
            "Video Software": {
                "Any Video Software": "Any Video Software 🎬",
                "Adobe Premiere": "Adobe Premiere 🎬",
                "DaVinci Resolve": "DaVinci Resolve 🎞️",
                "Final Cut Pro": "Final Cut Pro 🎥",
                "Sony Vegas": "Sony Vegas 📹",
                "Filmora": "Filmora 🎬",
                "After Effects": "After Effects ✨",
                "OBS": "OBS Studio 🔴",
            },
            "Video Skills": {
                "Any Video Skill": "Any Video Skill 🎬",
                "Editing": "Editing 🎬",
                "Color Grading": "Color Grading 🎨",
                "Motion Graphics": "Motion Graphics ✨",
                "Cinematography": "Cinematography 🎥",
                "Drone Footage": "Drone Footage 🚁",
                "Lighting": "Lighting 💡",
                "Sound Design": "Sound Design 🎙️",
            },
        },
    },

    # ------------------------------------------------ named in 2.2 with no
    # skills defined — the picker opened empty for all three. Built here in the
    # same paradigm: a tools category plus a craft category, each led by "Any …".
    "ghostwriter": {
        "name": "Ghostwriter",
        "emoji": "👻",
        "since": "2.4",
        "blurb": "You write it and someone else says it.",
        "categories": {
            "Writing Tools": {
                "Any Writing Tool": "Any Writing Tool 👻",
                "Pen & Paper": "Pen & Paper ✍️",
                "Notes App": "Notes App 📱",
                "Google Docs": "Google Docs 📄",
                "Microsoft Word": "Microsoft Word 📝",
                "Notion": "Notion 🗂️",
                "Voice Memos": "Voice Memos 🎙️",
                "Rhyme Dictionary": "Rhyme Dictionary 📖",
                "Reference Tracks": "Reference Tracks 🎧",
            },
            "Writing Skills": {
                "Any Writing Skill": "Any Writing Skill 👻",
                "Songwriting": "Songwriting ✍️",
                "Topline Writing": "Topline Writing 🎶",
                "Hook Writing": "Hook Writing 🪝",
                "Verse Writing": "Verse Writing 📜",
                "Bridge Writing": "Bridge Writing 🌉",
                "Melody Writing": "Melody Writing 🎵",
                "Rhyme Schemes": "Rhyme Schemes 🔁",
                "Wordplay": "Wordplay 🧠",
                "Punchlines": "Punchlines 👊",
                "Cadence & Flow": "Cadence & Flow 🌊",
                "Storytelling": "Storytelling 📖",
                "Concept Development": "Concept Development 💡",
                "Editing & Rewrites": "Editing & Rewrites ✂️",
            },
        },
    },
    "manager": {
        "name": "Manager",
        "emoji": "🕴️",
        "since": "2.4",
        "blurb": "You run the business so the artist can be an artist.",
        "categories": {
            "Management Tools": {
                "Any Management Tool": "Any Management Tool 🕴️",
                "Spreadsheets": "Spreadsheets 📊",
                "Notion": "Notion 🗂️",
                "Trello": "Trello 📋",
                "Asana": "Asana ✅",
                "Airtable": "Airtable 🗄️",
                "Slack": "Slack 💬",
                "CRM": "CRM 🤝",
                "DocuSign": "DocuSign 🖊️",
                "QuickBooks": "QuickBooks 💵",
                "Calendly": "Calendly 📅",
                "Chartmetric": "Chartmetric 📈",
            },
            "Management Skills": {
                "Any Management Skill": "Any Management Skill 🕴️",
                "Artist Development": "Artist Development 🌱",
                "Contract Negotiation": "Contract Negotiation ⚖️",
                "Budgeting": "Budgeting 💵",
                "Release Planning": "Release Planning 🗓️",
                "Booking & Touring": "Booking & Touring 🚌",
                "Marketing Strategy": "Marketing Strategy 📣",
                "Publicity & PR": "Publicity & PR 📰",
                "A&R": "A&R 👂",
                "Royalty Accounting": "Royalty Accounting 🏦",
                "Brand Partnerships": "Brand Partnerships 🤝",
                "Team Building": "Team Building 👥",
                "Analytics & Reporting": "Analytics & Reporting 📈",
            },
        },
    },
    "developer": {
        "name": "Developer",
        "emoji": "👾",
        "since": "2.4",
        "blurb": "You build the thing the rest of it runs on.",
        "categories": {
            # The top 20 languages by professional use (TIOBE / Stack Overflow
            # consensus). Twenty exactly — no more, so the picker stays a picker
            # and not a phone book. Niche languages go under "Any Language".
            "Programming Languages": {
                "Any Language": "Any Language 👾",
                "Python": "Python 🐍",
                "JavaScript": "JavaScript 🟨",
                "TypeScript": "TypeScript 🔷",
                "Java": "Java ☕",
                "C": "C 🔩",
                "C++": "C++ ⚙️",
                "C#": "C# 🎯",
                "SQL": "SQL 🗄️",
                "Go": "Go 🐹",
                "Rust": "Rust 🦀",
                "PHP": "PHP 🐘",
                "Swift": "Swift 🦅",
                "Kotlin": "Kotlin 🤖",
                "Ruby": "Ruby 💎",
                "R": "R 📊",
                "Dart": "Dart 🎯",
                "Scala": "Scala 🌀",
                "MATLAB": "MATLAB 📐",
                "Perl": "Perl 🐪",
                "Lua": "Lua 🌙",
            },
            "Developer Tools": {
                "Any Dev Tool": "Any Dev Tool 👾",
                "VS Code": "VS Code 🔵",
                "Git & GitHub": "Git & GitHub 🐙",
                "Terminal & Shell": "Terminal & Shell ⌨️",
                "Docker": "Docker 🐳",
                "Kubernetes": "Kubernetes ☸️",
                "Xcode": "Xcode 🍎",
                "Android Studio": "Android Studio 🤖",
                "IntelliJ IDEA": "IntelliJ IDEA 🧠",
                "Vim / Neovim": "Vim / Neovim 📗",
                "Jupyter": "Jupyter 📓",
                "Postman": "Postman 📮",
            },
            "Development Skills": {
                "Any Dev Skill": "Any Dev Skill 👾",
                "Frontend": "Frontend 🖥️",
                "Backend": "Backend 🔌",
                "Mobile Apps": "Mobile Apps 📱",
                "APIs & Integrations": "APIs & Integrations 🔗",
                "Databases": "Databases 🗄️",
                "DevOps & Deploy": "DevOps & Deploy 🚀",
                "Testing & QA": "Testing & QA 🧪",
                "Security": "Security 🔐",
                "AI & Machine Learning": "AI & Machine Learning 🧠",
                "Audio Programming": "Audio Programming 🎛️",
                "Game Development": "Game Development 🎮",
            },
        },
    },
}


# Keys that reached production before there was a catalog to check them against.
# The 2.2 UI passed a different key than its own database held for four of the
# five personas, so stored profiles contain all of these spellings. Normalising
# rather than rejecting means nobody loses a persona they already picked.
PERSONA_ALIASES = {
    "beat-producer": "producer",
    "beat producer": "producer",
    "beatproducer": "producer",
    "independent artist": "artist",
    "independent-artist": "artist",
    "indie artist": "artist",
    "engineer": "mix-engineer",
    "mix engineer": "mix-engineer",
    "mixengineer": "mix-engineer",
    "mixing engineer": "mix-engineer",
    "video": "videographer",
    "videography": "videographer",
    "dev": "developer",
    "coder": "developer",
    "programmer": "developer",
    "writer": "ghostwriter",
    "ghost writer": "ghostwriter",
    "artist manager": "manager",
}


def _squash(value):
    """Lowercase, collapse any run of whitespace, strip. Turns 'Independent
    artist', 'Developer ' and a key split across a line break into one form."""
    return " ".join(str(value or "").split()).lower()


def normalize_persona_key(value):
    """Canonical persona key for anything a client might send, or None.

    Handles the exact drift found in 2.2: wrong case, trailing spaces, a double
    space, a hyphen where there wasn't one, and the old key names.
    """
    squashed = _squash(value)
    if not squashed:
        return None
    if squashed in PERSONAZ:
        return squashed
    if squashed in PERSONA_ALIASES:
        return PERSONA_ALIASES[squashed]
    # "🎤 Artist" / "Mix Engineer" — match on the display name too, since the
    # frontend has passed labels where keys were expected.
    for key, persona in PERSONAZ.items():
        if squashed == _squash(persona["name"]) or squashed == _squash(label_for(key)):
            return key
    hyphenated = squashed.replace(" ", "-")
    if hyphenated in PERSONAZ:
        return hyphenated
    if hyphenated in PERSONA_ALIASES:
        return PERSONA_ALIASES[hyphenated]
    # Last resort: ignore separators entirely. 2.2's Mix Engineer button held a
    # raw line break inside the string literal ('E\nngineer'), so the key that
    # reached this function was broken mid-word.
    return _NO_SEPARATOR.get(_strip_separators(squashed))


def _strip_separators(value):
    return _squash(value).replace(" ", "").replace("-", "").replace("_", "")


# {separator-free spelling: canonical key} — built once, covers both the catalog
# keys and every alias.
_NO_SEPARATOR = {
    **{_strip_separators(k): k for k in PERSONAZ},
    **{_strip_separators(alias): key for alias, key in PERSONA_ALIASES.items()},
}


def label_for(key):
    """'🎤 Artist' — emoji then name, the form the UI shows."""
    persona = PERSONAZ.get(key)
    return f"{persona['emoji']} {persona['name']}" if persona else ""


def skills_for(key):
    """Flat {skill key: label} across every category of one persona."""
    persona = PERSONAZ.get(key)
    if not persona:
        return {}
    flat = {}
    for skills in persona["categories"].values():
        flat.update(skills)
    return flat


def skill_key_for(persona_key, value):
    """Canonical skill key from a key OR a stored label, or None.

    Needed because 2.2 stored the *label* ("Acoustic Guitar 🎸") as the skill
    name, so existing profiles have to be read back through this.
    """
    if not value:
        return None
    flat = skills_for(persona_key)
    squashed = _squash(value)
    for key, label in flat.items():
        if squashed in (_squash(key), _squash(label)):
            return key
    return None


def is_any_skill(skill_key):
    """True for the wildcard entry that opens each category."""
    return _squash(skill_key).startswith("any")


def normalize_start(value):
    """A skill start date as YYYY-MM-DD, or None.

    Accepts what 2.2 actually wrote — `M/D/YYYY`, from
    `${mo}/${day}/${yr}` — as well as the ISO form the rest of the backend
    reads. Before this, `profile_max_experience` looked for a `start` key in
    ISO format and found a `startDate` key in slash format, so every member's
    experience computed as None no matter how long they'd been playing.
    """
    raw = str(value or "").strip()
    if not raw:
        return None
    if "/" in raw:
        parts = raw.split("/")
        if len(parts) != 3:
            return None
        month, day, year = parts
    elif "-" in raw:
        parts = raw.split("-")
        if len(parts) != 3:
            return None
        year, month, day = parts
    else:
        return None
    try:
        y, m, d = int(year), int(month), int(day)
    except ValueError:
        return None
    if not (1 <= m <= 12 and 1 <= d <= 31 and 1000 <= y <= 9999):
        return None
    return f"{y:04d}-{m:02d}-{d:02d}"


def normalize_skill(persona_key, entry):
    """One stored skill -> {key, name, start, catalog}. None only if it's empty.

    NOT destructive. A skill the catalog doesn't recognise keeps its name and is
    marked ``catalog: False`` instead of being dropped — the platform has
    personas beyond the eight in the picker (MimeZ, DirectZ), and silently
    deleting a member's skills to satisfy a catalog would be the worse bug.
    """
    if isinstance(entry, str):
        name, start = entry, None
    elif isinstance(entry, dict):
        name = entry.get("key") or entry.get("name") or entry.get("skill")
        # 2.2 wrote `startDate`; the API documents `start`. Accept both.
        start = entry.get("start") or entry.get("startDate") or entry.get("start_date")
    else:
        return None

    name = str(name or "").strip()
    if not name:
        return None

    key = skill_key_for(persona_key, name)
    if key:
        return {
            "key": key,
            "name": skills_for(persona_key)[key],
            "start": normalize_start(start),
            "catalog": True,
        }
    return {"key": None, "name": name[:80], "start": normalize_start(start), "catalog": False}


def normalize_personas(value):
    """Clean a profile's whole `personas` list into one shape.

    Accepts everything production has produced: bare key strings from before the
    picker existed, and `{key, name, skills}` dicts from after. Output is always
    ``[{key, name, label, skills: [...], catalog: bool}]``, deduplicated by
    persona. Entries the catalog doesn't know are kept with ``catalog: False`` —
    see ``normalize_skill``.
    """
    if not isinstance(value, list):
        return []
    out, seen = [], {}
    for item in value:
        if isinstance(item, str):
            raw_key, raw_skills = item, []
        elif isinstance(item, dict):
            raw_key = item.get("key") or item.get("name")
            raw_skills = item.get("skills") or []
        else:
            continue

        key = normalize_persona_key(raw_key)
        known = key is not None
        if not known:
            # Keep it, under a tidied key, so nothing is lost.
            key = _squash(raw_key).replace(" ", "-")
            if not key:
                continue

        if key in seen:
            persona = seen[key]
        else:
            persona = {
                "key": key,
                "name": PERSONAZ[key]["name"] if known else str(raw_key)[:60],
                "label": label_for(key) if known else str(raw_key)[:60],
                "skills": [],
                "catalog": known,
            }
            seen[key] = persona
            out.append(persona)

        have = {(s["key"], s["name"]) for s in persona["skills"]}
        for raw in raw_skills if isinstance(raw_skills, list) else []:
            skill = normalize_skill(key if known else None, raw)
            if not skill or (skill["key"], skill["name"]) in have:
                continue
            have.add((skill["key"], skill["name"]))
            persona["skills"].append(skill)
    return out


def catalog_payload():
    """The whole catalog, in the order the picker should render it."""
    return {
        "personas": [
            {
                "key": key,
                "name": persona["name"],
                "emoji": persona["emoji"],
                "label": label_for(key),
                "blurb": persona["blurb"],
                "since": persona["since"],
                "skill_count": len(skills_for(key)),
                "categories": [
                    {
                        "name": cat,
                        "skills": [
                            {"key": sk, "label": label, "any": is_any_skill(sk)}
                            for sk, label in skills.items()
                        ],
                    }
                    for cat, skills in persona["categories"].items()
                ],
            }
            for key, persona in PERSONAZ.items()
        ],
        "aliases": dict(PERSONA_ALIASES),
        # The client renders "Any …" entries in the accent colour and treats a
        # skill date as required — both stated here so it stops being folklore.
        "rules": {
            "any_prefix": "Any",
            "start_date_format": "YYYY-MM-DD",
            "start_date_required": True,
        },
    }
