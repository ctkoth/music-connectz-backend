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


# ---- InVenTorieZ: what it's worth, and the AI's read ----
import json
import shutil
import tempfile
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from .models import InventoryAIRating, Upload, wallet_for

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
       b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82")


class WhatItIsWorth(Fixture):
    def test_an_exact_price_or_a_level_never_both_and_junk_is_dropped(self):
        out = clean_inventory([
            {"name": "Mic", "price": "$1,249.50"},
            {"name": "Cable", "price_level": 2},
            {"name": "Both", "price_cents": 5000, "price_level": 9},
            {"name": "Junk", "price": "lots", "price_level": 11},
            {"name": "Typo", "price_cents": 10 ** 12},
        ])
        by = {x["name"]: x for x in out}
        self.assertEqual(by["Mic"]["price_cents"], 124950)
        self.assertEqual(by["Cable"]["price_level"], 2)
        self.assertEqual(by["Both"], {**by["Both"], "price_cents": 5000})
        self.assertNotIn("price_level", by["Both"])
        for n in ("Junk", "Typo"):
            self.assertFalse({"price_cents", "price_level"} & set(by[n]))

    def test_the_total_adds_prices_and_never_turns_levels_into_dollars(self):
        s = inventoryz.value_summary([{"price_cents": 100}, {"price_cents": 250}, {"price_level": 3}, {"price_level": 8}, {}])
        self.assertEqual(s, {"total_cents": 350, "priced": 2, "levels": 2, "level_avg": 5.5, "unvalued": 1})

    def priced(self):
        p = profile_for(self.owner)
        p.inventory = clean_inventory([{"name": "Guitar", "kind": "instrument", "where": "home", "price": "900"}])
        p.save()
        return p

    def test_members_see_the_worth_by_default_and_the_logged_out_page_never_does(self):
        self.priced()
        d = self.get()
        self.assertEqual(d["items"][0]["price_cents"], 90000)
        self.assertEqual(d["value"]["total_cents"], 90000)
        public = APIClient().get("/api/economy/public/members/owner/")
        self.assertEqual(public.status_code, 200)
        self.assertEqual(public.data["inventory"][0]["name"], "Guitar")
        self.assertNotIn("price_cents", public.data["inventory"][0])

    def test_private_worth_is_hidden_from_members_but_the_piece_is_not(self):
        p = self.priced()
        p.visibility = {"inventory_value": ["private"]}
        p.save()
        d = self.get()
        self.assertEqual(d["items"][0]["name"], "Guitar")
        self.assertNotIn("price_cents", d["items"][0])
        self.assertIsNone(d["value"])
        mine = APIClient()
        mine.force_authenticate(self.owner)
        self.assertEqual(mine.get("/api/economy/inventoryz/").data["items"][0]["price_cents"], 90000)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class TheAIRatesWhatThePhotoShows(Fixture):
    def setUp(self):
        super().setUp()
        self.me = APIClient()
        self.me.force_authenticate(self.owner)

    def tearDown(self):
        from django.conf import settings
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)

    def photo(self, user=None):
        u = Upload.objects.create(user=user or self.owner, name="amp.png", content_type="image/png", size_bytes=len(PNG),
                                  file=SimpleUploadedFile("amp.png", PNG, content_type="image/png"))
        return f"https://admin.example/api/economy/media/{u.id}/{u.file.name.rsplit('/', 1)[-1]}"

    def kit(self, *pieces):
        p = profile_for(self.owner)
        p.inventory = clean_inventory(list(pieces))
        p.save()

    def run_ai(self, reply, body):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"candidates": [{"content": {"parts": [{"text": json.dumps(reply)}]}}]}
        with patch("apps.economy.gemini.generate_content", return_value=(resp, ["m"])) as g, \
                patch("apps.economy.vocalcoach._key", return_value="k"):
            r = self.me.post("/api/economy/inventoryz/ai/", body, format="json")
        return r, g

    def test_it_rates_the_photographed_pieces_and_the_set_and_skips_a_name_with_no_photo(self):
        self.kit({"name": "Amp", "kind": "outboard", "photo": self.photo()},
                 {"name": "Jacket", "kind": "clothing", "photo": self.photo()},
                 {"name": "Mystery", "kind": "other"})
        r, g = self.run_ai({"pieces": [{"n": 1, "score": 8, "why": "clean"}, {"n": 2, "score": 6, "why": "worn cuffs"}],
                            "set": {"score": 7, "why": "coherent"}}, {"names": [], "together": True})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual([x["score"] for x in r.data["rated"]], [8, 6])
        self.assertEqual(r.data["set"]["score"], 7)
        self.assertEqual(r.data["skipped"][0]["name"], "Mystery")
        self.assertTrue(r.data["charged"])
        prompt = g.call_args[0][1]["contents"][0]["parts"][0]["text"]
        self.assertIn("NEVER estimate a price", prompt)
        self.assertEqual(len(g.call_args[0][1]["contents"][0]["parts"]), 3)   # the prompt and two photos

    def test_hidden_until_the_owner_shows_it(self):
        self.kit({"name": "Amp", "kind": "outboard", "photo": self.photo()})
        self.run_ai({"pieces": [{"n": 1, "score": 9, "why": "spotless"}]}, {"names": ["Amp"]})
        self.assertIsNone(self.get()["items"][0]["ai"])
        self.assertEqual(self.me.get("/api/economy/inventoryz/").data["items"][0]["ai"]["score"], 9)
        self.assertEqual(self.me.patch("/api/economy/inventoryz/ai/", {"item": "Amp", "shown": True}, format="json").status_code, 200)
        self.assertEqual(self.get()["items"][0]["ai"]["score"], 9)

    def test_nothing_rated_is_nothing_charged(self):
        self.kit({"name": "Amp", "kind": "outboard", "photo": self.photo()})
        before = wallet_for(self.owner).promptz
        r, _ = self.run_ai({"pieces": [{"n": 1, "score": None, "why": "can't see it"}]}, {"names": ["Amp"]})
        self.assertFalse(r.data["charged"])
        self.assertIn("nothing was charged", r.data["detail"])
        self.assertEqual(wallet_for(self.owner).promptz, before)
        self.assertFalse(InventoryAIRating.objects.exists())

    def test_it_never_reads_somebody_elses_upload_or_a_typed_address(self):
        self.kit({"name": "Stolen", "kind": "other", "photo": self.photo(user=self.rater)},
                 {"name": "Linked", "kind": "other", "photo": "https://example.com/x.png"})
        r, g = self.run_ai({"pieces": []}, {"names": []})
        self.assertEqual(r.status_code, 400)
        g.assert_not_called()

    def test_a_new_photo_marks_the_reading_as_of_an_older_one(self):
        self.kit({"name": "Amp", "kind": "outboard", "photo": self.photo()})
        self.run_ai({"pieces": [{"n": 1, "score": 7, "why": "ok"}]}, {"names": ["Amp"]})
        self.kit({"name": "Amp", "kind": "outboard", "photo": self.photo()})
        self.assertTrue(self.me.get("/api/economy/inventoryz/").data["items"][0]["ai"]["older_photo"])

    def test_the_price_is_stated_before_the_run(self):
        d = self.me.get("/api/economy/inventoryz/").data
        self.assertIn("cost_cents", d["ai"])
        self.assertIn("never guesses a price", d["ai"]["note"])
        self.assertNotIn("ai", self.get())          # another member's view carries no run button
