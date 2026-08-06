"""The sandbox OCC runs code in — Modal.

Every OCC surface so far has said the same thing out loud: OCC edits, tracks
and version-controls code, but it does not RUN it, because running a stranger's
code needs a container per member and that is infrastructure, not a toggle.
This is that infrastructure.

Four rules it inherits from the rest of the app, and none of them are optional:

**It is off until it is real.** With no Modal tokens, `configured()` is False,
`/occ/spec/` keeps `can_execute: False`, and the run endpoint returns 503 with
the reason. No screen offers a Run button that does nothing.

**The price is stated before the button.** A run costs Energy by the second and
GET on the run endpoint returns the rate, the ceiling for the member's tier and
what they have left today — so the cost is known before anything is spent.

**A failed attempt isn't billed.** If the sandbox never produced a usable
result — no container, timed out reaching Modal, SDK missing — nothing is
charged. Code that ran and exited non-zero IS a usable result: that's an error
message the member asked for, and it's billed. Same rule vocalcoach.py bills on.

**A run is not a dead end.** Every run becomes a TaskZ row (the spec's own "one
list, one truth") AND a WorkZ output, so the thing that came out of the sandbox
can be posted, rated, commented on, or carried into another app like anything
else here.
"""
import math
import shlex

from django.conf import settings
from django.utils import timezone

from .models import TIER_STATZ

# What a run costs, per second of sandbox time. Modal bills real money by the
# second; this is the member-facing price in Energy, which is the resource
# that regenerates — so running code is rate-limited by time rather than by
# whether somebody topped up.
ENERGY_PER_SECOND = 1

# Ceilings by tier. Execution is the StatZ reservation — it is the expensive
# thing, and it's what StatZ is for. Everyone else gets told, not hidden from.
TIER_RUN_LIMITS = {
    TIER_STATZ: {"per_run_seconds": 120, "per_day_seconds": 1800},
}
NEEDS_TIER = TIER_STATZ

# How each language is run. `{f}` is the source file the sandbox writes.
# Compiled languages compile and run in one command so a compile error comes
# back as output rather than as a silent nothing.
RUNNERS = {
    "python":     {"file": "main.py",  "image": "python:3.12-slim",   "cmd": "python {f}"},
    "javascript": {"file": "main.js",  "image": "node:22-slim",       "cmd": "node {f}"},
    "typescript": {"file": "main.ts",  "image": "node:22-slim",
                   "cmd": "npx --yes tsx {f}"},
    "ruby":       {"file": "main.rb",  "image": "ruby:3.3-slim",      "cmd": "ruby {f}"},
    "php":        {"file": "main.php", "image": "php:8.3-cli",        "cmd": "php {f}"},
    "go":         {"file": "main.go",  "image": "golang:1.23",        "cmd": "go run {f}"},
    "rust":       {"file": "main.rs",  "image": "rust:1-slim",
                   "cmd": "rustc {f} -o /tmp/a && /tmp/a"},
    "java":       {"file": "Main.java", "image": "eclipse-temurin:21", "cmd": "java {f}"},
    "kotlin":     {"file": "main.kts", "image": "zenika/kotlin",      "cmd": "kotlinc -script {f}"},
    "lua":        {"file": "main.lua", "image": "nickblah/lua:5.4",   "cmd": "lua {f}"},
    "c":          {"file": "main.c",   "image": "gcc:14",
                   "cmd": "gcc {f} -o /tmp/a && /tmp/a"},
    "cpp":        {"file": "main.cpp", "image": "gcc:14",
                   "cmd": "g++ -std=c++20 {f} -o /tmp/a && /tmp/a"},
}

# Anything longer is truncated rather than stored whole — a runaway loop
# printing forever must not be able to fill the database.
MAX_OUTPUT_CHARS = 40_000
MAX_SOURCE_CHARS = 200_000


