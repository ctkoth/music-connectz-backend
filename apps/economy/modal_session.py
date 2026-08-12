"""A Modal sandbox that lives across tool calls.

`modal_sandbox.run_source()` creates a container, waits for it, reads its
output and throws it away. That is exactly right for the Run button — one file,
one answer — and useless for an agent, which needs to write a file, run the
tests, read the failure, edit, and run them again. Each of those in a fresh
container is a different machine every time.

So this is the same infrastructure with a different lifetime: **create once,
`exec()` many, close at the end.** Everything else it inherits unchanged from
`modal_sandbox`, deliberately — the tier gate, the per-second Energy price, and
the rule that a sandbox which never started is never billed.

Two things it does NOT relax, and both are load-bearing:

**The network stays blocked.** `block_network=True` on every session a member
opens. A member's code reaching the internet from the platform's Modal account
is the platform's outbound traffic wearing their intent, and that is not a knob
worth a convenience. Phase 4 opens it for the owner alone, per-session, logged
every time — but the DEFAULT has to be the safe one, because a default is what
everybody gets.

**Seconds are counted from the wall clock, not from what the caller claims.**
A session is billed for how long it was actually open, so a long-running agent
cannot spend an hour of container time and report two minutes.
"""
import logging

from django.utils import timezone

from .modal_sandbox import (
    MAX_OUTPUT_CHARS,
    RUNNERS,
    SandboxError,
    configured,
    unavailable_reason,
)

log = logging.getLogger(__name__)

# The image a session runs in. One image for the whole session rather than one
# per language: an agent that writes a Python test and a shell script should not
# need two containers to run them, and switching image mid-session would mean
# losing the filesystem it just built.
SESSION_IMAGE = "python:3.12-slim"

# The wall-clock lifetime of a session, whatever the member's per-run budget
# says. A container nobody closed is a container we pay for, so this is the
# backstop for a request that dies before `close()`.
SESSION_MAX_SECONDS = 900

# Per command inside the session. Long enough for a test suite, short enough
# that one wedged command can't eat the whole session.
COMMAND_TIMEOUT_SECONDS = 120


class SandboxSession:
    """One live container, held open across many commands.

    Use it as a context manager so the container is closed even when the agent
    loop raises — a leaked sandbox bills until Modal's own timeout reaps it.
    """

    def __init__(self, *, seconds=SESSION_MAX_SECONDS, workdir="/work"):
        self.seconds = max(1, min(int(seconds), SESSION_MAX_SECONDS))
        self.workdir = workdir
        self.sandbox = None
        self.started_at = None
        self.closed_at = None

    # -- lifetime ---------------------------------------------------------

    def open(self):
        """Start the container. Raises SandboxError if it never came up."""
        if not configured():
            raise SandboxError(unavailable_reason())
        try:
            import modal
        except ImportError as exc:                           # pragma: no cover
            raise SandboxError(
                "The `modal` package isn't installed on the server.") from exc

        from django.conf import settings
        try:
            app = modal.App.lookup(
                getattr(settings, "MODAL_APP_NAME", "music-connectz-occ"),
                create_if_missing=True)
            self.sandbox = modal.Sandbox.create(
                "sleep", str(self.seconds),
                image=modal.Image.from_registry(SESSION_IMAGE),
                app=app,
                timeout=self.seconds,
                # Not negotiable for a member session. See the module docstring.
                block_network=True,
            )
        except Exception as exc:                             # pragma: no cover
            # Nothing came up, so nothing is charged — the same rule
            # vocalcoach.py bills on and occ_run.py inherited.
            raise SandboxError(f"The sandbox didn't start: {exc}"[:300]) from exc
        self.started_at = timezone.now()
        return self

    def close(self):
        """Terminate the container. Safe to call twice, and never raises."""
        if self.sandbox is not None and self.closed_at is None:
            try:
                self.sandbox.terminate()
            except Exception as exc:                         # pragma: no cover
                # A container we failed to kill is Modal's timeout's problem
                # now. Worth a log line, not worth failing the member's run.
                log.warning("OCC sandbox: terminate failed — %s", str(exc)[:200])
        self.closed_at = self.closed_at or timezone.now()

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc_info):
        self.close()
        return False

    # -- work -------------------------------------------------------------

    @property
    def elapsed_seconds(self):
        """Wall-clock seconds this session has been open — what it's billed on."""
        if self.started_at is None:
            return 0
        end = self.closed_at or timezone.now()
        return max(1, int((end - self.started_at).total_seconds()))

    def exec(self, command, *, timeout=COMMAND_TIMEOUT_SECONDS):
        """Run one shell command in the live container.

        A non-zero exit code is NOT an error here — a failing test suite is the
        output the agent asked for, and the whole point of holding the container
        open is that it can read that failure and fix it.
        """
        if self.sandbox is None:
            raise SandboxError("That sandbox session isn't open.")
        try:
            proc = self.sandbox.exec("bash", "-lc", command, timeout=int(timeout))
            out = (proc.stdout.read() or "")[:MAX_OUTPUT_CHARS]
            err = (proc.stderr.read() or "")[:MAX_OUTPUT_CHARS]
            code = proc.returncode
        except Exception as exc:                             # pragma: no cover
            # The command didn't run. Reported rather than raised, so the agent
            # loop treats it like any other failed tool and carries on.
            return {"ok": False, "stdout": "", "stderr": str(exc)[:MAX_OUTPUT_CHARS],
                    "exit_code": -1, "error": f"That command didn't run: {exc}"[:300]}
        return {"ok": True, "stdout": out, "stderr": err,
                "exit_code": code if code is not None else -1}

    def materialise(self, files, *, workdir=None):
        """Write a project's OccFile rows into the container.

        `files` is an iterable of (path, content). Paths must ALREADY have been
        through `normalize_occ_path` — this is where a bad one would become a
        real traversal, so it re-checks rather than trusting its caller. Two
        gates on the same value is cheap; the failure it prevents is not.
        """
        from .models import normalize_occ_path

        root = workdir or self.workdir
        written, refused = [], []
        for raw_path, content in files:
            path = normalize_occ_path(raw_path)
            if not path:
                refused.append(raw_path)
                continue
            # A quoted heredoc delimiter, so nothing in the member's source is
            # expanded by the shell on the way in — same technique run_source
            # uses, for the same reason.
            script = (
                f"mkdir -p {shell_quote(root)}/$(dirname {shell_quote(path)}) && "
                f"cat > {shell_quote(root)}/{shell_quote(path)} <<'MCZ_EOF'\n"
                f"{content}\nMCZ_EOF"
            )
            result = self.exec(script, timeout=30)
            (written if result.get("exit_code") == 0 else refused).append(path)
        return {"written": written, "refused": refused}


def shell_quote(text):
    """shlex.quote, imported here so callers don't need to know that."""
    import shlex
    return shlex.quote(str(text))


def session_languages():
    """Which languages a session can run — inherited, never a second list."""
    return sorted(RUNNERS.keys())
