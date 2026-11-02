"""Is the place member uploads go actually going to keep them?

This exists because it did not, and nothing said so.

Render's web filesystem is ephemeral: it is part of the container image, and a
new container is built on every deploy. With no S3/R2 bucket configured,
`MEDIA_ROOT` is a directory inside that container — so every track, video,
cover and avatar any member has ever uploaded is destroyed the next time
anything is merged to `main`.

The `Upload` rows survive in Postgres, because they are in a different system
that does persist. So the app goes on believing the files exist: the feed
renders a player for a track that 404s, the coach asks storage how big a file
is and gets an exception, and the member is told "Something went wrong on our
side" about their own missing music.

Nothing in the code can prevent this — the fix is configuration, a bucket and
its keys. What the code CAN do is refuse to be quiet about it, in the three
places somebody might be looking:

* the deploy log, via a Django system check (`migrate` runs checks, and
  build.sh runs `migrate` on every deploy);
* the running service's log, once, at startup;
* `GET /`, so it can be read from a browser without dashboard access.

A warning nobody sees is the same as no warning, which is what we had.
"""
import logging
import os

from django.conf import settings

logger = logging.getLogger(__name__)

# Render sets this on every service it runs. It is what distinguishes "this
# container's disk will be thrown away" from a laptop, where the same local
# storage backend is completely fine and a warning would be noise — and a
# warning that cries wolf in dev is one nobody reads in production.
RENDER_ENV = "RENDER"

# The env var that says "I have mounted a persistent disk at MEDIA_ROOT".
# There is no way to ask the filesystem whether it survives a deploy — a Render
# disk mount looks exactly like the container's own directory — so this is an
# assertion by whoever configured it, and it is the only thing the check will
# take as one.
DURABLE_ENV = "MEDIA_DURABLE"

DOCS = ("Two ways to fix it, both configuration and neither one a code change. "
        "A BUCKET: set S3_BUCKET_NAME, S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY "
        "(plus S3_ENDPOINT_URL for Cloudflare R2); settings.py switches over on "
        "the next restart. Or a DISK: add the `disk:` block in render.yaml, set "
        "MEDIA_ROOT to its mountPath and MEDIA_DURABLE=1. The bucket scales and "
        "the disk is free of credentials; either one keeps the music.")


def _env_flag(name):
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def is_mounted(path):
    """Is `path` on a mounted volume — itself or any parent short of "/"?

    A Render disk is a mount point and the container's own directory is not, so
    this CAN tell a declared disk from one that was never attached. The module
    used to say nothing could (and so took MEDIA_DURABLE=1 on faith): a flag
    over a directory inside the container is the exact lie that deletes
    everybody's music on the next deploy, and it is checkable. A subdirectory of
    a mounted disk counts, so MEDIA_ROOT may sit inside one.
    """
    try:
        p = os.path.abspath(str(path))
        while p and p != os.path.dirname(p):
            if os.path.ismount(p):
                return True
            p = os.path.dirname(p)
    except Exception:                                    # pragma: no cover
        return True      # cannot tell: do not call a real disk a lie
    return False


CANARY_NAME = ".mcz-canary"
_canary = {}


def touch_canary():
    """Leave a marker in MEDIA_ROOT, or find the one a previous deploy left.

    Whether a disk survives a deploy is a fact about the NEXT deploy, so the
    only proof is a file that is still there after one. The first run writes it;
    every later start that finds it reports `survived: True` and when it was
    first written. A start that does NOT find it, on a service that has been
    running for a while, is storage that was wiped. Never raises, and touches
    no database (`GET /` must not).
    """
    from datetime import datetime, timezone
    try:
        path = os.path.join(str(settings.MEDIA_ROOT), CANARY_NAME)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                _canary.update(survived=True, since=fh.read().strip())
            return dict(_canary)
        except FileNotFoundError:
            pass
        os.makedirs(os.path.dirname(path), exist_ok=True)
        now = datetime.now(timezone.utc).isoformat()
        try:
            # O_EXCL: two gunicorn workers start together and only one writes.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(now)
        except FileExistsError:
            pass
        _canary.update(survived=False, since=now)
    except Exception:                                    # pragma: no cover
        _canary.update(survived=None, since="")
    return dict(_canary)


def _backend():
    """The dotted path of whatever is storing uploads right now."""
    try:
        return settings.STORAGES["default"]["BACKEND"]
    except (AttributeError, KeyError, TypeError):       # pragma: no cover
        return ""


def upload_storage_state():
    """What is holding member uploads, and whether a deploy will wipe it.

    Returns a dict rather than a bool: "durable" is the answer, and the rest is
    what makes the answer checkable by somebody who does not trust it.
    """
    backend = _backend()
    local = backend.endswith("FileSystemStorage")
    on_render = bool(os.environ.get(RENDER_ENV))
    # A mounted persistent disk is local storage that DOES survive a deploy,
    # and it is indistinguishable from the container's own directory from in
    # here. Whoever mounted it says so; nothing else can.
    declared = local and _env_flag(DURABLE_ENV)
    # ...except that it CAN be checked, a little: a disk is a mount point. A
    # declared disk with nothing mounted under MEDIA_ROOT is the lie that costs
    # everyone their music, so on Render it is not believed.
    unmounted = (declared and on_render
                 and not is_mounted(getattr(settings, "MEDIA_ROOT", "")))
    on_disk = declared and not unmounted
    # Ephemeral means all three: on the container's own disk, running somewhere
    # that throws the container away, and no disk mounted under it. Any one of
    # those being false is fine.
    ephemeral = local and on_render and not on_disk
    return {
        "backend": backend.rsplit(".", 1)[-1] or "unknown",
        "bucket": os.environ.get("S3_BUCKET_NAME") or "",
        "durable": not ephemeral,
        "ephemeral": ephemeral,
        # How it is durable, when it is — so "durable: true" can be checked
        # rather than believed. A disk that was declared and never mounted
        # reads as "a persistent disk" here, which is the one lie this can
        # tell, and the reason MEDIA_DURABLE has to be set deliberately.
        "kept_by": ("a bucket" if not local
                    else "a persistent disk" if on_disk
                    else "nothing — a disk is declared but nothing is mounted at MEDIA_ROOT" if unmounted
                    else "nothing" if on_render else "this machine"),
        "canary": dict(_canary) or None,
        "where": str(getattr(settings, "MEDIA_ROOT", "")) if local else "object storage",
        "detail": (
            "Uploads are on this container's own disk, and this container is "
            "replaced on every deploy — so every file a member has uploaded is "
            "deleted the next time anything ships. "
            + ("MEDIA_DURABLE says a disk is mounted, but nothing is mounted at "
               "MEDIA_ROOT, so the declaration is not believed — attach the disk "
               "in render.yaml. " if unmounted else "")
            + DOCS
        ) if ephemeral else "",
    }


def warn_once():
    """Say it in the running service's log, at startup. Never raises: a warning
    that can take the app down is worse than the thing it warns about."""
    try:
        if _backend().endswith("FileSystemStorage") and os.environ.get(RENDER_ENV):
            touch_canary()
        state = upload_storage_state()
    except Exception:                                    # pragma: no cover
        return
    if state["ephemeral"]:
        logger.warning(
            "MEMBER UPLOADS ARE NOT DURABLE — storing to %s on an ephemeral "
            "container disk. Every uploaded file is destroyed on the next "
            "deploy. %s", state["where"], DOCS)
