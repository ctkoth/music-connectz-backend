"""The VST catalog — what a plugin is, not how to run one.

This is deliberately a *matching* layer. Nothing here loads or executes a
plugin: browsers cannot run native VST binaries, and that is a security boundary
rather than a missing feature. What the spec actually asks for — "DawZ needs VST
support with filtering based on users VST" — is a catalog and a search, and that
works today regardless of which audio path DawZ eventually takes.

Same shape as the BodieZ equipment bank, which is the proven pattern here: a
closed vocabulary, members toggle what they have, and search filters on it.

    (key, name, vendor, kind, formats, price_tier)

`formats` is the wire format list — a plugin often ships several. It's the field
a desktop scanner would match against when it walks a real plugin folder, so it
is stored even though nothing reads it yet.
"""

# --- what a plugin does ------------------------------------------------------
KIND_SYNTH = "synth"
KIND_DRUMS = "drums"
KIND_SAMPLER = "sampler"
KIND_EQ = "eq"
KIND_COMPRESSOR = "compressor"
KIND_REVERB = "reverb"
KIND_DELAY = "delay"
KIND_SATURATION = "saturation"
KIND_PITCH = "pitch"
KIND_VOCAL = "vocal"
KIND_MASTERING = "mastering"
KIND_UTILITY = "utility"
KIND_AMP = "amp"
KIND_ORCHESTRAL = "orchestral"

KINDS = [
    (KIND_SYNTH, "Synth", "🎹"),
    (KIND_DRUMS, "Drums", "🥁"),
    (KIND_SAMPLER, "Sampler", "🎛️"),
    (KIND_EQ, "EQ", "📊"),
    (KIND_COMPRESSOR, "Compressor", "🔧"),
    (KIND_REVERB, "Reverb", "✨"),
    (KIND_DELAY, "Delay", "🔁"),
    (KIND_SATURATION, "Saturation", "🔥"),
    (KIND_PITCH, "Pitch", "🎯"),
    (KIND_VOCAL, "Vocal", "🎤"),
    (KIND_MASTERING, "Mastering", "🏁"),
    (KIND_UTILITY, "Utility", "🧰"),
    (KIND_AMP, "Amp / Guitar", "🎸"),
    (KIND_ORCHESTRAL, "Orchestral", "🎻"),
]
KIND_KEYS = [k for k, _, _ in KINDS]

# --- how it's installed ------------------------------------------------------
# A desktop scanner matches these against real files: .vst3, .component, .dll.
FORMATS = [
    ("vst3", "VST3", "🔌"),
    ("vst2", "VST2", "🔌"),
    ("au", "Audio Unit", "🍎"),
    ("aax", "AAX (Pro Tools)", "🎙️"),
    ("clap", "CLAP", "👏"),
    ("wam", "Web Audio Module", "🌐"),   # the only one a browser can host
    ("standalone", "Standalone", "🖥️"),
]
FORMAT_KEYS = [k for k, _, _ in FORMATS]

# --- what it costs -----------------------------------------------------------
PRICE_FREE = "free"
PRICE_PAID = "paid"
PRICE_SUBSCRIPTION = "subscription"
PRICE_TIERS = [
    (PRICE_FREE, "Free", "🆓"),
    (PRICE_PAID, "Paid", "💲"),
    (PRICE_SUBSCRIPTION, "Subscription", "🔄"),
]
PRICE_KEYS = [k for k, _, _ in PRICE_TIERS]

