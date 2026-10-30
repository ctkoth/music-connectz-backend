"""One shape for a PersonaZ entry, and the recovery for the rows that lost it.

A persona is `{key, name, skills}`. It has been stored as a bare string (just a
key) and as the whole dict, and `clean_persona` accepts both — that part was
already true and is not new.

What is new is the third shape, which is not a shape anyone designed: a string
holding the *printed form* of a dict.

    "{'name': 'Independent Artist', 'emoji': '🎤', 'skills': []}"

Something ran `str()` over a persona before it reached the database. The write
path that did it is long fixed — `accounts.views` carries the note — but
**fixing a writer never repairs what it already wrote**, and this is the exact
failure the client-side `socialData.js` calls out about localStorage: the bad
shape is already sitting in people's accounts, so a member stays broken until
they happen to save their profile again.

Worse, it broke quietly. Every consumer of `profile.personas` in this codebase
guards with `if not isinstance(persona, dict): continue` — postz's skill
pricing, questz's rate check, occ_suggest, social's rate range, publicz's
public card. Those guards are correct and they are why nothing ever crashed;
they are also why nobody noticed. A member in this state does not see an error.
They see a persona that renders as machine noise on their profile, their
priced skills silently missing from what a post costs, and their public card
quietly short one persona. Nothing to report, so nothing gets reported.

So the recovery lives HERE and runs on the way IN and on the way OUT: a save
un-mangles it for good, and a read un-mangles it in the meantime for everybody
who has not saved since. `manage.py repair_personas --write` is the sweep that
makes the read-side repair stop being needed.
"""
import ast
import json
from urllib.parse import urlparse

from .interestz_table import BRANDS, TRAITS


# Bio/interests/pet peeves — bounded the same way `skills` already is
# (`[:100]`, `[:80]` per name), so a persona row cannot be grown into a
# payload by pasting a novel into one field.
MAX_BIO_CHARS = 500
MAX_TAGS = 20
MAX_TAG_CHARS = 40


def _clean_tag_list(value):
    """A bounded list of short strings — interests or pet peeves. Junk
    entries are dropped rather than failing the whole save, the same rule
    `soundz.clean_overrides` follows for one bad key."""
    if not isinstance(value, list):
        return []
    out = []
    for item in value[:MAX_TAGS]:
        tag = str(item or "").strip()[:MAX_TAG_CHARS]
        if tag:
            out.append(tag)
    return out


def clean_tags(value):
    """`_clean_tag_list`, for callers outside this module (a character's hobbies)."""
    return _clean_tag_list(value)


def _clean_keys(value, table):
    """The keys in `value` that are on `table`, once each, in order."""
    if not isinstance(value, list):
        return []
    return [k for k in dict.fromkeys(str(x) for x in value[:MAX_TAGS * 2]) if k in table][:MAX_TAGS]


def _recover(text):
    """A dict back out of a string that is the printed form of one, else None.

    `ast.literal_eval` evaluates literals only — no names, no calls, no
    attribute access — so this cannot execute what a member typed. JSON is
    tried too, because the same mistake made in JavaScript produces double
    quotes and `str()` in Python produces single ones, and a repair that only
    handles the language that caused it once is a repair that runs out.
    """
    text = (text or "").strip()
    if not (text.startswith("{") and text.endswith("}")):
        return None
    for parse in (ast.literal_eval, json.loads):
        try:
            out = parse(text)
        except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
            continue
        if isinstance(out, dict):
            return out
    return None


RATE_HOUR, RATE_WORK = "hour", "work"
RATE_UNITS = (RATE_HOUR, RATE_WORK)


def rate_unit_of(skill):
    """"work" or "hour" — what a skill's `rate_cents` is a price per. Anything else is hourly."""
    if isinstance(skill, dict) and str(skill.get("rate_unit") or "").lower() == RATE_WORK:
        return RATE_WORK
    return RATE_HOUR


SKILL_GENRES_MAX = 8


def clean_skill_genres(raw):
    """['Trap', 'Drill'] from whatever arrived: strings only, trimmed, no markup, unique, a few."""
    if not isinstance(raw, (list, tuple)):
        return []
    out, seen = [], set()
    for g in raw:
        if not isinstance(g, str):
            continue
        g = " ".join(g.replace("<", " ").replace(">", " ").split())[:40]
        if g and g.lower() not in seen:
            seen.add(g.lower())
            out.append(g)
        if len(out) >= SKILL_GENRES_MAX:
            break
    return out


