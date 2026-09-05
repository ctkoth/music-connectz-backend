"""RoyaltieZ — the balance, who may create it, and what cashing out costs.

Three endpoints have been mounted and answering since long before anything
called them, and the audit that produced this file found why that mattered:

  * `RoyaltyAccrueView` said "open for testing" and was. Any authenticated
    member could POST an arbitrary amount to their own royalty balance, and
    the cashout below moves that balance into `money_cents` — which pays other
    members, buys PromptZ and settles CollabZ deals. Two endpoints, an open
    mint, and the money did not stay in the account that printed it.
  * `royalties` was not in `WalletSerializer`, so no live surface could see a
    balance a member had genuinely accrued.
  * The cashout rate depends on the plan AND the tier, and nothing published
    it — so a client could only state the price before the button by keeping
    its own copy of the tax table.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.catalog import CASHOUT_INSTANT, CASHOUT_WEEKLY, cashout_rate
from apps.economy.models import (RoyaltyEntry, TIER_STATZ, membership_for,
                                 wallet_for)

User = get_user_model()
PW = "hunter2hunter2"
GET = "/api/economy/royalties/"
ACCRUE = "/api/economy/royalties/accrue/"
CASHOUT = "/api/economy/royalties/cashout/"


def bank(user, cents):
    w = wallet_for(user)
    w.royalties_cents = cents
    w.save(update_fields=["royalties_cents"])
    return w


class TheMintIsClosedTests(TestCase):
    def setUp(self):
        self.member = User.objects.create_user("m", "m@e.com", PW)
        self.client = APIClient()
        self.client.force_authenticate(self.member)

    def test_a_member_cannot_print_their_own_royalties(self):
        r = self.client.post(ACCRUE, {"amount_cents": 1_000_000}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(wallet_for(self.member).royalties_cents, 0)

    def test_and_therefore_cannot_print_spendable_money(self):
        # The whole reason the mint mattered: royalties become money_cents,
        # and money_cents pays other members.
        self.client.post(ACCRUE, {"amount_cents": 1_000_000}, format="json")
        r = self.client.post(CASHOUT, {"plan": "quarterly"}, format="json")
        self.assertEqual(r.status_code, 400)          # nothing to cash out
        self.assertEqual(wallet_for(self.member).money_cents, 0)

    def test_the_owner_may_credit_the_member_whose_media_earned(self):
        owner = User.objects.create_superuser("owner", "o@e.com", PW)
        earner = User.objects.create_user("earner", "e@e.com", PW)
        c = APIClient()
        c.force_authenticate(owner)
        r = c.post(ACCRUE, {"amount_cents": 500, "username": "earner",
                            "source": "Spotify Q3"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["username"], "earner")
        # Credited to the EARNER, not to the owner who pressed the button.
        self.assertEqual(wallet_for(earner).royalties_cents, 500)
        self.assertEqual(wallet_for(owner).royalties_cents, 0)
        self.assertEqual(RoyaltyEntry.objects.get(user=earner).source, "Spotify Q3")

    def test_crediting_a_member_who_does_not_exist_says_so(self):
        owner = User.objects.create_superuser("owner", "o@e.com", PW)
        c = APIClient()
        c.force_authenticate(owner)
        r = c.post(ACCRUE, {"amount_cents": 500, "username": "ghost"}, format="json")
        self.assertEqual(r.status_code, 404)


class ThePriceIsStatedBeforeTheButtonTests(TestCase):
    """The cost/gain rule, on the one screen where the cost is a percentage."""

    def setUp(self):
        self.user = User.objects.create_user("p", "p@e.com", PW)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        bank(self.user, 10_000)          # $100.00

    def test_every_plan_arrives_with_its_arithmetic_done(self):
        d = self.client.get(GET).data
        plans = {p["plan"]: p for p in d["plans"]}
        self.assertEqual(set(plans), {"instant", "weekly", "monthly", "quarterly"})
        for p in plans.values():
            # Both halves of the trade, in cents, for THIS balance.
            self.assertEqual(p["tax_cents"] + p["net_cents"], 10_000)

    def test_the_numbers_match_the_server_s_own_table(self):
        plans = {p["plan"]: p for p in self.client.get(GET).data["plans"]}
        self.assertEqual(plans["instant"]["tax_cents"], round(10_000 * CASHOUT_INSTANT))
        self.assertEqual(plans["quarterly"]["tax_cents"], 0)

    def test_the_rate_follows_the_member_s_tier(self):
        # Weekly is the per-tier one, so it is the one that proves the ladder
        # is read per member rather than hardcoded.
        free = {p["plan"]: p for p in self.client.get(GET).data["plans"]}["weekly"]
        m = membership_for(self.user)
        m.tier = TIER_STATZ
        m.save(update_fields=["tier"])
        statz = {p["plan"]: p for p in self.client.get(GET).data["plans"]}["weekly"]
        self.assertEqual(free["rate"], CASHOUT_WEEKLY["free"])
        self.assertEqual(statz["rate"], CASHOUT_WEEKLY["statz"])
        self.assertGreater(statz["net_cents"], free["net_cents"])

    def test_an_empty_balance_still_publishes_the_ladder(self):
        # A member with nothing needs to see what the plans WOULD cost, or the
        # screen teaches them nothing about why to come back.
        bank(self.user, 0)
        d = self.client.get(GET).data
        self.assertEqual(len(d["plans"]), 4)
        self.assertTrue(all(p["net_cents"] == 0 for p in d["plans"]))
        self.assertEqual(d["plans"][0]["rate"], cashout_rate("instant", "free"))

    def test_the_screen_admits_nothing_pays_in_yet(self):
        # An empty balance means two very different things, and guessing wrong
        # is the difference between "I earned nothing" and "this is not wired".
        self.assertIn("accrual_is_live", self.client.get(GET).data)


class TheBalanceIsVisibleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("v", "v@e.com", PW)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        bank(self.user, 2_500)

    def test_the_wallet_carries_royalties_now(self):
        w = self.client.get("/api/economy/wallet/").data["wallet"]
        self.assertEqual(w["royalties_cents"], 2_500)
        self.assertEqual(w["royalties"], 25.0)

    def test_cashing_out_pays_the_stated_net_and_says_what_it_took(self):
        r = self.client.post(CASHOUT, {"plan": "quarterly"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        b = r.data["breakdown"]
        self.assertEqual((b["gross_cents"], b["tax_cents"], b["net_cents"]), (2_500, 0, 2_500))
        w = wallet_for(self.user)
        self.assertEqual(w.royalties_cents, 0)
        self.assertEqual(w.money_cents, 2_500)
        # And the response's wallet shows the emptied balance, which it could
        # not do while the serializer omitted the field.
        self.assertEqual(r.data["wallet"]["royalties_cents"], 0)

    def test_the_ledger_records_both_sides(self):
        self.client.post(CASHOUT, {"plan": "instant"}, format="json")
        kinds = list(RoyaltyEntry.objects.filter(user=self.user)
                     .values_list("kind", flat=True))
        self.assertIn(RoyaltyEntry.KIND_CASHOUT, kinds)
        e = RoyaltyEntry.objects.get(user=self.user, kind=RoyaltyEntry.KIND_CASHOUT)
        self.assertEqual(e.tax_cents, round(2_500 * CASHOUT_INSTANT))
