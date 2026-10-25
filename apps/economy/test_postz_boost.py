"""Boost a post (⚡ buys a labelled day near the top of the feed) and the 1 ⚡ post floor."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.catalog import (BOOST_ENERGY, BOOST_HOURS, BOOST_SLOTS, POST_ENERGY_FLOOR)
from apps.economy.models import Post, Wallet, wallet_for
from apps.economy.postz import post_cost_cents

User = get_user_model()
FEED = "/api/economy/postz/"


class PostFloorTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("poster", "p@e.com", "pw-Long-enough-1")
        self.c = APIClient(); self.c.force_authenticate(self.u)

    def test_a_post_with_no_priced_skill_costs_the_floor(self):
        total, lines = post_cost_cents(self.u, [])
        self.assertEqual(total, POST_ENERGY_FLOOR)
        self.assertEqual(lines[-1]["skill"], "Posting")

    def test_submissions_that_refuse_when_short_are_not_floored(self):
        self.assertEqual(post_cost_cents(self.u, [], floor=0)[0], 0)

    def test_creating_one_charges_the_floor_and_the_quote_matches(self):
        Wallet.objects.update_or_create(user=self.u, defaults={"energy": 5})
        self.assertEqual(self.c.get(FEED + "cost/").json()["cost"]["amount"], POST_ENERGY_FLOOR)
        r = self.c.post(FEED, {"title": "hello"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(wallet_for(self.u).energy, 5 - POST_ENERGY_FLOOR)

    def test_it_is_never_a_wall(self):
        Wallet.objects.update_or_create(user=self.u, defaults={"energy": 0})
        self.assertEqual(self.c.post(FEED, {"title": "broke but posting"}, format="json").status_code, 201)
        self.assertEqual(wallet_for(self.u).energy, 0)


class BoostTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("poster", "p@e.com", "pw-Long-enough-1")
        self.o = User.objects.create_user("other", "o@e.com", "pw-Long-enough-1")
        self.c = APIClient(); self.c.force_authenticate(self.u)
        Wallet.objects.update_or_create(user=self.u, defaults={"energy": BOOST_ENERGY * 3})
        self.p = Post.objects.create(author=self.u, title="mine", visibility="public")

    def url(self, p=None):
        return f"{FEED}{(p or self.p).id}/boost/"

    def test_the_price_and_what_it_buys_are_quoted_first(self):
        q = self.c.get(self.url()).json()
        self.assertEqual((q["cost_energy"], q["hours"], q["allowed"]), (BOOST_ENERGY, BOOST_HOURS, True))
        self.assertIn("does not change ratings", q["what_you_get"])

    def test_boosting_charges_once_and_marks_the_post(self):
        r = self.c.post(self.url(), {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(wallet_for(self.u).energy, BOOST_ENERGY * 2)
        self.p.refresh_from_db()
        self.assertGreater(self.p.boosted_until, timezone.now() + timedelta(hours=BOOST_HOURS - 1))

    def test_without_the_energy_nothing_happens(self):
        Wallet.objects.filter(user=self.u).update(energy=BOOST_ENERGY - 1)
        r = self.c.post(self.url(), {}, format="json")
        self.assertEqual(r.status_code, 402)
        self.p.refresh_from_db()
        self.assertIsNone(self.p.boosted_until)
        self.assertEqual(wallet_for(self.u).energy, BOOST_ENERGY - 1)

    def test_only_your_own_public_post(self):
        theirs = Post.objects.create(author=self.o, title="theirs", visibility="public")
        self.assertEqual(self.c.post(self.url(theirs), {}, format="json").status_code, 404)
        priv = Post.objects.create(author=self.u, title="draft", visibility="private")
        r = self.c.post(self.url(priv), {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(wallet_for(self.u).energy, BOOST_ENERGY * 3)

    def test_it_cannot_be_stacked_without_end(self):
        for _ in range(3):
            self.c.post(self.url(), {}, format="json")
        self.p.refresh_from_db()
        self.assertLessEqual(self.p.boosted_until, timezone.now() + timedelta(hours=73))
        self.assertEqual(self.c.post(self.url(), {}, format="json").status_code, 400)

    def test_boosted_posts_lead_the_feed_labelled_and_only_a_few(self):
        mine = [Post.objects.create(author=self.u, title=f"b{i}", visibility="public",
                                    boosted_until=timezone.now() + timedelta(hours=i + 1))
                for i in range(BOOST_SLOTS + 2)]
        plain = Post.objects.create(author=self.o, title="plain", visibility="public")
        posts = self.c.get(FEED + "?sort=new").json()["posts"]
        lead = posts[:BOOST_SLOTS]
        self.assertTrue(all(d["boosted"] for d in lead))
        self.assertEqual({d["id"] for d in lead}, {p.id for p in mine[-BOOST_SLOTS:]})
        rest = {d["id"]: d for d in posts[BOOST_SLOTS:]}
        self.assertIn(plain.id, rest)
        self.assertFalse(rest[plain.id]["boosted"])

    def test_an_expired_boost_leads_nothing(self):
        Post.objects.filter(pk=self.p.pk).update(boosted_until=timezone.now() - timedelta(minutes=1))
        d = next(x for x in self.c.get(FEED).json()["posts"] if x["id"] == self.p.id)
        self.assertFalse(d["boosted"])


class BuyMoreSubmissionsTests(TestCase):
    def setUp(self):
        from apps.economy.catalog import (SUBMISSION_PACK, SUBMISSION_PACK_ENERGY, SUBMISSION_PACKS_MAX)
        self.pack, self.cost, self.max = SUBMISSION_PACK, SUBMISSION_PACK_ENERGY, SUBMISSION_PACKS_MAX
        self.u = User.objects.create_user("maker", "m@e.com", "pw-Long-enough-1")
        self.c = APIClient(); self.c.force_authenticate(self.u)
        Wallet.objects.update_or_create(user=self.u, defaults={"energy": self.cost * (self.max + 2)})

    def test_the_price_is_quoted_and_a_pack_raises_todays_cap_only(self):
        from apps.economy.models import submission_cap_for
        before = submission_cap_for(self.u)
        q = self.c.get("/api/economy/submissions/").json()
        self.assertEqual((q["buy"]["pack"], q["buy"]["cost_energy"]), (self.pack, self.cost))
        r = self.c.post("/api/economy/submissions/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(submission_cap_for(self.u), before + self.pack)
        self.assertEqual(wallet_for(self.u).energy, self.cost * (self.max + 1))

    def test_it_stops_at_the_daily_pack_limit_without_charging(self):
        for _ in range(self.max):
            self.assertEqual(self.c.post("/api/economy/submissions/", {}, format="json").status_code, 200)
        energy = wallet_for(self.u).energy
        self.assertEqual(self.c.post("/api/economy/submissions/", {}, format="json").status_code, 400)
        self.assertEqual(wallet_for(self.u).energy, energy)

    def test_without_the_energy_nothing_is_added(self):
        from apps.economy.models import submission_cap_for
        Wallet.objects.filter(user=self.u).update(energy=self.cost - 1)
        before = submission_cap_for(self.u)
        self.assertEqual(self.c.post("/api/economy/submissions/", {}, format="json").status_code, 402)
        self.assertEqual(submission_cap_for(self.u), before)
