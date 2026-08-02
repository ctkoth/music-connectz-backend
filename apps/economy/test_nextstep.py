"""Every refusal says what to do next.

A member who hits a wall has one question: what now? Answering it with a price
and a route converts. Answering it with `{"detail": "insufficient balance"}`
makes them close the app — that was seventeen paywalls with no price, no tier
and nowhere to go, and it was the biggest conversion hole in this codebase.

The rule these pin: attach the next step to the REFUSAL, never to the browse.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from . import nextstep
from .models import (MerchItem, PaymentIntent, Venue, membership_for,
                     profile_for, wallet_for)

User = get_user_model()


def member(name, cents=0, spinaz=0):
    u = User.objects.create_user(username=name, password="nextstep-pass-1")
    w = wallet_for(u)
    w.money_cents, w.spinaz = cents, spinaz
    w.save(update_fields=["money_cents", "spinaz"])
    return u


class NotEnoughTests(TestCase):
    """The money wall. Never a bare 'insufficient balance' again."""

    def setUp(self):
        self.u = member("skint", cents=500)

    def test_it_says_the_price_and_the_shortfall(self):
        body = nextstep.not_enough(self.u, need_cents=2000, feature="A thing")
        self.assertEqual(body["need_cents"], 2000)
        self.assertEqual(body["short_cents"], 1500)

    def test_it_always_offers_somewhere_to_go(self):
        body = nextstep.not_enough(self.u, need_cents=2000)
        self.assertIn("next", body)
        self.assertTrue(body["next"]["action"])
        self.assertTrue(body["next"]["label"])

    def test_it_says_whether_spinaz_would_cover_it(self):
        """SpinAZ is the route for somebody with no card, which on a music
        platform is a big share of the audience."""
        body = nextstep.not_enough(self.u, need_cents=2000)
        self.assertIn("spinaz_would_cover", body)

    def test_a_caller_can_say_something_more_specific(self):
        body = nextstep.not_enough(self.u, need_cents=2000,
                                   detail="Hoodie costs $20.00 — you're $15.00 short.")
        self.assertIn("$15.00", body["detail"])


class WalletOnHoldTests(TestCase):
    def test_it_explains_rather_than_accuses(self):
        """A stolen card funds somebody else's wallet. The member being held
        may have had nothing to do with it."""
        w = wallet_for(member("held"))
        w.frozen_reason = "A card payment of $50.00 was disputed."
        w.save(update_fields=["frozen_reason"])
        body = nextstep.wallet_on_hold(w)
        self.assertTrue(body["on_hold"])
        self.assertIn("disputed", body["why"])
        self.assertIn("next", body)

    def test_it_says_what_still_works(self):
        w = wallet_for(member("held2"))
        body = nextstep.wallet_on_hold(w)
        self.assertIn("getting paid", body["can_still"])


class FrozenWalletIsNotA500Tests(TestCase):
    """WalletFrozen is raised inside pay_between — the right place to enforce
    it, the wrong place to render it. Before the exception handler existed,
    every view that moved money 500'd on a frozen wallet."""

    def setUp(self):
        self.buyer = member("frozen_buyer", cents=50_000)
        seller = member("seller")
        self.item = MerchItem.objects.create(seller=seller, title="Hoodie",
                                             price_cents=2000)
        PaymentIntent.objects.create(
            user=self.buyer, provider=PaymentIntent.PROVIDER_STRIPE,
            provider_ref="ch_frozen_1", amount_cents=50_000,
            status=PaymentIntent.STATUS_COMPLETED)
        from .payments import _freeze_for_dispute
        _freeze_for_dispute({"id": "dp_1", "charge": "ch_frozen_1",
                             "payment_intent": None})
        self.client = APIClient()
        self.client.force_authenticate(self.buyer)

    def test_buying_with_a_frozen_wallet_is_a_403_not_a_500(self):
        r = self.client.post(reverse("economy-merch-buy", args=[self.item.id]),
                             {}, format="json")
        self.assertEqual(r.status_code, 403, r.content)

    def test_the_refusal_explains_and_offers_a_route(self):
        r = self.client.post(reverse("economy-merch-buy", args=[self.item.id]),
                             {}, format="json")
        body = r.json()
        self.assertTrue(body["on_hold"])
        self.assertIn("next", body)