def clean_persona(raw):
    """Normalize one PersonaZ entry, keeping its skills and their start dates.

    Always returns a dict, so downstream code has one shape to reason about.
    Skill stints are the input to `profile_max_experience`, so they are
    preserved verbatim — both the new `periods` list and the legacy single
    `start`.
    """
    if not isinstance(raw, dict):
        # A printed dict is recovered and then run through the SAME path a real
        # dict takes, rather than being special-cased into a shape of its own.
        # Whatever the supported shape carries is what survives the repair, and
        # it stays that way without anyone maintaining two versions of it.
        recovered = _recover(raw if isinstance(raw, str) else None)
        if recovered is not None:
            return clean_persona(recovered)
        return {"key": str(raw)[:60], "name": str(raw)[:60], "skills": []}

    skills = []
    for s in (raw.get("skills") or [])[:100]:
        if not isinstance(s, dict):
            name = str(s)[:80]
            if name:
                skills.append({"name": name})
            continue
        name = str(s.get("name", ""))[:80]
        if not name:
            continue
        # Stints. Experience is the SUM of these, so a member who stopped is
        # not credited for the years they were away. The legacy single `start`
        # is read as one still-open stint and preserved on the way through —
        # dropping it here would silently zero somebody's experience.
        periods = []
        for pr in (s.get("periods") or [])[:20]:
            if not isinstance(pr, dict):
                continue
            start = str(pr.get("start") or "")[:10]
            if not start:
                continue
            end = str(pr.get("end") or "")[:10]
            periods.append({"start": start, "end": end} if end else {"start": start})
        # Hourly rate, in cents. The blueprint prices CallZ by "the other
        # member's skill rate per hour" and nothing stored one, so the price
        # range had no metric to gate on.
        try:
            rate = max(0, int(s.get("rate_cents") or 0))
        except (TypeError, ValueError):
            rate = 0
        entry = {"name": name}
        # What the price is FOR: an hour of the member's time, or one finished piece of work.
        # Hourly is the default and is not stored, so every price written before this existed
        # keeps meaning what it always meant.
        if rate and str(s.get("rate_unit") or "").lower() == RATE_WORK:
            entry["rate_unit"] = RATE_WORK
        if periods:
            entry["periods"] = periods
        else:
            start = str(s.get("start") or "")[:10]
            if start:
                entry["start"] = start
        if rate:
            entry["rate_cents"] = rate
        # The genres this skill is practised in - the same names every genre picker offers
        # ("Rapping" in Trap and Drill). Free-form tags, not a closed list: the picker's list
        # lives in the client, and a member who works in a genre we have not listed should not
        # be refused for it. Short, de-duplicated, plain text.
        genres = clean_skill_genres(s.get("genres"))
        if genres:
            entry["genres"] = genres
        skills.append(entry)

    key = str(raw.get("key") or raw.get("name") or "")[:60]
    out = {"key": key, "name": str(raw.get("name") or key)[:60], "skills": skills}

    # Bio, interests, pet peeves — flavor text a member types about THIS
    # persona, never inferred and never scored. A DirectZ or MangaZ persona
    # built off these carries what its owner actually said about it, not a
    # guess dressed up as one — the same reason PersonalitieZ is declared
    # rather than detected.
    bio = str(raw.get("bio") or "").strip()[:MAX_BIO_CHARS]
    if bio:
        out["bio"] = bio
    interests = _clean_tag_list(raw.get("interests"))
    if interests:
        out["interests"] = interests
    pet_peeves = _clean_tag_list(raw.get("pet_peeves"))
    if pet_peeves:
        out["pet_peeves"] = pet_peeves

    # Brands and strengths the member PICKED (interestz.py). Closed lists, so a
    # key that isn't on one is dropped, and both are declared rather than
    # measured: nothing may read `declared_strengths` as a measurement. The
    # `declared_` prefix is also what lets a test find every reader, which a
    # bare word (the coach has its own) could not.
    brands = _clean_keys(raw.get("declared_brands"), BRANDS)
    if brands:
        out["declared_brands"] = brands
    strengths = _clean_keys(raw.get("declared_strengths"), TRAITS)
    if strengths:
        out["declared_strengths"] = strengths

    return out


