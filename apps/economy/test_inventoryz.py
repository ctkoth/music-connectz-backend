"""InventoryZ: the profile inventory, rated piece by piece and in total."""
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from . import inventoryz
from .models import ItemRating, profile_for
from .social import clean_inventory

User = get_user_model()


def stock(user, *names, kind="instrument"):
    p = profile_for(user)
    p.inventory = clean_inventory([{"name": n, "kind": kind} for n in names])
    p.save()


class Fixture(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner", password="pw")
        self.rater = User.objects.create_user("rater", password="pw")
        self.c = APIClient()
        self.c.force_authenticate(self.rater)

    def get(self, who="owner"):
        return self.c.get(f"/api/economy/inventoryz/?username={who}").data

    def rate(self, item, score, as_user=None):
        c = self.c
        if as_user:
            c = APIClient()
            c.force_authenticate(as_user)
        return c.post("/api/economy/social/rate/", {"item": item, "score": score}, format="json")


class TheInventoryIsTheProfileOne(Fixture):
    def test_clothes_are_a_kind_and_a_photo_is_kept_only_when_safe(self):
        out = clean_inventory([
            {"name": "Stage jacket", "kind": "clothing", "photo": "/api/economy/media/3/jacket.jpg"},
            {"name": "Hat", "kind": "clothing", "photo": "javascript:alert(1)"},
        ])
        self.assertEqual(out[0]["kind"], "clothing")
        self.assertEqual(out[0]["photo"], "/api/economy/media/3/jacket.jpg")
        self.assertNotIn("photo", out[1])

    def test_pieces_come_from_the_profile(self):
        stock(self.owner, "Fender Jazz Bass", "SM58")
        d = self.get()
        self.assertEqual([i["name"] for i in d["items"]], ["Fender Jazz Bass", "SM58"])
        self.assertEqual(d["items"][0]["item_id"], f"gear:{self.owner.id}:fender-jazz-bass")
        self.assertIsNone(d["items"][0]["rating"])
        self.assertTrue(d["items"][0]["can_rate"])
        self.assertIn("rating_reward", d)


class Rating(Fixture):
    def test_each_piece_and_the_total(self):
        stock(self.owner, "Bass", "Mic")
        bass, mic = (i["item_id"] for i in self.get()["items"])
        others = [User.objects.create_user(f"r{i}", password="pw") for i in range(3)]
        self.assertEqual(self.rate(bass, 8).status_code, 200)
        d = self.get()
        self.assertEqual(d["items"][0]["rating"], 8)
        self.assertEqual(d["items"][0]["my_rating"], 8)
        self.assertIsNone(d["total"]["rating"], "one rating is not a total")
        self.rate(bass, 6, others[0])
        self.rate(mic, 4, others[1])
        d = self.get()
        self.assertEqual(d["total"]["count"], 3)
        self.assertEqual(d["total"]["rating"], 6)
        self.assertEqual(d["total"]["pieces_rated"], 2)

    def test_the_owner_cannot_rate_their_own_kit(self):
        stock(self.owner, "Bass")
        key = inventoryz.item_key(self.owner.id, "Bass")
        r = self.rate(key, 10, self.owner)
        self.assertEqual(r.status_code, 403)
        self.assertFalse(ItemRating.objects.filter(item_id=key).exists())
        c = APIClient()
        c.force_authenticate(self.owner)
        mine = c.get("/api/economy/inventoryz/").data
        self.assertFalse(mine["items"][0]["can_rate"])
        self.assertIn("rename_note", mine)

    def test_a_removed_piece_takes_its_ratings_out_of_the_total(self):
        stock(self.owner, "Bass", "Mic")
        for i, u in enumerate(User.objects.create_user(f"x{i}", password="pw") for i in range(3)):
            self.rate(inventoryz.item_key(self.owner.id, "Bass"), 9, u)
        self.assertEqual(self.get()["total"]["rating"], 9)
        stock(self.owner, "Mic")
        self.assertIsNone(self.get()["total"]["rating"])

    def test_queries_do_not_grow_with_pieces(self):
        stock(self.owner, "A")
        self.get()
        with CaptureQueriesContext(connection) as one:
            self.get()
        stock(self.owner, *[f"Piece {i}" for i in range(20)])
        with CaptureQueriesContext(connection) as many:
            self.get()
        self.assertEqual(len(one), len(many))

    def test_it_never_moves_a_measurement(self):
        # A taste rating of somebody's kit must not reach skills, royalties or prices.
        import pathlib
        here = pathlib.Path(__file__).parent
        for f in here.glob("*.py"):
            if f.name in ("inventoryz.py", "models.py") or f.name.startswith("test_"):
                continue
            self.assertNotIn('"gear:', f.read_text(), f.name)
