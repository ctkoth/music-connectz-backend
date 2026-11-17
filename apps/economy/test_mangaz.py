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


class _Base(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("m", "m@e.com", "pw12345678")
        self.c = APIClient(); self.c.force_authenticate(self.u)
        w = wallet_for(self.u); w.promptz = 100; w.save()
        self.lou = Character.objects.create(user=self.u, name="Lou", bio="Talks in puns", personality="E---")
        self.kat = Character.objects.create(user=self.u, name="Kat", bio="Dry and blunt")


class MangaZTests(_Base):

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


class MangaDrawTests(_Base):
    def setUp(self):
        super().setUp()
        self.page = MangaPage.objects.create(user=self.u, idea="x", character_ids=[self.lou.id],
                                             panels=[{"n": 1, "action": "Lou waves", "characters": ["Lou"], "dialogue": []}])

    @patch("apps.economy.mangaz._key", return_value="k")
    @patch("apps.economy.gemini.draw_image", return_value=("iVBORw0KGgo=", "image/png"))
    def test_a_drawn_panel_is_kept_and_billed(self, _d, _k):
        before = wallet_for(self.u).promptz
        with self.settings(MEDIA_ROOT="/tmp/mcz-test-media"):
            r = self.c.post(f"/api/economy/mangaz/{self.page.id}/panel/1/draw/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn("/media/", r.data["panels"][0]["image"])
        self.assertLess(wallet_for(self.u).promptz, before)

    @patch("apps.economy.mangaz._key", return_value="k")
    @patch("apps.economy.gemini.draw_image", return_value=(None, None))
    def test_a_failed_panel_is_free(self, _d, _k):
        before = wallet_for(self.u).promptz
        self.assertEqual(self.c.post(f"/api/economy/mangaz/{self.page.id}/panel/1/draw/").status_code, 502)
        self.assertEqual(wallet_for(self.u).promptz, before)


    @patch("apps.economy.mangaz._key", return_value="k")
    @patch("apps.economy.gemini.draw_image", return_value=("iVBORw0KGgo=", "image/png"))
    def test_the_whole_page_in_one_image(self, _d, _k):
        with self.settings(MEDIA_ROOT="/tmp/mcz-test-media"):
            r = self.c.post(f"/api/economy/mangaz/{self.page.id}/panel/0/draw/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn("/media/", r.data["page_image"])
        self.assertEqual(r.data["panels"][0].get("image", ""), "")


class PageDesignerTests(TestCase):
    """The page designer's layout rides in the panels, cleaned; characters per page ladder 3/6/all."""

    def test_box_and_bubbles_are_cleaned(self):
        from apps.economy.mangaz import clean_panels
        out = clean_panels([{"action": "x", "dialogue": [{"who": "Ana", "line": "hi"}],
                             "box": [0.5, 0.5, 0.9, 0.9], "bubbles": [{"i": 0, "x": 2, "y": 0.1}, {"i": 5, "x": 0, "y": 0}]},
                            {"action": "y", "box": "nope"}], ["Ana"])
        self.assertEqual(out[0]["box"], [0.5, 0.5, 0.5, 0.5])
        self.assertEqual(out[0]["bubbles"], [{"i": 0, "x": 1.0, "y": 0.1}])
        self.assertIsNone(out[1]["box"])

    def test_characters_per_page_follow_the_tier(self):
        from django.contrib.auth import get_user_model
        from apps.economy.mangaz import MAX_CHARACTERS, chars_for
        from apps.economy.models import Membership, TIER_PREMIUM, TIER_STATZ
        u = get_user_model().objects.create_user("mangak", password="pw12345!x")
        self.assertEqual(chars_for(u), 3)
        Membership.objects.update_or_create(user=u, defaults={"tier": TIER_PREMIUM})
        self.assertEqual(chars_for(u), 6)
        Membership.objects.update_or_create(user=u, defaults={"tier": TIER_STATZ})
        self.assertEqual(chars_for(u), MAX_CHARACTERS)
