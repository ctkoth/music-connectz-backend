"""Whose request this is — one reader, because it decides who gets paid.

There were FIVE copies of these four lines (`trial.py`, `postz.py`,
`links.py`, `adz.py`, `dupez.py`), and all five were wrong the same way:

    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if fwd:
        return fwd.split(",")[0].strip()      # <- the caller's own value

Each proxy APPENDS the address it saw, so a request arriving with its own
`X-Forwarded-For: 1.2.3.4` leaves our proxy as `1.2.3.4, <real>`. Entry `[0]`
is therefore whatever the sender invented, and every one of these is a control
that reads it:

- `postz` mints 🍥 per "distinct authenticated user + IP", and its own comment
  says the cap is there "so rotating IPs / accounts can't farm it". Rotating
  IPs was one header.
- `links` pays +5 ⚡ for a genuine visit, capped per address per day.
- `adz` pays for an ad view, capped per address per day.
- `dupez` records the address an account SIGNED UP from, and two accounts
  sharing one is a duplicate signal. Spoofable in both directions: hide your
  own second account, or put somebody else's address on your signup and raise
  a flag against them.
- `trial` gated the one free no-account take.

So: count from the RIGHT, past the proxies that are ours. `TRUSTED_PROXY_HOPS`
is 1 for Render on its own; a CDN in front makes it 2. Too small over-trusts
the caller; too large reads one of our own proxies and collapses every visitor
onto a single address — which is why nothing keyed on this should be a hard
"one per address" rule. It is a ceiling or a signal, never the only control.
"""
import os


def trusted_proxy_hops():
    """Read per call so it can be changed without a deploy, and so a bad value
    degrades to 1 rather than raising inside a rate limiter."""
    try:
        return max(1, int(os.environ.get("TRUSTED_PROXY_HOPS", "1")))
    except (TypeError, ValueError):
        return 1


def client_ip(request):
    """The caller's address, as far as our own proxies can vouch for it."""
    try:
        fwd = request.META.get("HTTP_X_FORWARDED_FOR", "") or ""
        chain = [p.strip() for p in fwd.split(",") if p.strip()]
        if chain:
            return chain[-min(trusted_proxy_hops(), len(chain))][:64]
        return (request.META.get("REMOTE_ADDR") or "")[:64]
    except (AttributeError, TypeError):
        # dupez swallowed these already; keeping that is right — an address is
        # a hint and a reward cap, never a reason a request cannot complete.
        return ""
