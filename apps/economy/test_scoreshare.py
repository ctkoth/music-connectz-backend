from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import ScoreShare, mint_score_share
from apps.economy.scoreshare import short_verdict


class ScoreShareTests(TestCase):
    def test_minted_from_the_coach_answer_only(self):
        u = User.objects.create_user("sharer", password="pw12345!x")
        tok = mint_score_share("rapz", {"score": 8, "verdict": "Flow is locked. Breath runs out on bar 12."}, user=u, genre="Trap")
        row = ScoreShare.objects.get(token=tok)
        self.assertEqual((row.score, row.user, row.genre), (8, u, "Trap"))

    def test_no_score_no_card(self):
        self.assertEqual(mint_score_share("singz", {"score": None, "unscorable": "silence"}), "")
        self.assertFalse(ScoreShare.objects.exists())

    def test_public_json_and_image(self):
        u = User.objects.create_user("sharer2", password="pw12345!x")
        tok = mint_score_share("singz", {"score": 7, "verdict": "Pitch is solid. Breath control cost you."}, user=u)
        c = APIClient()
        d = c.get(f"/api/economy/scores/{tok}/").json()
        self.assertEqual((d["score"], d["username"], d["verdict"]), (7, "sharer2", "Pitch is solid."))
        r = c.get(f"/api/economy/scores/{tok}/card.png")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/png")
        self.assertTrue(r.content.startswith(b"\x89PNG"))
        self.assertEqual(c.get("/api/economy/scores/nope/").status_code, 404)

    def test_trial_take_is_anonymous(self):
        tok = mint_score_share("drumz", {"score": 5, "verdict": "x"})
        self.assertEqual(APIClient().get(f"/api/economy/scores/{tok}/").json()["username"], "")

    def test_short_verdict_cuts_on_a_word(self):
        self.assertTrue(len(short_verdict("word " * 100)) <= 160)
