"""MangaZ script step: your characters and idea become an editable panel script."""
import json
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.mangaz import script_prompt
from apps.economy.models import Character, MangaPage, wallet_for

User = get_user_model()


def reply(panels):
    r = MagicMock(status_code=200)
    r.json.return_value = {"candidates": [{"content": {"parts": [{"text": json.dumps({"title": "Pun Fight", "panels": panels})}]}}]}
    return r


class MangaZTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("m", "m@e.com", "pw12345678")
        self.c = APIClient(); self.c.force_authenticate(self.u)
        w = wallet_for(self.u); w.promptz = 100; w.save()
        self.lou = Character.objects.create(user=self.u, name="Lou", bio="Talks in puns", personality="E---")
        self.kat = Character.objects.create(user=self.u, name="Kat", bio="Dry and blunt")

    def test_each_character_is_described_by_their_own_voice(self):
        p = script_prompt([self.lou, self.kat], "they argue about pizza", 4, "chibi")
        self.assertIn("Talks in puns", p)
        self.assertIn("Dry and blunt", p)
        self.assertIn("<idea>", p)

    @patch("apps.economy.mangaz._key", return_value="k")
    @patch("apps.economy.gemini.requests.post")
    def test_script_is_cleaned_and_kept(self, rq, _k):
        rq.return_value = reply([{"shot": "wide", "action": "Lou slips", "characters": ["Lou", "Stranger"],
                                  "dialogue": [{"who": "Lou", "line": "Pizza my heart"}, {"who": "Nobody", "line": "x"}]}])
        r = self.c.post("/api/economy/mangaz/", {"character_ids": [self.lou.id, self.kat.id], "idea": "pizza", "panels": 4}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        panel = r.data["panels"][0]
        self.assertEqual(panel["characters"], ["Lou"])            # no invented people
        self.assertEqual([d["who"] for d in panel["dialogue"]], ["Lou"])  # an invented speaker's line is dropped
        self.assertIn("AI-made", r.data["ai_label"])
        pid = r.data["id"]
        r = self.c.patch(f"/api/economy/mangaz/{pid}/", {"panels": [{"action": "edited", "dialogue": []}]}, format="json")
        self.assertEqual(MangaPage.objects.get().panels[0]["action"], "edited")

    def test_someone_elses_character_is_not_usable(self):
        other = User.objects.create_user("o", "o@e.com", "pw12345678")
        theirs = Character.objects.create(user=other, name="Theirs")
        r = self.c.post("/api/economy/mangaz/", {"character_ids": [theirs.id], "idea": "x"}, format="json")
        self.assertEqual(r.status_code, 400)

    @patch("apps.economy.mangaz._key", return_value="k")
    @patch("apps.economy.gemini.requests.post")
    def test_empty_answer_is_not_charged(self, rq, _k):
        rq.return_value = reply([])
        before = wallet_for(self.u).promptz
        r = self.c.post("/api/economy/mangaz/", {"character_ids": [self.lou.id], "idea": "x"}, format="json")
        self.assertEqual(r.status_code, 502)
        self.assertEqual(wallet_for(self.u).promptz, before)
