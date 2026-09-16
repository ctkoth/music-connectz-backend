"""The member search is the heaviest read on the platform, and VybeZ fires it
from three text inputs.

Measured at 8.3 queries per member — 322 for a 39-member search — and every
keystroke in age-min, age-max or max-km triggered one, because `search` is a
useCallback in the effect's deps. Typing "25" was two searches, so 644
queries; filling all three numeric fields was nearer 2,500.

Six per-card reads did it: two rating medians, a FaceZ rating join, a
membership read, and the followers query THREE separate times — once for the
count, once inside `social_sources` to build the "Music ConnectZ" reach
source out of the same rows, and once more in `reach_median`, which rebuilds
that entire list from scratch.

`worn_badges_by_user` and `Audience` directly above them were already batched.
The numbers on the card were not.
"""
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from .models import (AttractivenessRating, Follow, OverallRating, Profile,
                     attractiveness_median, follow_counts, overall_median)

User = get_user_model()
PW = "hunter2hunter2"
CEILING = 25


class TheSearchDoesNotScaleWithItsResultsTests(TestCase):

    def build(self, n):
        users = []
        for i in range(n):
            u = User.objects.create_user(f"m{i}", f"m{i}@x.test", PW)
            Profile.objects.update_or_create(user=u, defaults={
                "display_name": f"M{i}", "gender": "male", "location": "Leeds"})
            users.append(u)
        # Real edges and ratings, or the batch is measured against empty
        # tables and proves nothing.
        for i, u in enumerate(users):
            Follow.objects.get_or_create(follower=users[(i + 1) % n], following=u)
            OverallRating.objects.get_or_create(rater=users[(i + 2) % n], target=u,
                                                defaults={"score": 8})
            AttractivenessRating.objects.get_or_create(rater=users[(i + 3) % n], target=u,
                                                       defaults={"score": 7})
        return users[0]

    def cost(self, n):
        me = self.build(n)
        c = APIClient()
        c.force_authenticate(me)
        c.get("/api/economy/members/")
        with CaptureQueriesContext(connection) as q:
            r = c.get("/api/economy/members/")
        self.assertEqual(r.status_code, 200)
        return len(q), len(r.data["members"])

    def test_five_members_and_fifty_cost_the_same(self):
        small, n_small = self.cost(5)
        User.objects.all().delete()
        big, n_big = self.cost(50)
        self.assertGreater(n_big, n_small)
        self.assertEqual(small, big,
                         f"{n_small} members cost {small} queries and {n_big} cost {big}")

    def test_it_stays_under_the_ceiling(self):
        n, members = self.cost(50)
        self.assertLessEqual(n, CEILING, f"{members} members cost {n} queries")


class TheNumbersAreStillRightTests(TestCase):
    """A batch that changes an answer is worse than the N+1 it replaced."""

    def setUp(self):
        self.a = User.objects.create_user("aa", "aa@x.test", PW)
        self.b = User.objects.create_user("bb", "bb@x.test", PW)
        self.c_ = User.objects.create_user("cc", "cc@x.test", PW)
        for u in (self.a, self.b, self.c_):
            Profile.objects.update_or_create(user=u, defaults={"display_name": u.username})
        self.client_ = APIClient()
        self.client_.force_authenticate(self.a)

    def cards(self):
        r = self.client_.get("/api/economy/members/")
        return {m["username"]: m for m in r.data["members"]}

    def test_the_batched_medians_match_the_per_user_helpers(self):
        for score in (4, 6, 9):
            u = User.objects.create_user(f"r{score}", f"r{score}@x.test", PW)
            OverallRating.objects.create(rater=u, target=self.b, score=score)
            AttractivenessRating.objects.create(rater=u, target=self.b, score=score - 1)
        card = self.cards()["bb"]
        self.assertEqual(card["overall"], overall_median(self.b))
        self.assertEqual(card["median"], attractiveness_median(self.b))

    def test_an_unrated_member_is_None_not_zero(self):
        """A fake number ends the question; an empty one invites a real
        rating — and `.get()` on a batch dict returns None for a missing key,
        which is exactly what the per-user helper returned. That is luck
        rather than design unless it is pinned."""
        self.assertIsNone(self.cards()["cc"]["overall"])
        self.assertIsNone(self.cards()["cc"]["median"])

    def test_followers_friends_and_fans_survive_the_batch(self):
        """friends is the mutual set and fans is one-way, so the batch has to
        hand back the SETS rather than four numbers — doing that arithmetic in
        two places is how the two come to disagree."""
        Follow.objects.create(follower=self.a, following=self.b)   # a -> b
        Follow.objects.create(follower=self.b, following=self.a)   # mutual
        Follow.objects.create(follower=self.c_, following=self.b)  # a fan of b
        card = self.cards()["bb"]
        plain = follow_counts(self.b)
        for key in ("followers", "following", "friends", "fans"):
            self.assertEqual(card[key], plain[key], key)

    def test_reach_median_is_unchanged_by_being_computed_from_the_list(self):
        from .models import reach_median
        self.assertEqual(self.cards()["bb"]["reach_median"], reach_median(self.b))

    def test_a_single_card_still_works_with_no_batch_at_all(self):
        """Public profiles and the member modal call `_profile_card` with
        nothing batched. One card's six queries is not worth a call site, but
        it has to still be right."""
        OverallRating.objects.create(rater=self.a, target=self.b, score=8)
        r = self.client_.get(f"/api/economy/public/members/{self.b.username}/")
        self.assertEqual(r.status_code, 200, r.content)
