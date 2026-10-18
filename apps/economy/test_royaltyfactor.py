from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from . import royaltyfactor as rf
from .models import (ItemRating, ListenProgress, Playlist, PlaylistItem, Post, RoyaltyEntry,
                     SkillRating, TakeScore, profile_for)
from .playlistz import accrue_playlist_royalties_for_date

User = get_user_model()


def mk(name):
    return User.objects.create_user(name, f"{name}@e.com", "pw-Long-enough-1")


class CurveTests(TestCase):
    def test_full_at_seven_floor_at_one_and_unrated_is_neutral(self):
        self.assertEqual(rf.curve(10), 1.0)
        self.assertEqual(rf.curve(7), 1.0)
        self.assertEqual(rf.curve(1), rf.FLOOR)
        self.assertEqual(rf.curve(None), 1.0)
        self.assertTrue(rf.FLOOR < rf.curve(3) < rf.curve(5) < 1.0)          # worse earns less, monotonically
        self.assertGreater(rf.FLOOR, 0)                                       # never to zero

    def test_no_bonus_above_the_full_rate(self):
        self.assertEqual(rf.curve(10), rf.curve(7))


class BadRatingsEarnLessTests(TestCase):
    def setUp(self):
        self.listener = mk("lstn")
        self.pl = Playlist.objects.create(owner=self.listener, title="Mix", visibility="public")
        self.fans = [mk(f"fan{i}") for i in range(40)]
        self.raters = [mk(f"rt{i}") for i in range(6)]

    def _track(self, author, title, rating=None, n_raters=6):
        post = Post.objects.create(author=author, title=title, visibility="public")
        PlaylistItem.objects.create(playlist=self.pl, kind=PlaylistItem.KIND_POST, post=post,
                                    position=post.id, title=title, added_by=self.listener)
        for f in self.fans:
            ListenProgress.objects.create(user=f, item_id=f"post:{post.id}", seconds=30)
        if rating is not None:
            for r in self.raters[:n_raters]:
                ItemRating.objects.create(user=r, item_id=f"post:{post.id}", score=rating)
        return post

    def _earned(self, author):
        return sum(e.amount_cents + e.tax_cents for e in RoyaltyEntry.objects.filter(user=author))

    def _run(self, *authors_posts):
        for a, title, rating, n in authors_posts:
            self._track(a, title, rating, n)
        accrue_playlist_royalties_for_date(timezone.now().date())

    def test_a_badly_rated_track_earns_less_than_a_good_or_unrated_one(self):
        good, bad, none = mk("good"), mk("bad"), mk("none")
        self._run((good, "g", 9, 6), (bad, "b", 2, 6), (none, "n", None, 0))
        self.assertEqual(self._earned(good), self._earned(none))              # good = full rate = unrated
        self.assertLess(self._earned(bad), self._earned(good))
        self.assertGreater(self._earned(bad), 0)                              # never zero

    def test_too_few_raters_changes_nothing(self):
        few, none = mk("few"), mk("none2")
        self._run((few, "f", 1, 4), (none, "n2", None, 0))                    # four one-star ratings: not enough
        self.assertEqual(self._earned(few), self._earned(none))

    def test_the_credited_do_not_count_as_raters(self):
        a = mk("authr")
        post = Post.objects.create(author=a, title="x", visibility="public")
        for r in self.raters:
            ItemRating.objects.create(user=r, item_id=f"post:{post.id}", score=1)
        ItemRating.objects.create(user=a, item_id=f"post:{post.id}", score=10)
        self.assertEqual(rf.post_rating(post), (1, 6))

    def test_the_statement_before_the_payout_matches_the_payout(self):
        a = mk("said")
        post = self._track(a, "s", 2, 6)
        c = APIClient(); c.force_authenticate(a)
        d = c.get("/api/economy/royalty/ratings/").data
        row = next(p for p in d["posts"] if p["post_id"] == post.id)
        self.assertTrue(row["applied"])
        self.assertEqual(row["factor"], rf.curve(2))
        self.assertIn(str(rf.FULL_AT), d["rule"])


class CoachCountsForSkillzTests(TestCase):
    def setUp(self):
        self.u = mk("skiller")
        self.c = APIClient(); self.c.force_authenticate(self.u)
        for i in range(4):
            SkillRating.objects.create(rater=mk(f"sr{i}"), subject=self.u, skill="Vocalist", item_id=f"post:{i}", score=4)

    def _takes(self, score, n=5, app="singz"):
        for _ in range(n):
            TakeScore.objects.create(user=self.u, app_key=app, scores={"pitch": score}, overall=score)

    def test_off_by_default_so_the_coach_changes_nothing(self):
        self._takes(10)
        rating, detail = rf.blended_skill_rating(self.u, "Vocalist")
        self.assertEqual(rating, 4)
        self.assertIsNone(detail["coach"])

    def test_opting_in_blends_the_coach_as_a_few_votes_and_says_so(self):
        self._takes(10)
        r = self.c.post("/api/economy/skillz-coach/", {"enabled": True}, format="json")
        self.assertTrue(r.data["enabled"])
        self.assertIn("both ways", r.data["note"])
        rating, detail = rf.blended_skill_rating(User.objects.get(pk=self.u.pk), "Vocalist")
        self.assertEqual(rating, round((4 * 4 + 10 * rf.COACH_VOTES) / (4 + rf.COACH_VOTES), 1))
        self.assertTrue(detail["coach"]["used"])

    def test_it_cuts_both_ways(self):
        self._takes(1)
        self.c.post("/api/economy/skillz-coach/", {"enabled": True}, format="json")
        rating, _ = rf.blended_skill_rating(User.objects.get(pk=self.u.pk), "Vocalist")
        self.assertLess(rating, 4)

    def test_too_few_takes_is_not_a_coach_reading(self):
        self._takes(10, n=rf.MIN_COACH_TAKES - 1)
        self.c.post("/api/economy/skillz-coach/", {"enabled": True}, format="json")
        rating, detail = rf.blended_skill_rating(User.objects.get(pk=self.u.pk), "Vocalist")
        self.assertEqual(rating, 4)
        self.assertFalse(detail["coach"]["used"])

    def test_a_skill_with_no_coach_is_untouched(self):
        for i in range(3):
            SkillRating.objects.create(rater=mk(f"dr{i}"), subject=self.u, skill="Designer", item_id=f"post:{i}", score=5)
        self._takes(10)
        self.c.post("/api/economy/skillz-coach/", {"enabled": True}, format="json")
        rating, detail = rf.blended_skill_rating(User.objects.get(pk=self.u.pk), "Designer")
        self.assertEqual(rating, 5)
        self.assertIsNone(detail["coach"])

    def test_it_needs_an_explicit_yes_or_no(self):
        self.assertEqual(self.c.post("/api/economy/skillz-coach/", {}, format="json").status_code, 400)
        self.assertFalse(profile_for(self.u).coach_counts_for_skillz)

    def test_the_skillz_list_shows_when_the_coach_is_part_of_a_rating(self):
        from .ratez import skills_of
        self._takes(10)
        self.c.post("/api/economy/skillz-coach/", {"enabled": True}, format="json")
        row = next(s for s in skills_of(User.objects.get(pk=self.u.pk)) if s["skill"] == "Vocalist")
        self.assertTrue(row["coach"]["used"])
