"""BadgeZ — a title you wear and an effect you feel.

The standard every badge is held to: it changes a number the member can point
at, and the effect is read by the system it affects. A badge whose multiplier
lived only in its description would be a sticker.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import (
    BADGES,
    Badge,
    ItemRating,
    Post,
    PostContributor,
    RATING_REWARD_DAILY_CAP,
    TIER_FREE,
    TIER_STATZ,
    badge_effects,
    energy_rate_per_hour,
    grant_badge,
    membership_for,
    profile_for,
    recheck_badges,
)

User = get_user_model()
PW = "hunter2hunter2"
BADGEZ = "/api/economy/badgez/"
GIFT = "/api/economy/badgez/gift/"


class BadgeBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="maker", password=PW)
        membership_for(self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.owner = User.objects.create_user(username="owner", password=PW,
                                              is_staff=True, is_superuser=True)
        membership_for(self.owner)
        self.oc = APIClient(); self.oc.force_authenticate(self.owner)


class EveryBadgeDoesSomethingTests(BadgeBase):
    def test_no_badge_is_only_decoration(self):
        # The whole rule, asserted once.
        for key, spec in BADGES.items():
            self.assertTrue(spec.get("effects"), f"{key} has no effect")
            self.assertTrue(spec.get("effect_note"), f"{key} doesn't say what it does")

    def test_every_badge_says_how_it_is_come_by(self):
        for key, spec in BADGES.items():
            self.assertTrue(spec.get("how"), key)
            # Earned badges carry a check; gifted ones say they're gifted.
            self.assertTrue(spec.get("check") or spec.get("gifted"), key)

    def test_effects_add_up_across_badges(self):
        grant_badge(self.user, "verified_reach")     # ×1.25
        grant_badge(self.user, "founding")           # ×1.25
        # 1.25 × 1.25 exactly — multiplied at full precision, rounded once.
        self.assertEqual(badge_effects(self.user)["energy_multiplier"], 1.5625)

    def test_effects_are_computed_not_stored(self):
        # A stored copy is how an effect outlives the badge that justified it.
        grant_badge(self.user, "verified_reach")
        self.assertIn("energy_multiplier", badge_effects(self.user))
        Badge.objects.filter(user=self.user, key="verified_reach").delete()
        self.assertNotIn("energy_multiplier", badge_effects(self.user))


class TheEffectsActuallyBiteTests(BadgeBase):
    def test_the_energy_multiplier_moves_the_energy_rate(self):
        p = profile_for(self.user)
        p.links = [{"label": "IG", "url": "https://x.test", "verified": True,
                    "followers": 1000, "verified_count": 1000}]
        p.save(update_fields=["links"])
        fresh = User.objects.get(pk=self.user.pk)
        before = energy_rate_per_hour(fresh)
        self.assertGreater(before, 0)
        grant_badge(self.user, "founding")
        self.assertEqual(energy_rate_per_hour(User.objects.get(pk=self.user.pk)),
                         int(before * 1.25))

    def test_the_rating_cap_bonus_raises_the_cap_that_pays(self):
        from apps.economy.models import Transaction, reward_for_rating
        # Fill the base cap.
        for i in range(RATING_REWARD_DAILY_CAP):
            reward_for_rating(self.user, f"post:{i}")
        self.assertEqual(reward_for_rating(self.user, "post:x"), 0)
        grant_badge(self.user, "ear")
        self.assertGreater(reward_for_rating(self.user, "post:y"), 0)

    def test_the_owner_badge_grants_statz_the_moment_it_lands(self):
        # A tier that only applies on some later unrelated save is a promise
        # with a delay nobody explained.
        self.assertEqual(membership_for(self.user).tier, TIER_FREE)
        grant_badge(self.user, "owner")
        self.assertEqual(membership_for(self.user).tier, TIER_STATZ)

    def test_the_owner_badge_carries_the_tax_and_the_royalties(self):
        grant_badge(self.user, "owner")
        fx = badge_effects(self.user)
        self.assertEqual(fx["dev_tax_share"], 1.0)
        self.assertTrue(fx["intelligence_royalties"])


class EarnedNotClaimedTests(BadgeBase):
    def test_verified_reach_lands_when_an_account_is_verified(self):
        p = profile_for(self.user)
        p.links = [{"label": "IG", "url": "https://x.test", "verified": True,
                    "followers": 500}]
        p.save(update_fields=["links"])
        self.assertIn("verified_reach", recheck_badges(User.objects.get(pk=self.user.pk)))

    def test_it_does_not_land_on_an_unverified_link(self):
        p = profile_for(self.user)
        p.links = [{"label": "IG", "url": "https://x.test", "followers": 999999}]
        p.save(update_fields=["links"])
        self.assertNotIn("verified_reach", recheck_badges(User.objects.get(pk=self.user.pk)))

    def test_the_collaborator_badge_counts_shipped_collabs(self):
        for i in range(10):
            post = Post.objects.create(author=self.owner, title=f"c{i}")
            PostContributor.objects.create(post=post, user=self.user, slot="image")
        self.assertIn("collaborator", recheck_badges(self.user))

    def test_nine_is_not_ten(self):
        for i in range(9):
            post = Post.objects.create(author=self.owner, title=f"c{i}")
            PostContributor.objects.create(post=post, user=self.user, slot="image")
        self.assertNotIn("collaborator", recheck_badges(self.user))

    def test_the_ear_counts_ratings_given_not_received(self):
        for i in range(100):
            ItemRating.objects.create(user=self.user, item_id=f"post:{i}", score=8)
        self.assertIn("ear", recheck_badges(self.user))

    def test_an_earned_badge_cannot_be_gifted(self):
        # Handing out an earned badge by favour would make every earned badge
        # unreadable — nobody could tell which were met and which were granted.
        r = self.oc.post(GIFT, {"key": "collaborator", "username": "maker"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("earned, not gifted", r.data["detail"])

    def test_only_the_owner_gifts(self):
        r = self.client.post(GIFT, {"key": "founding", "username": "maker"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_the_owner_can_gift_a_gifted_badge(self):
        r = self.oc.post(GIFT, {"key": "founding", "username": "maker"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(Badge.objects.filter(user=self.user, key="founding").exists())

    def test_gifting_twice_does_not_duplicate(self):
        self.oc.post(GIFT, {"key": "founding", "username": "maker"}, format="json")
        again = self.oc.post(GIFT, {"key": "founding", "username": "maker"}, format="json")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(Badge.objects.filter(user=self.user).count(), 1)

    def test_the_member_is_told_what_it_does(self):
        grant_badge(self.user, "founding")
        note = self.user.notifications.first()
        self.assertIn("Founding Fifty", note.text)
        self.assertIn("Half price", note.text)


class TitlesAndPrivacyTests(BadgeBase):
    def setUp(self):
        super().setUp()
        grant_badge(self.user, "straight_shooter")

    def test_a_title_can_be_worn_once_the_badge_is_held(self):
        r = self.client.patch(BADGEZ, {"title": "Straight Shooter"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["title"], "Straight Shooter")

    def test_a_title_you_do_not_hold_is_refused(self):
        r = self.client.patch(BADGEZ, {"title": "Owner"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(profile_for(self.user).badge_title, "")

    def test_a_badge_can_be_hidden(self):
        # An achievement is also a disclosure.
        self.client.patch(BADGEZ, {"key": "straight_shooter", "visible": False},
                          format="json")
        seen = self.oc.get(f"{BADGEZ}?username=maker").data["badges"]
        self.assertEqual(seen, [])

    def test_hiding_a_badge_does_not_cost_you_its_effect(self):
        # Privacy that costs you something you earned is privacy with a price.
        self.client.patch(BADGEZ, {"key": "straight_shooter", "visible": False},
                          format="json")
        self.assertTrue(badge_effects(self.user)["stake_waived"])

    def test_hiding_the_badge_takes_its_title_down_too(self):
        # Otherwise the title leaks what the switch was meant to conceal.
        self.client.patch(BADGEZ, {"title": "Straight Shooter"}, format="json")
        self.client.patch(BADGEZ, {"key": "straight_shooter", "visible": False},
                          format="json")
        self.assertEqual(profile_for(self.user).badge_title, "")

    def test_only_the_holder_sees_the_privacy_switch(self):
        mine = self.client.get(BADGEZ).data["badges"][0]
        theirs = self.oc.get(f"{BADGEZ}?username=maker").data["badges"][0]
        self.assertIn("visible", mine)
        self.assertNotIn("visible", theirs)

    def test_the_whole_catalogue_is_shown_so_nothing_is_a_surprise(self):
        keys = {b["key"] for b in self.client.get(BADGEZ).data["catalogue"]}
        self.assertEqual(keys, set(BADGES))
