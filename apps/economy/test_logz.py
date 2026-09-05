from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.catalog import LOGZ_HISTORY_DAYS
from apps.economy.features import FEATURES, can_use, gate_detail
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
        # Premium so the whole ledger is in window; these cover the rows, not
        # the history ladder.
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

    def test_logz_is_not_gated_at_all(self):
        """A member's own ledger is not a feature we rent to them.

        It WAS Premium-only, which answered "where did my SpinaZ go" with an
        upsell — while occ_spec.py already advertised SpinaZ and Energy as
        things a Free member opens IN LogZ. The door was published and locked."""
        self._tier(TIER_FREE)
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_logz_is_not_in_the_feature_table_any_more(self):
        # A stale row here would put a lock back on the client's LogZ tile
        # even though the endpoint answers everybody.
        self.assertNotIn("logz", FEATURES)

    def test_the_tier_buys_depth_and_says_so_in_days(self):
        for tier, days in ((TIER_FREE, 30), (TIER_PREMIUM, 366), (TIER_STATZ, None)):
            self._tier(tier)
            body = self.client.get(URL).data
            self.assertEqual(body["history_days"], days, tier)
            self.assertTrue(body["history_label"], tier)
            self.assertEqual(len(body["history_ladder"]), len(LOGZ_HISTORY_DAYS))

    def test_free_sees_today_and_is_told_what_is_out_of_window(self):
        """A limit that hides rows must SAY it hid them. Silence reads as
        'nothing happened', which is a different and worse claim."""
        self._tier(TIER_FREE)
        award_spinaz(self.user, 5, "recent")
        old_row = Transaction.objects.filter(user=self.user).first()
        Transaction.objects.filter(pk=old_row.pk).update(
            created_at=timezone.now() - timedelta(days=400))
        award_spinaz(self.user, 7, "today")
        body = self.client.get(URL).data
        notes = [e["note"] for e in body["entries"]]
        self.assertIn("today", notes)
        self.assertNotIn("recent", notes)
        self.assertEqual(body["hidden_by_tier"], 1)

    def test_statz_sees_all_of_it(self):
        self._tier(TIER_STATZ)
        award_spinaz(self.user, 5, "ancient")
        Transaction.objects.filter(user=self.user).update(
            created_at=timezone.now() - timedelta(days=4000))
        body = self.client.get(URL).data
        self.assertEqual([e["note"] for e in body["entries"]], ["ancient"])
        self.assertEqual(body["hidden_by_tier"], 0)

    def test_can_use_is_a_ladder_not_an_equality(self):
        # StatZ must open everything Premium opens.
        self.assertTrue(can_use(TIER_STATZ, "tellz"))
        self.assertTrue(can_use(TIER_STATZ, "automationz"))
        self.assertFalse(can_use(TIER_PREMIUM, "automationz"))

    def test_a_gate_that_does_exist_still_says_what_it_buys(self):
        # One wording for every gate — the property the LogZ 403 used to prove.
        body = gate_detail("automationz")
        self.assertIn("AutomationZ", body["detail"])
        self.assertTrue(body["blurb"], "a gate must say what it unlocks, not just 'upgrade'")
        self.assertEqual(body["required_tier"], TIER_STATZ)

    def test_an_unknown_feature_is_open_not_locked(self):
        # A typo in a key must never silently lock somebody out of what they paid for.
        self.assertTrue(can_use(TIER_FREE, "not_a_real_feature"))

    def test_the_feature_map_says_what_this_member_has(self):
        self._tier(TIER_PREMIUM)
        feats = {f["key"]: f for f in self.client.get("/api/economy/features/").data["features"]}
        self.assertNotIn("logz", feats, "LogZ is not a gate any more")
        self.assertTrue(feats["tellz"]["unlocked"])
        self.assertTrue(feats["suggestionz"]["unlocked"])
        self.assertFalse(feats["automationz"]["unlocked"], "AutomationZ is StatZ-only")
        self.assertFalse(feats["gitz"]["unlocked"], "GitZ is StatZ-only")

    def test_every_feature_carries_a_label_emoji_and_blurb(self):
        feats = self.client.get("/api/economy/features/").data["features"]
        self.assertTrue(feats)
        for f in feats:
            self.assertTrue(f["label"] and f["emoji"] and f["blurb"], f)


class LedgerRowsAreDoorsTests(TestCase):
    """Nothing is a dead end — including a balance.

    A LogZ row said what moved and why and then stopped. The member reading
    "referral (referrer) +300 🍥" had the answer to "did it pay?" and no way to
    get back to the thing that paid. `Transaction.open_in` is where that goes.

    The rule it must keep: a row with no recorded origin renders as a plain
    row. Guessing a destination from the note text would send somebody to the
    wrong app, which is worse than not offering the trip.
    """

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("d", "d@e.com", "pw12345678")
        self.client.force_authenticate(self.user)

    def rows(self):
        return self.client.get(URL).data["entries"]

    def test_a_referral_row_leads_back_to_where_it_was_earned(self):
        joinee = User.objects.create_user("j", "j@e.com", "pw12345678")
        record_referral(self.user, joinee)
        row = next(r for r in self.rows() if "referral" in r["note"])
        self.assertEqual(row["open_in"], "earnz")

    def test_a_rating_reward_leads_back_to_postz(self):
        award_energy(self.user, 1, "rated a post", open_in="postz")
        self.assertEqual(self.rows()[0]["open_in"], "postz")

    def test_a_row_with_no_recorded_origin_says_so_rather_than_guessing(self):
        award_spinaz(self.user, 5, "something we did not tag")
        self.assertEqual(self.rows()[0]["open_in"], "")

    def test_an_over_long_target_is_trimmed_not_rejected(self):
        # A ledger write must never be the reason a reward fails to land.
        award_spinaz(self.user, 5, "x", open_in="a" * 200)
        self.assertEqual(len(self.rows()[0]["open_in"]), 64)
