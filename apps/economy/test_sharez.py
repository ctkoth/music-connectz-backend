from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import MangaPage, SentenceWork, SharedItem


class ShareZTests(TestCase):
    def setUp(self):
        U = get_user_model()
        self.me, self.other = U.objects.create_user("maker", password="pw12345!x"), U.objects.create_user("fan", password="pw12345!x")
        self.c, self.o, self.anon = APIClient(), APIClient(), APIClient()
        self.c.force_authenticate(self.me); self.o.force_authenticate(self.other)
        self.piece = SentenceWork.objects.create(user=self.me, kind="poem", topic="rain", text="It rained.")
        self.page = MangaPage.objects.create(user=self.me, title="Ep 1", idea="x",
                                             panels=[{"n": 1, "dialogue": [{"who": "Ana", "line": "Hi"}], "image": ""}])

    def test_nothing_is_open_until_its_maker_shares_it(self):
        self.assertFalse(self.c.get("/api/economy/sharez/", {"kind": "sentence", "ref": self.piece.id}).data["shared"])
        self.assertEqual(self.o.post("/api/economy/sharez/", {"kind": "sentence", "ref": self.piece.id}, format="json").status_code, 404)
        r = self.c.post("/api/economy/sharez/", {"kind": "sentence", "ref": self.piece.id}, format="json")
        self.assertEqual(r.status_code, 200)
        tok = r.data["token"]
        self.assertGreaterEqual(len(tok), 16)
        page = self.anon.get(f"/api/economy/sharez/{tok}/")
        self.assertEqual(page.data["text"], "It rained.")
        self.assertEqual(page.data["owner"], "maker")
        self.assertEqual(page.data["item"], f"shared:{tok}")

    def test_sharing_twice_is_one_link_and_unsharing_kills_it(self):
        a = self.c.post("/api/economy/sharez/", {"kind": "manga", "ref": self.page.id}, format="json").data["token"]
        b = self.c.post("/api/economy/sharez/", {"kind": "manga", "ref": self.page.id}, format="json").data["token"]
        self.assertEqual(a, b)
        self.assertEqual(self.o.delete(f"/api/economy/sharez/{a}/").status_code, 404)
        self.c.delete(f"/api/economy/sharez/{a}/")
        self.assertEqual(self.anon.get(f"/api/economy/sharez/{a}/").status_code, 404)

    def test_a_shared_piece_gets_the_whole_social_bar(self):
        tok = self.c.post("/api/economy/sharez/", {"kind": "sentence", "ref": self.piece.id}, format="json").data["token"]
        item = f"shared:{tok}"
        d = self.o.get("/api/economy/social/", {"item": item}).data
        self.assertTrue(d["share"]["path"].startswith("/x/"))
        self.assertTrue(any("Sentence ConnectZ" in o["label"] for o in d["opens"]))
        self.assertEqual(self.o.post("/api/economy/social/react/", {"item": item, "value": 1}, format="json").status_code, 200)

    def test_a_deleted_source_closes_the_link(self):
        tok = self.c.post("/api/economy/sharez/", {"kind": "sentence", "ref": self.piece.id}, format="json").data["token"]
        self.piece.delete()
        self.assertEqual(self.anon.get(f"/api/economy/sharez/{tok}/").status_code, 404)
        self.assertEqual(SharedItem.objects.count(), 1)

    def test_one_call_lists_everything_shared_of_a_kind(self):
        tok = self.c.post("/api/economy/sharez/", {"kind": "sentence", "ref": self.piece.id}, format="json").data["token"]
        self.assertEqual(self.c.get("/api/economy/sharez/", {"kind": "sentence"}).data["shared"], {str(self.piece.id): tok})
