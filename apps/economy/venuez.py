"""VenueZ — CollabZ when everyone is in the same room.

The whole app is one rule, stated once here so no screen has to restate it:

    Whoever RECEIVES the skill pays for it,
    and the price comes from whoever PROVIDES it.

    performance  the visitor came for the host      → visitor pays, host's rates
    session 🤝   the host wanted the room full      → host pays, visitor's rates
    free         nobody pays

Both directions read the same way, which is the point: a jam session is not a
different economy from a booking, it is the same economy with the arrow turned
round. That is why `quote_for` takes a side rather than branching on kind at
every call site.

The rate is ALWAYS the provider's own PersonaZ number, never a figure the
other side typed into a form — the same rule `post_cost_cents` follows, and
for the same reason: a price the counterparty can set is not a price.
"""
from django.utils import timezone

from .models import VenueBooking, VenueEvent
from .postz import skill_prices


def provider_for(event, visitor):
    """The user whose rates price this booking, or None when it is free."""
    side = event.provider_side()
    if side == "host":
        return event.host
    if side == "visitor":
        return visitor
    return None


def quote_for(event, visitor, skills=None, hours=None):
    """What this booking costs, who pays it, and the line items behind it.

    Quoted BEFORE anybody commits, and returned whole so the button can state
    the price rather than the result revealing it. A skill the provider has
    not priced contributes 0 and is still listed — a silent omission reads as
    a discount and then surprises somebody at the door.
    """
    hours = max(1, int(hours or event.hours or 1))
    names = [s for s in (skills if skills is not None else event.skills) or []
             if isinstance(s, str)][:40]

    provider = provider_for(event, visitor)
    if provider is None:
        return {
            "kind": event.kind, "free": True, "amount_cents": 0,
            "payer": "", "payee": "", "hours": hours, "basis": event.basis,
            "lines": [], "unpriced": [],
        }

    rates = skill_prices(provider)
    lines, subtotal, unpriced = [], 0, []
    for name in names:
        cents = rates.get(name.strip(), 0)
        if not cents:
            unpriced.append(name.strip())
        lines.append({"skill": name.strip(), "cents": cents})
        subtotal += cents

    # Per hour multiplies; an agreed total is the total however long it runs.
    amount = subtotal * hours if event.basis == VenueEvent.BASIS_HOUR else subtotal

    host_pays = event.kind == VenueEvent.KIND_SESSION
    return {
        "kind": event.kind,
        "free": False,
        "amount_cents": amount,
        "hourly_cents": subtotal,
        "hours": hours,
        "basis": event.basis,
        # Said as sides, not usernames, so the client can render it before a
        # visitor is even chosen.
        "payer": "host" if host_pays else "visitor",
        "payee": "visitor" if host_pays else "host",
        "payer_is_host": host_pays,
        "lines": lines,
        # Named rather than dropped: "you listed 3 skills, 2 of them are
        # priced" is a fact the provider can act on by pricing the third.
        "unpriced": unpriced,
    }


def age_ok(user, event):
    """Whether this member clears the room's age rule.

    Unknown age fails a restricted room. An IRL door is the one place where
    "we could not tell" must not resolve to "come in" — the read path already
    re-applies the age gate for explicit voice, and this is the same rule
    where the consequence is physical rather than textual.
    """
    if not event.min_age:
        return True, ""
    # profile_age parses the stored "YYYY-MM-DD" string and answers None when
    # it cannot. Reused rather than reimplemented: `birthday` is a CharField,
    # and a second parser beside the first is how one of them ends up wrong.
    from .models import profile_age, profile_for
    age = profile_age(profile_for(user))
    if age is None:
        return False, ("This one is %d+ and your birthday isn't on your "
                       "profile yet." % event.min_age)
    if age < event.min_age:
        return False, "This one is %d+." % event.min_age
    return True, ""


def seats_left(event):
    taken = event.bookings.filter(status__in=[
        VenueBooking.STATUS_ACCEPTED, VenueBooking.STATUS_ATTENDED,
    ]).count()
    return max(0, event.capacity - taken)


def can_book(user, event):
    """(ok, reason). Every refusal is a sentence somebody can act on."""
    if event.host_id == user.id:
        return False, "It's your own venue."
    if event.status == VenueEvent.STATUS_CANCELLED:
        return False, "That venue was cancelled."
    if event.status == VenueEvent.STATUS_DONE or event.starts_at < timezone.now():
        return False, "That one has already happened."
    if not seats_left(event):
        return False, "It's full."
    ok, why = age_ok(user, event)
    if not ok:
        return False, why
    return True, ""


def address_for(event, user):
    """The doorstep, and only for somebody entitled to stand on it.

    The host always sees it. A visitor sees it once their booking is ACCEPTED
    — not when they request one, because a request nobody approved should not
    hand out an address, and not on the public listing, because a listing that
    pairs an address with the hours its owner will be busy is a different
    product from the one this is meant to be.
    """
    if not event.address:
        return ""
    if event.host_id == user.id:
        return event.address
    booked = event.bookings.filter(
        visitor=user,
        status__in=[VenueBooking.STATUS_ACCEPTED, VenueBooking.STATUS_ATTENDED],
    ).exists()
    return event.address if booked else ""
