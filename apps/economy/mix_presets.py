"""Mix presets: a genre's usual mix, applied to every part of a piece.

A preset is a set of NUDGES on each part's usual place (`instrument_mix.role_default`), so it works
for any combination of instruments and never replaces what the coach set with a fixed table. They
are starting points, said so on the sheet like the coach's own numbers — never a measurement.

Tier: everybody may READ the list. Premium can apply one to hear or download it (nothing stored);
StatZ can apply one AND keep it, and save their own AI-written presets by type (`AIPreset`). The
keep and the library are saved preferences, so `statz_trial.DRIVERS` lists them as not sampled.
"""
from . import instrumental_mix as mixmod

# genre: (label, {role-group: {param: delta}}). Groups: drums, bass, lead, chords, space_parts.
PRESETS = {
    "hip hop": ("Hip Hop", {"drums": {"gain": 0.05, "compress": 0.15, "low": 1.0},
                            "bass": {"low": 1.5, "compress": 0.1},
                            "chords": {"space": -0.1, "gain": -0.05}}),
    "trap": ("Trap", {"drums": {"compress": 0.2, "high": 1.0}, "bass": {"low": 2.0, "gain": 0.05},
                      "chords": {"space": 0.1}}),
    "rock": ("Rock", {"drums": {"space": 0.1, "compress": 0.1}, "chords": {"gain": 0.05, "mid": 0.5},
                      "bass": {"mid": 0.5}}),
    "metal": ("Metal", {"drums": {"compress": 0.2, "high": 1.0, "gain": 0.05},
                        "chords": {"gain": 0.1, "mid": -0.5, "high": 0.5}, "bass": {"mid": 1.0}}),
    "country": ("Country", {"chords": {"pan": 0.0, "space": 0.05, "high": 0.5}, "lead": {"gain": 0.05},
                            "drums": {"compress": -0.1}}),
    "pop": ("Pop", {"lead": {"gain": 0.1, "compress": 0.15, "high": 0.5}, "drums": {"compress": 0.1},
                    "chords": {"space": 0.1}}),
    "jazz": ("Jazz", {"drums": {"compress": -0.3, "gain": -0.1}, "bass": {"compress": -0.3},
                      "chords": {"space": 0.1, "compress": -0.1}}),
    "edm": ("EDM", {"drums": {"compress": 0.25, "gain": 0.05}, "bass": {"low": 1.0, "compress": 0.2},
                    "chords": {"space": 0.15, "high": 0.5}}),
    "lofi": ("Lo-Fi", {"chords": {"high": -2.0, "space": 0.1}, "drums": {"high": -1.5, "compress": 0.2},
                       "lead": {"high": -1.5}}),
    "rnb": ("R&B", {"bass": {"low": 1.0}, "chords": {"space": 0.15}, "lead": {"space": 0.1, "compress": 0.1}}),
    "classical": ("Classical", {"drums": {"gain": -0.2}, "chords": {"space": 0.2, "compress": -0.15},
                                "lead": {"space": 0.15}}),
}

_GROUP = {"drums": "drums", "bass": "bass", "synth_bass": "bass", "lead": "lead"}


def group_of(inst):
    return _GROUP.get(inst, "chords")


def listing():
    return [{"key": k, "label": v[0]} for k, v in PRESETS.items()]


def apply_nudges(instruments, nudges):
    """{instrument: flat mix} — each part's usual place plus the nudges for its group, clamped."""
    out = {}
    for inst in instruments:
        base = mixmod.role_default(inst)
        for name, d in (nudges.get(group_of(inst)) or {}).items():
            if name in mixmod.PARAMS:
                base[name] = base[name] + d
        out[inst] = {n: mixmod.clamp(n, v, mixmod.PARAMS[n][2]) for n, v in base.items()}
    return out


def for_genre(key, instruments):
    row = PRESETS.get(str(key or "").strip().lower())
    return apply_nudges(instruments, row[1]) if row else None


def clean_nudges(raw):
    """What the AI (or a member) sent as {group: {param: delta}} -> only known groups/params, bounded."""
    out = {}
    if not isinstance(raw, dict):
        return out
    for g in ("drums", "bass", "lead", "chords"):
        row = raw.get(g)
        if not isinstance(row, dict):
            continue
        clean = {}
        for n, v in row.items():
            if n in mixmod.PARAMS:
                lo, hi, _ = mixmod.PARAMS[n]
                try:
                    clean[n] = round(max(-(hi - lo) / 2, min((hi - lo) / 2, float(v))), 2)
                except (TypeError, ValueError):
                    pass
        if clean:
            out[g] = clean
    return out