class DeadEndPaywallsAreGoneTests(TestCase):
    """The specific endpoints that used to answer 'insufficient balance'."""

    def setUp(self):
        self.u = member("browser", cents=100)
        self.client = APIClient()
        self.client.force_authenticate(self.u)

    def assert_has_a_way_out(self, response):
        self.assertEqual(response.status_code, 402, response.content)
        body = response.json()
        self.assertNotEqual(body["detail"], "insufficient balance")
        self.assertIn("next", body)
        self.assertIn("short_cents", body)

    def test_merchz_says_the_price_and_the_gap(self):
        seller = member("merch_seller")
        item = MerchItem.objects.create(seller=seller, title="Hoodie",
                                        price_cents=5000)
        r = self.client.post(reverse("economy-merch-buy", args=[item.id]), {},
                             format="json")
        self.assert_has_a_way_out(r)
        self.assertIn("Hoodie", r.json()["detail"])

    def test_venuez_says_the_price_and_the_gap(self):
        host = member("venue_host", cents=10_000)
        venue = Venue.objects.create(host=host, title="Open mic",
                                     host_price_cents=5000)
        r = self.client.post(reverse("economy-venue-join", args=[venue.id]), {},
                             format="json")
        self.assert_has_a_way_out(r)
        self.assertIn("Open mic", r.json()["detail"])


class VerificationIsNotSilentTests(TestCase):
    """A member whose document was rejected used to see a screen identical to
    never having started, with no way to try again."""

    def test_it_says_the_status_and_offers_a_retry(self):
        u = member("unverified")
        p = profile_for(u)
        p.verification_status = "failed"
        p.verification_reason = "document_unreadable"
        p.save(update_fields=["verification_status", "verification_reason"])
        body = nextstep.verification_needed(p)
        self.assertEqual(body["verification_status"], "failed")
        self.assertTrue(body["retryable"])
        self.assertIn("next", body)
        self.assertIn("try again", body["why"])

    def test_a_check_in_flight_is_not_offered_as_retryable(self):
        """Telling somebody to retry mid-check makes them do it twice."""
        p = profile_for(member("checking"))
        p.verification_status = "processing"
        p.save(update_fields=["verification_status"])
        self.assertFalse(nextstep.verification_needed(p)["retryable"])

    def test_never_started_reads_as_never_started(self):
        p = profile_for(member("fresh"))
        body = nextstep.verification_needed(p)
        self.assertEqual(body["verification_status"], "unstarted")
        self.assertIn("haven't verified", body["why"])


class OutOfPromptsTests(TestCase):
    """"You're out of prompts" with no number and no reset time is a dead end
    dressed as an explanation."""

    def test_it_says_how_many_when_it_resets_and_what_more_costs(self):
        body = nextstep.out_of_prompts(member("prompted"))
        self.assertIn("allowance", body)
        self.assertIn("resets", body["why"])
        self.assertIn("next", body)
        self.assertIn("upgrade", body)

    def test_it_names_what_the_paid_tiers_get(self):
        body = nextstep.out_of_prompts(member("prompted2"))
        self.assertIn("Premium", body["note"])


class RefusalShapeTests(TestCase):
    """One shape, so a client renders one thing."""

    def test_a_refusal_without_a_route_is_still_valid(self):
        body = nextstep.refusal("No.")
        self.assertEqual(body["detail"], "No.")
        self.assertNotIn("next", body)

    def test_extras_ride_along(self):
        body = nextstep.refusal("No.", action="/fix/", label="Fix", short=5)
        self.assertEqual(body["next"], {"action": "/fix/", "label": "Fix"})
        self.assertEqual(body["short"], 5)
