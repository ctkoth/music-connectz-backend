"""Keep this take — opt-in, per take, never by default.

A take recorded in the coach is scored and NOT stored, and the privacy policy says so.
That keeps a member's performance out of our storage, and it also means the history
has a score with nothing to play. So a member who wants the recording kept can say so
for THAT take, and the file is then a normal Upload: it counts against their storage
quota, they can delete it like any other, it goes when their account does, and LogZ and
the history can open it.

Opt-in per take rather than a standing setting on purpose: what is kept is somebody's
voice, and "yes, keep this one" is a clearer consent than a switch flipped months ago.
It never changes what the coach does, never costs credits, and a take that does not fit
the quota is still scored — it is just not kept, and the member is told why.
"""
from .catalog import limits_for
from .models import MB, Upload, membership_for, storage_used_bytes


def wants_keep(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def keep_take(user, f):
    """(Upload, "") when the take was stored; (None, reason) when it was not.

    Never raises: the take has been scored and paid for by now, and a storage problem
    must not turn that into an error."""
    try:
        lim = limits_for(membership_for(user).tier)
        if f.size > lim["upload_mb"] * MB:
            return None, f"Not kept — it is over your {lim['upload_mb']}MB per-file limit. It was still scored."
        if storage_used_bytes(user) + f.size > lim["storage_mb"] * MB:
            return None, (f"Not kept — it would take you past your {lim['storage_mb']}MB of storage. "
                          "Delete something in your uploads to make room. It was still scored.")
        try:
            f.seek(0)                       # scoring read it; the copy starts at the beginning
        except Exception:                   # pragma: no cover
            pass
        up = Upload.objects.create(user=user, file=f, name=str(getattr(f, "name", "take"))[:255],
                                   size_bytes=f.size,
                                   content_type=str(getattr(f, "content_type", "") or "")[:120])
        return up, ""
    except Exception:                       # pragma: no cover
        return None, "Not kept — the file could not be saved. It was still scored."
