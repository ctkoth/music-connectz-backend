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
from django.utils.dateparse import parse_datetime

from .models import VenueBooking, VenueEvent, award_spinaz, spend_spinaz, wallet_for
from .postz import charge_skill_energy, post_cost_cents, skill_prices, skills_from


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

    if event.kind == VenueEvent.KIND_SPINAZ:
        # Flat entry, not skill-priced: the room's price is the room's, and it
        # is the same for every visitor and every number of hours.
        return {
            "kind": event.kind, "free": False, "amount_cents": 0,
            "spinaz": event.spinaz_price,
            "payer": "visitor", "payee": "host", "payer_is_host": False,
            "hours": hours, "basis": event.basis, "lines": [], "unpriced": [],
        }

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


def _venue_target(event):
    return {"app_key": "venuez", "target": f"venuez:{event.id}"}


def refund_spinaz(b, why):
    """Give a held entry back to the visitor. Safe to call twice."""
    if b.spinaz_held and not b.spinaz_settled:
        award_spinaz(b.visitor, b.spinaz_held, f"VenueZ refund — {why}: {b.event.title}",
                     **_venue_target(b.event))
        b.spinaz_settled = True
        b.save(update_fields=["spinaz_settled"])


def settle_spinaz(event):
    """Pay held entries to the host once the event has started.

    Lazy, on read: nothing in this app runs on a timer, and the host is the
    one who looks at their own past rooms. Before the start nothing has been
    paid to anybody, so a cancel is a clean refund rather than a claw-back.
    """
    if event.kind != VenueEvent.KIND_SPINAZ or event.starts_at > timezone.now():
        return
    due = event.bookings.filter(status=VenueBooking.STATUS_ACCEPTED,
                                spinaz_held__gt=0, spinaz_settled=False)
    for b in due.select_related("visitor"):
        award_spinaz(event.host, b.spinaz_held,
                     f"VenueZ entry from {b.visitor.username}: {event.title}",
                     **_venue_target(event))
        b.spinaz_settled = True
        b.save(update_fields=["spinaz_settled"])


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


# ---- API -------------------------------------------------------------------
from django.db import transaction                       # noqa: E402
from rest_framework import status                       # noqa: E402
from rest_framework.permissions import IsAuthenticated  # noqa: E402
from rest_framework.response import Response            # noqa: E402
from rest_framework.views import APIView                # noqa: E402


def booking_dict(b, viewer):
    return {
        "id": b.id,
        "event": b.event_id,
        "visitor": b.visitor.username,
        "status": b.status,
        "skills": b.skills,
        "hours": b.hours,
        # The quote FROZEN at the moment both sides could see it. A PersonaZ
        # rate edited afterwards cannot move what was agreed, which is the
        # difference between a price and a bill.
        "quoted_cents": b.quoted_cents,
        "payer_is_host": b.payer_is_host,
        "spinaz_held": b.spinaz_held,
        "spinaz_settled": b.spinaz_settled,
        "mine": b.visitor_id == viewer.id,
        "created_at": b.created_at,
    }


def event_dict(event, viewer):
    """One venue, and everything a member needs BEFORE committing to it."""
    settle_spinaz(event)
    q = quote_for(event, viewer)
    ok, why = can_book(viewer, event)
    mine = event.host_id == viewer.id
    my = event.bookings.filter(visitor=viewer).first()
    return {
        "id": event.id,
        "host": event.host.username,
        "mine": mine,
        "kind": event.kind,
        "category": event.category,
        "spinaz_price": event.spinaz_price,
        "title": event.title,
        "description": event.description,
        "area": event.area,
        # Empty until a booking is ACCEPTED. Asking is not being let in.
        "address": address_for(event, viewer),
        "starts_at": event.starts_at,
        "hours": event.hours,
        "basis": event.basis,
        "skills": event.skills,
        "capacity": event.capacity,
        "seats_left": seats_left(event),
        "min_age": event.min_age,
        "status": event.status,
        # The price, stated before the button that agrees to it — and stated
        # in BOTH directions, because on a session the host is the one paying
        # and a screen that only ever renders "what this costs you" would be
        # wrong half the time.
        "quote": q,
        "can_book": ok,
        "why_not": why,
        "my_booking": booking_dict(my, viewer) if my else None,
        # Who was there is who may judge it — see the note above VENUE_ITEM.
        "rating": venue_rating_state(event, viewer),
        "bookings": ([booking_dict(b, viewer) for b in
                      event.bookings.select_related("visitor")[:100]]
                     if mine else []),
        # Nothing is a dead end: a venue is a room full of people who could
        # work together, so it opens into the app that handles that.
        "open_in": [{
            "app": "collabz", "target": "collabz-deals",
            "label": "Start a collab from this",
            "what": "Turn who turned up into a deal with the worth written down.",
        }],
    }


