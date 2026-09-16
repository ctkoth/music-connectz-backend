"""What one feed load costs, and why that number is the one to watch.

The feed re-polls every 30 seconds from every open tab, so its query count is
not a page-load cost — it is a standing load that every idle member
contributes to forever.

Measured before this: 108 queries for 50 posts, about 2 per card. Three
per-card counts were doing it, and the batching pattern was already beside
them — `_reactions_for`, the CollabDeal count and `take_state_for` had each
been collapsed into one query, and `shares`, `joins` and `rating` were missed.

`joins` is the one worth remembering: it sits behind `if p.visibility ==
"restricted"`, so a feed of public posts measures TWO N+1s and a real feed
has three. A benchmark built from convenient data hides the case that costs.
"""
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from .models import ItemRating, Post, PostJoin, PostShare

User = get_user_model()
PW = "hunter2hunter2"

# Fixed cost: the member's own wallet, membership, price and cap, plus the
# handful of aggregates. Headroom over the measured 11 so an honest extra
# read is not a failing test, but nowhere near enough to hide an N+1.
CEILING = 20


class TheFeedDoesNotScaleWithItsOwnLengthTests(TestCase):

    def build(self, n_posts, n_authors=5, restricted_every=3, rate_every=2):
        authors = [User.objects.create_user(f"a{i}", f"a{i}@x.test", PW)
                   for i in range(n_authors)]
        rater = User.objects.create_user("rater", "r@x.test", PW)
        for i in range(n_posts):
            p = Post.objects.create(
                author=authors[i % n_authors], title=f"post {i}",
                description="something",
                # The case a public-only benchmark misses.
                visibility="restricted" if i % restricted_every == 0 else "public")
            PostShare.objects.create(post=p, user=rater)
            if i % restricted_every == 0:
                PostJoin.objects.create(post=p, user=rater)
            if i % rate_every == 0:
                ItemRating.objects.create(user=rater, item_id=f"post:{p.id}", score=7)
        return authors[0]

    def cost(self, n):
        me = self.build(n)
        c = APIClient()
        c.force_authenticate(me)
        c.get("/api/economy/postz/")      # warm per-process caches
        with CaptureQueriesContext(connection) as q:
            r = c.get("/api/economy/postz/")
        self.assertEqual(r.status_code, 200)
        return len(q), len(r.data["posts"])

    def test_one_post_and_sixty_cost_the_same(self):
        small, n_small = self.cost(1)
        Post.objects.all().delete()
        User.objects.all().delete()
        big, n_big = self.cost(60)
        self.assertGreater(n_big, n_small)
        self.assertEqual(
            small, big,
            f"{n_small} posts cost {small} queries and {n_big} cost {big} — "
            "the feed is scaling with its own length again")

    def test_it_stays_under_the_ceiling(self):
        n, posts = self.cost(60)
        self.assertLessEqual(n, CEILING, f"{posts} posts cost {n} queries")

    def test_restricted_posts_do_not_add_a_query_each(self):
        """`joins` was counted per card behind a `restricted` check, so it was
        invisible to any benchmark built from public posts."""
        me = self.build(40, restricted_every=1)     # every post restricted
        c = APIClient()
        c.force_authenticate(me)
        c.get("/api/economy/postz/")
        with CaptureQueriesContext(connection) as q:
            c.get("/api/economy/postz/")
        self.assertLessEqual(len(q), CEILING)


class TheNumbersAreStillRightTests(TestCase):
    """Batching that changes an answer is worse than the N+1 it replaced."""

    def setUp(self):
        self.author = User.objects.create_user("auth", "au@x.test", PW)
        self.rater = User.objects.create_user("rat", "ra@x.test", PW)
        self.c = APIClient()
        self.c.force_authenticate(self.author)

    def feed(self):
        return {p["id"]: p for p in self.c.get("/api/economy/postz/").data["posts"]}

    def test_shares_are_counted_per_post_not_pooled(self):
        a = Post.objects.create(author=self.author, title="a")
        b = Post.objects.create(author=self.author, title="b")
        PostShare.objects.create(post=a, user=self.rater)
        PostShare.objects.create(post=a, user=self.author)
        PostShare.objects.create(post=b, user=self.rater)
        rows = self.feed()
        self.assertEqual(rows[a.id]["shares"], 2)
        self.assertEqual(rows[b.id]["shares"], 1)

    def test_a_post_nobody_shared_reads_zero_not_missing(self):
        p = Post.objects.create(author=self.author, title="lonely")
        self.assertEqual(self.feed()[p.id]["shares"], 0)

    def test_the_median_rating_matches_the_per_post_helper(self):
        from .models import item_rating_median
        p = Post.objects.create(author=self.author, title="rated")
        for score in (4, 6, 9):
            u = User.objects.create_user(f"u{score}", f"u{score}@x.test", PW)
            ItemRating.objects.create(user=u, item_id=f"post:{p.id}", score=score)
        self.assertEqual(self.feed()[p.id]["rating"],
                         item_rating_median(f"post:{p.id}"))

    def test_an_unrated_post_is_None_not_zero(self):
        """A fake number ends the question; an empty one invites a real
        rating. The substance rule, and the batch must not turn one into the
        other by defaulting a missing key to 0."""
        p = Post.objects.create(author=self.author, title="unrated")
        self.assertIsNone(self.feed()[p.id]["rating"])

    def test_joins_only_count_on_a_restricted_post(self):
        pub = Post.objects.create(author=self.author, title="pub", visibility="public")
        res = Post.objects.create(author=self.author, title="res", visibility="restricted")
        PostJoin.objects.create(post=pub, user=self.rater)
        PostJoin.objects.create(post=res, user=self.rater)
        rows = self.feed()
        self.assertEqual(rows[pub.id]["joins"], 0)
        self.assertEqual(rows[res.id]["joins"], 1)

    def test_creating_a_post_still_works_without_the_batch(self):
        """Create and edit call `_post_dict` with no batched counts — one
        extra query on one post is not worth a batching call site, but the
        None/_UNSET defaults have to still produce the right answer.

        (`GET /api/economy/postz/<id>/` is deliberately NOT this shape: it is
        the logged-out public card, which carries far less.)"""
        r = self.c.post("/api/economy/postz/", {"title": "fresh"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["shares"], 0)
        self.assertEqual(r.data["joins"], 0)
        self.assertIsNone(r.data["rating"])
