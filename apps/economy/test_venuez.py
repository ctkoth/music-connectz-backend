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
from .models import Profile, VenueBooking, VenueEvent, profile_for, wallet_for

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


class Endpoints(TestCase):
    """The booking lifecycle, and the two rules that must survive it."""

    def setUp(self):
        self.host = User.objects.create_user(username="eh", password="pw")
        self.visitor = User.objects.create_user(username="ev", password="pw")
        self.other = User.objects.create_user(username="eo", password="pw")
        _priced(self.host, Mixing=5000)
        _priced(self.visitor, Mixing=700)

    def _mk(self, kind=VenueEvent.KIND_PERFORMANCE, **kw):
        return _event(self.host, kind, address="12 Real Street", **kw)

    def test_the_listing_quotes_the_price_before_anybody_books(self):
        """Cost up front: the price is ON the listing, not behind the button."""
        ev = self._mk()
        self.client.force_login(self.visitor)
        row = next(v for v in self.client.get("/api/economy/venuez/").json()["venues"]
                   if v["id"] == ev.id)
        self.assertEqual(row["quote"]["amount_cents"], 10000)
        self.assertEqual(row["quote"]["payer"], "visitor")
        self.assertTrue(row["can_book"])

    def test_a_session_quotes_the_host_as_the_payer(self):
        """The arrow turns; the screen has to turn with it."""
        ev = self._mk(VenueEvent.KIND_SESSION)
        self.client.force_login(self.visitor)
        row = self.client.get(f"/api/economy/venuez/{ev.id}/").json()
        self.assertEqual(row["quote"]["payer"], "host")
        self.assertEqual(row["quote"]["amount_cents"], 1400)   # visitor's rate

    def test_the_address_is_not_on_the_public_listing(self):
        ev = self._mk()
        self.client.force_login(self.visitor)
        self.assertEqual(
            self.client.get(f"/api/economy/venuez/{ev.id}/").json()["address"], "")

    def test_booking_freezes_the_quote_and_accepting_opens_the_door(self):
        ev = self._mk()
        self.client.force_login(self.visitor)
        r = self.client.post(f"/api/economy/venuez/{ev.id}/book/", {}, "application/json")
        self.assertEqual(r.status_code, 201)
        booking = r.json()["booking"]
        self.assertEqual(booking["quoted_cents"], 10000)
        self.assertEqual(booking["status"], "requested")

        # Still no address — asking is not being let in.
        self.assertEqual(
            self.client.get(f"/api/economy/venuez/{ev.id}/").json()["address"], "")

        self.client.force_login(self.host)
        r = self.client.post(f"/api/economy/venuez/bookings/{booking['id']}/respond/",
                             {"accept": True}, "application/json")
        self.assertEqual(r.status_code, 200)

        self.client.force_login(self.visitor)
        self.assertEqual(
            self.client.get(f"/api/economy/venuez/{ev.id}/").json()["address"],
            "12 Real Street")

    def test_a_rate_change_cannot_move_an_agreed_booking(self):
        """The frozen quote is the difference between a price and a bill."""
        ev = self._mk()
        self.client.force_login(self.visitor)
        bid = self.client.post(f"/api/economy/venuez/{ev.id}/book/", {},
                               "application/json").json()["booking"]["id"]
        _priced(self.host, Mixing=99999)          # host triples their rate after
        b = VenueBooking.objects.get(pk=bid)
        self.assertEqual(b.quoted_cents, 10000)

    def test_only_the_host_answers_a_booking(self):
        ev = self._mk()
        self.client.force_login(self.visitor)
        bid = self.client.post(f"/api/economy/venuez/{ev.id}/book/", {},
                               "application/json").json()["booking"]["id"]
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(
            f"/api/economy/venuez/bookings/{bid}/respond/",
            {"accept": True}, "application/json").status_code, 404)

    def test_you_cannot_ask_twice(self):
        ev = self._mk()
        self.client.force_login(self.visitor)
        self.client.post(f"/api/economy/venuez/{ev.id}/book/", {}, "application/json")
        self.assertEqual(self.client.post(
            f"/api/economy/venuez/{ev.id}/book/", {}, "application/json").status_code,
            409)

    def test_an_under_age_visitor_is_refused_at_acceptance_too(self):
        """A birthday can be edited between asking and being let in."""
        ev = self._mk(min_age=21)
        p = profile_for(self.visitor)
        today = timezone.now().date()
        p.birthday = today.replace(year=today.year - 30).isoformat()
        p.save()

        self.client.force_login(self.visitor)
        bid = self.client.post(f"/api/economy/venuez/{ev.id}/book/", {},
                               "application/json").json()["booking"]["id"]
        p.birthday = today.replace(year=today.year - 16).isoformat()
        p.save()

        self.client.force_login(self.host)
        r = self.client.post(f"/api/economy/venuez/bookings/{bid}/respond/",
                             {"accept": True}, "application/json")
        self.assertEqual(r.status_code, 409)
        self.assertIn("21+", r.json()["detail"])

    def test_cancelling_the_venue_does_not_delete_the_booking(self):
        """Somebody who was accepted needs to SEE that it's off."""
        ev = self._mk()
        self.client.force_login(self.visitor)
        bid = self.client.post(f"/api/economy/venuez/{ev.id}/book/", {},
                               "application/json").json()["booking"]["id"]
        self.client.force_login(self.host)
        self.client.delete(f"/api/economy/venuez/{ev.id}/")
        self.assertTrue(VenueBooking.objects.filter(pk=bid).exists())
        self.assertEqual(VenueEvent.objects.get(pk=ev.id).status, "cancelled")

    def test_creating_needs_a_real_kind_and_a_future_date(self):
        self.client.force_login(self.host)
        base = {"title": "x", "area": "Denver",
                "starts_at": (timezone.now() + timedelta(days=1)).isoformat()}
        self.assertEqual(self.client.post(
            "/api/economy/venuez/", {**base, "kind": "nonsense"},
            "application/json").status_code, 400)
        self.assertEqual(self.client.post(
            "/api/economy/venuez/",
            {**base, "kind": "free",
             "starts_at": (timezone.now() - timedelta(days=1)).isoformat()},
            "application/json").status_code, 400)
        self.assertEqual(self.client.post(
            "/api/economy/venuez/", {**base, "kind": "free"},
            "application/json").status_code, 201)

    def test_a_venue_is_not_a_dead_end(self):
        ev = self._mk()
        self.client.force_login(self.visitor)
        row = self.client.get(f"/api/economy/venuez/{ev.id}/").json()
        self.assertTrue(row["open_in"])


