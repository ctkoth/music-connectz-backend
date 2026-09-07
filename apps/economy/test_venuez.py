"""VenueZ: one rule, both directions, and the door.

The rule under test everywhere here — whoever RECEIVES the skill pays for it,
and the price comes from whoever PROVIDES it — is the whole feature. If a
performance ever prices off the visitor's rates, or a session off the host's,
somebody is quoting a number the other side controls.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from . import venuez
from .models import Profile, VenueBooking, VenueEvent, profile_for

User = get_user_model()


def _priced(user, **skills):
    """Give `user` PersonaZ skills at the given rates, in cents."""
    p = profile_for(user)
    p.personas = [{
        "key": "main", "name": "Main",
        "skills": [{"name": n, "rate_cents": c} for n, c in skills.items()],
    }]
    p.save()
    return p


def _event(host, kind, **kw):
    kw.setdefault("title", "A room")
    kw.setdefault("area", "Denver")
    kw.setdefault("starts_at", timezone.now() + timedelta(days=1))
    kw.setdefault("skills", ["Mixing"])
    kw.setdefault("hours", 2)
    return VenueEvent.objects.create(host=host, kind=kind, **kw)


class TheRule(TestCase):
    """Which way the money goes, and whose rates set it."""

    def setUp(self):
        self.host = User.objects.create_user(username="host", password="pw")
        self.visitor = User.objects.create_user(username="vis", password="pw")
        # Deliberately different rates on the same skill, so a test can tell
        # WHOSE number was used rather than only that a number appeared.
        _priced(self.host, Mixing=5000)
        _priced(self.visitor, Mixing=700)

    def test_performance_charges_the_visitor_at_the_hosts_rate(self):
        ev = _event(self.host, VenueEvent.KIND_PERFORMANCE)
        q = venuez.quote_for(ev, self.visitor)
        self.assertEqual(q["payer"], "visitor")
        self.assertEqual(q["payee"], "host")
        self.assertFalse(q["payer_is_host"])
        self.assertEqual(q["hourly_cents"], 5000)      # the HOST's rate
        self.assertEqual(q["amount_cents"], 10000)     # x2 hours

    def test_session_charges_the_host_at_the_visitors_rate(self):
        ev = _event(self.host, VenueEvent.KIND_SESSION)
        q = venuez.quote_for(ev, self.visitor)
        self.assertEqual(q["payer"], "host")
        self.assertEqual(q["payee"], "visitor")
        self.assertTrue(q["payer_is_host"])
        self.assertEqual(q["hourly_cents"], 700)       # the VISITOR's rate
        self.assertEqual(q["amount_cents"], 1400)

    def test_the_arrow_turns_but_the_rule_does_not(self):
        """The same two people, the same skill, priced from opposite sides."""
        perf = venuez.quote_for(_event(self.host, VenueEvent.KIND_PERFORMANCE),
                                self.visitor)
        sess = venuez.quote_for(_event(self.host, VenueEvent.KIND_SESSION),
                                self.visitor)
        self.assertNotEqual(perf["payer"], sess["payer"])
        self.assertNotEqual(perf["hourly_cents"], sess["hourly_cents"])

    def test_free_charges_nobody(self):
        q = venuez.quote_for(_event(self.host, VenueEvent.KIND_FREE), self.visitor)
        self.assertTrue(q["free"])
        self.assertEqual(q["amount_cents"], 0)
        self.assertEqual(q["payer"], "")

    def test_a_total_does_not_multiply_by_hours(self):
        ev = _event(self.host, VenueEvent.KIND_PERFORMANCE,
                    basis=VenueEvent.BASIS_TOTAL, hours=5)
        self.assertEqual(venuez.quote_for(ev, self.visitor)["amount_cents"], 5000)

    def test_an_unpriced_skill_is_named_not_hidden(self):
        """Silently dropping it reads as a discount and surprises somebody."""
        ev = _event(self.host, VenueEvent.KIND_PERFORMANCE,
                    skills=["Mixing", "Tarot"])
        q = venuez.quote_for(ev, self.visitor)
        self.assertEqual(q["unpriced"], ["Tarot"])
        self.assertEqual(len(q["lines"]), 2)
        self.assertEqual(q["hourly_cents"], 5000)

    def test_the_price_never_comes_from_the_other_side(self):
        """A host with no rates cannot be made expensive by the visitor's."""
        _priced(self.host)  # clears the host's skills
        ev = _event(self.host, VenueEvent.KIND_PERFORMANCE)
        self.assertEqual(venuez.quote_for(ev, self.visitor)["amount_cents"], 0)