# ------------------------------------------------- what a persona's skills say they ARE

# "Independent Artist" or "Designer" says nothing about what the person does. Next to it goes what
# their declared skills add up to: rapping → 🎤 Rapper, singing → 🎶 Singer, guitar → 🎸 Guitarist,
# Adobe Illustrator → 🖌️ Illustrator. Matched on the skill's stable key (acoustic_guitar) OR its label
# ("Acoustic Guitar 🎸") — a stint is stored under either — and listed in the order the member
# declared them. A wildcard ("Any Rapping") counts: claiming the category is claiming the role.
#
# DECLARED, never inferred (the PersonalitieZ rule): nothing is read from takes, posts or ratings, so
# no one is called a Rapper because of what a model heard. It is derived on READ and never stored — a
# stored copy would go stale the day a skill is removed.
#
# {persona letters-only key: [(emoji, role, {skill tokens}), ...]}. Tokens are unique to a role within
# a persona, with one deliberate exception noted inline.
_ARTIST = [
    ("🎤", "Rapper", {"any_rapping", "alternative_rap", "boom_bap", "chopper", "cloud_rap", "conscious_rap", "crunk",
                      "drill", "emo_rap", "g_funk", "gangsta_rap", "hardcore_hip_hop", "jazz_rap", "mumble_rap",
                      "old_school", "snap", "trap", "rapping", "rap"}),
    # "bass" is the VOICE here (a range class); the instrument is bass_guitar / double_bass below.
    ("🎶", "Singer", {"any_singing", "bass", "baritone", "tenor", "countertenor", "contralto", "alto",
                      "mezzo_soprano", "soprano", "vocals", "singing"}),
    ("🎸", "Guitarist", {"acoustic_guitar", "electric_guitar", "guitar"}),
    ("🎸", "Bassist", {"bass_guitar", "double_bass"}),
    ("🎹", "Pianist", {"acoustic_piano", "digital_piano", "piano"}),
    ("🎹", "Keyboardist", {"any_keyboard", "synthesizer", "organ", "harpsichord", "keys"}),
    ("🪗", "Accordionist", {"accordion"}),
    ("🥁", "Drummer", {"drums_snare", "drums_bass", "drums_bongo", "drums", "drummer"}),
    ("🥁", "Percussionist", {"any_percussion", "cymbals"}),
    ("🎻", "Violinist", {"violin"}),
    ("🎻", "Violist", {"viola"}),
    ("🎻", "Cellist", {"cello"}),
    ("🎵", "Harpist", {"harp"}),
    ("🪕", "Banjo player", {"banjo"}),
    ("🎵", "Mandolinist", {"mandolin"}),
    ("🎸", "Ukulele player", {"ukulele"}),
    ("✍️", "Songwriter", {"songwriting"}),
    ("🔥", "Freestyler", {"freestyle"}),
]
_ROLES = {
    ("indieartist", "independentartist"): _ARTIST,
    ("designer",): [
        ("🖌️", "Illustrator", {"illustrator", "icon_design"}),
        ("🎨", "Graphic Designer", {"graphic_design", "photoshop", "indesign", "coreldraw", "affinity", "canva",
                                    "any_design_skill", "any_design_software", "asset_production"}),
        ("🎯", "UI/UX Designer", {"figma", "ui_ux", "sketch"}),
        ("💿", "Cover Artist", {"cover_art_design"}),
        ("🔤", "Typographer", {"typography"}),
        ("🏷️", "Brand Designer", {"brand_identity"}),
        ("🌈", "Colour Specialist", {"color_theory"}),
        ("📐", "Layout Designer", {"composition"}),
        ("🧊", "3D Artist", {"blender"}),
        ("✨", "Motion Designer", {"after_effects_design"}),
        ("📖", "Visual Storyteller", {"visual_storytelling"}),
    ],
    ("videographer",): [
        ("🎥", "Videographer", {"filming", "cinematography", "camera_operation", "any_video_skill", "lighting",
                                "audio_capture"}),
        ("✂️", "Video Editor", {"editing", "premiere", "resolve", "finalcut", "vegas", "filmora",
                                "any_video_software"}),
        ("🎨", "Colourist", {"color_grading"}),
        ("✨", "Motion Designer", {"motion_graphics", "aftereffects"}),
        ("🚁", "Drone Operator", {"drone"}),
        ("🎞️", "Music Video Producer", {"music_video"}),
        ("🗂️", "Storyboard Artist", {"storyboarding"}),
    ],
    ("producer",): [
        ("🎚️", "Beat Maker", {"beat_making", "any_production", "drum_programming"}),
        ("🎛️", "Sound Designer", {"sound_design", "synthesis"}),
        ("🎼", "Arranger", {"arrangement"}),
        ("🎵", "Sampler", {"sampling"}),
    ],
    ("mixengineer",): [
        ("🎛️", "Mixing Engineer", {"mixing", "eq", "compression", "reverb_fx", "any_engineering", "stem_prep"}),
        ("🎙️", "Mastering Engineer", {"mastering"}),
        ("🎯", "Vocal Tuner", {"vocal_tuning"}),
    ],
    ("ghostwriter",): [
        ("✍️", "Lyricist", {"bars", "any_writing"}),
        ("🪝", "Hook Writer", {"hooks"}),
        ("🎼", "Topline Writer", {"toplines"}),
        ("📖", "Story Writer", {"storytelling", "concept_development"}),
    ],
    ("developer",): [
        ("🖥️", "Frontend Developer", {"frontend"}),
        ("🗄️", "Backend Developer", {"backend"}),
        ("📱", "Mobile Developer", {"mobile"}),
        ("🎚️", "Audio / DSP Engineer", {"audio_dsp"}),
        ("🔌", "API Developer", {"apis"}),
        ("🚀", "DevOps Engineer", {"devops"}),
    ],
    ("actor", "actress"): [
        ("🎪", "Stage Actor", {"stage_acting"}),
        ("🎥", "Screen Actor", {"screen_acting"}),
        ("😂", "Improviser", {"improv"}),
        ("🗣️", "Monologist", {"monologues"}),
    ],
    ("dancer",): [
        ("🎤", "Hip-Hop Dancer", {"hip_hop"}), ("🩰", "Ballet Dancer", {"ballet"}),
        ("🎭", "Contemporary Dancer", {"contemporary"}), ("🎷", "Jazz Dancer", {"jazz", "street_jazz"}),
        ("💃", "Latin Dancer", {"latin"}), ("🎪", "Popper", {"popping"}), ("🔐", "Locker", {"locking"}),
        ("🎩", "Tap Dancer", {"tap"}), ("🕺", "Freestyle Dancer", {"freestyle"}),
        ("📋", "Choreographer", {"choreography"}), ("👨\u200d🏫", "Dance Teacher", {"teaching"}),
    ],
    ("mime",): [
        ("👄", "Lip-Syncer", {"lipsync"}), ("🎭", "Pantomimist", {"pantomime"}),
    ],
    ("director",): [
        ("🎬", "Director", {"any_direction", "shot_calling", "talent_direction", "scene_blocking", "set_management"}),
        ("📝", "Treatment Writer", {"treatment_writing"}),
    ],
    ("manager",): [
        ("📋", "Project Manager", {"project_management", "performance_tracking", "resource_management"}),
        ("🗓️", "Release Planner", {"release_planning"}),
        ("🧭", "Team Lead", {"team_leadership", "strategic_planning", "any_leadership"}),
    ],
    ("arscout",): [
        ("🔭", "Talent Scout", {"talent_spotting", "any_scouting", "roster_building", "trend_reading"}),
        ("📊", "Market Analyst", {"market_analysis"}),
        ("📜", "Deal Maker", {"deal_structuring"}),
    ],
}

