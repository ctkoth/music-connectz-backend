"""Mix ConnectZ — AI mastering that runs on the member's own device.

The engine is in the frontend: it measures BS.1770 loudness, true peak and the
spectrum, then EQs, compresses, limits to a loudness target, dithers and writes
a WAV — every move traced to a measurement it can print. None of that touches
this server and none of it costs the platform anything, so there is nothing to
charge and nothing to log: a master is free, and the screen says so before the
button rather than leaving a member to wonder what a "Master it" will cost.

What lives here is the part only a server can own:

* **The ladder** (`catalog.MASTERING`) — how much compression each tier may
  reach. Served, never decided by the client; the engine masters at whatever
  intensity it is handed.
* **What the member chose to keep.** The WAV goes up through the ordinary
  uploads endpoint first, so the tier's upload and storage limits apply to it
  like any other file, and then `POST` records it as a `MasterWork` with the
  settings used and the before/after measurements. A master that is only on
  somebody's device is gone the moment they close the tab; a saved one can be
  played, compared against its original, and taken anywhere a file can go.

Deleting a master deletes its file — the same two steps the uploads screen
takes — so the storage it held comes back. The original it was made from is
never touched by that: it was the member's before they mastered it.
"""
import math

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import (MASTERING, MASTERING_INTENSITY_LABELS, limits_for, mastering_for,
                      mastering_ladder)
from .media import stable_media_url
from .models import MB, MasterWork, Upload, membership_for, storage_used_bytes

TITLE_MAX = 120
DEFAULT_TITLE = "Master"
LIST_MAX = 20

COST_LINE = "Free — mastered on your device. Nothing is uploaded unless you save it."

# ---- Cleaning what the client sends --------------------------------------
#
# A saved master's JSON is the member's own record of their own work, so it is
# CLEANED, never refused: an unknown key is dropped, a junk value becomes
# "not recorded", and nothing a client puts in a request makes the row grow
# without bound. Every range below is a sanity bound on what a meter can
# report, not a judgement about a good master.

INTENSITIES = tuple(MASTERING_INTENSITY_LABELS)
MONO_BASS = ("auto", "on", "off")
BIT_DEPTHS = (16, 24, 32)
EXPORT_FORMATS = ("wav", "mp3")
MP3_KBPS = (128, 192, 256, 320)
# The rates a master may be exported at: the two conversions offered, plus any
# file's own rate left as it was (which is the common case and is any value).
EXPORT_RATES = range(8000, 192_001)
SLUG_MAX = 24
BANDS_MAX = 40
# The most glue any tier is offered. Read off the ladder rather than typed, so
# moving StatZ's ceiling moves what a record can carry with it.
GLUE_DB_CEILING = max(row["glue_db_max"] for row in MASTERING.values())


def _num(v, lo, hi, digits=4):
    """A finite float clamped to [lo, hi], or None. Booleans are not numbers."""
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(f):
        return None
    return round(min(hi, max(lo, f)), digits)


def _int(v, lo, hi):
    f = _num(v, lo, hi)
    return None if f is None else int(round(f))


def _slug(v):
    """A short preset name ("balanced", "streaming"), or None."""
    if not isinstance(v, str):
        return None
    s = v.strip().lower()[:SLUG_MAX]
    return s if s and all(c.isalnum() or c in "-_" for c in s) else None


