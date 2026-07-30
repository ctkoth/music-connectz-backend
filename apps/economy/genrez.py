"""GenreZ — the canonical genre list.

Transcribed from the 2.2 build, where it lived as a bare array inside
`openGenreModal()`:

    const genres = ['Trap', 'Drill', 'Cloud Rap', 'Boom Bap', 'House', 'Techno',
                    'Pop', 'Hip Hop', 'R&B', 'Jazz', 'Soul', 'Indie',
                    'Electronic', 'Ambient', 'Lo-Fi'];

Fifteen, flat, single-select, and **required** on the Upload Work Example form.
It was missed in the first pass of the PersonaZ audit — see PERSONAZ_AUDIT.md #13
— because it wasn't in `instrumentDatabase` with the skills; it was a local
variable in a modal handler, which is exactly why it needed finding.

Two things worth knowing about the 2.2 list:

* **No emoji.** Unlike every skill label, the genre buttons rendered plain text.
  `name` here is byte-for-byte what a member saw; `emoji` is separate metadata the
  UI may use or ignore, so nothing about the original rendering is lost.
* **Four of them are also Rapping skills** (Trap, Drill, Cloud Rap, Boom Bap).
  That overlap is real and deliberate in 2.2 — a genre describes the work, a skill
  describes the person — so both are kept and `also_a_skill` flags them.
"""

# Genres exactly as 2.2 shipped them, in the order they were rendered.
V22_GENRES = ["Trap", "Drill", "Cloud Rap", "Boom Bap", "House", "Techno", "Pop",
              "Hip Hop", "R&B", "Jazz", "Soul", "Indie", "Electronic", "Ambient",
              "Lo-Fi"]

# Emoji are additive metadata — the 2.2 buttons had none, and `name` stays plain.
_EMOJI = {
    "Trap": "🏚️", "Drill": "⚔️", "Cloud Rap": "☁️", "Boom Bap": "🥁",
    "House": "🏠", "Techno": "🔊", "Pop": "✨", "Hip Hop": "🎤", "R&B": "💜",
    "Jazz": "🎷", "Soul": "🕊️", "Indie": "🎸", "Electronic": "🎛️",
    "Ambient": "🌌", "Lo-Fi": "📻",
    # 2.4 additions
    "Rock": "🎸", "Metal": "🤘", "Punk": "🧷", "Alternative": "🌀",
    "Country": "🤠", "Folk": "🪕", "Blues": "🎺", "Funk": "🕺", "Disco": "🪩",
    "Gospel": "🙌", "Classical": "🎻", "Orchestral": "🎼", "Reggae": "🌴",
    "Dancehall": "🔥", "Afrobeats": "🥁", "Amapiano": "🎹", "Reggaeton": "💃",
    "Latin": "🌶️", "Salsa": "💃", "K-Pop": "🇰🇷", "Drum & Bass": "🥁",
    "Dubstep": "🛸", "Garage": "🚪", "Trance": "🌠", "Hardstyle": "⚡",
    "Phonk": "🚗", "Hyperpop": "💊", "Emo": "🖤", "Experimental": "🧪",
    "World": "🌍", "Instrumental": "🎼", "Spoken Word": "🗣️",
}

# Added after the audit. 2.2's fifteen skew heavily to hip-hop and electronic —
# a rock band, a gospel choir or an afrobeats artist had nowhere to file their
# work. Added, never edited: every 2.2 entry above is untouched.
EXTRA_GENRES = ["Rock", "Metal", "Punk", "Alternative", "Country", "Folk",
                "Blues", "Funk", "Disco", "Gospel", "Classical", "Orchestral",
                "Reggae", "Dancehall", "Afrobeats", "Amapiano", "Reggaeton",
                "Latin", "Salsa", "K-Pop", "Drum & Bass", "Dubstep", "Garage",
                "Trance", "Hardstyle", "Phonk", "Hyperpop", "Emo",
                "Experimental", "World", "Instrumental", "Spoken Word"]

# Genres that are also skills in the artist PersonaZ. Kept in both on purpose: a
# genre describes the work, a skill describes the person.
ALSO_SKILLS = {"Trap", "Drill", "Cloud Rap", "Boom Bap"}

GENRES = V22_GENRES + EXTRA_GENRES

# {squashed name: canonical name} — built once, so lookup is a dict hit rather
# than a scan.
_INDEX = {}


def _squash(value):
    """Lowercase, collapse whitespace, and drop the separators people vary on.

    'R&B', 'r and b', 'RnB' and 'r&b' are one genre. 'Lo-Fi', 'lofi' and
    'lo fi' are one genre. Members type these by hand and always have.
    """
    text = " ".join(str(value or "").split()).lower()
    text = text.replace(" and ", " & ")
    return text.replace("&", "n").replace("-", "").replace(" ", "")


for _name in GENRES:
    _INDEX[_squash(_name)] = _name
# A few spellings that don't fall out of the squash rule.
_INDEX.update({
    "rnb": "R&B", "randb": "R&B", "rhythmandblues": "R&B",
    "hiphop": "Hip Hop", "rap": "Hip Hop",
    "lofi": "Lo-Fi", "lofihiphop": "Lo-Fi",
    "dnb": "Drum & Bass", "drumandbass": "Drum & Bass", "drumnbass": "Drum & Bass",
    "edm": "Electronic", "electronica": "Electronic",
    "kpop": "K-Pop", "afrobeat": "Afrobeats", "randbsoul": "Soul",
    "classicalmusic": "Classical",
})


def normalize_genre(value):
    """Canonical genre name, or None. Accepts any spelling a member might type."""
    squashed = _squash(value)
    return _INDEX.get(squashed) if squashed else None


def normalize_genres(values, limit=12):
    """Clean a list of genres: canonical, de-duplicated, order preserved.

    Unknown entries are DROPPED here, unlike persona skills — a genre is a
    closed vocabulary that drives filtering and discovery, so a free-text one
    would be a genre nobody can search for. The catalog is the point.
    """
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple)):
        return []
    out = []
    for raw in values:
        name = normalize_genre(raw)
        if name and name not in out:
            out.append(name)
        if len(out) >= limit:
            break
    return out


def is_v22(name):
    return name in V22_GENRES


def genre_payload(name):
    return {
        "key": name,
        "name": name,          # exactly what 2.2 rendered — no emoji in the name
        "emoji": _EMOJI.get(name, "🎵"),
        "since": "2.2" if is_v22(name) else "2.4",
        "also_a_skill": name in ALSO_SKILLS,
    }


def catalog_payload():
    """The whole genre list, 2.2's fifteen first and flagged as such."""
    return {
        "genres": [genre_payload(g) for g in GENRES],
        "v22": list(V22_GENRES),
        "count": len(GENRES),
        # 2.2 stored `selectedGenre` as a single string and the picker cleared
        # every other button on click. Stated so a client doesn't have to infer
        # it from behaviour.
        "rules": {
            "select": "one",
            "required_on_work": True,
            "max_on_profile": 12,
            "note": "A work example takes one genre. A profile may list several.",
        },
    }
