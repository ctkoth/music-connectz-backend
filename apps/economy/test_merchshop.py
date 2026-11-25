import io

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image
from rest_framework.test import APIClient

from . import merchshop
from .merchshop import DEV_TAX
from .models import TIER_FREE, TIER_PREMIUM, TIER_STATZ, PrintDesign, wallet_for


def png():
    b = io.BytesIO(); Image.new("RGB", (8, 8), "red").save(b, "PNG")
    return SimpleUploadedFile("d.png", b.getvalue(), content_type="image/png")


class SplitTests(TestCase):
    def test_dev_tax_is_on_the_markup_only(self):
        s = merchshop.split("shirt", 1000, 0.10)
        self.assertEqual(s, {"price": 2300, "printer": 1300, "dev_tax": 100, "designer": 900})

    def test_parts_add_up_to_the_price_for_every_product_and_rate(self):
        for p in merchshop.BASE_CENTS:
            for r in DEV_TAX.values():
                s = merchshop.split(p, 777, r)
                self.assertEqual(s["printer"] + s["dev_tax"] + s["designer"], s["price"])

    def test_designer_range_spans_the_tiers(self):
        r = merchshop.designer_range("hoodie", 1000)
        self.assertEqual(r, {"min": 1000 - round(1000 * DEV_TAX[TIER_FREE]), "max": 1000 - round(1000 * DEV_TAX[TIER_STATZ])})


class ShopApiTests(TestCase):
    def setUp(self):
        U = get_user_model()
        self.a = U.objects.create_user("ann", password="pw12345!x")
        self.b = U.objects.create_user("bob", password="pw12345!x")
        self.c = APIClient(); self.c.force_authenticate(self.a)

    def post(self, **kw):
        data = {"product": "shirt", "title": "Red tee", "markup_cents": "1000", "own_art": "1", "image": png(), "color": "#c81d25"}
        data.update(kw)
        return self.c.post("/api/economy/merch/shop/", data, format="multipart")

    def test_list_a_design_and_see_the_split_before_anything(self):
        r = self.post()
        self.assertEqual(r.status_code, 201, r.data)
        d = r.data["design"]
        self.assertEqual(d["split"]["price"], 2300)
        self.assertIn("designer_keeps", d)
        self.assertFalse(r.data["checkout_open"])

    def test_own_art_must_be_declared(self):
        self.assertEqual(self.post(own_art="").status_code, 400)

    def test_bad_product_and_markup_refused(self):
        self.assertEqual(self.post(product="teapot").status_code, 400)
        self.assertEqual(self.post(markup_cents=str(merchshop.MAX_MARKUP + 1)).status_code, 400)

    def test_others_see_it_without_the_designers_range(self):
        self.post()
        o = APIClient(); o.force_authenticate(self.b)
        d = o.get("/api/economy/merch/shop/?designer=ann").data["designs"][0]
        self.assertFalse(d["mine"]); self.assertNotIn("designer_keeps", d)

    def test_buy_is_closed_and_moves_nothing(self):
        pk = self.post().data["design"]["id"]
        o = APIClient(); o.force_authenticate(self.b)
        w = wallet_for(self.b); w.money_cents = 10000; w.save()
        r = o.post(f"/api/economy/merch/shop/{pk}/buy/")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(wallet_for(self.b).money_cents, 10000)

    def test_only_the_designer_edits_or_removes(self):
        pk = self.post().data["design"]["id"]
        o = APIClient(); o.force_authenticate(self.b)
        self.assertEqual(o.delete(f"/api/economy/merch/shop/{pk}/").status_code, 404)
        self.assertEqual(self.c.patch(f"/api/economy/merch/shop/{pk}/", {"markup_cents": 500}, format="json").data["design"]["markup_cents"], 500)
        self.assertEqual(self.c.delete(f"/api/economy/merch/shop/{pk}/").status_code, 204)
        self.assertFalse(PrintDesign.objects.get(pk=pk).active)


class ProductListTests(TestCase):
    def test_every_designer_product_has_a_cost_and_label(self):
        # Mirrors PRODUCTS in the frontend's src/merchz.js; a product there with no cost here cannot be listed.
        keys = {"shirt", "hoodie", "towel", "bandana", "wavecap", "durag", "mug", "phonecase", "baseballcap"}
        self.assertEqual(set(merchshop.BASE_CENTS), keys)
        self.assertEqual(set(merchshop.LABELS), keys)


class RateTests(TestCase):
    def test_coreys_merch_rates(self):
        self.assertEqual((DEV_TAX[TIER_FREE], DEV_TAX[TIER_PREMIUM], DEV_TAX[TIER_STATZ]), (0.10, 0.06, 0.03))
