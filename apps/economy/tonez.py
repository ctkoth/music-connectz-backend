"""Presets: a member saves a setting under a name and uses it anywhere — one ceiling PER KIND.

Kinds (`KINDS`): a track TONE and a track FX chain (both a DAW effect chain), and a MASTER (Mix
ConnectZ's mastering settings). Corey: presets of each type get the same numbers, so saving FX never
impedes on tones — each kind counts on its own against the tier's `tone_presets` (3 / 6 / unlimited).

Corey: let members save tone presets, with the tier numbers, so they can make voice presets of
their own. A preset is the chain a DAW track already carries — EQ, compressor, delay, reverb, filter,
gain — so a vocal sound dialled in once in Arsenal is one tap away on the next track, in Witchcraft,
on another device. Nothing is rendered here and nothing is charged; it is a saved setting.

What the server owns is the part that has to hold: whose it is, how many the tier keeps
(`tone_presets`: Free 3, Premium 6, StatZ unlimited) and that a stored chain is the right SHAPE.
The parameter RANGES are the client's (`src/daw/plugins.js cleanInserts` clamps every value as a
preset is applied), because they are properties of the effects, which live there; a second copy of
every range here is the drift this repo keeps writing about. So this keeps: a known effect type,
on/off, and finite numbers under that effect's own parameter names — nothing else gets stored.

Nobody loses a preset when the ceiling moves: over it, every preset stays usable, renamable and
deletable; only adding a NEW one is refused, with the number.
"""
import math
import re

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import TonePreset

# The effects a chain may hold, and each one's parameter names (mirrors src/daw/plugins.js PLUGINS).
PARAMS = {
    "eq": ("lowGain", "lowFreq", "midGain", "midFreq", "midQ", "highGain", "highFreq"),
    "comp": ("threshold", "ratio", "attack", "release", "knee", "makeup"),
    "delay": ("time", "sync", "feedback", "mix"),
    "reverb": ("decay", "predelay", "mix"),
    "filter": ("mode", "freq", "q"),
    "gain": ("db",),
}
MAX_INSERTS = 8
# An EQ's bands ride beside its params: how many is the tier's (`eq_bands`, said on the screen, applied there),
# the engine's own bound is MAX_BANDS, and each band is a known type with finite numbers. A preset keeps every
# band it was saved with, like a member over a ceiling keeps what they have.
BAND_TYPES = ("lowshelf", "peaking", "highshelf")
BAND_KEYS = ("f", "gain", "q")
MAX_BANDS = 32


def clean_bands(raw):
    out = []
    for b in raw if isinstance(raw, list) else []:
        if not isinstance(b, dict) or b.get("type") not in BAND_TYPES:
            continue
        band = {"type": b["type"]}
        for k in BAND_KEYS:
            try:
                v = float(b.get(k))
            except (TypeError, ValueError):
                continue
            if math.isfinite(v):
                band[k] = v
        if "f" in band:
            out.append(band)
        if len(out) >= MAX_BANDS:
            break
    return out
NAME_MAX = 60
NOTE_MAX = 200
WHO = "Your presets are yours: they follow you to every DAW and every device. Nobody else sees them."


def clean_chain(raw):
    """The chain as stored: known effects only, on/off, finite numbers under their own names."""
    out = []
    for ins in raw if isinstance(raw, list) else []:
        if not isinstance(ins, dict) or ins.get("type") not in PARAMS:
            continue
        params = {}
        given = ins.get("params") if isinstance(ins.get("params"), dict) else {}
        for k in PARAMS[ins["type"]]:
            try:
                v = float(given.get(k))
            except (TypeError, ValueError):
                continue
            if math.isfinite(v):
                params[k] = v
        row = {"type": ins["type"], "on": ins.get("on") is not False, "params": params}
        if ins["type"] == "eq" and isinstance(ins.get("bands"), list):
            row["bands"] = clean_bands(ins["bands"])
        out.append(row)
        if len(out) >= MAX_INSERTS:
            break
    return out


