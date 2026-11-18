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
        out.append({"type": ins["type"], "on": ins.get("on") is not False, "params": params})
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


# Each kind: what it is called on screen, and how its stored value is cleaned. A new kind is one row.
KINDS = {
    "tone": {"label": "Track tone", "clean": clean_chain},
    "fx": {"label": "Track FX", "clean": clean_chain},
    "master": {"label": "Mastering", "clean": clean_master},
}


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
        kinds[k] = {"label": spec["label"], "count": n, "full": cap is not None and n >= cap}
    return {"presets": [_row(p) for p in rows], "kinds": kinds, "limit": cap, "per_kind": True,
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
            return Response({"detail": "Save it as a track tone, track FX or mastering preset."}, status=status.HTTP_400_BAD_REQUEST)
        chain = KINDS[kind]["clean"](d.get("chain"))
        if not chain:
            return Response({"detail": "There's nothing to save yet: add an effect first." if kind != "master"
                             else "There are no settings to save yet."}, status=status.HTTP_400_BAD_REQUEST)
        note = " ".join(str(d.get("note") or "").split())[:NOTE_MAX]
        mine = TonePreset.objects.filter(owner=request.user, kind=kind)
        existing = None
        if d.get("id"):
            existing = TonePreset.objects.filter(owner=request.user, pk=d.get("id")).first()
            if existing is None:
                return Response({"detail": "That preset isn't yours, or was deleted."}, status=status.HTTP_404_NOT_FOUND)
            if existing.kind != kind:
                return Response({"detail": "A preset keeps its kind — save this as a new one instead."},
                                status=status.HTTP_400_BAD_REQUEST)
        if mine.filter(name__iexact=name).exclude(pk=existing.pk if existing else None).exists():
            return Response({"detail": f"You already have a preset called “{name}”. Pick another name, or update that one."},
                            status=status.HTTP_409_CONFLICT)
        if existing is None:
            cap = cap_for(request.user)
            if cap is not None and mine.count() >= cap:
                from .catalog import limits_for
                nxt = limits_for("premium")["tone_presets"]
                return Response({"detail": f"Your plan keeps {cap} {KINDS[kind]['label'].lower()} presets. Update or delete one to make room, "
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
