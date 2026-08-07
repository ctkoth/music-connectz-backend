"""The two toggles, finally doing something.

Both were stored booleans that nothing read. SuggestionZ now proposes work from
evidence and waits; AutomationZ removes the tap for what's safe to take without
asking — and only for that.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import (
    Badge,
    ItemRating,
    OccOutput,
    OccTask,
    TIER_FREE,
    TIER_PREMIUM,
    TIER_STATZ,
    membership_for,
    occ_settings_for,
    profile_for,
)

User = get_user_model()
PW = "hunter2hunter2"
SUGGEST = "/api/economy/occ/suggest/"


def as_tier(user, tier):
    m = membership_for(user)
    m.tier = tier
    m.save(update_fields=["tier", "updated_at"])
    return user


class SuggestBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="maker", password=PW)
        as_tier(self.user, TIER_PREMIUM)
        s = occ_settings_for(self.user)
        s.suggestionz = True
        s.save(update_fields=["suggestionz"])
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def earn_a_badge(self):
        for i in range(100):
            ItemRating.objects.create(user=self.user, item_id=f"post:{i}", score=8)

    def keys(self):
        return {i["key"] for i in self.client.get(SUGGEST).data["suggestions"]}


class ItReadsYourAccountTests(SuggestBase):
    def test_it_proposes_nothing_when_there_is_nothing_to_do(self):
        # A suggestion engine that always has something to say is noise.
        self.assertEqual(self.keys(), set())

    def test_unclaimed_badges_are_noticed(self):
        self.earn_a_badge()
        self.assertIn("claim_badges", self.keys())

    def test_unposted_work_is_noticed(self):
        OccOutput.objects.create(user=self.user, title="a hook")
        self.assertIn("share_work", self.keys())

    def test_unpriced_skills_are_noticed(self):
        p = profile_for(self.user)
        p.personas = [{"key": "p", "name": "P", "skills": [{"name": "Beat Producer"}]}]
        p.save(update_fields=["personas"])
        self.assertIn("price_skills", self.keys())

    def test_a_priced_skill_is_not_nagged_about(self):
        p = profile_for(self.user)
        p.personas = [{"key": "p", "name": "P",
                       "skills": [{"name": "Beat Producer", "rate_cents": 40}]}]
        p.save(update_fields=["personas"])
        self.assertNotIn("price_skills", self.keys())

    def test_unverified_links_are_noticed(self):
        p = profile_for(self.user)
        p.links = [{"label": "IG", "url": "https://x.test"}]
        p.save(update_fields=["links"])
        self.assertIn("verify_social", self.keys())

    def test_every_suggestion_says_what_why_and_how(self):
        # All three or it isn't a suggestion, it's an assertion.
        self.earn_a_badge()
        OccOutput.objects.create(user=self.user, title="a hook")
        for s in self.client.get(SUGGEST).data["suggestions"]:
            self.assertTrue(s["what"] and s["why"] and s["how"], s["key"])


class SuggestionZWaitsTests(SuggestBase):
    def test_a_premium_member_gets_suggestions_that_wait(self):
        self.earn_a_badge()
        r = self.client.post(SUGGEST, {}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["ran"], [])
        task = OccTask.objects.get(pk=r.data["suggested"][0])
        self.assertEqual(task.status, OccTask.STATUS_SUGGESTED)
        # …and nothing happened until the member says so.
        self.assertFalse(Badge.objects.filter(user=self.user).exists())

    def test_free_cannot_use_it(self):
        as_tier(self.user, TIER_FREE)
        r = self.client.post(SUGGEST, {}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data["required_tier"], "premium")

    def test_switching_it_off_stops_it(self):
        s = occ_settings_for(self.user)
        s.suggestionz = False
        s.save(update_fields=["suggestionz"])
        self.assertEqual(self.client.post(SUGGEST, {}, format="json").status_code, 409)

    def test_it_does_not_propose_the_same_thing_twice(self):
        # Proposing again is nagging.
        self.earn_a_badge()
        self.client.post(SUGGEST, {}, format="json")
        again = self.client.post(SUGGEST, {}, format="json")
        self.assertEqual(again.data["suggested"], [])
        self.assertEqual(OccTask.objects.count(), 1)


class AutomationZActsTests(SuggestBase):
    def setUp(self):
        super().setUp()
        as_tier(self.user, TIER_STATZ)
        s = occ_settings_for(self.user)
        s.automation = True
        s.save(update_fields=["automation"])

    def test_an_auto_safe_suggestion_runs_without_asking(self):
        self.earn_a_badge()
        r = self.client.post(SUGGEST, {}, format="json")
        self.assertEqual(len(r.data["ran"]), 1)
        task = OccTask.objects.get(pk=r.data["ran"][0])
        self.assertEqual(task.status, OccTask.STATUS_DONE)
        self.assertTrue(task.automated)
        # It actually did the thing.
        self.assertTrue(Badge.objects.filter(user=self.user, key="ear").exists())

    def test_it_tells_you_what_it_did(self):
        # The promise AutomationZ makes in exchange for not asking. NOT via
        # log_resource — LogZ is a resource ledger and returns early on a zero
        # amount, so those calls wrote nothing at all.
        self.earn_a_badge()
        self.client.post(SUGGEST, {}, format="json")
        note = self.user.notifications.first()
        self.assertIsNotNone(note)
        self.assertIn("without asking", note.text)
        self.assertIn("Undo it", note.text)

    def test_what_it_did_can_be_undone(self):
        self.earn_a_badge()
        r = self.client.post(SUGGEST, {}, format="json")
        task = OccTask.objects.get(pk=r.data["ran"][0])
        self.assertTrue(task.undo_payload)
        self.assertTrue(task.can_undo(TIER_STATZ))

    def test_publishing_your_work_still_asks_even_on_statz(self):
        # A tier can remove a tap; it cannot make an irreversible thing
        # reversible. Anything other members can see keeps its confirmation.
        OccOutput.objects.create(user=self.user, title="a hook")
        r = self.client.post(SUGGEST, {}, format="json")
        task = OccTask.objects.get(pk=r.data["suggested"][0])
        self.assertEqual(task.status, OccTask.STATUS_SUGGESTED)
        self.assertFalse(task.automated)
        self.assertEqual(OccOutput.objects.get().shared_post_id, None)

    def test_spending_still_asks_too(self):
        p = profile_for(self.user)
        p.personas = [{"key": "p", "name": "P", "skills": [{"name": "Beat Producer"}]}]
        p.save(update_fields=["personas"])
        r = self.client.post(SUGGEST, {}, format="json")
        self.assertEqual(r.data["ran"], [])

    def test_the_split_is_declared_up_front(self):
        self.earn_a_badge()
        OccOutput.objects.create(user=self.user, title="a hook")
        d = self.client.get(SUGGEST).data
        self.assertEqual(d["auto_safe"], ["claim_badges"])
        self.assertIn("share_work", d["needs_you"])
        self.assertIn("keeps its confirmation", d["note"])

    def test_automation_off_means_it_waits_like_anyone_else(self):
        s = occ_settings_for(self.user)
        s.automation = False
        s.save(update_fields=["automation"])
        self.earn_a_badge()
        r = self.client.post(SUGGEST, {}, format="json")
        self.assertEqual(r.data["ran"], [])
        self.assertFalse(Badge.objects.filter(user=self.user).exists())

    def test_premium_never_automates_even_with_the_flag_set(self):
        as_tier(self.user, TIER_PREMIUM)
        self.earn_a_badge()
        r = self.client.post(SUGGEST, {}, format="json")
        self.assertEqual(r.data["ran"], [])
        self.assertFalse(r.data["automation"])
