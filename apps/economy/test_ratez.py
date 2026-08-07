"""Every rating classified for what it is — and a post rating reaching the skills.

Five things were all called "a rating". A number with no label is a number
nobody can act on, and a post rating used to land on the post and stop, so a
mix engineer with forty well-rated posts had no rated skill to show for it.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.models import (
    CollabDeal,
    Post,
    SkillRating,
    membership_for,
    skill_rating_median,
)

User = get_user_model()
PW = "hunter2hunter2"
RATE = "/api/economy/social/rate/"
RATEZ = "/api/economy/ratez/"


class RatezBase(TestCase):
    def setUp(self):
        self.maker = User.objects.create_user(username="maker", password=PW)
        self.fans = [User.objects.create_user(username=f"fan{i}", password=PW) for i in range(4)]
        for u in [self.maker] + self.fans:
            membership_for(u)
        self.client = APIClient()
        self.client.force_authenticate(self.maker)

    def make_post(self, skills, title="Midnight"):
        p = Post.objects.create(author=self.maker, title=title, skills_used=skills,
                                visibility="public")
        # The rate window is 30s; these posts are rated immediately in tests.
        Post.objects.filter(pk=p.pk).update(created_at=timezone.now() - timedelta(minutes=5))
        return Post.objects.get(pk=p.pk)

    def rate(self, who, post, score):
        c = APIClient(); c.force_authenticate(who)
        return c.post(RATE, {"item": f"post:{post.id}", "score": score}, format="json")


class APostRatingReachesTheSkillsTests(RatezBase):
    def test_rating_a_post_rates_every_skill_that_made_it(self):
        post = self.make_post(["Mix / Master Engineer", "Beat Producer"])
        self.rate(self.fans[0], post, 9)
        self.assertEqual(skill_rating_median(self.maker, "Mix / Master Engineer"), 9)
        self.assertEqual(skill_rating_median(self.maker, "Beat Producer"), 9)

    def test_the_post_keeps_its_own_rating_too(self):
        # Both, not one instead of the other.
        post = self.make_post(["Beat Producer"])
        r = self.rate(self.fans[0], post, 8)
        self.assertEqual(r.data["rating"], 8)
        self.assertEqual(skill_rating_median(self.maker, "Beat Producer"), 8)

    def test_a_skill_median_is_across_the_posts_that_used_it(self):
        a = self.make_post(["Beat Producer"], "one")
        b = self.make_post(["Beat Producer"], "two")
        self.rate(self.fans[0], a, 10)
        self.rate(self.fans[1], b, 6)
        self.assertEqual(skill_rating_median(self.maker, "Beat Producer"), 8)

    def test_changing_your_rating_moves_the_skill_it_fed(self):
        # Otherwise the two disagree from then on.
        post = self.make_post(["Beat Producer"])
        self.rate(self.fans[0], post, 3)
        self.assertEqual(skill_rating_median(self.maker, "Beat Producer"), 3)
        self.rate(self.fans[0], post, 9)
        self.assertEqual(skill_rating_median(self.maker, "Beat Producer"), 9)
        self.assertEqual(SkillRating.objects.count(), 1)

    def test_rating_your_own_post_credits_no_skill(self):
        post = self.make_post(["Beat Producer"])
        self.rate(self.maker, post, 10)
        self.assertIsNone(skill_rating_median(self.maker, "Beat Producer"))

    def test_a_post_with_no_skills_declared_credits_nothing(self):
        post = self.make_post([])
        self.rate(self.fans[0], post, 9)
        self.assertEqual(SkillRating.objects.count(), 0)

    def test_only_posts_feed_skills(self):
        # A battle entry or a playlist is rated as itself; there is no skill
        # behind it to credit.
        c = APIClient(); c.force_authenticate(self.fans[0])
        c.post(RATE, {"item": "playlist:1", "score": 9}, format="json")
        self.assertEqual(SkillRating.objects.count(), 0)


class CollabCreditsTheRightPersonTests(RatezBase):
    """Rating the whole work is not a rating of everyone for everything."""

    def setUp(self):
        super().setUp()
        self.designer = User.objects.create_user(username="designer", password=PW)
        membership_for(self.designer)
        deal = CollabDeal.objects.create(
            initiator=self.maker, title="Midnight", currency=CollabDeal.CURRENCY_SPINAZ,
            participants=[{"username": "maker"}, {"username": "designer"}])
        self.post = Post.objects.create(
            author=self.maker, title="Midnight", visibility="public", source_deal=deal,
            contributors=[{"username": "maker", "slot": "audio"},
                          {"username": "designer", "slot": "image"}])
        Post.objects.filter(pk=self.post.pk).update(
            created_at=timezone.now() - timedelta(minutes=5))
        self.post.refresh_from_db()

    def test_each_contributor_is_credited_for_their_own_slot(self):
        self.rate(self.fans[0], self.post, 9)
        self.assertEqual(skill_rating_median(self.maker, "Independent Artist"), 9)
        self.assertEqual(skill_rating_median(self.designer, "Designer"), 9)

    def test_the_designer_is_not_credited_for_the_music(self):
        self.rate(self.fans[0], self.post, 9)
        self.assertIsNone(skill_rating_median(self.designer, "Independent Artist"))
        self.assertIsNone(skill_rating_median(self.maker, "Designer"))


class ClassifiedTests(RatezBase):
    def test_every_kind_is_named_and_says_what_it_measures(self):
        r = self.client.get("/api/economy/ratez/kinds/")
        kinds = {k["key"]: k for k in r.data["kinds"]}
        self.assertEqual(set(kinds), {"post", "skill", "contribution", "overall",
                                      "attractiveness"})
        for k in kinds.values():
            self.assertTrue(k["name"] and k["of"] and k["how"] and k["desc"], k)

    def test_the_two_that_are_about_the_person_say_so(self):
        kinds = {k["key"]: k for k in self.client.get("/api/economy/ratez/kinds/").data["kinds"]}
        self.assertEqual(kinds["overall"]["of"], "you")
        self.assertEqual(kinds["attractiveness"]["of"], "you")
        self.assertEqual(kinds["post"]["of"], "the work")

    def test_a_skill_rating_is_declared_as_derived_never_given(self):
        kinds = {k["key"]: k for k in self.client.get("/api/economy/ratez/kinds/").data["kinds"]}
        self.assertIn("derived", kinds["skill"]["how"])

    def test_ratez_separates_the_kinds_rather_than_averaging_them(self):
        post = self.make_post(["Beat Producer", "Mix / Master Engineer"])
        self.rate(self.fans[0], post, 8)
        r = self.client.get(RATEZ)
        self.assertEqual(r.data["post"]["median"], 8)
        skills = {s["skill"]: s for s in r.data["skill"]["skills"]}
        self.assertEqual(skills["Beat Producer"]["rating"], 8)
        self.assertIsNone(r.data["overall"]["median"])
        self.assertIsNone(r.data["attractiveness"]["median"])

    def test_a_skill_shows_how_much_work_is_behind_it(self):
        a, b = self.make_post(["Beat Producer"], "one"), self.make_post(["Beat Producer"], "two")
        self.rate(self.fans[0], a, 9)
        self.rate(self.fans[1], b, 9)
        skills = self.client.get(RATEZ).data["skill"]["skills"]
        self.assertEqual(skills[0]["count"], 2)

    def test_skills_rank_by_evidence_not_by_score(self):
        # A 10 from one rating should not outrank a 9 from three.
        thin = self.make_post(["Designer"], "thin")
        for i, p in enumerate([self.make_post(["Beat Producer"], f"p{i}") for i in range(3)]):
            self.rate(self.fans[i], p, 9)
        self.rate(self.fans[3], thin, 10)
        skills = self.client.get(RATEZ).data["skill"]["skills"]
        self.assertEqual(skills[0]["skill"], "Beat Producer")

    def test_i_can_read_someone_elses(self):
        post = self.make_post(["Beat Producer"])
        self.rate(self.fans[0], post, 7)
        c = APIClient(); c.force_authenticate(self.fans[1])
        r = c.get(f"{RATEZ}?username=maker")
        self.assertEqual(r.data["username"], "maker")
        self.assertFalse(r.data["mine"])
        self.assertEqual(r.data["post"]["median"], 7)

    def test_an_unrated_member_reports_nothing_rather_than_zero(self):
        # A zero would read as "rated badly" instead of "not rated".
        r = self.client.get(RATEZ)
        self.assertIsNone(r.data["post"]["median"])
        self.assertEqual(r.data["skill"]["skills"], [])
