"""The mix of an Instrumental ConnectZ piece: level, stereo, space, EQ and compression per instrument.

Corey: the mix needs depth, stereo, space, compression and EQ. The coach sets all of it when the
piece is made (the same compose call, no extra price), Premium can change it, StatZ can change it
AND keep it.

What a MIDI file can and cannot carry decides the shape:

* **In the .mid file:** level (note velocity), pan (CC10), reverb send = space (CC91) and the high
  tone as brightness (CC74). A DAW loads these straight onto the track.
* **Not in the .mid file:** compression and EQ work on SOUND, which a MIDI file does not contain.
  They are heard in the browser preview and handed over as a MIX SHEET — plain suggestions per
  instrument for whoever mixes it in Pro Tools. The sheet says so; it never pretends the file has them.
* **The coach's numbers are starting points.** Nothing here is a measurement of the music, and the
  sheet is labelled that way.
* **A piece made before this existed plays as composed.** A missing field is neutral (no pan, no send,
  flat EQ, no compression), so an old download is byte-for-byte what it was.
"""
from .models import TIER_DEBUG, TIER_PREMIUM, TIER_STATZ, membership_for

# name: (low, high, neutral)
PARAMS = {"gain": (0.0, 1.0, 1.0), "pan": (-1.0, 1.0, 0.0), "space": (0.0, 1.0, 0.0),
          "compress": (0.0, 1.0, 0.0), "low": (-6.0, 6.0, 0.0), "mid": (-6.0, 6.0, 0.0),
          "high": (-6.0, 6.0, 0.0)}

# Where a part usually sits when the coach did not say: gain, pan, space, compress, low, mid, high.
ROLE = {
    "drums": (0.90, 0.00, 0.15, 0.60, 0.0, 0.0, 1.0),
    "bass": (0.85, 0.00, 0.05, 0.70, 1.0, 0.0, -1.0),
    "synth_bass": (0.85, 0.00, 0.05, 0.70, 1.0, 0.0, -1.0),
    "lead": (0.80, 0.00, 0.30, 0.50, 0.0, 0.5, 0.5),
    "electric_guitar": (0.75, 0.50, 0.30, 0.50, 0.0, 0.5, 0.0),
    "piano": (0.75, -0.20, 0.30, 0.30, 0.0, 0.0, 0.0),
    "epiano": (0.70, 0.25, 0.30, 0.30, 0.0, 0.0, 0.0),
    "acoustic_guitar": (0.70, -0.50, 0.25, 0.40, -0.5, 0.0, 0.5),
    "brass": (0.70, 0.15, 0.25, 0.50, 0.0, 0.5, 0.0),
    "organ": (0.60, -0.35, 0.30, 0.20, 0.0, 0.0, -0.5),
    "strings": (0.60, 0.00, 0.50, 0.20, 0.0, 0.0, 0.5),
    "choir": (0.50, 0.00, 0.60, 0.20, 0.0, 0.0, 0.5),
    "pad": (0.50, 0.00, 0.60, 0.10, -0.5, -0.5, 0.0),
}
_ORDER = ("gain", "pan", "space", "compress", "low", "mid", "high")


def role_default(inst):
    return dict(zip(_ORDER, ROLE.get(inst, (0.75, 0.0, 0.2, 0.3, 0.0, 0.0, 0.0))))


def clamp(name, value, fallback):
    lo, hi, _ = PARAMS[name]
    try:
        return round(max(lo, min(hi, float(value))), 2)
    except (TypeError, ValueError):
        return fallback


def flat(t):
    """A track dict as the model or the member wrote it -> {gain,pan,space,compress,low,mid,high} or {}
    for the keys that are present. Accepts tone as a nested dict or as low/mid/high."""
    out = {}
    tone = t.get("tone") if isinstance(t.get("tone"), dict) else {}
    for name in PARAMS:
        src = tone.get(name) if name in ("low", "mid", "high") and name in tone else t.get(name)
        if src is not None and not (isinstance(src, str) and not src.strip()):
            out[name] = src
    return out


def fill(t, inst):
    """For a NEW piece: every parameter, the coach's value when usable, else the part's usual place."""
    base, given = role_default(inst), flat(t)
    return {n: clamp(n, given.get(n), base[n]) for n in PARAMS}


def mix_of(track):
    """A STORED track's mix. A field it never had is neutral, so an old piece plays as composed."""
    given = flat(track)
    return {n: clamp(n, given.get(n), PARAMS[n][2]) for n in PARAMS}