def _int(d, key, default, lo, hi):
    try:
        return max(lo, min(hi, int(d.get(key, default))))
    except (TypeError, ValueError):
        return default


class VenueListView(APIView):
    """GET the venues worth showing; POST a new one."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        cat = request.query_params.get("category", "")
        rows = (VenueEvent.objects
                .filter(starts_at__gte=timezone.now())
                .exclude(status=VenueEvent.STATUS_CANCELLED))
        mine = VenueEvent.objects.filter(host=request.user)
        if cat in dict(VenueEvent.CATEGORY_CHOICES):
            rows, mine = rows.filter(category=cat), mine.filter(category=cat)
        rows = rows.select_related("host").prefetch_related("bookings__visitor")[:100]
        mine = mine.select_related("host").prefetch_related("bookings__visitor")[:100]
        seen, out = set(), []
        for e in list(rows) + list(mine):
            if e.id in seen:
                continue
            seen.add(e.id)
            out.append(event_dict(e, request.user))
        return Response({"venues": out})

    def post(self, request):
        d = request.data or {}
        title = str(d.get("title", "")).strip()[:160]
        area = str(d.get("area", "")).strip()[:120]
        kind = str(d.get("kind", "")).strip()
        if not title or not area:
            return Response({"detail": "A venue needs a title and an area."},
                            status=status.HTTP_400_BAD_REQUEST)
        if kind not in dict(VenueEvent.KIND_CHOICES):
            return Response({"detail": "kind must be performance|session|free|spinaz"},
                            status=status.HTTP_400_BAD_REQUEST)
        spinaz_price = _int(d, "spinaz_price", 0, 0, 100000)
        if kind == VenueEvent.KIND_SPINAZ and spinaz_price < 1:
            return Response({"detail": "A SpinaZ room needs an entry price of at least 1 🍥."},
                            status=status.HTTP_400_BAD_REQUEST)
        if kind != VenueEvent.KIND_SPINAZ:
            spinaz_price = 0
        category = d.get("category") if d.get("category") in dict(VenueEvent.CATEGORY_CHOICES) \
            else VenueEvent.CATEGORY_MUSIC

        starts_at = parse_datetime(str(d.get("starts_at", "")))
        if not starts_at:
            return Response({"detail": "starts_at must be an ISO datetime."},
                            status=status.HTTP_400_BAD_REQUEST)
        if timezone.is_naive(starts_at):
            starts_at = timezone.make_aware(starts_at)
        if starts_at < timezone.now():
            return Response({"detail": "That's in the past."},
                            status=status.HTTP_400_BAD_REQUEST)

        skills = [str(s).strip()[:80] for s in (d.get("skills") or [])
                  if str(s).strip()][:40]
        basis = (d.get("basis") if d.get("basis") in dict(VenueEvent.BASIS_CHOICES)
                 else VenueEvent.BASIS_HOUR)

        event = VenueEvent.objects.create(
            host=request.user, kind=kind, title=title, area=area,
            description=str(d.get("description", ""))[:4000],
            address=str(d.get("address", "")).strip()[:300],
            starts_at=starts_at, hours=_int(d, "hours", 1, 1, 24), basis=basis,
            skills=skills, capacity=_int(d, "capacity", 1, 1, 500),
            min_age=_int(d, "min_age", 0, 0, 99),
            category=category, spinaz_price=spinaz_price,
        )
        return Response(event_dict(event, request.user),
                        status=status.HTTP_201_CREATED)


class VenueDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        event = VenueEvent.objects.select_related("host").filter(pk=pk).first()
        if not event:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(event_dict(event, request.user))

    def delete(self, request, pk):
        """The host calls it off. Bookings are told by the status, not deleted —
        somebody who was accepted needs to see that it is cancelled, not find
        an empty page where their evening was."""
        event = VenueEvent.objects.filter(pk=pk, host=request.user).first()
        if not event:
            return Response({"detail": "Not yours, or not here."},
                            status=status.HTTP_404_NOT_FOUND)
        event.status = VenueEvent.STATUS_CANCELLED
        event.save(update_fields=["status"])
        for b in event.bookings.filter(spinaz_held__gt=0, spinaz_settled=False).select_related("visitor", "event"):
            refund_spinaz(b, "the host cancelled")
        return Response(event_dict(event, request.user))


class VenueBookView(APIView):
    """Ask for a seat. The quote is frozen here, before the host answers."""
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk):
        event = (VenueEvent.objects.select_for_update()
                 .select_related("host").filter(pk=pk).first())
        if not event:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)

        ok, why = can_book(request.user, event)
        if not ok:
            return Response({"detail": why}, status=status.HTTP_409_CONFLICT)
        if event.bookings.filter(visitor=request.user).exists():
            return Response({"detail": "You've already asked for this one."},
                            status=status.HTTP_409_CONFLICT)

        d = request.data or {}
        asked = skills_from(d)
        skills = asked or list(event.skills or [])
        hours = _int(d, "hours", event.hours, 1, 24)
        q = quote_for(event, request.user, skills=skills, hours=hours)

        # ⚡ is what it costs to PUT THIS UP, so the visitor asking for the seat
        # pays it, out of their own rates — money's host/visitor direction is a
        # separate question and `quote_for` above is the one that answers it.
        # Charging the host here would have let anybody drain a host's ⚡ by
        # asking for seats they never agreed to, and told them the host's
        # balance while they did it.
        #
        # Only the skills the visitor NAMED are charged for. Falling back to the
        # room's own list would bill somebody for a line they never wrote.
        held = 0
        if event.kind == VenueEvent.KIND_SPINAZ:
            if spend_spinaz(request.user, event.spinaz_price,
                            f"VenueZ entry held: {event.title}", **_venue_target(event)) is None:
                have = max(0, wallet_for(request.user).spinaz or 0)
                return Response({"detail": f"Entry is {event.spinaz_price} 🍥 and you have {have}.",
                                 "spinaz_needed": event.spinaz_price, "spinaz_available": have},
                                status=status.HTTP_402_PAYMENT_REQUIRED)
            held = event.spinaz_price

        energy, denied = charge_skill_energy(request.user, asked)
        if denied:
            if held:
                award_spinaz(request.user, held, f"VenueZ entry returned: {event.title}",
                             **_venue_target(event))
            body, code = denied
            body["detail"] = (f"Asking for this seat costs {body['energy_needed']} ⚡ "
                              f"and you have {body['energy_available']}.")
            return Response(body, status=code)

        b = VenueBooking.objects.create(
            event=event, visitor=request.user, skills=skills, hours=hours,
            quoted_cents=q["amount_cents"], payer_is_host=q.get("payer_is_host", False),
            spinaz_held=held,
        )

        # ZodiacZ — Sagittarius goes. Every VenuZ room is a physical one, so
        # asking for a seat IS the action; the stretch is the length of the
        # booking, which is the only thing here we actually measure.
        from .signbonus import try_award
        try_award(request.user, "venue_book", stretch=hours >= 3)

        return Response({"booking": booking_dict(b, request.user),
                         "venue": event_dict(event, request.user), **energy},
                        status=status.HTTP_201_CREATED)


class VenueQuoteView(APIView):
    """GET what THIS booking costs, for the skills and hours actually asked for.

    The quote on the listing is the room's own defaults. The moment a visitor
    names their own skills or a different number of hours, that figure stops
    being the one that will be charged — and a price that no longer matches the
    button it sits above is the bill this rule exists to stop.

    So it runs the SAME `quote_for` the booking runs, and prices the ⚡ off the
    same `post_cost_cents`, rather than the screen doing arithmetic of its own.
    Money and ⚡ are quoted together because they answer different questions and
    a member is about to commit to both: money can be owed BY the host (a
    session pays the visitor), while the ⚡ is always the asker's, for the skills
    the asker named.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        event = VenueEvent.objects.select_related("host").filter(pk=pk).first()
        if not event:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)

        # A GET carries them comma-joined, the way PostCostView takes them.
        raw = request.query_params.get("skills", "")
        asked = [s for s in (x.strip()[:80] for x in raw.split(",")) if s][:40]
        skills = asked or list(event.skills or [])
        hours = _int(request.query_params, "hours", event.hours, 1, 24)

        # Only the named skills are charged in ⚡ — the rule the booking follows,
        # quoted here by the same helper so the two cannot answer differently.
        cost, lines = post_cost_cents(request.user, asked)
        have = max(0, wallet_for(request.user).energy or 0)
        return Response({
            "quote": quote_for(event, request.user, skills=skills, hours=hours),
            "energy": {
                "cost": cost,
                "lines": lines,
                "available": have,
                "affordable": have >= cost,
                "short": max(0, cost - have),
            },
            # Which list priced it, so the screen can say whose skills these are
            # rather than implying the member chose a list they never touched.
            "skills": skills,
            "named": bool(asked),
        })


