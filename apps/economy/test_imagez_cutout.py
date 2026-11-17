import base64
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.imagez_cutout import MAX_CENTS, MAX_OUTPUT_TOKENS, OUT_CENTS_PER_M, clean_masks, price_from_usage
from apps.economy.models import Membership, TIER_STATZ

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\0" * 20).decode()
PHOTO = "data:image/png;base64," + PNG
URL = "/api/economy/imagez/cutout/"


def reply(text):
    r = MagicMock(status_code=200)
    r.json.return_value = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    return r


class CleanMasksTests(TestCase):
    def test_only_well_formed_masks_survive(self):
        good = {"label": "dog", "box_2d": [10, 20, 500, 600], "mask": "data:image/png;base64," + PNG}
        bare = {"label": "cat", "box_2d": [0, 0, 1000, 1000], "mask": PNG}
        out = clean_masks([good, bare, {"box_2d": [500, 0, 10, 10], "mask": PNG},
                           {"box_2d": [0, 0, 10, 10], "mask": "data:image/png;base64,bm90IGEgcG5n"},
                           {"box_2d": [0, 0, 10], "mask": PNG}, "junk"])
        self.assertEqual([m["label"] for m in out], ["dog", "cat"])
        self.assertEqual(out[0]["box"], [10, 20, 500, 600])


class CutoutViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("pic", password="pw12345!x")
        self.c = APIClient()
        self.c.force_authenticate(self.user)

    def statz(self):
        Membership.objects.update_or_create(user=self.user, defaults={"tier": TIER_STATZ})

    def test_free_is_refused_before_anything_runs(self):
        r = self.c.post(URL, {"image": PHOTO}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertFalse(self.c.get(URL).data["allowed"])

    @patch("apps.economy.imagez_cutout._key", return_value="k")
    @patch("apps.economy.imagez_cutout._charge", return_value=0)
    @patch("apps.economy.imagez_cutout.generate_content")
    def test_a_mask_is_returned_and_billed(self, gen, bill, _k):
        self.statz()
        gen.return_value = (reply('[{"label":"me","box_2d":[0,0,1000,1000],"mask":"' + PNG + '"}]'), ["m"])
        r = self.c.post(URL, {"image": PHOTO}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(len(r.data["masks"]), 1)
        bill.assert_called_once()

    @patch("apps.economy.imagez_cutout._key", return_value="k")
    @patch("apps.economy.imagez_cutout._charge")
    @patch("apps.economy.imagez_cutout.generate_content")
    def test_no_subject_is_not_charged(self, gen, bill, _k):
        self.statz()
        gen.return_value = (reply("[]"), ["m"])
        r = self.c.post(URL, {"image": PHOTO}, format="json")
        self.assertEqual(r.data["masks"], [])
        bill.assert_not_called()

    @patch("apps.economy.imagez_cutout._key", return_value="k")
    def test_a_non_image_is_refused(self, _k):
        self.statz()
        r = self.c.post(URL, {"image": "data:text/html;base64,PGI+"}, format="json")
        self.assertEqual(r.status_code, 400)


class PriceTests(TestCase):
    def test_priced_from_tokens_between_the_stated_ends(self):
        self.assertEqual(price_from_usage({"promptTokenCount": 1300, "candidatesTokenCount": 200}), 1)
        self.assertEqual(price_from_usage({"promptTokenCount": 1300, "candidatesTokenCount": 9000}), 3)
        self.assertEqual(price_from_usage({"promptTokenCount": 1, "candidatesTokenCount": 10**8}), MAX_CENTS)
        self.assertEqual(price_from_usage(None), MAX_CENTS)

    def test_the_output_cap_cannot_cost_more_than_the_top_price(self):
        self.assertLessEqual(MAX_OUTPUT_TOKENS * OUT_CENTS_PER_M / 1_000_000, MAX_CENTS)

    def test_the_top_price_fits_inside_a_free_daily_prompt(self):
        from apps.economy.models import daily_prompt_covers
        self.assertTrue(daily_prompt_covers(MAX_CENTS))


class ChargeTests(TestCase):
    def test_a_free_prompt_pays_and_nothing_reaches_the_owner(self):
        from apps.economy.imagez_cutout import _charge
        u = get_user_model().objects.create_user("payer", password="pw12345!x")
        with patch("apps.economy.views.credit_owner") as owner:
            self.assertEqual(_charge(u, 2), 0)
            owner.assert_not_called()