# --- the catalog -------------------------------------------------------------
# Seeded with plugins that actually turn up on a working producer's machine.
# `browser_ok` marks the handful that genuinely run in a browser — everything
# else needs the desktop app, and saying so in the data stops the UI implying
# otherwise.
#
# (key, name, vendor, kind, formats, price, browser_ok)
PLUGINS = [
    # Synths
    ("serum", "Serum", "Xfer Records", KIND_SYNTH, ["vst3", "vst2", "au", "aax"], PRICE_PAID, False),
    ("massive-x", "Massive X", "Native Instruments", KIND_SYNTH, ["vst3", "au", "aax"], PRICE_PAID, False),
    ("sylenth1", "Sylenth1", "LennarDigital", KIND_SYNTH, ["vst3", "vst2", "au"], PRICE_PAID, False),
    ("omnisphere", "Omnisphere", "Spectrasonics", KIND_SYNTH, ["vst3", "au", "aax"], PRICE_PAID, False),
    ("vital", "Vital", "Vital Audio", KIND_SYNTH, ["vst3", "au", "clap"], PRICE_FREE, False),
    ("surge-xt", "Surge XT", "Surge Synth Team", KIND_SYNTH, ["vst3", "au", "clap", "wam"], PRICE_FREE, True),
    ("dexed", "Dexed", "Digital Suburban", KIND_SYNTH, ["vst3", "vst2", "au", "wam"], PRICE_FREE, True),
    ("pigments", "Pigments", "Arturia", KIND_SYNTH, ["vst3", "au", "aax"], PRICE_PAID, False),
    ("nexus", "Nexus", "reFX", KIND_SYNTH, ["vst3", "au", "aax"], PRICE_PAID, False),
    ("diva", "Diva", "u-he", KIND_SYNTH, ["vst3", "vst2", "au", "clap"], PRICE_PAID, False),

    # Drums / samplers
    ("battery-4", "Battery 4", "Native Instruments", KIND_DRUMS, ["vst3", "au", "aax"], PRICE_PAID, False),
    ("addictive-drums-2", "Addictive Drums 2", "XLN Audio", KIND_DRUMS, ["vst3", "au", "aax"], PRICE_PAID, False),
    ("superior-drummer-3", "Superior Drummer 3", "Toontrack", KIND_DRUMS, ["vst3", "au", "aax"], PRICE_PAID, False),
    ("kontakt", "Kontakt", "Native Instruments", KIND_SAMPLER, ["vst3", "au", "aax"], PRICE_PAID, False),
    ("tx16wx", "TX16Wx", "CWITEC", KIND_SAMPLER, ["vst3", "vst2", "au"], PRICE_FREE, False),

    # EQ / dynamics
    ("pro-q-3", "FabFilter Pro-Q 3", "FabFilter", KIND_EQ, ["vst3", "vst2", "au", "aax"], PRICE_PAID, False),
    ("pro-c-2", "FabFilter Pro-C 2", "FabFilter", KIND_COMPRESSOR, ["vst3", "vst2", "au", "aax"], PRICE_PAID, False),
    ("ssl-g-comp", "SSL G-Master Buss Compressor", "Solid State Logic", KIND_COMPRESSOR, ["vst3", "au", "aax"], PRICE_PAID, False),
    ("waves-cla-76", "CLA-76", "Waves", KIND_COMPRESSOR, ["vst3", "au", "aax"], PRICE_PAID, False),
    ("tdr-nova", "TDR Nova", "Tokyo Dawn Labs", KIND_EQ, ["vst3", "vst2", "au"], PRICE_FREE, False),
    ("tdr-kotelnikov", "TDR Kotelnikov", "Tokyo Dawn Labs", KIND_COMPRESSOR, ["vst3", "vst2", "au"], PRICE_FREE, False),
    ("ozone", "Ozone", "iZotope", KIND_MASTERING, ["vst3", "au", "aax"], PRICE_PAID, False),
    ("neutron", "Neutron", "iZotope", KIND_UTILITY, ["vst3", "au", "aax"], PRICE_PAID, False),

    # Time / space
    ("valhalla-vintage-verb", "Valhalla VintageVerb", "Valhalla DSP", KIND_REVERB, ["vst3", "vst2", "au", "aax"], PRICE_PAID, False),
    ("valhalla-supermassive", "Valhalla Supermassive", "Valhalla DSP", KIND_REVERB, ["vst3", "vst2", "au"], PRICE_FREE, False),
    ("pro-r", "FabFilter Pro-R", "FabFilter", KIND_REVERB, ["vst3", "vst2", "au", "aax"], PRICE_PAID, False),
    ("echoboy", "EchoBoy", "Soundtoys", KIND_DELAY, ["vst3", "au", "aax"], PRICE_PAID, False),
    ("soundtoys-5", "Soundtoys 5 Bundle", "Soundtoys", KIND_SATURATION, ["vst3", "au", "aax"], PRICE_PAID, False),

    # Vocal / pitch
    ("auto-tune-pro", "Auto-Tune Pro", "Antares", KIND_PITCH, ["vst3", "au", "aax"], PRICE_PAID, False),
    ("melodyne", "Melodyne", "Celemony", KIND_PITCH, ["vst3", "au", "aax"], PRICE_PAID, False),
    ("graillon-2", "Graillon 2", "Auburn Sounds", KIND_PITCH, ["vst3", "vst2", "au"], PRICE_FREE, False),
    ("waves-tune-real-time", "Waves Tune Real-Time", "Waves", KIND_VOCAL, ["vst3", "au", "aax"], PRICE_PAID, False),
    ("little-alterboy", "Little AlterBoy", "Soundtoys", KIND_VOCAL, ["vst3", "au", "aax"], PRICE_PAID, False),

    # Saturation / amp
    ("decapitator", "Decapitator", "Soundtoys", KIND_SATURATION, ["vst3", "au", "aax"], PRICE_PAID, False),
    ("saturn-2", "FabFilter Saturn 2", "FabFilter", KIND_SATURATION, ["vst3", "vst2", "au", "aax"], PRICE_PAID, False),
    ("guitar-rig", "Guitar Rig", "Native Instruments", KIND_AMP, ["vst3", "au", "aax"], PRICE_PAID, False),
    ("neural-dsp-archetype", "Neural DSP Archetype", "Neural DSP", KIND_AMP, ["vst3", "au", "aax"], PRICE_PAID, False),

    # Orchestral / utility
    ("spitfire-labs", "Spitfire LABS", "Spitfire Audio", KIND_ORCHESTRAL, ["vst3", "au", "aax"], PRICE_FREE, False),
    ("bbc-symphony", "BBC Symphony Orchestra", "Spitfire Audio", KIND_ORCHESTRAL, ["vst3", "au", "aax"], PRICE_PAID, False),
    ("youlean-loudness", "Youlean Loudness Meter", "Youlean", KIND_UTILITY, ["vst3", "vst2", "au"], PRICE_FREE, False),
    ("span", "SPAN", "Voxengo", KIND_UTILITY, ["vst3", "vst2", "au"], PRICE_FREE, False),
]

