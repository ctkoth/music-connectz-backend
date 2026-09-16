"""One budget for a whole request, instead of timeouts that add up.

A member sent a 3:05 take and watched a spinner for **853 seconds**. Nothing
was broken in the way anything reports: no exception, no 500, no dropped
connection. Every part was doing exactly what it was configured to do.

The arithmetic, which is the whole lesson:

    Files upload            timeout=300
    wait_active poll        40 tries x (20s GET timeout + 1.5s sleep) = 860
    generateContent         timeout=300  PER MODEL, and the chain has four
    ------------------------------------------------------------------
    one request may legally run for              2360s = 39 minutes

853s is `wait_active` one tick from the end of its own worst case. The member
was sitting in that loop.

And the thing that was supposed to stop it did not, for a reason that is
invisible from the config file. `render.yaml` says `--timeout 120`, which
reads as a request timeout. With `--threads 4` gunicorn runs the **gthread**
worker, whose main loop calls `notify()` every second to tell the arbiter it
is alive — and it keeps doing that while a request thread is blocked. So that
120 is a heartbeat check on the worker, never a bound on a request, and a
blocked thread can run for as long as its own `requests` timeouts allow.

A per-call timeout answers "how long may this ONE call hang". Nobody was
answering "how long may this member WAIT", and that is the only number a
person experiences. So:

- A `Deadline` is made once, at the view, from what a human will actually sit
  through, and passed down.
- Every leg asks `remaining()` and never gets more than the budget has left.
- Running out is a real, reported answer, not a hang.

The budget is deliberately shorter than any proxy between us and the member.
A request that dies at a proxy produces the same silence this exists to stop:
the member sees nothing, and we log nothing, because our own process is still
happily waiting on Google.
"""
import time


class Expired(Exception):
    """The budget ran out. Carries the member-facing sentence with it, because
    the caller that catches this is usually not the one that knows what the
    member was trying to do."""

    def __init__(self, message="that took longer than we're willing to make you wait"):
        super().__init__(message)
        self.message = message


class Deadline:
    """How long the member may be kept waiting, counted down.

    `remaining()` never returns more than the budget has left, and never less
    than `floor` — a 0.2s timeout on an HTTP call is not a call, it is a
    guaranteed failure that costs a round trip to discover.
    """

    def __init__(self, seconds, *, floor=1.0):
        self.total = float(seconds)
        self.floor = float(floor)
        self.started = time.monotonic()

    def spent(self):
        return time.monotonic() - self.started

    def left(self):
        return self.total - self.spent()

    def expired(self):
        return self.left() <= 0

    def check(self, message=None):
        """Raise if there is no time left. Called between legs, so a run that
        has already overspent does not start something new."""
        if self.expired():
            raise Expired(message) if message else Expired()

    def remaining(self, cap=None):
        """A timeout for the next call: what's left, never more than `cap`."""
        left = max(self.left(), self.floor)
        return min(left, cap) if cap else left

    def __repr__(self):                                   # pragma: no cover
        return f"<Deadline {self.spent():.1f}s of {self.total:.0f}s>"


# What one Boss Take is allowed to cost a member in WAITING.
#
# Not derived from what Gemini might need — that is how the 39 minutes above
# happened. Derived from a person with a phone: past about a minute and a half
# on an unmoving screen, people conclude it is broken and leave, and on the
# trial door they leave for good. Env-tunable so it can be moved without a
# deploy if real traffic says otherwise.
COACH_BUDGET_SECONDS = 100