class WhoMayRate(TestCase):
    """A rating needs knowledge and no stake — and a venue is the case where
    the public has neither."""

    def setUp(self):
        self.host = User.objects.create_user(username="rh", password="pw")
        self.guest = User.objects.create_user(username="rg", password="pw")
        self.stranger = User.objects.create_user(username="rs", password="pw")
        self.ev = _event(self.host, VenueEvent.KIND_FREE,
                         starts_at=timezone.now() - timedelta(hours=3))
        self.b = VenueBooking.objects.create(
            event=self.ev, visitor=self.guest,
            status=VenueBooking.STATUS_ACCEPTED)

    def _rate(self, who, score=9, **body):
        self.client.force_login(who)
        return self.client.post(f"/api/economy/venuez/{self.ev.id}/rate/",
                                {"score": score, **body}, "application/json")

    def test_somebody_who_was_there_may_rate_it(self):
        self.assertEqual(self._rate(self.guest).status_code, 200)
        from .models import item_rating_median
        self.assertEqual(item_rating_median(f"venue:{self.ev.id}"), 9)

    def test_a_stranger_may_not(self):
        """Rating a room you were never in is rating the description."""
        r = self._rate(self.stranger)
        self.assertEqual(r.status_code, 403)
        self.assertIn("were there", r.json()["detail"])

    def test_asking_for_a_seat_is_not_attending(self):
        VenueBooking.objects.filter(pk=self.b.pk).update(
            status=VenueBooking.STATUS_REQUESTED)
        self.assertEqual(self._rate(self.guest).status_code, 403)

    def test_you_cannot_rate_a_night_that_has_not_happened(self):
        VenueEvent.objects.filter(pk=self.ev.pk).update(
            starts_at=timezone.now() + timedelta(days=2))
        r = self._rate(self.guest)
        self.assertEqual(r.status_code, 403)
        self.assertIn("once it's happened", r.json()["detail"])

    def test_the_host_rates_guests_not_their_own_night(self):
        r = self._rate(self.host)
        self.assertEqual(r.status_code, 403)
        self.assertIn("hosted it", r.json()["detail"])

        # But they may rate somebody who came.
        self.assertEqual(self._rate(self.host, booking=self.b.id).status_code, 200)
        from .models import item_rating_median
        self.assertEqual(item_rating_median(f"venueguest:{self.b.id}"), 9)

    def test_a_guest_cannot_rate_another_guest(self):
        self.assertEqual(
            self._rate(self.stranger, booking=self.b.id).status_code, 403)

    def test_a_score_outside_1_to_10_is_refused(self):
        for bad in (0, 11, -3):
            with self.subTest(score=bad):
                self.assertEqual(self._rate(self.guest, score=bad).status_code, 400)

    def test_rating_again_replaces_rather_than_stacks(self):
        self._rate(self.guest, score=3)
        self._rate(self.guest, score=8)
        from .models import ItemRating
        self.assertEqual(
            ItemRating.objects.filter(item_id=f"venue:{self.ev.id}").count(), 1)

    def test_the_listing_says_why_you_cannot_rate_yet(self):
        self.client.force_login(self.stranger)
        row = self.client.get(f"/api/economy/venuez/{self.ev.id}/").json()
        self.assertFalse(row["rating"]["can_rate"])
        self.assertTrue(row["rating"]["why_not"])