class TheDoor(TestCase):
    def setUp(self):
        self.host = User.objects.create_user(username="h2", password="pw")
        self.visitor = User.objects.create_user(username="v2", password="pw")
        self.ev = _event(self.host, VenueEvent.KIND_FREE, capacity=1)

    def test_you_cannot_book_your_own(self):
        ok, why = venuez.can_book(self.host, self.ev)
        self.assertFalse(ok)
        self.assertIn("your own", why)

    def test_a_past_venue_is_closed(self):
        self.ev.starts_at = timezone.now() - timedelta(hours=1)
        self.ev.save()
        ok, why = venuez.can_book(self.visitor, self.ev)
        self.assertFalse(ok)
        self.assertIn("already happened", why)

    def test_capacity_counts_only_accepted_seats(self):
        other = User.objects.create_user(username="v3", password="pw")
        VenueBooking.objects.create(event=self.ev, visitor=other,
                                    status=VenueBooking.STATUS_REQUESTED)
        # A request is not a seat — otherwise anybody could fill a room by asking.
        self.assertEqual(venuez.seats_left(self.ev), 1)

        VenueBooking.objects.filter(visitor=other).update(
            status=VenueBooking.STATUS_ACCEPTED)
        self.assertEqual(venuez.seats_left(self.ev), 0)
        ok, why = venuez.can_book(self.visitor, self.ev)
        self.assertFalse(ok)
        self.assertIn("full", why)

    def test_a_cancelled_venue_refuses(self):
        self.ev.status = VenueEvent.STATUS_CANCELLED
        self.ev.save()
        self.assertFalse(venuez.can_book(self.visitor, self.ev)[0])


class TheAgeRule(TestCase):
    def setUp(self):
        self.host = User.objects.create_user(username="h3", password="pw")
        self.visitor = User.objects.create_user(username="v4", password="pw")
        self.ev = _event(self.host, VenueEvent.KIND_FREE, min_age=21)

    def _set_age(self, years):
        # birthday is a CharField holding "YYYY-MM-DD", not a DateField —
        # storing a date object here is what the first version of this test
        # did, and it is why age_ok grew its own parser instead of reusing
        # profile_age. The test caught it; the shape is the point.
        p = profile_for(self.visitor)
        today = timezone.now().date()
        p.birthday = today.replace(year=today.year - years).isoformat()
        p.save()

    def test_unknown_age_is_refused_not_waved_through(self):
        """At an IRL door, "we could not tell" must not mean "come in"."""
        ok, why = venuez.age_ok(self.visitor, self.ev)
        self.assertFalse(ok)
        self.assertIn("birthday", why)

    def test_under_age_is_refused(self):
        self._set_age(18)
        self.assertFalse(venuez.age_ok(self.visitor, self.ev)[0])

    def test_over_age_is_let_in(self):
        self._set_age(30)
        self.assertTrue(venuez.age_ok(self.visitor, self.ev)[0])

    def test_no_min_age_asks_nothing(self):
        open_ev = _event(self.host, VenueEvent.KIND_FREE)
        self.assertTrue(venuez.age_ok(self.visitor, open_ev)[0])


class TheAddress(TestCase):
    """A doorstep is not listing copy."""

    def setUp(self):
        self.host = User.objects.create_user(username="h4", password="pw")
        self.visitor = User.objects.create_user(username="v5", password="pw")
        self.stranger = User.objects.create_user(username="v6", password="pw")
        self.ev = _event(self.host, VenueEvent.KIND_FREE,
                         address="12 Real Street, Apt 4")

    def test_the_host_sees_it(self):
        self.assertTrue(venuez.address_for(self.ev, self.host))

    def test_a_stranger_does_not(self):
        self.assertEqual(venuez.address_for(self.ev, self.stranger), "")

    def test_asking_is_not_being_let_in(self):
        """A request the host has not accepted hands out nothing."""
        VenueBooking.objects.create(event=self.ev, visitor=self.visitor,
                                    status=VenueBooking.STATUS_REQUESTED)
        self.assertEqual(venuez.address_for(self.ev, self.visitor), "")

    def test_an_accepted_visitor_gets_it(self):
        VenueBooking.objects.create(event=self.ev, visitor=self.visitor,
                                    status=VenueBooking.STATUS_ACCEPTED)
        self.assertEqual(venuez.address_for(self.ev, self.visitor),
                         "12 Real Street, Apt 4")

    def test_a_declined_visitor_loses_it_again(self):
        VenueBooking.objects.create(event=self.ev, visitor=self.visitor,
                                    status=VenueBooking.STATUS_DECLINED)
        self.assertEqual(venuez.address_for(self.ev, self.visitor), "")