def clean_master(raw):
    """A mastering preset is Mix ConnectZ's settings, kept by the same rule as a saved master."""
    from .mixz import clean_settings
    out = clean_settings(raw)
    for k in ("bitDepth", "dither", "format", "kbps", "exportRate"):   # export choices are not the sound
        out.pop(k, None)
    return out


STRIP_SPEEDS = ("fast", "medium", "slow")


def clean_strip(raw):
    """A TrackZ channel strip (Mix ConnectZ): its low cut, its EQ bands and its compressor. The SHAPE is
    kept here; the ranges are strip.js's (`cleanStrip` clamps as a preset is applied), same rule as a chain.
    Empty when nothing in it is a number, so a blank strip cannot be saved as a preset."""
    if not isinstance(raw, dict):
        return {}
    out = {}
    try:
        hp = float(raw.get("hp"))
        if math.isfinite(hp):
            out["hp"] = hp
    except (TypeError, ValueError):
        pass
    if isinstance(raw.get("bands"), list):
        out["bands"] = clean_bands(raw["bands"])
    c = raw.get("comp")
    if isinstance(c, dict):
        comp = {"on": c.get("on") is True}
        for k in ("thresholdDb", "ratio", "makeupDb"):
            try:
                v = float(c.get(k))
            except (TypeError, ValueError):
                continue
            if math.isfinite(v):
                comp[k] = v
        if c.get("speed") in STRIP_SPEEDS:
            comp["speed"] = c["speed"]
        out["comp"] = comp
    return out if (out.get("bands") or "hp" in out or out.get("comp")) else {}


# A VST3 plugin preset: the plugin's own saved state (the base64 blob the Windows app's host returns), kept
# under the plugin's id. The blob is opaque — only that plugin can read it — so the server keeps its SHAPE
# (base64, a size bound) and nothing about what is inside. Counted PER PLUGIN: a member's compressor and
# their EQ each get the tier's number, the way a plugin's own preset browser belongs to that plugin.
VST_STATE_MAX = 400_000          # characters of base64 (~300 KB); a heavy plugin's state is well under this
_B64 = re.compile(r"^[A-Za-z0-9+/=]+$")
_UID = re.compile(r"^[A-Za-z0-9]{8,64}$")


def clean_vst(raw):
    if not isinstance(raw, dict):
        return {}
    uid = str(raw.get("uid") or "").strip()
    state = "".join(str(raw.get("state") or "").split())
    if not _UID.match(uid) or not state or len(state) > VST_STATE_MAX or not _B64.match(state):
        return {}
    def clip(k):
        return " ".join(str(raw.get(k) or "").split())[:80]
    return {"uid": uid, "plugin": clip("plugin"), "vendor": clip("vendor"), "state": state}


# Each kind: what it is called on screen, and how its stored value is cleaned. A new kind is one row.
KINDS = {
    "tone": {"label": "Track tone", "clean": clean_chain},
    "fx": {"label": "Track FX", "clean": clean_chain},
    "master": {"label": "Mastering", "clean": clean_master},
    "strip": {"label": "Channel strip", "clean": clean_strip},
    "vst": {"label": "Plugin", "clean": clean_vst, "per_plugin": True},
}


def _in_scope(rows, kind, chain):
    """The rows one ceiling counts: the whole kind, or — for a plugin preset — that plugin's own."""
    same = [p for p in rows if p.kind == kind]
    if KINDS[kind].get("per_plugin"):
        return [p for p in same if isinstance(p.chain, dict) and p.chain.get("uid") == chain.get("uid")]
    return same


def cap_for(user):
    from .catalog import limits_for
    from .models import membership_for
    return limits_for(membership_for(user).tier).get("tone_presets")


def _row(p):
    return {"id": p.id, "kind": p.kind, "name": p.name, "note": p.note, "chain": p.chain, "updated_at": p.updated_at.isoformat()}


