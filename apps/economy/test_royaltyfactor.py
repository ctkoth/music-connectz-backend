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
    def test_it_is_the_median_minus_five_times_ten_percent(self):
        self.assertEqual(rf.curve(5), 1.0)
        self.assertEqual(rf.curve(10), 1.5)
        self.assertEqual(rf.curve(1), 0.6)
        self.assertEqual(rf.curve(7), 1.2)
        self.assertEqual(rf.curve(3), 0.8)
        self.assertEqual(rf.curve(None), 1.0)                                 # unrated is neutral
        self.assertEqual((rf.LOWEST, rf.HIGHEST), (0.6, 1.5))

    def test_it_is_monotonic_and_never_zero(self):
        vals = [rf.curve(m) for m in range(1, 11)]
        self.assertEqual(vals, sorted(vals))
        self.assertGreater(min(vals), 0)

    def test_out_of_range_input_is_clamped_not_extrapolated(self):
        self.assertEqual(rf.curve(99), rf.HIGHEST)
        self.assertEqual(rf.curve(-3), rf.LOWEST)


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

    def test_better_rated_earns_more_and_worse_rated_earns_less_than_unrated(self):
        good, bad, none, mid = mk("good"), mk("bad"), mk("none"), mk("mid")
        self._run((good, "g", 9, 6), (bad, "b", 2, 6), (none, "n", None, 0), (mid, "m", 5, 6))
        self.assertEqual(self._earned(mid), self._earned(none))               # a 5 is the base rate
        self.assertGreater(self._earned(good), self._earned(none))
        self.assertLess(self._earned(bad), self._earned(none))
        self.assertGreater(self._earned(bad), 0)                              # never zero
        base = self._earned(none)
        self.assertAlmostEqual(self._earned(good) / base, rf.curve(9), delta=0.08)
        self.assertAlmostEqual(self._earned(bad) / base, rf.curve(2), delta=0.08)

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
        self.assertIn("minus 5", d["rule"])
        self.assertEqual((d["lowest_pct"], d["highest_pct"]), (60, 150))


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


class BattleCoachTests(TestCase):
    def _battle(self):
        from .models import Battle, BattleEntry
        a, b = mk("ba"), mk("bb")
        bt = Battle.objects.create(host=a, opponent=b, title="t", mode="1v1", status="open", kind="freestyle")
        ea = BattleEntry.objects.create(battle=bt, user=a, title="a")
        eb = BattleEntry.objects.create(battle=bt, user=b, title="b")
        for u in [mk(f"j{i}") for i in range(3)]:
            ItemRating.objects.create(user=u, item_id=ea.item_key, score=6)
            ItemRating.objects.create(user=u, item_id=eb.item_key, score=7)
        return bt, a, b

    def test_opt_in_coach_can_flip_the_winner(self):
        from .battlez import scoreboard
        bt, a, b = self._battle()
        self.assertEqual(scoreboard(bt)["host"]["median"], 6)
        TakeScore.objects.create(user=a, app_key="rapz", overall=10)
        self.assertEqual(scoreboard(bt)["host"]["median"], 6)          # not opted in: nothing changes
        p = profile_for(a); p.coach_counts_for_skillz = True; p.save()
        board = scoreboard(bt)
        self.assertGreater(board["host"]["median"], board["opponent"]["median"])
        self.assertEqual(board["host"]["coach"]["takes"], 1)


class GhostWriterSkillTests(TestCase):
    """Lyrics for a sung or rapped track are rated under the form they served, not as a performance."""

    def _post(self, skills_used, slot="text"):
        a, w = mk("gwauthor"), mk("gwriter")
        post = Post.objects.create(author=a, title="t", visibility="public", skills_used=skills_used,
                                   contributors=[{"username": "gwauthor", "slot": "audio"},
                                                 {"username": "gwriter", "slot": slot}])
        return post, a, w

    def test_a_ghostwriter_on_a_rap_is_credited_for_writing_rapping(self):
        from .models import skills_for_post
        post, a, w = self._post(["Rapping"])
        pairs = {(u.username, s) for u, s in skills_for_post(post)}
        self.assertIn(("gwriter", "Ghost Writer · Rapping"), pairs)
        self.assertIn(("gwauthor", "Independent Artist"), pairs)            # the performer is unchanged
        self.assertNotIn(("gwriter", "Rapping"), pairs)                     # never rated AS the rapper

    def test_with_no_performance_skill_it_stays_plain_ghost_writer(self):
        from .models import skills_for_post
        post, a, w = self._post(["Poetry"])
        self.assertIn(("gwriter", "Ghost Writer"), {(u.username, s) for u, s in skills_for_post(post)})

    def test_only_the_text_slot_is_a_ghostwriter(self):
        from .models import skills_for_post
        post, a, w = self._post(["Rapping"], slot="video")
        self.assertIn(("gwriter", "Videographer"), {(u.username, s) for u, s in skills_for_post(post)})