PLUGIN_KEYS = [p[0] for p in PLUGINS]
BY_KEY = {p[0]: p for p in PLUGINS}

_KIND_LABEL = {k: (n, e) for k, n, e in KINDS}
_FORMAT_LABEL = {k: (n, e) for k, n, e in FORMATS}


def plugin_payload(key):
    row = BY_KEY.get(key)
    if not row:
        return None
    k, name, vendor, kind, formats, price, browser_ok = row
    kind_name, kind_emoji = _KIND_LABEL.get(kind, (kind, ""))
    return {
        "key": k, "name": name, "vendor": vendor,
        "kind": kind, "kind_name": kind_name, "kind_emoji": kind_emoji,
        "formats": formats, "price": price,
        # Stated in the data so the UI never implies a plugin will run in a tab
        # when it can't. Only Web Audio Modules can.
        "browser_ok": browser_ok,
    }


def catalog_payload():
    return {
        "plugins": [plugin_payload(k) for k in PLUGIN_KEYS],
        "kinds": [{"key": k, "name": n, "emoji": e} for k, n, e in KINDS],
        "formats": [{"key": k, "name": n, "emoji": e} for k, n, e in FORMATS],
        "prices": [{"key": k, "name": n, "emoji": e} for k, n, e in PRICE_TIERS],
        "count": len(PLUGIN_KEYS),
        "browser_playable": sum(1 for p in PLUGINS if p[6]),
        "note": ("Native VST plugins cannot run in a browser — that's a security "
                 "boundary, not a missing feature. This catalog is for matching "
                 "and search. Only Web Audio Modules (browser_ok) can play in a "
                 "tab; the rest need the desktop app."),
    }


def normalize_keys(values, limit=400):
    """Canonical plugin keys from anything a client sends.

    Accepts keys, names, and 'Name — Vendor' display strings, because the same
    label-versus-key confusion that lost members' personas and genres would lose
    their plugins too. Unknown entries are dropped: this drives search, and a
    plugin nobody can search for is worse than none.
    """
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple)):
        return []
    out = []
    for raw in values:
        key = normalize_key(raw)
        if key and key not in out:
            out.append(key)
        if len(out) >= limit:
            break
    return out


def _squash(value):
    text = " ".join(str(value or "").split()).lower()
    return "".join(ch for ch in text if ch.isalnum())


_INDEX = {}
for _row in PLUGINS:
    _INDEX[_squash(_row[0])] = _row[0]          # key
    _INDEX[_squash(_row[1])] = _row[0]          # name
    _INDEX[_squash(f"{_row[1]} {_row[2]}")] = _row[0]   # "Serum Xfer Records"


def normalize_key(value):
    squashed = _squash(value)
    if not squashed:
        return None
    if squashed in _INDEX:
        return _INDEX[squashed]
    # "Serum — Xfer Records" and "Serum (Xfer)" both squash to something with the
    # vendor attached; fall back to a prefix match on the name.
    for indexed, key in _INDEX.items():
        if squashed.startswith(indexed) and len(indexed) >= 4:
            return key
    return None