def _state(user):
    rows = list(TonePreset.objects.filter(owner=user))
    cap = cap_for(user)
    from .catalog import limits_for
    kinds = {}
    for k, spec in KINDS.items():
        n = sum(1 for p in rows if p.kind == k)
        kinds[k] = {"label": spec["label"], "count": n, "full": cap is not None and n >= cap and not spec.get("per_plugin")}
    plugins = {}
    for p in rows:
        if p.kind == "vst" and isinstance(p.chain, dict) and p.chain.get("uid"):
            plugins[p.chain["uid"]] = plugins.get(p.chain["uid"], 0) + 1
    return {"presets": [_row(p) for p in rows], "kinds": kinds, "limit": cap, "per_kind": True, "per_plugin": plugins,
            "who": WHO, "cost": "Free",
            "ladder": {t: limits_for(t)["tone_presets"] for t in ("free", "premium", "statz")}}


class ToneZView(APIView):
    """GET your presets and the ceiling; POST {name, chain, note?, id?} saves one (an id updates it)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(_state(request.user))

    def post(self, request):
        d = request.data or {}
        name = " ".join(str(d.get("name") or "").split())[:NAME_MAX]
        if not name:
            return Response({"detail": "Give the preset a name, like “My vocal”."}, status=status.HTTP_400_BAD_REQUEST)
        kind = str(d.get("kind") or "tone")
        if kind not in KINDS:
            return Response({"detail": "Save it as a track tone, track FX, mastering, channel strip or plugin preset."}, status=status.HTTP_400_BAD_REQUEST)
        chain = KINDS[kind]["clean"](d.get("chain"))
        if not chain:
            return Response({"detail": "There's nothing to save yet: add an effect first." if kind not in ("master", "vst")
                             else "There are no settings to save yet."}, status=status.HTTP_400_BAD_REQUEST)
        note = " ".join(str(d.get("note") or "").split())[:NOTE_MAX]
        mine = _in_scope(list(TonePreset.objects.filter(owner=request.user, kind=kind)), kind, chain)
        existing = None
        if d.get("id"):
            existing = TonePreset.objects.filter(owner=request.user, pk=d.get("id")).first()
            if existing is None:
                return Response({"detail": "That preset isn't yours, or was deleted."}, status=status.HTTP_404_NOT_FOUND)
            if kind == "vst" and (not isinstance(existing.chain, dict) or existing.chain.get("uid") != chain["uid"]):
                return Response({"detail": "A preset belongs to the plugin it was saved from — save this as a new one instead."},
                                status=status.HTTP_400_BAD_REQUEST)
            if existing.kind != kind:
                return Response({"detail": "A preset keeps its kind — save this as a new one instead."},
                                status=status.HTTP_400_BAD_REQUEST)
        if any(p.name.lower() == name.lower() and (existing is None or p.pk != existing.pk) for p in mine):
            return Response({"detail": f"You already have a preset called “{name}”. Pick another name, or update that one."},
                            status=status.HTTP_409_CONFLICT)
        if existing is None:
            cap = cap_for(request.user)
            if cap is not None and len(mine) >= cap:
                from .catalog import limits_for
                nxt = limits_for("premium")["tone_presets"]
                return Response({"detail": f"Your plan keeps {cap} {KINDS[kind]['label'].lower()} presets{' for this plugin' if KINDS[kind].get('per_plugin') else ''}. Update or delete one to make room, "
                                           f"or upgrade (Premium keeps {nxt}; StatZ is unlimited).", "limit": cap},
                                status=status.HTTP_403_FORBIDDEN)
            existing = TonePreset(owner=request.user)
        existing.kind, existing.name, existing.chain, existing.note = kind, name, chain, note
        existing.save()
        return Response({"preset": _row(existing), **_state(request.user)}, status=status.HTTP_201_CREATED)


class ToneZDetailView(APIView):
    """DELETE one of your presets."""

    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        n, _ = TonePreset.objects.filter(owner=request.user, pk=pk).delete()
        if not n:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(_state(request.user))
