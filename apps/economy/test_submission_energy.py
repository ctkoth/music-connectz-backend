"""A submission costs the skills that went into it, and says so before it does.

BattleZ, VenueZ and CollabZ all take work and all took it for free, while the
screens beside them implied a price — the same gap `test_post_cost` was written
for, in the three apps that were not fixed at the time.

One difference from a post, pinned here because it is the whole reason the
insufficient-energy screen exists: a post that cannot be afforded is still made
and takes what is there, and a submission that cannot be afforded is REFUSED.
A refusal has to be a wall or there is nothing for the paradigm to explain.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import (
    Battle,
    BattleEntry,
    CollabDeal,
    membership_for,
    profile_for,
    wallet_for,
)

User = get_user_model()
PW = "hunter2hunter2"


def _priced(user, **rates):
    p = profile_for(user)
    p.personas = [{"key": "producer", "name": "Producer", "skills": [
        {"name": name, "rate_cents": cents} for name, cents in rates.items()
    ]}]
    p.save(update_fields=["personas"])


def _energy(user, amount):
    w = wallet_for(user)
    w.energy = amount
    w.save(update_fields=["energy"])
    return w


class BattleEntryEnergyTests(TestCase):
    def setUp(self):
        self.host = User.objects.create_user("host", "h@e.com", PW)
        self.entrant = User.objects.create_user("entrant", "e@e.com", PW)
        membership_for(self.entrant)
        _priced(self.entrant, Vocals=40, Mixing=25)
        self.battle = Battle.objects.create(host=self.host, title="16 bars")
        self.client = APIClient()
        self.client.force_authenticate(self.entrant)

    def enter(self, **over):
        return self.client.post(f"/api/economy/battlez/{self.battle.pk}/enter/",
                                {"title": "My 16", **over}, format="json")

    def test_the_combined_skill_price_comes_off(self):
        _energy(self.entrant, 500)
        r = self.enter(skills=["Vocals", "Mixing"])
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["energy_charged"], 65)
        self.assertEqual(wallet_for(self.entrant).energy, 435)

    def test_naming_no_skills_is_free(self):
        _energy(self.entrant, 3)
        self.assertEqual(self.enter().status_code, 201)
        self.assertEqual(wallet_for(self.entrant).energy, 3)

    def test_a_skill_they_have_not_priced_costs_nothing(self):
        _energy(self.entrant, 0)
        self.assertEqual(self.enter(skills=["Dog Walking"]).status_code, 201)

    def test_it_is_refused_when_they_cannot_afford_it(self):
        _energy(self.entrant, 10)
        r = self.enter(skills=["Vocals"])
        self.assertEqual(r.status_code, 402)
        self.assertTrue(r.data["insufficient"])
        self.assertEqual(r.data["energy_needed"], 40)
        self.assertEqual(r.data["energy_available"], 10)
        self.assertEqual(r.data["energy_short"], 30)

    def test_a_refused_entry_charges_nothing_and_leaves_nothing_behind(self):
        """The half-applied case: taking the ⚡ and refusing the entry, or
        writing the entry and not taking the ⚡, are both worse than either
        clean outcome."""
        _energy(self.entrant, 10)
        self.enter(skills=["Vocals"])
        self.assertEqual(wallet_for(self.entrant).energy, 10)
        self.assertFalse(BattleEntry.objects.filter(user=self.entrant).exists())

    def test_the_refusal_names_the_price_of_each_skill(self):
        _energy(self.entrant, 0)
        lines = self.enter(skills=["Vocals", "Dog Walking"]).data["lines"]
        self.assertEqual({l["skill"]: l["cents"] for l in lines},
                         {"Vocals": 40, "Dog Walking": 0})

    def test_the_refusal_never_names_anybody_else_s_balance(self):
        _energy(self.entrant, 1)
        _energy(self.host, 9999)
        body = self.enter(skills=["Vocals"]).data
        self.assertEqual(body["energy_available"], 1)


class CollabDraftEnergyTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_user("starter", "s@e.com", PW)
        self.partner = User.objects.create_user("partner", "p@e.com", PW)
        membership_for(self.me)
        membership_for(self.partner)
        _priced(self.me, Vocals=40)
        self.client = APIClient()
        self.client.force_authenticate(self.me)

    def draft(self, **over):
        return self.client.post("/api/economy/collab/", {
            "title": "A song", "currency": "money",
            "participants": [{"username": "starter", "worth_cents": 0},
                             {"username": "partner", "worth_cents": 0}],
            **over,
        }, format="json")

    def test_the_skills_the_starter_brings_are_what_it_costs(self):
        _energy(self.me, 100)
        r = self.draft(skills=["Vocals"])
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["energy_charged"], 40)
        self.assertEqual(wallet_for(self.me).energy, 60)

    def test_drafting_without_naming_a_skill_still_costs_nothing(self):
        """The screen said "Drafting costs nothing" for the whole life of the
        app. It is still true of a draft that names no skills, and the copy is
        conditional on exactly this."""
        _energy(self.me, 0)
        self.assertEqual(self.draft().status_code, 201)

    def test_a_refused_draft_creates_no_deal(self):
        _energy(self.me, 5)
        r = self.draft(skills=["Vocals"])
        self.assertEqual(r.status_code, 402)
        self.assertEqual(wallet_for(self.me).energy, 5)
        self.assertFalse(CollabDeal.objects.exists())


class VenueBookingEnergyTests(TestCase):
    """The room's own skill list is NOT what the visitor is charged for.

    `quote_for` falls back to the event's skills when the visitor names none,
    because the money quote has to have something to price. Charging ⚡ off that
    same fallback would bill somebody for a line they never wrote — and, when
    the event is a session (the HOST pays the money), an earlier draft of this
    charged the host's ⚡ for a request a stranger made, which is a way to empty
    somebody's wallet by asking them for things.
    """

    def setUp(self):
        from apps.economy.models import VenueEvent
        from django.utils import timezone
        from datetime import timedelta

        self.host = User.objects.create_user("roomhost", "r@e.com", PW)
        self.visitor = User.objects.create_user("visitor", "v@e.com", PW)
        membership_for(self.visitor)
        _priced(self.host, Mixing=100)
        _priced(self.visitor, Vocals=40)
        self.event = VenueEvent.objects.create(
            host=self.host, title="Session", kind="session",
            starts_at=timezone.now() + timedelta(days=1),
            capacity=5, skills=["Mixing"],
        )
        self.client = APIClient()
        self.client.force_authenticate(self.visitor)

    def book(self, **over):
        return self.client.post(f"/api/economy/venuez/{self.event.pk}/book/",
                                over, format="json")

    def test_the_room_s_own_skills_are_never_charged_to_the_visitor(self):
        _energy(self.visitor, 0)
        self.assertEqual(self.book().status_code, 201)

    def test_the_host_is_never_charged_for_a_request_they_did_not_make(self):
        _energy(self.visitor, 500)
        _energy(self.host, 500)
        self.book(skills=["Vocals"])
        self.assertEqual(wallet_for(self.host).energy, 500)

    def test_the_visitor_pays_for_the_skills_the_visitor_named(self):
        _energy(self.visitor, 500)
        r = self.book(skills=["Vocals"])
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["energy_charged"], 40)
        self.assertEqual(wallet_for(self.visitor).energy, 460)