def store(mix):
    """The flat mix as it is saved on a track."""
    return {"gain": mix["gain"], "pan": mix["pan"], "space": mix["space"], "compress": mix["compress"],
            "tone": {"low": mix["low"], "mid": mix["mid"], "high": mix["high"]}}


def clean_mix(raw, instruments):
    """{instrument: {param: value}} from a request: known instruments and known params, clamped."""
    out = {}
    if not isinstance(raw, dict):
        return out
    for inst, vals in raw.items():
        if inst not in instruments or not isinstance(vals, dict):
            continue
        row = {n: clamp(n, v, PARAMS[n][2]) for n, v in flat(vals).items()}
        if row:
            out[inst] = row
    return out


def rights(user):
    """The coach sets the mix for everybody; Premium can change it (to hear or download a version);
    StatZ can change it and keep it."""
    tier = membership_for(user).tier
    return {"can_change": tier in (TIER_PREMIUM, TIER_STATZ, TIER_DEBUG),
            "can_keep": tier in (TIER_STATZ, TIER_DEBUG)}


def midi_cc(mix, present):
    """[(controller, value)] for the parameters a file may carry. `present` is which names the track
    or the request actually has, so a piece that never had a pan does not suddenly get one."""
    ccs = []
    if "pan" in present:
        ccs.append((10, round(64 + mix["pan"] * 63)))
    if "space" in present:
        ccs.append((91, round(mix["space"] * 127)))
    if "high" in present:
        ccs.append((74, max(0, min(127, round(64 + mix["high"] * 10)))))
    return ccs


# --- the mix sheet ----------------------------------------------------------------------------

def _comp_words(amount, inst):
    if amount < 0.05:
        return "none needed"
    ratio = "2:1" if amount < 0.35 else "3:1" if amount < 0.55 else "4:1" if amount < 0.8 else "6:1"
    if inst in ("bass", "synth_bass"):
        attack, release = "30 ms", "100 ms"
    elif inst == "drums":
        attack, release = "10 ms", "60 ms"
    elif inst in ("pad", "strings", "choir"):
        attack, release = "40 ms", "200 ms"
    else:
        attack, release = "20 ms", "120 ms"
    reduction = "1-2 dB" if amount < 0.35 else "2-3 dB" if amount < 0.55 else "3-5 dB" if amount < 0.8 else "5-7 dB"
    return f"{ratio}, attack about {attack}, release about {release}, aim for {reduction} of gain reduction"


def _eq_words(mix, inst):
    parts = []
    for band, name, hz in (("low", "low shelf", "100 Hz"), ("mid", "mid bell", "1-3 kHz"),
                           ("high", "high shelf", "8 kHz")):
        v = mix[band]
        if abs(v) >= 0.5:
            parts.append(f"{name} {v:+.1f} dB at {hz}")
    if inst in ("bass", "synth_bass"):
        parts.append("leave the low end alone; check 200-300 Hz for mud")
    elif inst in ("piano", "epiano", "organ", "acoustic_guitar", "electric_guitar", "pad", "strings", "choir", "brass", "lead"):
        parts.append("high-pass around 80-120 Hz so the low end stays with the bass and kick")
    return "; ".join(parts) or "flat"


def sheet(work_tracks, labels):
    """Plain text: one block per instrument. Honest about what is a starting point."""
    lines = ["MIX SHEET — starting points from the coach, not measurements of your music.",
             "A MIDI file carries level, pan and reverb send; EQ and compression are applied to the sound",
             "once an instrument plays it, so they are listed here for whoever mixes it.", ""]
    for t in work_tracks:
        inst = t["instrument"]
        m = mix_of(t) if flat(t) else role_default(inst)
        side = "centre" if abs(m["pan"]) < 0.08 else f"{abs(m['pan']) * 100:.0f}% {'right' if m['pan'] > 0 else 'left'}"
        depth = "up front" if m["space"] < 0.2 else "in the room" if m["space"] < 0.5 else "set back, spacious"
        lines += [labels.get(inst, inst).upper(),
                  f"  Level: {m['gain'] * 100:.0f}%   Pan: {side}   Space: {depth} (reverb send {m['space'] * 100:.0f}%)",
                  f"  EQ: {_eq_words(m, inst)}",
                  f"  Compression: {_comp_words(m['compress'], inst)}", ""]
    return "\n".join(lines).rstrip() + "\n"
