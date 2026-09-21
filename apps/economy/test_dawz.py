"""DawZ — seven DAW placeholders, none built, a click is a vote.

Follows `MoneyBattleVote`'s own shape: a vote is a toggle, not a counter a
member cannot take back.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.dawz import DAW_IDS, DAWS, DawVote

User = get_user_model()
PW = "hunter2hunter2"
URL = "/api/economy/dawz/"


class Base(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("d", "d@e.com", PW)
        self.client = APIClient()
        self.client.force_authenticate(self.user)


class TheCatalogTests(Base):
    def test_all_seven_are_listed_and_none_are_built(self):
        d = self.client.get(URL).data["daws"]
        self.assertEqual(len(d), 7)
        self.assertTrue(all(row["built"] is False for row in d))

    def test_the_ids_match_the_one_list(self):
        d = self.client.get(URL).data["daws"]
        self.assertEqual({row["id"] for row in d}, DAW_IDS)

    def test_a_fresh_member_has_voted_for_nothing(self):
        d = self.client.get(URL).data["daws"]
        self.assertTrue(all(row["votes"] == 0 for row in d))
        self.assertTrue(all(row["my_vote"] is False for row in d))

    def test_every_daw_carries_a_description(self):
        for row in DAWS:
            self.assertTrue(row["desc"])
            self.assertTrue(row["knockoff"])


class VotingTests(Base):
    def test_posting_a_daw_id_casts_a_vote(self):
        r = self.client.post(URL, {"daw_id": "intuition"}, format="json")
        row = next(x for x in r.data["daws"] if x["id"] == "intuition")
        self.assertEqual(row["votes"], 1)
        self.assertTrue(row["my_vote"])
        self.assertEqual(DawVote.objects.filter(user=self.user, daw_id="intuition").count(), 1)

    def test_voting_again_withdraws_the_vote(self):
        self.client.post(URL, {"daw_id": "intuition"}, format="json")
        r = self.client.post(URL, {"daw_id": "intuition"}, format="json")
        row = next(x for x in r.data["daws"] if x["id"] == "intuition")
        self.assertEqual(row["votes"], 0)
        self.assertFalse(row["my_vote"])

    def test_a_member_may_vote_for_more_than_one_daw(self):
        self.client.post(URL, {"daw_id": "intuition"}, format="json")
        r = self.client.post(URL, {"daw_id": "arsenal"}, format="json")
        voted = {x["id"] for x in r.data["daws"] if x["my_vote"]}
        self.assertEqual(voted, {"intuition", "arsenal"})

    def test_a_fake_daw_id_is_refused(self):
        r = self.client.post(URL, {"daw_id": "not-a-real-daw"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_a_tally_is_not_weighted_by_tier(self):
        # The substance rule's test applied to a headcount: every member's
        # vote counts the same, or "which DAW do people want" stops meaning
        # what it says.
        from apps.economy.models import TIER_STATZ, membership_for
        other = User.objects.create_user("statz", "s@e.com", PW)
        membership_for(other).tier = TIER_STATZ
        membership_for(other).save(update_fields=["tier"])
        other_client = APIClient()
        other_client.force_authenticate(other)
        self.client.post(URL, {"daw_id": "azrael"}, format="json")
        r = other_client.post(URL, {"daw_id": "azrael"}, format="json")
        row = next(x for x in r.data["daws"] if x["id"] == "azrael")
        self.assertEqual(row["votes"], 2)