def clean_settings(raw):
    """Keep only what the engine actually reads, each coerced to its type.

    The intensity is NOT re-checked against the member's tier here. The master
    ran on their device and cost nobody anything; a member who edits the client
    to reach Heaviest has taken nothing from anyone, and refusing to RECORD what
    they already made would only lose them their own settings. The ladder is
    enforced where it means something — the screen that offers the choice.
    """
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    style = _slug(raw.get("style"))
    if style:
        out["style"] = style
    if raw.get("intensity") in INTENSITIES:
        out["intensity"] = raw["intensity"]
    target = raw.get("target")
    if isinstance(target, str):
        t = _slug(target)
        if t:
            out["target"] = t
    else:
        t = _num(target, -60, 0, 2)     # a bare LUFS figure
        if t is not None:
            out["target"] = t
    if "width" in raw:
        # Percent of the side channel; None is "the style's own".
        out["width"] = _num(raw.get("width"), 0, 200, 1)
    if raw.get("monoBass") in MONO_BASS:
        out["monoBass"] = raw["monoBass"]
    if isinstance(raw.get("eq"), bool):
        out["eq"] = raw["eq"]
    trims = raw.get("trims")
    if isinstance(trims, dict):
        out["trims"] = {k: (_num(trims.get(k), -12, 12, 2) or 0.0) for k in ("low", "mid", "high")}
    if "glueDb" in raw:
        # None is "the intensity's own amount".
        out["glueDb"] = _num(raw.get("glueDb"), 0, GLUE_DB_CEILING, 2)
    depth = _int(raw.get("bitDepth"), 0, 64)
    if depth in BIT_DEPTHS:
        out["bitDepth"] = depth
    if isinstance(raw.get("dither"), bool):
        out["dither"] = raw["dither"]
    # A loudness set by hand ("custom" target), and DynamicZ: punch and multiband.
    lufs = _num(raw.get("lufs"), -20, -7, 1)
    if lufs is not None:
        out["lufs"] = lufs
    punch = _int(raw.get("punch"), -50, 50)
    if punch is not None:
        out["punch"] = punch
    if isinstance(raw.get("multiband"), bool):
        out["multiband"] = raw["multiband"]
    # How it was delivered, so a revision can be delivered the same way.
    if raw.get("format") in EXPORT_FORMATS:
        out["format"] = raw["format"]
    kbps = _int(raw.get("kbps"), 0, 1000)
    if kbps in MP3_KBPS:
        out["kbps"] = kbps
    rate = _int(raw.get("exportRate"), 0, 768_000)
    if rate in EXPORT_RATES:
        out["exportRate"] = rate
    # Raising a vocal that sat too low: the lift on the centre of the mix, and a
    # separate vocal file's level against the beat. Whether a vocal file was
    # mixed in is kept; the file never is, the same rule as the reference.
    if raw.get("vocal") == "auto":
        out["vocal"] = "auto"           # measured on each master, the default
    else:
        vocal = _num(raw.get("vocal"), 0, 6, 1)
        if vocal is not None:
            out["vocal"] = vocal
    level = _num(raw.get("vocalLevel"), -12, 12, 1)
    if level is not None:
        out["vocalLevel"] = level
    if isinstance(raw.get("vocalFile"), bool):
        out["vocalFile"] = raw["vocalFile"]
    if isinstance(raw.get("reference"), bool):
        # Whether a reference track was matched — never the reference itself.
        out["reference"] = raw["reference"]
    return out


# key -> (lo, hi, is_int). What the meter reports, bounded.
MEASURES = {
    "lufs": (-150, 20, False),
    "lra": (0, 100, False),
    "truePeakDb": (-200, 40, False),
    "samplePeakDb": (-200, 40, False),
    "plr": (-100, 200, False),
    "correlation": (-1, 1, False),
    "lowCorrelation": (-1, 1, False),
    "sideToMidDb": (-200, 100, False),
    "seconds": (0, 24 * 3600, False),
    "sampleRate": (1, 768_000, True),
    "channels": (1, 32, True),
    "clippedSamples": (0, 10 ** 12, True),
}


