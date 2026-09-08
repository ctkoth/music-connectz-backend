"""The resource marks, in one place — the server's half of `src/resources.js`.

The client has had one place for these since SpinaZ was rendering three
different ways. The server never did: CLAUDE.md says "use these, they are
already established in the codebase", and then every module that needed one
typed the character again — `logz.RESOURCE_EMOJI` here, a literal in a
notification there, another in a refusal string.

That is the same bug the client already fixed once, and it is worse on this
side, because a mark typed into a prompt or an error string is one nobody sees
until a member does. Import them; never retype the character.

Rule 1 needs them at all times: a bare number is the violation, and the mark is
what makes a cost a price rather than a quantity.
"""
from .models import Transaction

ENERGY = "⚡"     # mana; regenerates hourly at reach ÷ tier
SPINAZ = "🍥"     # coin; earned by rating, referring, AdZ/OfferZ
PROMPTZ = "🏷️"   # prepaid AI credits; the daily free allowance is separate
MONEY = "💵"      # real cash balance, in cents server-side
XP = "⭐"         # SkillZ progression

BY_RESOURCE = {
    Transaction.RES_ENERGY: ENERGY,
    Transaction.RES_SPINAZ: SPINAZ,
    Transaction.RES_PROMPTZ: PROMPTZ,
    Transaction.RES_MONEY: MONEY,
    Transaction.RES_XP: XP,
}


def mark(resource):
    """The mark for a resource key, or "" for one we do not have a mark for.

    Empty rather than a placeholder: a wrong mark on a price is worse than a
    missing one, because the member reads it as a currency they hold.
    """
    return BY_RESOURCE.get(resource, "")


def amount(n, resource, sign=""):
    """"+300 🍥" — a number with its mark, the way rule 1 wants it."""
    return f"{sign}{n:,} {mark(resource)}".strip()