class RoyaltiesNeverOweTests(TestCase):
    """Corey: (median − 5) × 10% on top of the base. A 4 or lower earns LESS, never owes."""

    def test_every_rating_is_a_positive_factor_and_four_or_less_is_below_the_base(self):
        for m in range(1, 5):
            self.assertGreater(rf.curve(m), 0, m)
            self.assertLess(rf.curve(m), 1.0, m)
        self.assertEqual(rf.curve(5), 1.0)
        self.assertGreater(rf.curve(6), 1.0)

    def test_no_median_however_wild_goes_below_the_floor(self):
        for m in (-50, 0, 0.5, 1):
            self.assertEqual(rf.curve(m), rf.LOWEST)
        self.assertGreater(rf.LOWEST, 0)

    def test_a_low_rated_track_never_writes_a_negative_royalty_row(self):
        t = BadRatingsEarnLessTests("test_better_rated_earns_more_and_worse_rated_earns_less_than_unrated")
        t.setUp()
        a = mk("lowauth")
        t._run((a, "low", 1, 6))
        from .models import RoyaltyEntry
        rows = list(RoyaltyEntry.objects.filter(user=a))
        self.assertTrue(rows)
        self.assertTrue(all(r.amount_cents > 0 and r.tax_cents >= 0 for r in rows))


class DerivedRoyaltyTests(TestCase):
    """A cover or remix pays the original's author a cut of what it earns; never new money."""

    def _world(self, cover_rating=None):
        """One harness: an ordinary post and a cover of somebody's song, same plays, one accrual."""
        t = BadRatingsEarnLessTests("test_better_rated_earns_more_and_worse_rated_earns_less_than_unrated")
        t.setUp()
        orig, cov, plain = mk("origauth"), mk("coverer"), mk("plainposter")
        song = Post.objects.create(author=orig, title="Song", visibility="public")
        t._track(plain, "plain", None, 0)
        post = t._track(cov, "My cover", cover_rating, 6 if cover_rating else 0)
        post.derived = {"id": song.id, "kind": "cover", "title": "Song", "author": "origauth"}
        post.save(update_fields=["derived"])
        accrue_playlist_royalties_for_date(timezone.now().date())
        earned = lambda u: sum(e.amount_cents + e.tax_cents for e in RoyaltyEntry.objects.filter(user=u))
        return earned(orig), earned(cov), earned(plain)

    def test_the_original_gets_twenty_percent_and_nothing_is_created(self):
        from .derivedroyalty import DERIVED_ROYALTY_PCT
        o, c, plain = self._world()
        self.assertGreater(o, 0)
        self.assertEqual(o + c, plain)                                         # a split, never new money
        self.assertAlmostEqual(o / plain, DERIVED_ROYALTY_PCT / 100, delta=0.03)

    def test_a_poorly_rated_cover_pays_the_original_less_too(self):
        o, c, plain = self._world(cover_rating=2)
        self.assertLess(o + c, plain)
        self.assertGreater(o, 0)

    def test_no_original_no_cut_and_the_poster_never_pays_themselves(self):
        from .derivedroyalty import original_cut
        a = mk("self_cover")
        post = Post.objects.create(author=a, title="x", visibility="public",
                                   derived={"id": 1, "kind": "cover", "title": "t", "author": "self_cover"})
        self.assertEqual(original_cut(post, 100), (None, 0))
        post.derived = {"id": 1, "kind": "cover", "title": "t", "author": "deleted_user"}
        self.assertEqual(original_cut(post, 100), (None, 0))
        post.derived = {}
        self.assertEqual(original_cut(post, 100), (None, 0))

    def test_the_terms_are_served_before_posting(self):
        c = APIClient(); c.force_authenticate(mk("reader"))
        d = c.get("/api/economy/derivedz/").data
        self.assertEqual(d["pct"], 20)
        self.assertIn("20%", d["text"])
