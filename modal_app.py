"""Modal functions for Music ConnectZ. Deploy with `modal deploy modal_app.py`.

Why this exists: transcoding is the one job that cannot share a box with the
web server. ffmpeg pins a CPU for the length of the file, and on a small Render
instance one member converting a video makes the whole site time out for
everybody else. Modal runs it in an isolated container that spins up, does the
work, and disappears — you pay for the seconds it ran and nothing while idle.

The Django side (economy/transcode.py) calls this by name and falls back
cleanly when Modal isn't configured, so a deployment without a Modal token
behaves exactly as it did before rather than erroring.

    pip install modal
    modal setup                    # links your account, opens a browser
    modal deploy modal_app.py      # publishes the functions below

Then set MODAL_TOKEN_ID and MODAL_TOKEN_SECRET on the web service.
"""
import modal

APP_NAME = "music-connectz"

# ffmpeg from the distro rather than a pip wheel — the wheels are frequently
# built without the encoders we need, and libmp3lame is not optional here.
image = (
    modal.Image.debian_slim()
    .apt_install("ffmpeg")
    .pip_install("requests")
)

app = modal.App(APP_NAME, image=image)


@app.function(timeout=600, memory=2048)
def transcode_to_mp3(source_url: str, bitrate: str = "320k") -> bytes:
    """Pull a media URL, strip the video, return mp3 bytes.

    Returns the audio rather than writing it anywhere: storage is Django's job
    and it already enforces per-tier quotas. A function that also uploaded
    would need the storage credentials, and those have no business here.

    Raises RuntimeError with something a member can read — the caller turns it
    into a 422, because "the source has no audio track" is a fact about their
    file, not a server fault.
    """
    import os
    import subprocess
    import tempfile

    import requests

    if not source_url:
        raise RuntimeError("No source URL.")

    src = out = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".src", delete=False) as fh:
            src = fh.name
            # Streamed, not read into memory — a long video is bigger than the
            # container's RAM and .content would kill the function outright.
            with requests.get(source_url, stream=True, timeout=120) as r:
                r.raise_for_status()
                for chunk in r.iter_content(chunk_size=1 << 20):
                    fh.write(chunk)
        out = src + ".mp3"
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", src, "-vn", "-ac", "2", "-b:a", bitrate, out],
            capture_output=True, timeout=540,
        )
        if proc.returncode != 0 or not os.path.exists(out):
            tail = (proc.stderr or b"").decode("utf8", "replace")[-300:]
            raise RuntimeError(
                f"Transcode failed — the source may have no audio track. {tail}")
        with open(out, "rb") as fh:
            return fh.read()
    finally:
        for path in (src, out):
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
