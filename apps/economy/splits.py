"""How a pot of money gets divided between the people who earned it.

One implementation, because three different ones would eventually disagree
about who gets the rounding remainder, and the person who loses it never finds
out. MangaZ splits by pages authored, CollabZ by agreed percentage — different
weights, identical arithmetic.

Two rules that matter more than they look:

**Nothing evaporates.** Integer division loses cents. `sum(shares) == pot`
always, with the remainder going to a named person rather than the void —
cents lost to rounding are cents somebody earned.

**An empty or zero-weight split pays the fallback, not nobody.** A collab
where everyone left their percentage at 0 is a collab still being negotiated,
not one where the money disappears.
"""


def by_weight(pot_cents, weights, fallback=None):
    """Divide `pot_cents` among `weights` ({who: number}). Returns {who: cents}.

    `fallback` receives the whole pot when no weight is positive, and receives
    the rounding remainder otherwise. Pass the owner — somebody has to be
    answerable for the odd cent.
    """
    pot_cents = int(pot_cents or 0)
    positive = {who: float(w) for who, w in (weights or {}).items()
                if float(w or 0) > 0}
    if pot_cents <= 0:
        return {}
    if not positive:
        return {fallback: pot_cents} if fallback is not None else {}

    total = sum(positive.values())
    shares, paid = {}, 0
    for who, weight in positive.items():
        cut = int(pot_cents * weight / total)
        shares[who] = cut
        paid += cut
    remainder = pot_cents - paid
    if remainder:
        target = fallback if fallback is not None else next(iter(positive))
        shares[target] = shares.get(target, 0) + remainder
    return shares


def describe(shares, pot_cents):
    """A split somebody can check before the money moves.

    Shown rather than assumed: a payout people only see afterwards is one they
    query afterwards, and by then it has already happened.
    """
    return {
        "pot_cents": int(pot_cents or 0),
        "shares": [
            {"user": getattr(who, "username", str(who)),
             "cents": cents,
             "percent": round(cents * 100 / pot_cents, 2) if pot_cents else 0}
            for who, cents in sorted(
                shares.items(),
                key=lambda kv: (-kv[1], getattr(kv[0], "username", "")))
        ],
        "balanced": sum(shares.values()) == int(pot_cents or 0),
    }