def configured():
    """Both tokens, or it isn't hooked up. One of the two is a typo, not a setup."""
    return bool(getattr(settings, "MODAL_TOKEN_ID", "")
                and getattr(settings, "MODAL_TOKEN_SECRET", ""))


def unavailable_reason():
    """Why running is off, in words a member can act on. Empty when it's on."""
    if not configured():
        return ("Running code needs a sandbox, and the sandbox isn't connected yet. "
                "Set MODAL_TOKEN_ID and MODAL_TOKEN_SECRET on the server and this "
                "switches on by itself.")
    try:
        import modal  # noqa: F401
    except ImportError:
        return ("The sandbox tokens are set but the `modal` package isn't installed "
                "on the server — add it and redeploy.")
    return ""


def limits_for(tier):
    """The ceilings for a tier — zeros when the tier can't run at all."""
    return TIER_RUN_LIMITS.get(tier, {"per_run_seconds": 0, "per_day_seconds": 0})


def seconds_used_today(user):
    """Sandbox seconds this member has already spent since midnight."""
    from django.db.models import Sum
    from .models import OccTask
    start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return (OccTask.objects
            .filter(user=user, kind=OccTask.KIND_BUILD, created_at__gte=start)
            .aggregate(n=Sum("run_seconds"))["n"] or 0)


def price_for(seconds):
    """What a run of this length costs, stated before it is spent."""
    return max(0, int(math.ceil(seconds * ENERGY_PER_SECOND)))


class SandboxError(Exception):
    """The sandbox never produced a usable result — so nothing is charged."""


def run_source(language, source, *, seconds, workdir="/work"):
    """Run `source` in a fresh Modal sandbox. Returns the result dict.

    Raises SandboxError when nothing usable came back. A non-zero exit code is
    NOT an error here — a compiler telling you what's wrong is the output the
    member asked for.
    """
    runner = RUNNERS.get(language)
    if not runner:
        raise SandboxError(f"OCC can't run {language} yet.")
    if not configured():
        raise SandboxError(unavailable_reason())
    try:
        import modal
    except ImportError as exc:                                   # pragma: no cover
        raise SandboxError("The `modal` package isn't installed on the server.") from exc

    path = f"{workdir}/{runner['file']}"
    # The source goes in via a heredoc with a quoted delimiter, so nothing in
    # the member's code is expanded by the shell on the way in.
    script = (
        f"mkdir -p {workdir} && cd {workdir} && "
        f"cat > {shlex.quote(runner['file'])} <<'MCZ_EOF'\n{source}\nMCZ_EOF\n"
        + runner["cmd"].format(f=shlex.quote(path))
    )

    started = timezone.now()
    try:
        app = modal.App.lookup(getattr(settings, "MODAL_APP_NAME", "music-connectz-occ"),
                               create_if_missing=True)
        sandbox = modal.Sandbox.create(
            "bash", "-lc", script,
            image=modal.Image.from_registry(runner["image"]),
            app=app,
            timeout=int(seconds),
            # No network from inside the sandbox. A member's code should not be
            # able to reach the internet from our account — that's someone
            # else's outbound traffic wearing our name.
            block_network=True,
        )
        sandbox.wait()
        out = (sandbox.stdout.read() or "")[:MAX_OUTPUT_CHARS]
        err = (sandbox.stderr.read() or "")[:MAX_OUTPUT_CHARS]
        code = sandbox.returncode
    except Exception as exc:                                     # pragma: no cover
        # Anything from here is "the sandbox didn't happen": no container, bad
        # token, Modal unreachable. Not the member's fault, so not their bill.
        raise SandboxError(f"The sandbox didn't start: {exc}"[:300]) from exc

    elapsed = max(1, int((timezone.now() - started).total_seconds()))
    return {
        "stdout": out,
        "stderr": err,
        "exit_code": code if code is not None else -1,
        "seconds": min(elapsed, int(seconds)),
        "language": language,
        "timed_out": elapsed >= int(seconds) and code is None,
    }
