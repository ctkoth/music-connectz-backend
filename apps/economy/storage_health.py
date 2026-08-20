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

DOCS = ("Set S3_BUCKET_NAME, S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY "
        "(plus S3_ENDPOINT_URL for Cloudflare R2). settings.py switches to the "
        "bucket automatically — no code change and no redeploy of this app is "
        "needed beyond restarting it with the variables set.")


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
    # Ephemeral means BOTH: stored on the container's own disk, AND running
    # somewhere that throws the container away. Either alone is fine.
    ephemeral = local and on_render
    return {
        "backend": backend.rsplit(".", 1)[-1] or "unknown",
        "bucket": os.environ.get("S3_BUCKET_NAME") or "",
        "durable": not ephemeral,
        "ephemeral": ephemeral,
        "where": str(getattr(settings, "MEDIA_ROOT", "")) if local else "object storage",
        "detail": (
            "Uploads are on this container's own disk, and this container is "
            "replaced on every deploy — so every file a member has uploaded is "
            "deleted the next time anything ships. " + DOCS
        ) if ephemeral else "",
    }


def warn_once():
    """Say it in the running service's log, at startup. Never raises: a warning
    that can take the app down is worse than the thing it warns about."""
    try:
        state = upload_storage_state()
    except Exception:                                    # pragma: no cover
        return
    if state["ephemeral"]:
        logger.warning(
            "MEMBER UPLOADS ARE NOT DURABLE — storing to %s on an ephemeral "
            "container disk. Every uploaded file is destroyed on the next "
            "deploy. %s", state["where"], DOCS)
