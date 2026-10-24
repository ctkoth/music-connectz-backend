from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.models import Referral, ScoreShare, TakeScore, award_spinaz

URL = "/api/economy/whyz/"
User = get_user_model()


class WhyZTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("whyer", "w@e.com", "pw-Long-enough-1")
        self.c = APIClient()
        self.c.force_authenticate(self.u)

    def _by(self):
        return {r["key"]: r for r in self.c.get(URL).json()["reasons"]}

    def test_with_no_history_no_reason_claims_a_number_and_each_says_how_to_find_out(self):
        for r in self._by().values():
            self.assertEqual(r["proof"], "", r["key"])           # never "0 shares", never invented
            self.assertTrue(r["try_it"], r["key"])
            self.assertTrue(r["tab"])

    def test_proof_appears_only_where_it_is_true(self):
        for _ in range(2):
            TakeScore.objects.create(user=self.u, app_key="rapz", overall=6)
        award_spinaz(self.u, 40, "rating")
        by = self._by()
        self.assertIn("2 takes scored", by["fix"]["proof"])
        self.assertEqual(by["fix"]["try_it"], "")                 # proven, so no nudge
        self.assertIn("40", by["earn"]["proof"])
        self.assertEqual(by["reach"]["proof"], "")                # nothing shared yet

    def test_a_card_opened_by_strangers_is_counted_and_shows_as_reach(self):
        row = ScoreShare.objects.create(token="a" * 12, app_key="rapz", score=6, user=self.u)
        for _ in range(3):
            APIClient().get(f"/api/economy/scores/{row.token}/")
        row.refresh_from_db()
        self.assertEqual(row.views, 3)
        other = User.objects.create_user("joiner", "j@e.com", "pw-Long-enough-1")
        Referral.objects.create(referrer=self.u, joinee=other)
        proof = self._by()["reach"]["proof"]
        self.assertIn("opened 3 times", proof)
        self.assertIn("1 person joined", proof)

    def test_a_measured_climb_is_the_proof_for_getting_better(self):
        for d, v in ((12, 4), (11, 4), (10, 4), (3, 7), (2, 7), (1, 7)):
            t = TakeScore.objects.create(user=self.u, app_key="rapz", overall=6, scores={"flow": v})
            TakeScore.objects.filter(pk=t.pk).update(created_at=timezone.now() - timedelta(days=d))
        self.assertIn("4.0 → 7.0", self._by()["climb"]["proof"])


class HumanCreditTests(TestCase):
    """The reason behind the robot, and credit to the human: a card says who made
    the performance (as THEY declared it), what the AI scored it and why."""

    def setUp(self):
        self.u = User.objects.create_user("maker", "m@e.com", "pw-Long-enough-1")
        self.row = ScoreShare.objects.create(
            token="h" * 12, app_key="rapz", score=6, verdict="Locked in.", user=self.u,
            payload={"strengths": ["Cadence stays locked", "second"], "fixes": ["Land the last bar"],
                     "listeners": {"median": 9.7, "count": 4}})
        self.c = APIClient()

    def test_the_card_gives_the_reasons_the_listeners_and_no_human_claim_until_declared(self):
        d = self.c.get(f"/api/economy/scores/{self.row.token}/").json()
        self.assertEqual([w["kind"] for w in d["why"]], ["strengths", "fixes"])
        self.assertEqual(d["why"][0]["text"], "Cadence stays locked")
        self.assertEqual(d["listeners"], {"median": 9.7, "count": 4})   # real people, beside the AI's number
        self.assertFalse(d["human"])                                     # nothing claimed yet

    def test_only_the_maker_can_declare_it_human_made_and_the_card_says_declared(self):
        from apps.economy.scoreshare import render_card, share_dict
        url = f"/api/economy/scores/{self.row.token}/human/"
        self.assertEqual(self.c.post(url, {"declared": True}, format="json").status_code, 401)   # not signed in
        other = APIClient()
        other.force_authenticate(User.objects.create_user("faker", "f@e.com", "pw-Long-enough-1"))
        self.assertEqual(other.post(url, {"declared": True}, format="json").status_code, 404)    # not theirs
        self.c.force_authenticate(self.u)
        self.assertEqual(self.c.post(url, {"declared": "yes"}, format="json").status_code, 400)
        self.assertEqual(self.c.post(url, {"declared": True}, format="json").status_code, 200)
        self.row.refresh_from_db()
        d = share_dict(self.row)
        self.assertTrue(d["human"])
        self.assertTrue(render_card(d).startswith(b"\x89PNG"))
        self.assertTrue(render_card(d, story=True).startswith(b"\x89PNG"))
        self.c.post(url, {"declared": False}, format="json")             # reversible
        self.row.refresh_from_db()
        self.assertFalse(share_dict(self.row)["human"])