def clean_measures(raw):
    """Numeric measurements only, finite and bounded; NaN and ±inf are dropped
    (silence measures −inf LUFS, and that is "no reading", not a number)."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for key, (lo, hi, is_int) in MEASURES.items():
        v = _int(raw.get(key), lo, hi) if is_int else _num(raw.get(key), lo, hi)
        if v is not None:
            out[key] = v
    bands = raw.get("bands")
    if isinstance(bands, list):
        clean = []
        for b in bands[:BANDS_MAX]:
            if not isinstance(b, dict):
                continue
            f = _num(b.get("f"), 1, 100_000, 2)
            if f is None:
                continue
            # A band with no energy in it is null on the meter, and stays null.
            clean.append({"f": f, "db": _num(b.get("db"), -200, 60, 2)})
        out["bands"] = clean
    return out


def clean_title(raw):
    t = " ".join(str(raw or "").split())[:TITLE_MAX].strip()
    return t or DEFAULT_TITLE


# ---- Serving ---------------------------------------------------------------

def _missing(upload):
    return upload is None or bool(upload.missing_since)


def master_dict(m, request=None):
    up = m.upload
    src = m.source_upload
    return {
        "id": m.id,
        "title": m.title,
        "created_at": m.created_at.isoformat(),
        "settings": m.settings or {},
        "before": m.before or {},
        "after": m.after or {},
        # The stable media route, never the storage's own (signed, expiring)
        # address — see media.py.
        "url": (stable_media_url(up, request) or None) if not _missing(up) else None,
        "size_mb": round(up.size_bytes / MB, 2) if up else 0,
        "content_type": up.content_type if up else "",
        "missing": _missing(up),
        # The original it was made from, so a saved master can still be
        # compared against it rather than only played.
        "source_url": (stable_media_url(src, request) or None) if not _missing(src) else None,
    }


def storage_state(user, tier):
    lim = limits_for(tier)
    used = storage_used_bytes(user)
    cap = lim["storage_mb"] * MB
    return {
        "used_mb": round(used / MB, 1),
        "storage_mb": lim["storage_mb"],
        "upload_mb": lim["upload_mb"],
        "free_mb": round(max(cap - used, 0) / MB, 1),
    }


def _own_upload(user, raw_id):
    try:
        pk = int(raw_id)
    except (TypeError, ValueError):
        return None
    return Upload.objects.filter(pk=pk, user=user).first()


def _bad(detail, code=status.HTTP_400_BAD_REQUEST):
    return Response({"detail": detail}, status=code)


class MixView(APIView):
    """GET: the ladder, what your tier reaches, what it costs (nothing), your
    storage and your saved masters. POST: keep one you already uploaded."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        tier = membership_for(request.user).tier
        masters = (MasterWork.objects.filter(user=request.user)
                   .select_related("upload", "source_upload")[:LIST_MAX])
        return Response({
            "tier": tier,
            "allowed": mastering_for(tier),
            "ladder": mastering_ladder(),
            "intensity_labels": dict(MASTERING_INTENSITY_LABELS),
            "cost": {"free": True, "line": COST_LINE},
            "storage": storage_state(request.user, tier),
            "masters": [master_dict(m, request) for m in masters],
        })

    def post(self, request):
        d = request.data if isinstance(request.data, dict) else {}
        up = _own_upload(request.user, d.get("upload_id"))
        if up is None:
            return _bad("That file isn't one of your uploads — upload the master first, then save it.")
        if not (up.content_type or "").lower().startswith("audio/"):
            return _bad(f"A master has to be an audio file, and that one is "
                        f"{up.content_type or 'of no stated type'}.")
        if up.missing_since:
            return _bad("That file isn't on the server any more — upload the master again.")
        src = None
        raw_src = d.get("source_upload_id")
        if raw_src not in (None, ""):
            src = _own_upload(request.user, raw_src)
            if src is None:
                return _bad("The original you named isn't one of your uploads.")
            if src.pk == up.pk:
                # Deleting the master would then delete the original with it.
                return _bad("The master and the original can't be the same file.")
        if MasterWork.objects.filter(upload=up).exists():
            # Two records on one file means deleting either takes the other's
            # file with it.
            return _bad("That file is already saved as a master.", status.HTTP_409_CONFLICT)
        m = MasterWork.objects.create(
            user=request.user, title=clean_title(d.get("title")), upload=up, source_upload=src,
            settings=clean_settings(d.get("settings")),
            before=clean_measures(d.get("before")), after=clean_measures(d.get("after")),
        )
        return Response(master_dict(m, request), status=status.HTTP_201_CREATED)


class MixDetailView(APIView):
    """DELETE: the record and its master file, so the storage comes back. The
    original it was made from is never deleted by this."""

    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        m = (MasterWork.objects.filter(pk=pk, user=request.user)
             .select_related("upload").first())
        if not m:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        up = m.upload
        # A file already known to be gone was not counted against the member
        # (storage_used_bytes), so deleting it frees nothing.
        freed = up.size_bytes if up is not None and not up.missing_since else 0
        with transaction.atomic():
            m.delete()
            if up is not None and up.user_id == request.user.id:
                # The same two steps DELETE /api/economy/uploads/<pk>/ takes:
                # the bytes from storage, then the row.
                up.file.delete(save=False)
                up.delete()
        tier = membership_for(request.user).tier
        return Response({"deleted": True, "freed_mb": round(freed / MB, 2),
                         "storage": storage_state(request.user, tier)})
