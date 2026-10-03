from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import Post, PostSale, wallet_for


def client(u):
    c = APIClient(); c.force_authenticate(u); return c


class PostBuyTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user("seller", password="pw12345!x")
        self.buyer = User.objects.create_user("buyer", password="pw12345!x")
        self.post = Post.objects.create(author=self.seller, title="Track", visibility="public")

    def price(self, cents, who=None):
        return client(who or self.seller).post(
            "/api/economy/postz/", {"edit_id": self.post.id, "price_cents": cents}, format="json")

    def test_author_sets_price_and_it_is_on_the_card(self):
        r = self.price(500)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["price_cents"], 500)
        self.assertEqual(self.price(0).json()["price_cents"], 0)

    def test_price_bounds_and_owner_only(self):
        self.assertEqual(self.price(5).status_code, 400)
        self.assertEqual(self.price(10 ** 7).status_code, 400)
        self.assertIn(self.price(500, who=self.buyer).status_code, (403, 404))
        self.post.refresh_from_db(); self.assertIsNone(self.post.price_cents)

    def test_quote_then_buy_pays_seller(self):
        self.price(500)
        w = wallet_for(self.buyer); w.money_cents = 1000; w.save()
        q = client(self.buyer).get(f"/api/economy/postz/{self.post.id}/sale/").json()
        self.assertEqual((q["price_cents"], q["balance_cents"], q["bought"]), (500, 1000, False))
        self.assertEqual(q["fee_cents"] + q["creators_cents"], 500)
        r = client(self.buyer).post(f"/api/economy/postz/{self.post.id}/sale/")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(wallet_for(self.buyer).money_cents, 500)
        self.assertEqual(wallet_for(self.seller).money_cents, q["creators_cents"])
        # Second buy refused, not charged.
        self.assertEqual(client(self.buyer).post(f"/api/economy/postz/{self.post.id}/sale/").status_code, 400)
        self.assertEqual(wallet_for(self.buyer).money_cents, 500)

    def test_short_balance_charges_nothing(self):
        self.price(500)
        w = wallet_for(self.buyer); w.money_cents = 100; w.save()
        r = client(self.buyer).post(f"/api/economy/postz/{self.post.id}/sale/")
        self.assertEqual(r.status_code, 402)
        self.assertEqual(wallet_for(self.buyer).money_cents, 100)
        self.assertFalse(PostSale.objects.exists())

    def test_feed_marks_bought_in_one_query(self):
        self.price(500)
        PostSale.objects.create(post=self.post, buyer=self.buyer, price_cents=500)
        posts = client(self.buyer).get("/api/economy/postz/").json()
        posts = posts.get("posts", posts) if isinstance(posts, dict) else posts
        mine = [p for p in posts if p["id"] == self.post.id][0]
        self.assertTrue(mine["bought"])
        self.assertEqual(mine["price_cents"], 500)
