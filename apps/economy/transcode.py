"""Getting audio out of a video, wherever there's a machine that can do it.

Two backends, one function. `to_mp3()` tries local ffmpeg first and falls back
to Modal (modal.com), a serverless runner that spins a container up, does the
work, and disappears. Whichever answers, the caller gets mp3 bytes back and
never learns which one ran.

Why the fallback exists at all: ffmpeg pins a CPU for the length of the file.
On a small Render instance one member converting a video makes the whole site
time out for everybody else, and Render's Python image has no ffmpeg on it
anyway — which is why DistributeZ's transcode has been answering 503 in
production since it shipped. Modal bills by the second the container ran and
nothing while idle, so the box that does the heavy work isn't the box serving
requests, and isn't running at all most of the time.

Configure it with MODAL_TOKEN_ID and MODAL_TOKEN_SECRET (see modal_app.py for
the deploy steps). With neither ffmpeg nor a Modal token, `available()` is
False and callers refuse cleanly with a route — the behaviour a deployment had
before this module existed, minus the dead end.
"""
import os
import shutil
import subprocess
import tempfile
import urllib.request

MODAL_APP = "music-connectz"
MODAL_FUNCTION = "transcode_to_mp3"

#: Local ffmpeg gets a shorter leash than Modal does. It's sharing a CPU with
#: the web server, so a long file has to give up before the request does.
LOCAL_TIMEOUT = 120
MODAL_TIMEOUT = 600


class TranscodeUnavailable(RuntimeError):
    """No backend is configured or reachable. A 503 — the server's problem."""


class TranscodeFailed(RuntimeError):
    """The source couldn't be converted. A 422 — a fact about their file.

    Kept separate from Unavailable on purpose: "your video has no audio track"
    and "we have nowhere to run ffmpeg" read identically to a member if you
    give them the same status code, and only one of them is worth retrying.
    """


def has_local_ffmpeg():
    return bool(shutil.which("ffmpeg"))


def modal_configured():
    """True when Modal could actually be called.

    Both halves of the token matter. An ID with no secret authenticates
    nothing, and finding that out inside a request means the member waited for
    a download before hearing no.
    """
    if not (os.environ.get("MODAL_TOKEN_ID") and os.environ.get("MODAL_TOKEN_SECRET")):
        return False
    try:
        import modal  # noqa: F401
    except ImportError:
        return False
    return True


def available():
    return has_local_ffmpeg() or modal_configured()


def backend():
    """Which one would run, for status endpoints and error messages."""
    if has_local_ffmpeg():
        return "local"
    if modal_configured():
        return "modal"
    return ""


def to_mp3(url, bitrate="320k"):
    """Fetch `url`, drop the video, return mp3 bytes.

    Local ffmpeg wins when it's there — it's free and there's no network hop.
    Modal is the fallback rather than the default for the same reason: a
    machine that already has ffmpeg shouldn't be paying per second to borrow
    somebody else's.
    """
    url = str(url or "").strip()
    if not url:
        raise TranscodeFailed("No source URL.")
    if has_local_ffmpeg():
        return _to_mp3_local(url, bitrate)
    if modal_configured():
        return _to_mp3_modal(url, bitrate)
    raise TranscodeUnavailable(
        "No transcoder is configured — install ffmpeg on the host or set "
        "MODAL_TOKEN_ID and MODAL_TOKEN_SECRET.")


def _to_mp3_local(url, bitrate):
    src = out = None
    try:
        fd, src = tempfile.mkstemp(suffix=".src")
        os.close(fd)
        try:
            urllib.request.urlretrieve(url, src)
        except Exception as exc:
            raise TranscodeFailed(f"Couldn't fetch the source: {exc}"[:200]) from exc
        out = src + ".mp3"
        try:
            proc = subprocess.run(
                ["ffmpeg", "-y", "-i", src, "-vn", "-ac", "2", "-b:a", bitrate, out],
                capture_output=True, timeout=LOCAL_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            raise TranscodeFailed("Transcode timed out — try a shorter clip.") from exc
        if proc.returncode != 0 or not os.path.exists(out):
            raise TranscodeFailed(
                "Transcode failed — the source may not contain an audio track.")
        with open(out, "rb") as fh:
            return fh.read()
    finally:
        for path in (src, out):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass


def _to_mp3_modal(url, bitrate):
    """Call the deployed Modal function by name.

    Looked up by name rather than imported from modal_app: importing that
    module pulls the Modal SDK into the web process at startup, and a deploy
    that hasn't run yet would then break boot instead of one endpoint.
    """
    import modal

    try:
        fn = modal.Function.from_name(MODAL_APP, MODAL_FUNCTION)
    except Exception as exc:
        raise TranscodeUnavailable(
            f"Modal transcoder not deployed — run `modal deploy modal_app.py`. {exc}"[:200]
        ) from exc

    try:
        data = fn.remote(url, bitrate)
    except Exception as exc:
        # The function raises RuntimeError for a bad source. Everything else —
        # auth, timeouts, the platform being down — is ours, not theirs.
        if type(exc).__name__ in ("RuntimeError", "FunctionTimeoutError"):
            raise TranscodeFailed(str(exc)[:200]) from exc
        raise TranscodeUnavailable(f"Modal transcoder error: {exc}"[:200]) from exc

    if not isinstance(data, (bytes, bytearray)) or not data:
        raise TranscodeFailed(
            "Transcode produced nothing — the source may have no audio track.")
    return bytes(data)