class VenueBookingRespondView(APIView):
    """The host says yes or no. Yes is what releases the address."""
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk):
        b = (VenueBooking.objects.select_for_update()
             .select_related("event", "visitor").filter(pk=pk).first())
        if not b or b.event.host_id != request.user.id:
            return Response({"detail": "Not yours, or not here."},
                            status=status.HTTP_404_NOT_FOUND)
        if b.status != VenueBooking.STATUS_REQUESTED:
            return Response({"detail": f"That booking is already {b.status}."},
                            status=status.HTTP_409_CONFLICT)

        accept = bool((request.data or {}).get("accept"))
        if accept and not seats_left(b.event):
            return Response({"detail": "It's full."}, status=status.HTTP_409_CONFLICT)
        # The age rule is re-checked at acceptance, not only at the request.
        # A birthday can be edited in between, and the door is the moment that
        # matters.
        if accept:
            age_pass, age_why = age_ok(b.visitor, b.event)
            if not age_pass:
                return Response({"detail": age_why}, status=status.HTTP_409_CONFLICT)

        b.status = (VenueBooking.STATUS_ACCEPTED if accept
                    else VenueBooking.STATUS_DECLINED)
        b.save(update_fields=["status"])
        if not accept:
            refund_spinaz(b, "declined")
        return Response({"booking": booking_dict(b, request.user),
                         "venue": event_dict(b.event, request.user)})