# Role → the AI coach for that instrument, so a rapper is pointed at RapZ. One list; Lilith reads it.
ROLE_COACH = {"Rapper": "rapz", "Singer": "singz", "Guitarist": "guitarz", "Ukulele player": "guitarz",
              "Bassist": "bassz", "Pianist": "keyz", "Keyboardist": "keyz", "Drummer": "drumz",
              "Percussionist": "drumz", "Violinist": "violinz"}


def _skill_token(name):
    """'Acoustic Guitar 🎸' and 'acoustic_guitar' → 'acoustic_guitar'."""
    import re
    return re.sub(r"[^a-z0-9]+", "_", re.sub(r"[^\x00-\x7f]", "", str(name or "").lower())).strip("_")


def role_pairs(persona):
    """[(emoji, role)] this persona's declared skills add up to, in declared order. [] when the
    persona has no role table or none of its skills name a role."""
    import re
    ident = {re.sub(r"[^a-z]", "", str(persona.get(f, "")).lower()) for f in ("key", "name")} - {""}
    table = next((t for keys, t in _ROLES.items() if ident & set(keys)), None)
    if not table:
        return []
    out = []
    for s in persona.get("skills") or []:
        tok = f"_{_skill_token(s.get('name') if isinstance(s, dict) else s)}_"
        # A stint is stored under the key ("illustrator") or the label ("Adobe Illustrator 🖌️"), so a
        # key matches as a whole run of words inside the token. The LONGEST key wins: "bass_guitar"
        # is a Bassist although "bass" (the voice) is inside it.
        best = None
        for emoji, role, keys in table:
            for k in keys:
                if f"_{k}_" in tok and (best is None or len(k) > best[0]):
                    best = (len(k), emoji, role)
        if best and best[2] not in [r for _, r in out]:
            out.append((best[1], best[2]))
    return out