class TheQuoteMatchesTheCharge(TestCase):
    """The quote endpoint exists so the button can state its own price.

    Its one job is to answer for the skills and hours ACTUALLY asked for, and
    to answer the same thing the booking will then do. A quote that drifts from
    the charge is worse than no quote — it is a promise the next screen breaks.
    """

    def setUp(self):
        self.host = User.objects.create_user(username="qhost", password="pw")
        self.visitor = User.objects.create_user(username="qvis", password="pw")
        _priced(self.host, Mixing=5000, Mastering=3000)
        _priced(self.visitor, Drums=400, Bass=250)
        self.client.force_login(self.visitor)

    def _quote(self, ev, **params):
        q = "&".join(f"{k}={v}" for k, v in params.items())
        return self.client.get(f"/api/economy/venuez/{ev.id}/quote/?{q}")

    def test_naming_no_skills_quotes_the_rooms_own_list(self):
        ev = _event(self.host, VenueEvent.KIND_PERFORMANCE)
        d = self._quote(ev).json()
        self.assertFalse(d["named"])
        self.assertEqual(d["skills"], ["Mixing"])
        self.assertEqual(d["quote"]["amount_cents"], 10000)   # host 5000 x 2h
        # Nothing was named, so asking costs no ⚡ — the room's list is not a
        # bill the visitor wrote.
        self.assertEqual(d["energy"]["cost"], 0)

    def test_hours_move_the_quote_because_they_move_the_charge(self):
        ev = _event(self.host, VenueEvent.KIND_PERFORMANCE)
        self.assertEqual(self._quote(ev, hours=1).json()["quote"]["amount_cents"], 5000)
        self.assertEqual(self._quote(ev, hours=4).json()["quote"]["amount_cents"], 20000)

    def test_a_session_prices_the_named_skills_off_the_visitors_own_rates(self):
        ev = _event(self.host, VenueEvent.KIND_SESSION, hours=1)
        d = self._quote(ev, skills="Drums,Bass").json()
        self.assertTrue(d["named"])
        self.assertTrue(d["quote"]["payer_is_host"])          # the host pays
        self.assertEqual(d["quote"]["amount_cents"], 650)     # 400 + 250, theirs
        # And the ⚡ for asking is the same two skills, off the same rates.
        self.assertEqual(d["energy"]["cost"], 650)

    def test_the_quoted_energy_is_what_the_booking_actually_takes(self):
        """The property the endpoint exists for."""
        ev = _event(self.host, VenueEvent.KIND_SESSION, hours=1)
        w = wallet_for(self.visitor)
        w.energy = 5000
        w.save()
        quoted = self._quote(ev, skills="Drums,Bass").json()["energy"]["cost"]
        before = wallet_for(self.visitor).energy
        r = self.client.post(f"/api/economy/venuez/{ev.id}/book/",
                             {"skills": ["Drums", "Bass"]}, "application/json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(before - wallet_for(self.visitor).energy, quoted)

    def test_an_unaffordable_ask_is_named_as_such_before_it_is_made(self):
        ev = _event(self.host, VenueEvent.KIND_SESSION, hours=1)
        w = wallet_for(self.visitor)
        w.energy = 100
        w.save()
        d = self._quote(ev, skills="Drums,Bass").json()["energy"]
        self.assertFalse(d["affordable"])
        self.assertEqual(d["short"], 550)
        # And the booking then refuses, rather than the quote having lied.
        r = self.client.post(f"/api/economy/venuez/{ev.id}/book/",
                             {"skills": ["Drums", "Bass"]}, "application/json")
        self.assertEqual(r.status_code, 402)
        self.assertTrue(r.json()["insufficient"])

    def test_an_unpriced_skill_is_named_rather_than_dropped(self):
        ev = _event(self.host, VenueEvent.KIND_SESSION, hours=1)
        d = self._quote(ev, skills="Drums,Kazoo").json()
        self.assertIn("Kazoo", d["quote"]["unpriced"])
        self.assertEqual(d["quote"]["amount_cents"], 400)

    def test_a_free_room_quotes_free_and_costs_no_energy(self):
        ev = _event(self.host, VenueEvent.KIND_FREE)
        d = self._quote(ev).json()
        self.assertTrue(d["quote"]["free"])
        self.assertEqual(d["energy"]["cost"], 0)
