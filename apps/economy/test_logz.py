from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.features import FEATURES, can_use, required_tier
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

    def test_logz_is_open_at_every_tier_and_must_stay_that_way(self):
        """LogZ was Premium and was deliberately unlocked. Do not put it back.

        A member who cannot read their own ledger cannot answer "did my
        referral pay?" or "what took that ⚡" about their OWN account. That is
        the ladder rule's "whether", not its "how much" — and the app's own
        cross-pollination note leans on it: a balance is supposed to lead back
        to the action that changed it, which is a door LogZ is the other side
        of.

        This test used to assert the opposite and was left behind when the
        table changed, so it failed on main for weeks reading exactly like an
        instruction to re-gate the feature. It now fails the other way, which
        is the way that protects members.
        """
        for t in (TIER_FREE, TIER_PREMIUM, TIER_STATZ):
            self._tier(t)
            self.assertEqual(self.client.get(URL).status_code, 200, t)
        self.assertEqual(required_tier("logz"), TIER_FREE)

    def test_a_gate_that_does_fire_says_what_the_tier_buys(self):
        # The 403 body used to be exercised through LogZ. LogZ no longer
        # refuses anybody, so the machinery is checked against a feature that
        # genuinely is gated — otherwise unlocking a feature quietly deletes
        # the only coverage of how every other gate speaks.
        self._tier(TIER_FREE)
        resp = self.client.get("/api/economy/journalz/lookback/")
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertEqual(resp.data["required_tier"], TIER_PREMIUM)
        self.assertEqual(resp.data["feature"], "journalz_lookback")
        self.assertIn("On This Day", resp.data["detail"])
        self.assertIn("Premium", resp.data["detail"])
        self.assertTrue(resp.data["blurb"], "a gate must say what it unlocks, not just 'upgrade'")

    def test_the_view_reads_the_table_rather_than_hardcoding_the_answer(self):
        # `LogZView` still runs `can_use`, and that is deliberate: the check is
        # table-driven, so it costs nothing while LogZ is free and it keeps the
        # table honest if the tier ever moves. Pinned here because a check that
        # can never fire today is exactly the kind of thing somebody deletes as
        # dead code — and deleting it would let features.py say "premium" while
        # the endpoint served everybody.
        with mock.patch.dict(FEATURES["logz"], {"tier": TIER_PREMIUM}):
            self._tier(TIER_FREE)
            self.assertEqual(self.client.get(URL).status_code, 403)
            self._tier(TIER_PREMIUM)
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


class LedgerOpensOntoWhatItBoughtTests(TestCase):
    """A spend is a fee until the ledger can point at what it paid for. A coach
    spend opens onto the rating, the report and the file."""

    def setUp(self):
        from django.utils import timezone
        from apps.economy.models import TakeScore, link_spend
        self.user = User.objects.create_user("buyer", "b@e.com", "pw12345678")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.t0 = timezone.now()
        Transaction.objects.create(user=self.user, kind=Transaction.KIND_SPEND, amount_cents=0,
                                   note="RapZ Boss Take — AI Coach · daily prompt 🏷️")
        self.take = TakeScore.objects.create(
            user=self.user, app_key="rapz", overall=6, genre="Trap", scores={"flow": 6},
            read={"verdict": "Locked in.", "strengths": ["Cadence"], "fixes": ["Last bar"],
                  "practice": [{"what": "Slow bars", "why": "w", "how": "h"}], "exact": 6.2})
        self.linked = link_spend(self.user, f"take:{self.take.pk}", self.t0, "RapZ Boss Take — AI Coach")

    def _row(self):
        return [e for e in self.client.get(URL).json()["entries"] if e["ref"]][0]

    def test_the_spend_is_pointed_at_the_take_it_bought(self):
        self.assertTrue(self.linked)
        o = self._row()["outcome"]
        self.assertEqual(o["kind"], "take")
        self.assertEqual(o["rating"]["score"], 6)
        self.assertEqual(o["rating"]["exact"], 6.2)
        self.assertEqual(o["report"]["verdict"], "Locked in.")
        self.assertEqual(o["report"]["fixes"], ["Last bar"])
        self.assertEqual(o["report"]["practice"][0]["what"], "Slow bars")

    def test_each_number_is_paired_with_what_the_coach_heard_behind_it(self):
        self.take.scores = {"flow": 6, "timing": 4}
        self.take.upgrades = {"context": {"heard": [
            {"t": "0:12", "what": "Drifts behind the beat in the second bar", "dim": "timing", "confidence": 3},
            {"t": "0:03", "what": "Maybe late", "dim": "timing", "confidence": 1},
            {"t": "0:20", "what": "Cadence stays locked", "dim": "flow", "confidence": 2}]}}
        self.take.save(update_fields=["scores", "upgrades"])
        dims = {d["key"]: d for d in self._row()["outcome"]["rating"]["dimensions"]}
        self.assertEqual(dims["timing"]["value"], 4)
        self.assertEqual(dims["timing"]["detail"], "Drifts behind the beat in the second bar")  # the confident one
        self.assertEqual(dims["flow"]["detail"], "Cadence stays locked")
        self.assertTrue(dims["flow"]["label"])                                                  # never a bare key

    def test_the_file_is_shown_when_kept_and_said_plainly_when_it_was_not(self):
        o = self._row()["outcome"]
        self.assertFalse(o["file"]["kept"])                        # scored, not kept
        self.assertIn("not kept", o["file"]["why"])
        from apps.economy.models import Upload
        from django.core.files.base import ContentFile
        up = Upload.objects.create(user=self.user, name="take.webm", content_type="audio/webm", size_bytes=3,
                                   file=ContentFile(b"abc", name="take.webm"))
        self.take.upload = up
        self.take.save(update_fields=["upload"])
        f = self._row()["outcome"]["file"]
        self.assertTrue(f["kept"])
        self.assertEqual(f["name"], "take.webm")
        self.assertTrue(f["url"])

    def test_a_row_with_no_ref_has_no_outcome_and_a_forged_ref_reads_as_nothing(self):
        other = User.objects.create_user("other", "o@e.com", "pw12345678")
        from apps.economy.models import TakeScore
        theirs = TakeScore.objects.create(user=other, app_key="rapz", overall=9)
        Transaction.objects.create(user=self.user, kind=Transaction.KIND_SPEND, amount_cents=-1,
                                   note="forged", ref=f"take:{theirs.pk}")
        rows = {e["note"]: e for e in self.client.get(URL).json()["entries"]}
        self.assertIsNone(rows["forged"]["outcome"])               # somebody else's take is not shown
