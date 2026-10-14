"""A reference listen is somebody else's track, analysed and forgotten.

The substance rule: nothing it does may be mistakable for the member's own take.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import models as m
from apps.economy.instruments import INSTRUMENTS, reference_prompt_for, scores_for
from apps.economy.models import TIER_STATZ, membership_for, wallet_for
from apps.economy.test_vocalcoach import GOOD, fake_gemini, take

User = get_user_model()
REF = {**GOOD, "borrow": "Lay back on the second beat.",
       "fixes": ["should be dropped"], "next_drill": "should be dropped"}


def counts():
    return {n: getattr(m, n).objects.count()
            for n in ("TakeScore", "ItemRating", "TrainingProfile", "TrainingEvent",
                      "Upload", "Post", "ScoreShare", "Observation")
            if hasattr(m, n)}


class ReferenceListenTests(TestCase):
    def setUp(self):
        self.c = APIClient()
        self.u = User.objects.create_user("r", "r@e.com", "pw12345678")
        self.c.force_authenticate(self.u)
        mem = membership_for(self.u); mem.tier = TIER_STATZ; mem.save()
        w = wallet_for(self.u); w.money_cents = 100000; w.save()

    def _post(self, **extra):
        with patch("apps.economy.vocalcoach._key", return_value="k"), \
             patch("apps.economy.gemini.requests.post", return_value=fake_gemini(REF)):
            return self.c.post("/api/singz/coach/",
                               {"take": take(), "genre": "R&B", "reference": "true", **extra},
                               format="multipart")

    def test_it_writes_nothing_that_measures_the_member(self):
        before = counts()
        r = self._post()
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(counts(), before)
        self.assertTrue(r.data["reference"])
        self.assertIsNone(r.data["take_score_id"])
        self.assertEqual(r.data["share_url"], "")
        self.assertFalse(r.data["saved"])

    def test_no_fixes_and_a_borrow_note(self):
        d = self._post().data
        self.assertEqual(d["fixes"], [])
        self.assertEqual(d["next_drill"], "")
        self.assertEqual(d["borrow"], "Lay back on the second beat.")
        self.assertIn("pitch", d["scores"])

    def test_it_is_billed_like_a_take_and_a_failure_is_not(self):
        with patch("apps.economy.vocalcoach._bill", return_value=3) as bill:
            r = self._post()
        self.assertEqual(r.data["cost_cents"], 3)
        self.assertTrue(bill.call_args.kwargs["count_daily"])
        with patch("apps.economy.vocalcoach._key", return_value="k"), \
             patch("apps.economy.gemini.requests.post", return_value=fake_gemini(REF, 500)), \
             patch("apps.economy.vocalcoach._bill") as bill:
            r = self.c.post("/api/singz/coach/", {"take": take(), "reference": "1"},
                            format="multipart")
        self.assertGreaterEqual(r.status_code, 400)
        bill.assert_not_called()

    def test_it_will_not_take_your_own_posts_or_journal(self):
        r = self._post(post_id="1")
        self.assertEqual(r.status_code, 400)

    def test_the_price_and_notice_are_stated_before_pressing(self):
        d = self.c.get("/api/singz/coach/").data["reference"]
        self.assertIn("cost_cents", d)
        self.assertFalse(d["charged_on_failure"])
        self.assertIn("right to analyse", d["notice"])

    def test_the_trial_refuses_it_with_a_sentence(self):
        anon = APIClient()
        with patch("apps.economy.trial.score_take") as st:
            r = anon.post("/api/singz/trial/", {"take": take(), "reference": "true"},
                          format="multipart")
        self.assertEqual(r.status_code, 403)
        self.assertTrue(r.data["detail"])
        st.assert_not_called()

    def test_every_instrument_has_a_reference_prompt_with_its_keys(self):
        for k in INSTRUMENTS:
            p = reference_prompt_for(k, "Jazz")
            for dim in scores_for(k):
                self.assertIn(f'"{dim}"', p)
            self.assertNotIn('"fixes"', p)
            self.assertIn("NOT the listener's own performance", p)