def artist_roles(persona):
    """The display strings: '🎤 Rapper', '🖌️ Illustrator'. Named for the first persona that had
    them; it now covers every persona with a role table."""
    return [f"{e} {r}" for e, r in role_pairs(persona)]


def personas_of(profile):
    """Every persona on a profile, in the one shape, repaired if it needs it.

    Read paths call this instead of touching `profile.personas` directly, so a
    member whose row was mangled sees their own personas correctly TODAY rather
    than after the next sweep and after their next save.
    """
    out = []
    for x in (getattr(profile, "personas", None) or []):
        c = clean_persona(x)
        roles = artist_roles(c)
        if roles:
            c["roles"] = roles          # derived on read; clean_persona drops it on any write
        out.append(c)
    return out


def needs_repair(stored):
    """True when this stored list is not already what `clean_persona` makes.

    The sweep's test, kept beside the repair so the two cannot disagree about
    what "broken" means.
    """
    stored = stored or []
    return [clean_persona(x) for x in stored] != list(stored)


# ---- Profile links ----
#
# A link is `{label, url}`, and it is rendered as `<a href>` on the member card
# AND on the logged-out public profile. `POST /api/economy/profile/` wrote the
# list straight off the request body, so an unvalidated URL there is a stored
# `javascript:` waiting for the next person to open somebody's page — React
# warns about one and puts it in the DOM anyway.
#
# The writer validates now. Like the persona repair above, that does nothing
# for what it already wrote, and this one is not cosmetic — so reads go through
# `links_of` too, and nobody is one un-run management command away from serving
# an executable href to a stranger.
SAFE_LINK_SCHEMES = ("http", "https", "mailto")


def clean_link(raw):
    """One `{label, url}`, or None if the URL is not one we will render.

    A scheme allowlist rather than a `javascript:` denylist: `data:`,
    `vbscript:` and every future one are refused by not being named, which is
    the only version of this check that does not need editing every time
    somebody finds a new way to spell it.
    """
    if isinstance(raw, str):
        raw = {"url": raw, "label": ""}
    if not isinstance(raw, dict):
        return None
    url = str(raw.get("url") or "").strip()[:500]
    if not url:
        return None
    try:
        scheme = (urlparse(url).scheme or "").lower()
    except ValueError:
        return None
    # A bare "musicconnectz.net" has no scheme and is what people actually
    # type, so it is completed rather than refused.
    if not scheme:
        url = "https://" + url
    elif scheme not in SAFE_LINK_SCHEMES:
        return None
    return {"label": str(raw.get("label") or "")[:80], "url": url}


def links_of(profile):
    """Every renderable link on a profile. Refused ones are dropped, not fixed:
    there is no honest guess at what somebody meant by `javascript:`."""
    return [l for l in (clean_link(x) for x in (getattr(profile, "links", None) or [])) if l]


def profile_needs_repair(profile):
    """True when this profile's stored JSON is not what the cleaners make of it."""
    personas = list(profile.personas or [])
    links = list(profile.links or [])
    return ([clean_persona(x) for x in personas] != personas
            or links_of(profile) != links)