class VenueBookingCancelView(APIView):
    """Either side can withdraw. Both are allowed for the same reason a
    dispute is: the cheap failure is somebody not turning up, and the
    expensive one is somebody turning up to a room that isn't there."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        b = (VenueBooking.objects.select_related("event", "visitor")
             .filter(pk=pk).first())
        if not b or request.user.id not in (b.visitor_id, b.event.host_id):
            return Response({"detail": "Not yours, or not here."},
                            status=status.HTTP_404_NOT_FOUND)
        if b.status in (VenueBooking.STATUS_ATTENDED, VenueBooking.STATUS_CANCELLED):
            return Response({"detail": f"That booking is already {b.status}."},
                            status=status.HTTP_409_CONFLICT)
        # Once the room has started the entry is the host's; before, it was
        # never anybody's but the visitor's, so it goes straight back.
        settle_spinaz(b.event)
        b.refresh_from_db()
        b.status = VenueBooking.STATUS_CANCELLED
        b.save(update_fields=["status"])
        refund_spinaz(b, "cancelled")
        return Response({"booking": booking_dict(b, request.user),
                         "venue": event_dict(b.event, request.user)})


# ---- Who may rate a night ---------------------------------------------------
# One rule decides it, and it lands differently in each app:
#
#     A rating needs KNOWLEDGE and no STAKE.
#
# * A collab's split is re-cut by ratings, so money follows them — and
#   `rating_split` already excludes the deal's own members for exactly that
#   reason. Outsiders can hear the finished track (knowledge) and gain nothing
#   from the split (no stake). Correct as it stands; do not open it up.
# * A battle is a public verdict on public work. Anyone can hear it, nobody is
#   paid by the outcome. Open.
# * A VENUE is the opposite of both, and that is why this exists. The thing
#   being rated is an evening in a room, which somebody who was not in the
#   room has NO knowledge of. Letting the public rate it would be rating the
#   description — a score off form completeness, which is precisely what the
#   substance rule forbids.
#
# So: attendance-gated, and two-sided, because the host and the visitor were
# both there and each knows something the other cannot report about themselves.
VENUE_ITEM = "venue:%d"
GUEST_ITEM = "venueguest:%d"


def venue_rating_state(event, viewer):
    """Whether this member may rate this night, and what it is rated so far."""
    from .models import ItemRating, item_rating_median

    happened = event.starts_at <= timezone.now()
    attended = event.bookings.filter(
        visitor=viewer,
        status__in=[VenueBooking.STATUS_ACCEPTED, VenueBooking.STATUS_ATTENDED],
    ).exists()

    why = ""
    if not happened:
        why = "You can rate it once it's happened."
    elif event.host_id == viewer.id:
        why = "You hosted it — rate the people who came instead."
    elif not attended:
        why = "Only people who were there can rate it."

    return {
        "item": VENUE_ITEM % event.id,
        "median": item_rating_median(VENUE_ITEM % event.id),
        "count": ItemRating.objects.filter(item_id=VENUE_ITEM % event.id).count(),
        "can_rate": not why,
        "why_not": why,
        "mine": (ItemRating.objects
                 .filter(item_id=VENUE_ITEM % event.id, user=viewer)
                 .values_list("score", flat=True).first()),
    }


class VenueRateView(APIView):
    """Rate the night, or rate somebody who came to it.

    The gate is attendance and it is checked HERE, not on the client: an
    outsider rating a room they were never in is the substance rule's failure
    case, and a screen that merely hides the control does not stop a POST.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from .models import ItemRating

        event = VenueEvent.objects.select_related("host").filter(pk=pk).first()
        if not event:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            score = int((request.data or {}).get("score", 0))
        except (TypeError, ValueError):
            score = 0
        if not 1 <= score <= 10:
            return Response({"detail": "score must be 1-10"},
                            status=status.HTTP_400_BAD_REQUEST)

        # The host rating a guest, or a guest rating the night.
        guest_booking_id = (request.data or {}).get("booking")
        if guest_booking_id:
            b = event.bookings.filter(pk=guest_booking_id).first()
            if event.host_id != request.user.id or not b:
                return Response({"detail": "Only the host rates who came."},
                                status=status.HTTP_403_FORBIDDEN)
            if b.status not in (VenueBooking.STATUS_ACCEPTED,
                                VenueBooking.STATUS_ATTENDED):
                return Response({"detail": "They weren't let in."},
                                status=status.HTTP_409_CONFLICT)
            if event.starts_at > timezone.now():
                return Response({"detail": "It hasn't happened yet."},
                                status=status.HTTP_409_CONFLICT)
            item = GUEST_ITEM % b.id
        else:
            state = venue_rating_state(event, request.user)
            if not state["can_rate"]:
                return Response({"detail": state["why_not"]},
                                status=status.HTTP_403_FORBIDDEN)
            item = state["item"]

        ItemRating.objects.update_or_create(
            user=request.user, item_id=item, defaults={"score": score})
        return Response({"venue": event_dict(event, request.user)})
