import base64
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.imagez_cutout import clean_masks
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
    @patch("apps.economy.imagez_cutout._bill", return_value=0)
    @patch("apps.economy.imagez_cutout.generate_content")
    def test_a_mask_is_returned_and_billed(self, gen, bill, _k):
        self.statz()
        gen.return_value = (reply('[{"label":"me","box_2d":[0,0,1000,1000],"mask":"' + PNG + '"}]'), ["m"])
        r = self.c.post(URL, {"image": PHOTO}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(len(r.data["masks"]), 1)
        bill.assert_called_once()

    @patch("apps.economy.imagez_cutout._key", return_value="k")
    @patch("apps.economy.imagez_cutout._bill")
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
