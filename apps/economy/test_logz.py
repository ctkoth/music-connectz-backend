from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.features import can_use
from apps.economy.models import (TIER_FREE, TIER_PREMIUM, TIER_STATZ, Transaction,
                                 award_energy, award_spinaz, complete_onboarding,
                                 membership_for, record_referral, wallet_for)

User = get_user_model()
URL = "/api/economy/logz/"


class ResourceMovesAreRecordedTests(TestCase):
    """Balances say where you are. Until LogZ nothing said how you got there —
    award_spinaz took a `note` from every caller and threw it away."""

    def setUp(self):
        self.user = User.objects.create_user("k", "k@e.com", "pw12345678")

    def test_a_spinaz_award_leaves_a_line(self):
        award_spinaz(self.user, 300, "referral (referrer)")
        t = Transaction.objects.get(user=self.user)
        self.assertEqual(t.resource, "spinaz")
        self.assertEqual(t.amount, 300)
        self.assertEqual(t.note, "referral (referrer)")
        self.assertIsNotNone(t.created_at)

    def test_an_energy_award_leaves_a_line(self):
        award_energy(self.user, 50, "onboarding")
        t = Transaction.objects.get(user=self.user, resource="energy")
        self.assertEqual(t.amount, 50)

    def test_a_referral_records_BOTH_sides(self):
        joinee = User.objects.create_user("steve515", "s@e.com", "pw12345678")
        record_referral(self.user, joinee)
        self.assertEqual(Transaction.objects.filter(user=self.user, resource="spinaz").count(), 1)
        self.assertEqual(Transaction.objects.filter(user=joinee, resource="spinaz").count(), 1)
        self.assertEqual(Transaction.objects.get(user=self.user, resource="spinaz").amount, 300)
        self.assertEqual(Transaction.objects.get(user=joinee, resource="spinaz").amount, 100)

    def test_onboarding_records_both_resources(self):
        complete_onboarding(self.user)
        kinds = set(Transaction.objects.filter(user=self.user).values_list("resource", flat=True))
        self.assertEqual(kinds, {"spinaz", "energy"})

    def test_a_zero_award_is_not_a_line(self):
        award_spinaz(self.user, 0, "nothing happened")
        self.assertFalse(Transaction.objects.filter(user=self.user).exists())

    def test_the_balance_still_moves(self):
        award_spinaz(self.user, 300, "referral")
        self.assertEqual(wallet_for(self.user).spinaz, 300)


class LogZViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("k", "k@e.com", "pw12345678")
        self.client.force_authenticate(self.user)
        # LogZ is a Premium feature; these cover the ledger, not the gate.
        m = membership_for(self.user); m.tier = TIER_PREMIUM; m.save(update_fields=["tier", "updated_at"])

    def test_it_shows_what_happened_and_when(self):
        award_spinaz(self.user, 300, "referral (referrer)")
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 200, resp.content)
        row = resp.data["entries"][0]
        self.assertEqual(row["resource"], "spinaz")
        self.assertEqual(row["emoji"], "🍥")
        self.assertEqual(row["display"], "+300 🍥")
        self.assertEqual(row["note"], "referral (referrer)")
        self.assertIsNotNone(row["at"])

    def test_a_spend_reads_as_a_spend(self):
        award_spinaz(self.user, -50, "bought a SpecZ")
        self.assertEqual(self.client.get(URL).data["entries"][0]["display"], "-50 🍥")

    def test_newest_first(self):
        award_spinaz(self.user, 1, "older")
        award_spinaz(self.user, 2, "newer")
        self.assertEqual(self.client.get(URL).data["entries"][0]["note"], "newer")

    def test_it_can_be_narrowed_to_one_resource(self):
        award_spinaz(self.user, 300, "referral")
        award_energy(self.user, 5, "rated a post")
        rows = self.client.get(URL, {"resource": "spinaz"}).data["entries"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["resource"], "spinaz")

    def test_totals_span_the_whole_ledger_not_just_the_page(self):
        for i in range(5):
            award_spinaz(self.user, 100, f"n{i}")
        totals = {t["resource"]: t["amount"] for t in self.client.get(URL, {"limit": 2}).data["totals"]}
        self.assertEqual(len(self.client.get(URL, {"limit": 2}).data["entries"]), 2)
        self.assertEqual(totals["spinaz"], 500)

    def test_money_renders_in_dollars_not_cents(self):
        Transaction.objects.create(user=self.user, kind=Transaction.KIND_ADD,
                                   resource="money", amount=500, amount_cents=500, note="Added funds")
        self.assertEqual(self.client.get(URL, {"resource": "money"}).data["entries"][0]["display"], "+5.00 💵")

    def test_you_only_see_your_own(self):
        other = User.objects.create_user("other", "o@e.com", "pw12345678")
        award_spinaz(other, 999, "not yours")
        self.assertEqual(self.client.get(URL).data["entries"], [])

    def test_it_needs_auth(self):
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(URL).status_code, (401, 403))


class FeatureGateTests(TestCase):
    """Gates were written inline — vocalcoach.py hardcodes its own StatZ check —
    so each new one meant another hand-rolled 403 with its own wording, and the
    client had to guess what it could offer."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("k", "k@e.com", "pw12345678")
        self.client.force_authenticate(self.user)

    def _tier(self, t):
        m = membership_for(self.user); m.tier = t; m.save(update_fields=["tier", "updated_at"])

    def test_logz_is_a_premium_feature(self):
        self._tier(TIER_FREE)
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertEqual(resp.data["required_tier"], TIER_PREMIUM)
        self.assertEqual(resp.data["feature"], "logz")

    def test_the_403_says_what_the_tier_buys(self):
        self._tier(TIER_FREE)
        body = self.client.get(URL).data
        self.assertIn("LogZ", body["detail"])
        self.assertTrue(body["blurb"], "a gate must say what it unlocks, not just 'upgrade'")

    def test_premium_and_statz_both_open_it(self):
        for t in (TIER_PREMIUM, TIER_STATZ):
            self._tier(t)
            self.assertEqual(self.client.get(URL).status_code, 200)

    def test_can_use_is_a_ladder_not_an_equality(self):
        # StatZ must open everything Premium opens.
        self.assertTrue(can_use(TIER_STATZ, "logz"))
        self.assertTrue(can_use(TIER_STATZ, "automationz"))
        self.assertFalse(can_use(TIER_PREMIUM, "automationz"))

    def test_an_unknown_feature_is_open_not_locked(self):
        # A typo in a key must never silently lock somebody out of what they paid for.
        self.assertTrue(can_use(TIER_FREE, "not_a_real_feature"))

    def test_the_feature_map_says_what_this_member_has(self):
        self._tier(TIER_PREMIUM)
        feats = {f["key"]: f for f in self.client.get("/api/economy/features/").data["features"]}
        self.assertTrue(feats["logz"]["unlocked"])
        self.assertTrue(feats["tellz"]["unlocked"])
        self.assertTrue(feats["suggestionz"]["unlocked"])
        self.assertFalse(feats["automationz"]["unlocked"], "AutomationZ is StatZ-only")
        self.assertFalse(feats["gitz"]["unlocked"], "GitZ is StatZ-only")

    def test_every_feature_carries_a_label_emoji_and_blurb(self):
        feats = self.client.get("/api/economy/features/").data["features"]
        self.assertTrue(feats)
        for f in feats:
            self.assertTrue(f["label"] and f["emoji"] and f["blurb"], f)
