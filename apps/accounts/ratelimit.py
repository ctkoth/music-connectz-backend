"""Failed-attempt limits, for the doors anybody can knock on.

There was no rate limiting anywhere in this project — not in settings, not on
a single view. `/api/auth/login/` took 25 wrong passwords in a row and
answered 400 to every one of them, and would have taken 25 million. Combined
with registration having accepted the literal string "password" until today,
every account that signed up with a top-100 password is one script away.

Two decisions shape this, and both are lessons from elsewhere in this
codebase.

**It counts FAILURES, not requests.** DRF's own throttles count every call,
which would mean a member who logs in successfully all day slowly runs
themselves out of budget, and a test suite that logs in a hundred times
starts failing for a reason that has nothing to do with what it tests. A
successful login clears the bucket. Only a wrong password costs anything, so
the limit is invisible to everybody who is not guessing.

**It is keyed BOTH ways, and neither one alone.** This is the trial door's
lesson repeated: an address is not a person. A limit keyed only on IP punishes
everybody behind a mobile carrier's CGNAT for one stranger's mistakes; a limit
keyed only on the account being guessed does nothing about somebody walking a
list of accounts. So:

- per IDENTIFIER, tight — one account cannot be guessed at, from anywhere.
- per ADDRESS, loose — sized so a shared carrier address full of ordinary
  people never reaches it, because only failures count and honest people do
  not fail thirty times.

The address comes from `economy.clientip`, the one reader, for the reason that
module exists: DRF's own `get_ident` uses the whole X-Forwarded-For string when
`NUM_PROXIES` is unset, so an attacker varying that header gets a fresh bucket
per request and the limit stops nobody.

The cache is Django's default LocMemCache and gunicorn runs two workers, so
these counts are PER WORKER — the real-world limit is about double what is
written here. That is fine for what this is for (a scripted guesser hits it
either way) and is the reason the numbers are not tuned finer than they are.
A shared cache would make them exact; it is not worth a Redis for this.
"""
from django.core.cache import cache

from apps.economy.clientip import client_ip

# Per account being guessed. Eight wrong passwords is far more than a person
# with a password manager and a typo, and nothing at all to a script.
PER_IDENTIFIER = 8
# Per address. Loose on purpose — a carrier's CGNAT address fronts thousands
# of people, and this only ever counts failures.
PER_ADDRESS = 40
# How long a bucket remembers. Long enough that guessing is pointless, short
# enough that somebody who locked themselves out is not stuck for the evening.
WINDOW_SECONDS = 15 * 60


def _key(kind, value):
    return f"authfail:{kind}:{str(value or '').strip().lower()[:128]}"


def failures(kind, value):
    return cache.get(_key(kind, value), 0)


def note_failure(kind, value):
    """Record one. `add` then `incr` so the TTL is set once and the window is
    a real window rather than one that slides forward on every attempt — a
    sliding window never expires while an attack is running, which turns a
    rate limit into a permanent lockout for whoever owns that address."""
    k = _key(kind, value)
    cache.add(k, 0, WINDOW_SECONDS)
    try:
        return cache.incr(k)
    except ValueError:
        # Expired between the add and the incr. Losing one count is fine.
        cache.set(k, 1, WINDOW_SECONDS)
        return 1


def clear(kind, value):
    cache.delete(_key(kind, value))


def login_block_reason(request, identifier):
    """Why this login attempt should be refused before a password is checked,
    or None. Returns the sentence the member reads."""
    if failures("id", identifier) >= PER_IDENTIFIER:
        return ("Too many failed sign-ins for that account. Wait a few minutes, "
                "or reset your password.")
    if failures("ip", client_ip(request)) >= PER_ADDRESS:
        return ("Too many failed sign-ins from this connection. Wait a few minutes "
                "and try again.")
    return None


def note_login_failure(request, identifier):
    note_failure("id", identifier)
    note_failure("ip", client_ip(request))


def note_login_success(request, identifier):
    """A good password clears the account's bucket.

    Not the address bucket: the account has proven who it is, the connection
    has proven nothing, and one real login among a run of guesses is exactly
    what a successful guess looks like.
    """
    clear("id", identifier)
