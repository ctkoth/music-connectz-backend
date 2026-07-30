"""Tests for print-on-demand MerchZ — one design, many products, no inventory.

The money split is the part worth guarding hardest. A sale has to pay the printer
before it pays anyone, and the obvious implementation (`pay_between`) doesn't:
it hands the seller the whole amount minus tax, out of money that owes a printer
the print cost.
"""
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import pod, pod_reports
from apps.economy.models import (TIER_FREE, MerchDesign, PrintListing,
                                 PrintOrder, PrintProduct, Transaction,
                                 membership_for, wallet_for)

User = get_user_model()

ADDRESS = {"name": "A Buyer", "line1": "1 Main St", "city": "Denver",
           "country": "US", "postcode": "80202"}


def a_png():
    """The smallest valid PNG — enough for ImageField to accept an upload."""
    return SimpleUploadedFile(
        "art.png",
        (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
         b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
         b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"),
        content_type="image/png",
    )


class CatalogTests(TestCase):
    def test_seeding_is_idempotent_and_updates_in_place(self):
        self.assertEqual(pod.seed_blanks(), len(pod.BLANKS))
        self.assertEqual(PrintProduct.objects.count(), len(pod.BLANKS))
        # running again creates nothing new
        self.assertEqual(pod.seed_blanks(), 0)
        self.assertEqual(PrintProduct.objects.count(), len(pod.BLANKS))

    def test_a_reprice_in_the_source_reprices_the_row(self):
        pod.seed_blanks()
        tee = PrintProduct.objects.get(key="tee")
        tee.base_cost_cents = 9999
        tee.save()
        pod.seed_blanks()
        self.assertEqual(PrintProduct.objects.get(key="tee").base_cost_cents,
                         next(b for b in pod.BLANKS if b["key"] == "tee")["base_cost_cents"])

    def test_landed_cost_includes_shipping(self):
        pod.seed_blanks()
        tee = PrintProduct.objects.get(key="tee")
        self.assertEqual(tee.landed_cost_cents, tee.base_cost_cents + tee.shipping_cents)

    def test_the_suggested_price_clears_cost_and_ends_in_99(self):
        pod.seed_blanks()
        for p in PrintProduct.objects.all():
            price = pod.suggested_price_cents(p)
            self.assertGreater(price, p.landed_cost_cents, p.key)
            self.assertEqual(price % 100, 99, p.key)

    def test_the_quote_breaks_a_price_down(self):
        pod.seed_blanks()
        tee = PrintProduct.objects.get(key="tee")
        q = pod.quote(tee, 2500)
        self.assertEqual(q["price_cents"], 2500)
        self.assertEqual(q["base_cost_cents"], tee.landed_cost_cents)
        self.assertEqual(q["margin_cents"], 2500 - tee.landed_cost_cents)
        self.assertTrue(q["profitable"])
        self.assertEqual(pod.quote(tee, 2500, quantity=3)["price_cents"], 7500)

    def test_a_price_below_cost_is_refused_with_the_break_even(self):
        pod.seed_blanks()
        hoodie = PrintProduct.objects.get(key="hoodie")
        ok, detail = pod.validate_price(hoodie, hoodie.landed_cost_cents - 1)
        self.assertFalse(ok)
        self.assertIn("at a loss", detail)
        self.assertIn(str(hoodie.landed_cost_cents), detail)
        # exactly at cost is still refused — zero margin isn't a sale, it's admin
        self.assertFalse(pod.validate_price(hoodie, hoodie.landed_cost_cents)[0])
        self.assertTrue(pod.validate_price(hoodie, hoodie.landed_cost_cents + 1)[0])

    def test_price_bounds_and_junk(self):
        pod.seed_blanks()
        tee = PrintProduct.objects.get(key="tee")
        self.assertFalse(pod.validate_price(tee, "abc")[0])
        self.assertFalse(pod.validate_price(tee, None)[0])
        self.assertFalse(pod.validate_price(tee, pod.MAX_PRICE_CENTS + 1)[0])

    def test_the_provider_is_manual_until_keys_are_set(self):
        self.assertEqual(pod.provider_name(), "manual")

    def test_addresses_are_validated_and_trimmed_to_what_a_printer_needs(self):
        self.assertFalse(pod.validate_address(None)[0])
        ok, detail = pod.validate_address({"name": "x"})
        self.assertFalse(ok)
        self.assertIn("line1", detail)
        self.assertTrue(pod.validate_address(ADDRESS)[0])
        cleaned = pod.clean_address({**ADDRESS, "ssn": "nope", "notes": "hi"})
        self.assertNotIn("ssn", cleaned)
        self.assertNotIn("notes", cleaned)
        self.assertEqual(cleaned["city"], "Denver")


class MoneyTests(TestCase):
    """A sale pays the printer first, the creator second, and never confuses them."""

    def setUp(self):
        pod.seed_blanks()
        self.seller = User.objects.create_user("maker", "m@e.com", "pw12345678")
        self.buyer = User.objects.create_user("fan", "f@e.com", "pw12345678")
        w = wallet_for(self.buyer)
        w.money_cents = 20_000
        w.save()
        m = membership_for(self.buyer)
        m.tier = TIER_FREE          # 10% developer tax
        m.save(update_fields=["tier", "updated_at"])
        self.design = MerchDesign.objects.create(owner=self.seller, title="Logo",
                                                 image=a_png())
        self.tee = PrintProduct.objects.get(key="tee")
        self.listing = PrintListing.objects.create(
            design=self.design, product=self.tee, seller=self.seller,
            title="Logo Tee", price_cents=2500,
        )

    def test_the_print_cost_comes_out_before_anyone_is_paid(self):
        landed = self.tee.landed_cost_cents               # 1100 + 450 = 1550
        # White L: the base variant, no size or colour upcharge in play. Upcharged
        # variants are covered in VariantTests.
        order, err = pod.place_order(self.buyer, self.listing, size="L", color="White",
                                     ship_to=ADDRESS)
        self.assertIsNone(err)

        margin = 2500 - landed                            # 950
        expected_tax = round(margin * 0.10)               # tax is on the margin only
        self.assertEqual(order.base_cost_cents, landed)
        self.assertEqual(order.price_cents, 2500)
        self.assertEqual(order.dev_tax_cents + order.seller_cents, margin)
        self.assertEqual(order.dev_tax_cents, expected_tax)

        # buyer paid the full price; seller got only their share of the margin
        self.assertEqual(wallet_for(self.buyer).money_cents, 20_000 - 2500)
        self.assertEqual(wallet_for(self.seller).money_cents, order.seller_cents)
        self.assertLess(order.seller_cents, margin)
        # and crucially: nowhere near the naive "price minus tax"
        self.assertLess(order.seller_cents, 2500 - expected_tax)

    def test_the_platform_keeps_the_print_cost_rather_than_paying_it_out(self):
        order, _ = pod.place_order(self.buyer, self.listing, ship_to=ADDRESS)
        paid_out = wallet_for(self.seller).money_cents
        withheld = order.price_cents - paid_out - order.dev_tax_cents
        self.assertEqual(withheld, order.base_cost_cents)

    def test_quantity_scales_cost_and_margin_together(self):
        order, err = pod.place_order(self.buyer, self.listing, quantity=3, ship_to=ADDRESS)
        self.assertIsNone(err)
        self.assertEqual(order.quantity, 3)
        self.assertEqual(order.price_cents, 7500)
        self.assertEqual(order.base_cost_cents, self.tee.landed_cost_cents * 3)

    def test_quantity_is_capped_and_never_zero(self):
        w = wallet_for(self.buyer)
        w.money_cents = 2500 * pod.MAX_QUANTITY + 2500   # enough for the cap
        w.save()
        order, err = pod.place_order(self.buyer, self.listing, quantity=9999, ship_to=ADDRESS)
        self.assertIsNone(err)
        self.assertEqual(order.quantity, pod.MAX_QUANTITY)
        order2, _ = pod.place_order(self.buyer, self.listing, quantity=0, ship_to=ADDRESS)
        self.assertEqual(order2.quantity, 1)

    def test_a_broke_buyer_is_refused_and_nothing_is_created(self):
        w = wallet_for(self.buyer)
        w.money_cents = 100
        w.save()
        order, err = pod.place_order(self.buyer, self.listing, ship_to=ADDRESS)
        self.assertIsNone(order)
        self.assertEqual(err, "insufficient balance")
        self.assertFalse(PrintOrder.objects.exists())
        self.assertEqual(wallet_for(self.buyer).money_cents, 100)

    def test_a_listing_whose_cost_rose_past_its_price_refuses_the_sale(self):
        """Print costs move. Better to refuse than to pay the creator out of the
        printer's money."""
        self.tee.base_cost_cents = 3000
        self.tee.save()
        self.listing.refresh_from_db()
        order, err = pod.place_order(self.buyer, self.listing, ship_to=ADDRESS)
        self.assertIsNone(order)
        self.assertIn("no longer covers its print cost", err)
        self.assertEqual(wallet_for(self.buyer).money_cents, 20_000)

    def test_an_order_starts_pending_with_no_provider_and_says_why(self):
        order, _ = pod.place_order(self.buyer, self.listing, ship_to=ADDRESS)
        self.assertEqual(order.status, PrintOrder.STATUS_PENDING)
        self.assertEqual(order.provider, "manual")
        self.assertIn("manual fulfilment", order.note)

    def test_orders_snapshot_their_money_so_a_reprice_cannot_rewrite_history(self):
        order, _ = pod.place_order(self.buyer, self.listing, ship_to=ADDRESS)
        self.listing.price_cents = 9900
        self.listing.save()
        order.refresh_from_db()
        self.assertEqual(order.price_cents, 2500)


class OrderLifecycleTests(TestCase):
    def setUp(self):
        pod.seed_blanks()
        self.seller = User.objects.create_user("maker", "m@e.com", "pw12345678")
        self.buyer = User.objects.create_user("fan", "f@e.com", "pw12345678")
        w = wallet_for(self.buyer)
        w.money_cents = 20_000
        w.save()
        design = MerchDesign.objects.create(owner=self.seller, title="Logo", image=a_png())
        self.listing = PrintListing.objects.create(
            design=design, product=PrintProduct.objects.get(key="mug"),
            seller=self.seller, title="Logo Mug", price_cents=2200,
        )
        self.order, _ = pod.place_order(self.buyer, self.listing, ship_to=ADDRESS)

    def test_it_walks_pending_to_delivered(self):
        for state in (PrintOrder.STATUS_SUBMITTED, PrintOrder.STATUS_IN_PRODUCTION,
                      PrintOrder.STATUS_SHIPPED, PrintOrder.STATUS_DELIVERED):
            ok, _ = pod.advance(self.order, state)
            self.assertTrue(ok, state)
        self.assertEqual(self.order.status, PrintOrder.STATUS_DELIVERED)

    def test_a_terminal_order_cannot_be_reopened_by_a_replayed_webhook(self):
        pod.advance(self.order, PrintOrder.STATUS_DELIVERED)
        ok, detail = pod.advance(self.order, PrintOrder.STATUS_SHIPPED)
        self.assertFalse(ok)
        self.assertIn("already delivered", detail)
        self.assertEqual(self.order.status, PrintOrder.STATUS_DELIVERED)

    def test_an_unknown_status_is_refused(self):
        ok, detail = pod.advance(self.order, "yeeted")
        self.assertFalse(ok)
        self.assertIn("unknown status", detail)

    def test_tracking_travels_with_the_status(self):
        pod.advance(self.order, PrintOrder.STATUS_SHIPPED,
                    tracking_url="https://track.example/abc", provider_order_id="pf_1")
        self.order.refresh_from_db()
        self.assertEqual(self.order.tracking_url, "https://track.example/abc")
        self.assertEqual(self.order.provider_order_id, "pf_1")


class EndpointTests(TestCase):
    def setUp(self):
        pod.seed_blanks()
        self.client = APIClient()
        self.seller = User.objects.create_user("maker", "m@e.com", "pw12345678")
        self.buyer = User.objects.create_user("fan", "f@e.com", "pw12345678")
        w = wallet_for(self.buyer)
        w.money_cents = 20_000
        w.save()

    def _design(self):
        self.client.force_authenticate(self.seller)
        return self.client.post("/api/economy/pod/designs/",
                                {"title": "Logo", "image": a_png()},
                                format="multipart").data["design"]["id"]

    def test_the_blank_catalog_is_public_and_advertises_no_inventory(self):
        resp = APIClient().get("/api/economy/pod/blanks/")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["made_to_order"])
        self.assertFalse(resp.data["holds_inventory"])
        keys = [b["key"] for b in resp.data["blanks"]]
        self.assertIn("tee", keys)
        self.assertIn("hoodie", keys)
        tee = next(b for b in resp.data["blanks"] if b["key"] == "tee")
        self.assertGreater(tee["suggested_price_cents"], tee["landed_cost_cents"])

    def test_upload_a_design_then_list_it_on_several_blanks(self):
        """The headline: one design, many products, one upload."""
        design_id = self._design()
        for product, price in (("tee", 2500), ("hoodie", 4500), ("mug", 1999)):
            resp = self.client.post("/api/economy/pod/listings/",
                                    {"design_id": design_id, "product": product,
                                     "price_cents": price}, format="json")
            self.assertEqual(resp.status_code, 201, resp.content)
            self.assertTrue(resp.data["listing"]["made_to_order"])
            self.assertTrue(resp.data["quote"]["profitable"])
        self.assertEqual(PrintListing.objects.count(), 3)
        self.assertEqual(MerchDesign.objects.count(), 1)
        mine = self.client.get("/api/economy/pod/listings/?mine=1").data["listings"]
        self.assertEqual(len(mine), 3)

    def test_the_same_design_cannot_be_listed_twice_on_one_blank(self):
        design_id = self._design()
        body = {"design_id": design_id, "product": "tee", "price_cents": 2500}
        self.assertEqual(self.client.post("/api/economy/pod/listings/", body,
                                          format="json").status_code, 201)
        self.assertEqual(self.client.post("/api/economy/pod/listings/", body,
                                          format="json").status_code, 409)

    def test_listing_below_cost_is_refused_with_a_number_to_use(self):
        design_id = self._design()
        resp = self.client.post("/api/economy/pod/listings/",
                                {"design_id": design_id, "product": "hoodie",
                                 "price_cents": 500}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("at a loss", resp.data["detail"])
        self.assertGreater(resp.data["suggested_price_cents"], resp.data["break_even_cents"])

    def test_you_cannot_list_someone_elses_design(self):
        design_id = self._design()
        self.client.force_authenticate(self.buyer)
        resp = self.client.post("/api/economy/pod/listings/",
                                {"design_id": design_id, "product": "tee",
                                 "price_cents": 2500}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_buying_creates_an_order_and_moves_the_money(self):
        design_id = self._design()
        listing_id = self.client.post("/api/economy/pod/listings/",
                                      {"design_id": design_id, "product": "tee",
                                       "price_cents": 2500},
                                      format="json").data["listing"]["id"]
        self.client.force_authenticate(self.buyer)
        resp = self.client.post(f"/api/economy/pod/listings/{listing_id}/buy/",
                                {"size": "L", "color": "White", "ship_to": ADDRESS},
                                format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        order = resp.data["order"]
        self.assertEqual(order["status"], "pending")
        self.assertEqual(order["price_cents"], 2500)
        self.assertGreater(order["base_cost_cents"], 0)
        self.assertEqual(order["seller_cents"] + order["dev_tax_cents"] + order["base_cost_cents"],
                         2500)

    def _sold_listing(self):
        design_id = self._design()
        listing_id = self.client.post("/api/economy/pod/listings/",
                                      {"design_id": design_id, "product": "tee",
                                       "price_cents": 2500},
                                      format="json").data["listing"]["id"]
        self.client.force_authenticate(self.buyer)
        order_id = self.client.post(f"/api/economy/pod/listings/{listing_id}/buy/",
                                    {"size": "L", "ship_to": ADDRESS},
                                    format="json").data["order"]["id"]
        return listing_id, order_id

    def test_an_address_is_required_for_a_physical_good(self):
        design_id = self._design()
        listing_id = self.client.post("/api/economy/pod/listings/",
                                      {"design_id": design_id, "product": "tee",
                                       "price_cents": 2500},
                                      format="json").data["listing"]["id"]
        self.client.force_authenticate(self.buyer)
        resp = self.client.post(f"/api/economy/pod/listings/{listing_id}/buy/",
                                {"size": "L"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("ship_to", resp.data["detail"])

    def test_an_invalid_size_is_refused(self):
        design_id = self._design()
        listing_id = self.client.post("/api/economy/pod/listings/",
                                      {"design_id": design_id, "product": "tee",
                                       "price_cents": 2500},
                                      format="json").data["listing"]["id"]
        self.client.force_authenticate(self.buyer)
        resp = self.client.post(f"/api/economy/pod/listings/{listing_id}/buy/",
                                {"size": "XXXXL", "ship_to": ADDRESS}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("size must be", resp.data["detail"])

    def test_you_cannot_buy_your_own_listing(self):
        design_id = self._design()
        listing_id = self.client.post("/api/economy/pod/listings/",
                                      {"design_id": design_id, "product": "tee",
                                       "price_cents": 2500},
                                      format="json").data["listing"]["id"]
        resp = self.client.post(f"/api/economy/pod/listings/{listing_id}/buy/",
                                {"size": "L", "ship_to": ADDRESS}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_the_seller_gets_a_fulfilment_queue(self):
        self._sold_listing()
        self.client.force_authenticate(self.seller)
        data = self.client.get("/api/economy/pod/orders/").data
        self.assertEqual(len(data["sales"]), 1)
        self.assertEqual(len(data["to_fulfil"]), 1)
        self.assertEqual(data["orders"], [])
        self.assertEqual(data["provider"], "manual")

    def test_the_buyer_sees_their_purchase_but_no_sales(self):
        self._sold_listing()
        self.client.force_authenticate(self.buyer)
        data = self.client.get("/api/economy/pod/orders/").data
        self.assertEqual(len(data["orders"]), 1)
        self.assertEqual(data["sales"], [])

    def test_only_the_seller_can_move_an_order_along(self):
        _, order_id = self._sold_listing()
        # the buyer just paid; they don't get to mark it shipped
        resp = self.client.post(f"/api/economy/pod/orders/{order_id}/status/",
                                {"status": "shipped"}, format="json")
        self.assertEqual(resp.status_code, 403)

        self.client.force_authenticate(self.seller)
        resp = self.client.post(f"/api/economy/pod/orders/{order_id}/status/",
                                {"status": "shipped",
                                 "tracking_url": "https://track.example/1"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["order"]["status"], "shipped")

    def test_a_sold_listing_is_deactivated_not_deleted(self):
        listing_id, _ = self._sold_listing()
        self.client.force_authenticate(self.seller)
        resp = self.client.delete(f"/api/economy/pod/listings/{listing_id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("deactivated", resp.data)
        self.assertFalse(PrintListing.objects.get(pk=listing_id).active)

    def test_an_unsold_listing_deletes_cleanly(self):
        design_id = self._design()
        listing_id = self.client.post("/api/economy/pod/listings/",
                                      {"design_id": design_id, "product": "tee",
                                       "price_cents": 2500},
                                      format="json").data["listing"]["id"]
        self.assertEqual(self.client.delete(f"/api/economy/pod/listings/{listing_id}/").status_code,
                         200)
        self.assertFalse(PrintListing.objects.exists())

    def test_a_design_that_has_sold_cannot_be_deleted(self):
        self._sold_listing()
        self.client.force_authenticate(self.seller)
        design_id = MerchDesign.objects.get().id
        resp = self.client.delete(f"/api/economy/pod/designs/{design_id}/")
        self.assertEqual(resp.status_code, 409)
        self.assertTrue(MerchDesign.objects.exists())

    def test_a_design_needs_a_title_and_an_image(self):
        self.client.force_authenticate(self.seller)
        self.assertEqual(self.client.post("/api/economy/pod/designs/", {"title": "x"},
                                          format="multipart").status_code, 400)
        self.assertEqual(self.client.post("/api/economy/pod/designs/", {"image": a_png()},
                                          format="multipart").status_code, 400)

    def test_designs_need_a_login(self):
        self.assertEqual(APIClient().get("/api/economy/pod/designs/").status_code, 401)


class SeedCommandTests(TestCase):
    def test_the_command_reports_the_catalog_and_the_manual_fallback(self):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("seed_pod", stdout=out)
        text = out.getvalue()
        self.assertIn("tee", text)
        self.assertIn("hoodie", text)
        self.assertIn("Provider: manual", text)
        self.assertIn("No POD provider configured", text)
        self.assertEqual(PrintProduct.objects.count(), len(pod.BLANKS))


class VariantTests(TestCase):
    """The customer's exact size gets made — and priced honestly.

    Sizes and colours are not unlimited: they're whatever the printer stocks for
    that blank. Extended sizes cost more, dark garments cost more to print, and a
    blank can be out of stock at the supplier even though nobody holds inventory.
    """

    def setUp(self):
        pod.seed_blanks()
        self.seller = User.objects.create_user("maker", "m@e.com", "pw12345678")
        self.buyer = User.objects.create_user("fan", "f@e.com", "pw12345678")
        w = wallet_for(self.buyer)
        w.money_cents = 20_000
        w.save()
        m = membership_for(self.buyer)
        m.tier = TIER_FREE
        m.save(update_fields=["tier", "updated_at"])
        self.tee = PrintProduct.objects.get(key="tee")
        design = MerchDesign.objects.create(owner=self.seller, title="Logo", image=a_png())
        self.listing = PrintListing.objects.create(
            design=design, product=self.tee, seller=self.seller,
            title="Logo Tee", price_cents=2500,
        )

    def test_extended_sizes_and_dark_colors_cost_more_to_make(self):
        self.assertEqual(self.tee.upcharge_cents("M", "White"), 0)
        self.assertEqual(self.tee.upcharge_cents("2XL", "White"), 200)
        self.assertEqual(self.tee.upcharge_cents("3XL", "White"), 400)
        self.assertEqual(self.tee.upcharge_cents("M", "Black"), 100)
        # they stack — a 3XL black tee is the most expensive variant
        self.assertEqual(self.tee.upcharge_cents("3XL", "Black"), 500)
        self.assertEqual(self.tee.landed_cost_for("3XL", "Black"),
                         self.tee.landed_cost_cents + 500)

    def test_the_buyer_pays_the_upcharge_and_the_creator_earns_the_same(self):
        """A shop selling mostly 3XL must not earn less per shirt than one
        selling mostly mediums."""
        small, err1 = pod.place_order(self.buyer, self.listing, size="M", color="White",
                                      ship_to=ADDRESS)
        big, err2 = pod.place_order(self.buyer, self.listing, size="3XL", color="Black",
                                    ship_to=ADDRESS)
        self.assertIsNone(err1)
        self.assertIsNone(err2)

        # the buyer paid $5 more for the big black one
        self.assertEqual(big.price_cents - small.price_cents, 500)
        self.assertEqual(big.upcharge_cents, 500)
        self.assertEqual(small.upcharge_cents, 0)
        # the printer gets all of that extra
        self.assertEqual(big.base_cost_cents - small.base_cost_cents, 500)
        # and the creator's cut is byte-for-byte identical
        self.assertEqual(big.seller_cents, small.seller_cents)
        self.assertEqual(big.dev_tax_cents, small.dev_tax_cents)

    def test_the_money_still_balances_on_an_upcharged_variant(self):
        order, _ = pod.place_order(self.buyer, self.listing, size="2XL", color="Navy",
                                   ship_to=ADDRESS)
        self.assertEqual(order.base_cost_cents + order.seller_cents + order.dev_tax_cents,
                         order.price_cents)

    def test_an_out_of_stock_variant_is_refused_and_nothing_is_charged(self):
        self.tee.unavailable = ["3XL", "Sand", "2XL|Navy"]
        self.tee.save()
        self.listing.refresh_from_db()
        before = wallet_for(self.buyer).money_cents

        for size, color in (("3XL", "Black"), ("M", "Sand"), ("2XL", "Navy")):
            order, err = pod.place_order(self.buyer, self.listing, size=size, color=color,
                                         ship_to=ADDRESS)
            self.assertIsNone(order, (size, color))
            self.assertIn("out of", err)
        self.assertEqual(wallet_for(self.buyer).money_cents, before)

        # a variant that isn't blocked still sells
        order, err = pod.place_order(self.buyer, self.listing, size="M", color="Black",
                                     ship_to=ADDRESS)
        self.assertIsNone(err)
        self.assertIsNotNone(order)

    def test_blocking_one_size_color_pair_leaves_the_rest_available(self):
        self.tee.unavailable = ["2XL|Navy"]
        self.tee.save()
        self.assertFalse(self.tee.variant_available("2XL", "Navy"))
        self.assertTrue(self.tee.variant_available("2XL", "Black"))
        self.assertTrue(self.tee.variant_available("M", "Navy"))

    def test_the_variant_table_shows_upcharges_and_a_price_range(self):
        table = pod.variant_table(self.tee, 2500)
        by_size = {s["value"]: s for s in table["sizes"]}
        self.assertEqual(by_size["M"]["upcharge_cents"], 0)
        self.assertEqual(by_size["3XL"]["upcharge_cents"], 400)
        self.assertTrue(by_size["3XL"]["available"])
        by_color = {c["value"]: c for c in table["colors"]}
        self.assertEqual(by_color["Black"]["upcharge_cents"], 100)
        # "$25.00 – $30.00" — the range a product page should print
        self.assertEqual(table["price_from_cents"], 2500)
        self.assertEqual(table["price_to_cents"], 3000)

    def test_the_variant_table_marks_stock_outs(self):
        self.tee.unavailable = ["3XL"]
        self.tee.save()
        table = pod.variant_table(self.tee, 2500)
        by_size = {s["value"]: s for s in table["sizes"]}
        self.assertFalse(by_size["3XL"]["available"])
        self.assertTrue(by_size["M"]["available"])

    def test_a_quote_is_variant_aware(self):
        plain = pod.quote(self.tee, 2500, size="M", color="White")
        big = pod.quote(self.tee, 2500, size="3XL", color="Black")
        self.assertEqual(plain["upcharge_cents"], 0)
        self.assertEqual(big["upcharge_cents"], 500)
        self.assertEqual(big["unit_price_cents"], 3000)
        # margin identical across variants
        self.assertEqual(plain["margin_cents"], big["margin_cents"])

    def test_products_with_no_upcharges_are_unaffected(self):
        mug = PrintProduct.objects.get(key="mug")
        self.assertEqual(mug.upcharge_cents("15oz", "Black"), 0)
        self.assertEqual(mug.landed_cost_for("15oz", "Black"), mug.landed_cost_cents)
        self.assertTrue(mug.variant_available("15oz", "Black"))

    def test_the_api_reports_variants_with_their_upcharges(self):
        resp = APIClient().get("/api/economy/pod/blanks/")
        tee = next(b for b in resp.data["blanks"] if b["key"] == "tee")
        sizes = {s["value"]: s["upcharge_cents"] for s in tee["variants"]["sizes"]}
        self.assertEqual(sizes["M"], 0)
        self.assertEqual(sizes["3XL"], 400)
        self.assertLess(tee["variants"]["price_from_cents"], tee["variants"]["price_to_cents"])

    def test_buying_an_upcharged_size_through_the_api_charges_the_extra(self):
        client = APIClient()
        client.force_authenticate(self.buyer)
        resp = client.post(f"/api/economy/pod/listings/{self.listing.id}/buy/",
                           {"size": "3XL", "color": "Black", "ship_to": ADDRESS},
                           format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["order"]["price_cents"], 3000)
        self.assertEqual(resp.data["order"]["upcharge_cents"], 500)
        self.assertEqual(resp.data["order"]["size"], "3XL")

    def test_a_size_the_printer_does_not_make_is_refused_with_the_list(self):
        client = APIClient()
        client.force_authenticate(self.buyer)
        resp = client.post(f"/api/economy/pod/listings/{self.listing.id}/buy/",
                           {"size": "5XL", "color": "Black", "ship_to": ADDRESS},
                           format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("size must be one of", resp.data["detail"])
        self.assertIn("variants", resp.data)


class BlankCatalogCoverageTests(TestCase):
    """What a creator can actually put a design on, and its process limits."""

    def setUp(self):
        pod.seed_blanks()

    def test_the_things_people_ask_for_are_all_there(self):
        keys = set(PrintProduct.objects.values_list("key", flat=True))
        for expected in ("tee", "tank", "long-sleeve", "hoodie", "crewneck",
                         "kimono", "bomber", "windbreaker", "denim-jacket",
                         "cap", "snapback", "trucker", "beanie",
                         "towel", "tote", "mug", "poster", "sticker", "vinyl-sleeve"):
            self.assertIn(expected, keys, expected)

    def test_every_blank_declares_a_known_print_method(self):
        for p in PrintProduct.objects.all():
            self.assertIn(p.print_method, pod.PRINT_METHODS, p.key)
            self.assertEqual(p.artwork["method"], p.print_method, p.key)

    def test_caps_and_jackets_are_embroidered_with_the_limits_that_implies(self):
        for key in ("cap", "snapback", "trucker", "beanie", "denim-jacket"):
            p = PrintProduct.objects.get(key=key)
            self.assertEqual(p.print_method, "embroidery", key)
            # embroidery is the one method with a hard colour ceiling
            self.assertEqual(p.artwork["max_colors"], 6, key)
            self.assertFalse(p.artwork["full_bleed"], key)
            self.assertIn("gradients", p.artwork["notes"])

    def test_the_kimono_and_jackets_are_all_over_print_and_need_full_bleed_art(self):
        for key in ("kimono", "bomber", "windbreaker"):
            p = PrintProduct.objects.get(key=key)
            self.assertEqual(p.print_method, "aop", key)
            self.assertTrue(p.artwork["full_bleed"], key)
            # cut-and-sew: a centred logo is the wrong design
            self.assertGreaterEqual(p.artwork["min_px"], 4000, key)
            self.assertIn("seams", p.artwork["notes"])

    def test_the_towel_is_sublimation_so_white_is_bare_fabric(self):
        towel = PrintProduct.objects.get(key="towel")
        self.assertEqual(towel.print_method, "sublimation")
        self.assertIn("no white ink", towel.artwork["notes"])

    def test_the_kimono_has_a_generous_size_run_not_exact_sizes(self):
        """Cut-and-sew garments come in paired sizes, not S/M/L/XL/2XL/3XL."""
        kimono = PrintProduct.objects.get(key="kimono")
        self.assertEqual(kimono.sizes, ["S/M", "L/XL", "2XL/3XL"])
        self.assertEqual(kimono.upcharge_cents("2XL/3XL"), 500)

    def test_every_blank_is_priceable_above_its_cost(self):
        for p in PrintProduct.objects.all():
            ok, detail = pod.validate_price(p, pod.suggested_price_cents(p))
            self.assertTrue(ok, f"{p.key}: {detail}")

    def test_jackets_cost_more_than_tees_so_the_suggested_price_follows(self):
        tee = PrintProduct.objects.get(key="tee")
        jacket = PrintProduct.objects.get(key="denim-jacket")
        self.assertGreater(jacket.landed_cost_cents, tee.landed_cost_cents)
        self.assertGreater(pod.suggested_price_cents(jacket),
                           pod.suggested_price_cents(tee))

    def test_the_api_publishes_the_methods_and_the_categories(self):
        data = APIClient().get("/api/economy/pod/blanks/").data
        self.assertIn("apparel", data["categories"])
        self.assertIn("accessories", data["categories"])
        self.assertIn("home", data["categories"])
        self.assertIn("embroidery", data["print_methods"])
        cap = next(b for b in data["blanks"] if b["key"] == "cap")
        self.assertEqual(cap["print_method"], "embroidery")
        self.assertEqual(cap["artwork"]["max_colors"], 6)
        self.assertIn("Baseball", cap["name"])

    def test_a_design_can_go_on_every_blank_in_the_catalog(self):
        """The pitch: one design, no inventory, every product."""
        seller = User.objects.create_user("maker", "m@e.com", "pw12345678")
        design = MerchDesign.objects.create(owner=seller, title="Logo", image=a_png())
        client = APIClient()
        client.force_authenticate(seller)
        for p in PrintProduct.objects.all():
            resp = client.post("/api/economy/pod/listings/",
                               {"design_id": design.id, "product": p.key,
                                "price_cents": pod.suggested_price_cents(p)},
                               format="json")
            self.assertEqual(resp.status_code, 201, f"{p.key}: {resp.content}")
        self.assertEqual(PrintListing.objects.count(), PrintProduct.objects.count())
        self.assertEqual(MerchDesign.objects.count(), 1)


class ReportingTests(TestCase):
    """Invoices, statements, and "what's selling" — the seller's paperwork."""

    def setUp(self):
        pod.seed_blanks()
        self.client = APIClient()
        self.seller = User.objects.create_user("maker", "m@e.com", "pw12345678")
        self.buyer = User.objects.create_user("fan", "f@e.com", "pw12345678")
        self.other = User.objects.create_user("nosy", "n@e.com", "pw12345678")
        w = wallet_for(self.buyer)
        w.money_cents = 100_000
        w.save()
        m = membership_for(self.buyer)
        m.tier = TIER_FREE
        m.save(update_fields=["tier", "updated_at"])
        design = MerchDesign.objects.create(owner=self.seller, title="Logo", image=a_png())
        self.tee = PrintListing.objects.create(
            design=design, product=PrintProduct.objects.get(key="tee"),
            seller=self.seller, title="Logo Tee", price_cents=2500)
        self.hoodie = PrintListing.objects.create(
            design=design, product=PrintProduct.objects.get(key="hoodie"),
            seller=self.seller, title="Logo Hoodie", price_cents=5500)

    def _buy(self, listing, **kw):
        kw.setdefault("ship_to", ADDRESS)
        order, err = pod.place_order(self.buyer, listing, **kw)
        self.assertIsNone(err, err)
        return order

    # ------------------------------------------------------------ invoice
    def test_an_invoice_reconciles_to_the_penny(self):
        order = self._buy(self.tee, size="L", color="White")
        doc = pod_reports.invoice(order, viewer=self.seller)
        t = doc["totals"]
        self.assertEqual(t["gross_cents"],
                         t["print_cost_cents"] + t["platform_fee_cents"] + t["seller_net_cents"])
        self.assertEqual(doc["number"], f"MCZ-POD-{order.id:06d}")
        self.assertEqual(doc["lines"][0]["description"], "Logo Tee")
        self.assertEqual(doc["lines"][0]["quantity"], 1)
        self.assertEqual(t["gross"], 25.0)

    def test_an_invoice_shows_the_variant_upcharge_as_its_own_line(self):
        """A buyer seeing $30 on a $25 shirt deserves to see why."""
        order = self._buy(self.tee, size="3XL", color="Black")
        doc = pod_reports.invoice(order, viewer=self.buyer)
        self.assertEqual(doc["totals"]["gross_cents"], 3000)
        upcharge = doc["lines"][1]
        self.assertIn("upcharge", upcharge["description"])
        self.assertEqual(upcharge["amount_cents"], 500)
        self.assertTrue(upcharge["included_above"])

    def test_quantity_shows_a_unit_price(self):
        order = self._buy(self.tee, size="M", color="White", quantity=4)
        doc = pod_reports.invoice(order, viewer=self.seller)
        self.assertEqual(doc["lines"][0]["quantity"], 4)
        self.assertEqual(doc["lines"][0]["unit_cents"], 2500)
        self.assertEqual(doc["lines"][0]["amount_cents"], 10_000)

    def test_the_invoice_says_it_is_not_a_tax_invoice(self):
        order = self._buy(self.tee, size="M", color="White")
        doc = pod_reports.invoice(order, viewer=self.seller)
        self.assertIn("no sales tax", doc["tax_note"].lower())

    def test_only_the_buyer_seller_and_owner_can_see_an_invoice(self):
        order = self._buy(self.tee, size="M", color="White")
        self.assertTrue(pod_reports.can_view(order, self.seller))
        self.assertTrue(pod_reports.can_view(order, self.buyer))
        self.assertFalse(pod_reports.can_view(order, self.other))
        # and the shipping address is withheld from anyone else
        self.assertNotIn("ship_to", pod_reports.invoice(order, viewer=self.other))
        self.assertEqual(pod_reports.invoice(order, viewer=self.seller)["ship_to"]["city"],
                         "Denver")

    def test_the_invoice_endpoint_404s_for_a_stranger(self):
        order = self._buy(self.tee, size="M", color="White")
        for user, expected in ((self.seller, 200), (self.buyer, 200), (self.other, 404)):
            self.client.force_authenticate(user)
            resp = self.client.get(f"/api/economy/pod/orders/{order.id}/invoice/")
            self.assertEqual(resp.status_code, expected, user.username)

    # ------------------------------------------------------------ what's selling
    def test_the_report_ranks_by_revenue_not_units(self):
        """Ten stickers and one hoodie are not the same result."""
        for _ in range(4):
            self._buy(self.tee, size="M", color="White")       # 4 x $25 = $100
        self._buy(self.hoodie, size="L", color="Sand")          # 1 x $55
        report = pod_reports.sales_report(self.seller)

        self.assertEqual(report["totals"]["orders"], 5)
        self.assertEqual(report["totals"]["units"], 5)
        self.assertEqual(report["totals"]["gross_cents"], 4 * 2500 + 5500)
        best = report["best_sellers"]
        self.assertEqual(best[0]["name"], "Logo Tee")
        self.assertEqual(best[0]["units"], 4)
        self.assertEqual(best[1]["name"], "Logo Hoodie")

    def test_the_report_breaks_down_by_size_and_color(self):
        """Which sizes move is what decides what you feature."""
        self._buy(self.tee, size="L", color="Black")
        self._buy(self.tee, size="L", color="White")
        self._buy(self.tee, size="3XL", color="Black")
        report = pod_reports.sales_report(self.seller)
        sizes = {r["size"]: r["units"] for r in report["by_size"]}
        self.assertEqual(sizes["L"], 2)
        self.assertEqual(sizes["3XL"], 1)
        colors = {r["color"]: r["units"] for r in report["by_color"]}
        self.assertEqual(colors["Black"], 2)
        self.assertEqual(colors["White"], 1)

    def test_the_report_groups_by_product_and_month(self):
        self._buy(self.tee, size="M", color="White")
        self._buy(self.hoodie, size="M", color="Sand")
        report = pod_reports.sales_report(self.seller)
        products = {r["product"]: r["units"] for r in report["by_product"]}
        self.assertEqual(products, {"tee": 1, "hoodie": 1})
        self.assertEqual(len(report["by_month"]), 1)
        self.assertEqual(report["by_month"][0]["orders"], 2)

    def test_the_report_totals_reconcile(self):
        self._buy(self.tee, size="2XL", color="Navy")
        self._buy(self.hoodie, size="3XL", color="Black")
        t = pod_reports.sales_report(self.seller)["totals"]
        self.assertEqual(t["gross_cents"],
                         t["print_cost_cents"] + t["fee_cents"] + t["net_cents"])

    def test_cancelled_orders_leave_revenue_but_stay_visible(self):
        keep = self._buy(self.tee, size="M", color="White")
        binned = self._buy(self.tee, size="M", color="White")
        pod.advance(binned, PrintOrder.STATUS_CANCELLED)

        report = pod_reports.sales_report(self.seller)
        self.assertEqual(report["totals"]["orders"], 1)
        self.assertEqual(report["totals"]["gross_cents"], keep.price_cents)
        # not hidden — a report that buries cancellations makes them unnoticeable
        self.assertEqual(report["cancelled"]["orders"], 1)
        self.assertEqual(report["by_status"]["cancelled"], 1)

    def test_the_report_counts_what_still_needs_making(self):
        self._buy(self.tee, size="M", color="White")
        shipped = self._buy(self.tee, size="L", color="White")
        pod.advance(shipped, PrintOrder.STATUS_SHIPPED)
        report = pod_reports.sales_report(self.seller)
        self.assertEqual(report["awaiting_fulfilment"], 1)

    def test_a_seller_with_no_sales_gets_zeroes_not_an_error(self):
        report = pod_reports.sales_report(self.other)
        self.assertEqual(report["totals"]["orders"], 0)
        self.assertEqual(report["totals"]["gross_cents"], 0)
        self.assertEqual(report["best_sellers"], [])
        self.assertEqual(report["by_month"], [])

    def test_a_seller_only_ever_sees_their_own_sales(self):
        self._buy(self.tee, size="M", color="White")
        self.client.force_authenticate(self.other)
        data = self.client.get("/api/economy/pod/sales/").data
        self.assertEqual(data["totals"]["orders"], 0)
        self.assertEqual(data["seller"], "nosy")

    def test_the_report_endpoint_validates_its_dates(self):
        self.client.force_authenticate(self.seller)
        self.assertEqual(
            self.client.get("/api/economy/pod/sales/?from=last-tuesday").status_code, 400)
        self.assertEqual(
            self.client.get("/api/economy/pod/sales/?to=13/1/2026").status_code, 400)
        self.assertEqual(
            self.client.get("/api/economy/pod/sales/?from=2026-01-01&to=2026-12-31").status_code,
            200)

    def test_a_date_window_excludes_sales_outside_it(self):
        from datetime import timedelta

        from django.utils import timezone as tz

        order = self._buy(self.tee, size="M", color="White")
        PrintOrder.objects.filter(pk=order.pk).update(
            created_at=tz.now() - timedelta(days=90))
        recent = pod_reports.parse_day((tz.now() - timedelta(days=7)).date().isoformat())
        self.assertEqual(pod_reports.sales_report(self.seller, start=recent)["totals"]["orders"], 0)
        self.assertEqual(pod_reports.sales_report(self.seller)["totals"]["orders"], 1)

    # ------------------------------------------------------------ statement
    def test_a_monthly_statement_lists_every_sale_and_balances(self):
        from django.utils import timezone as tz

        self._buy(self.tee, size="M", color="White")
        self._buy(self.hoodie, size="2XL", color="Black")
        now = tz.now()
        st = pod_reports.statement(self.seller, now.year, now.month)

        self.assertEqual(len(st["lines"]), 2)
        self.assertTrue(st["balanced"])
        self.assertEqual(st["period"], f"{now.year:04d}-{now.month:02d}")
        self.assertEqual(st["number"], f"MCZ-STMT-{self.seller.id}-{now.year}{now.month:02d}")
        self.assertEqual(st["payout_cents"], st["totals"]["net_cents"])
        self.assertEqual(st["totals"]["gross_cents"],
                         sum(l["gross_cents"] for l in st["lines"]))
        # every line carries the invoice number it came from
        self.assertTrue(all(l["invoice"].startswith("MCZ-POD-") for l in st["lines"]))

    def test_a_statement_for_a_quiet_month_is_empty_and_still_balances(self):
        st = pod_reports.statement(self.seller, 2020, 2)
        self.assertEqual(st["lines"], [])
        self.assertEqual(st["payout_cents"], 0)
        self.assertTrue(st["balanced"])

    def test_a_december_statement_rolls_the_year_over(self):
        st = pod_reports.statement(self.seller, 2026, 12)
        self.assertEqual(st["to"].year, 2027)
        self.assertEqual(st["to"].month, 1)

    def test_the_statement_endpoint_defaults_to_this_month_and_validates(self):
        self._buy(self.tee, size="M", color="White")
        self.client.force_authenticate(self.seller)
        resp = self.client.get("/api/economy/pod/statement/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["statement"]["lines"]), 1)

        self.assertEqual(self.client.get("/api/economy/pod/statement/?month=2026-13").status_code,
                         400)
        self.assertEqual(self.client.get("/api/economy/pod/statement/?month=nope").status_code,
                         400)
        self.assertEqual(
            self.client.get("/api/economy/pod/statement/?month=2026-01").status_code, 200)

    def test_reports_need_a_login(self):
        for url in ("/api/economy/pod/sales/", "/api/economy/pod/statement/"):
            self.assertEqual(APIClient().get(url).status_code, 401, url)


class RefundTests(TestCase):
    """Cancelling a paid order has to put the money back — all three legs."""

    def setUp(self):
        pod.seed_blanks()
        self.client = APIClient()
        self.seller = User.objects.create_user("maker", "m@e.com", "pw12345678")
        self.buyer = User.objects.create_user("fan", "f@e.com", "pw12345678")
        self.other = User.objects.create_user("nosy", "n@e.com", "pw12345678")
        w = wallet_for(self.buyer)
        w.money_cents = 20_000
        w.save()
        m = membership_for(self.buyer)
        m.tier = TIER_FREE
        m.save(update_fields=["tier", "updated_at"])
        design = MerchDesign.objects.create(owner=self.seller, title="Logo", image=a_png())
        self.listing = PrintListing.objects.create(
            design=design, product=PrintProduct.objects.get(key="tee"),
            seller=self.seller, title="Logo Tee", price_cents=2500)

    def _order(self, **kw):
        kw.setdefault("ship_to", ADDRESS)
        kw.setdefault("size", "L")
        kw.setdefault("color", "White")
        o, err = pod.place_order(self.buyer, self.listing, **kw)
        self.assertIsNone(err, err)
        return o

    def test_a_refund_reverses_every_leg_exactly(self):
        before_buyer = wallet_for(self.buyer).money_cents
        order = self._order()
        self.assertEqual(wallet_for(self.buyer).money_cents, before_buyer - 2500)
        seller_after_sale = wallet_for(self.seller).money_cents

        ok, detail = pod.refund_order(order, reason="wrong size", by=self.buyer)
        self.assertTrue(ok, detail)
        # buyer whole again, seller's credit clawed back
        self.assertEqual(wallet_for(self.buyer).money_cents, before_buyer)
        self.assertEqual(wallet_for(self.seller).money_cents,
                         seller_after_sale - order.seller_cents)
        self.assertEqual(order.status, PrintOrder.STATUS_CANCELLED)
        self.assertIn("wrong size", order.note)

    def test_the_refund_is_recorded_on_both_sides(self):
        order = self._order()
        pod.refund_order(order, reason="changed mind")
        notes = list(Transaction.objects.filter(
            note__icontains="refund").values_list("user_id", "amount_cents"))
        self.assertIn((self.buyer.id, order.price_cents), notes)
        self.assertIn((self.seller.id, -order.seller_cents), notes)

    def test_a_refund_removes_the_sale_from_revenue_but_not_from_sight(self):
        keep = self._order()
        binned = self._order()
        pod.refund_order(binned)
        report = pod_reports.sales_report(self.seller)
        self.assertEqual(report["totals"]["orders"], 1)
        self.assertEqual(report["totals"]["gross_cents"], keep.price_cents)
        self.assertEqual(report["cancelled"]["orders"], 1)

    def test_a_submitted_order_can_still_be_refunded(self):
        order = self._order()
        pod.advance(order, PrintOrder.STATUS_SUBMITTED)
        self.assertTrue(pod.refundable(order))
        self.assertTrue(pod.refund_order(order)[0])

    def test_an_order_already_being_made_cannot_be_refunded(self):
        """There's a real garment involved by then — silently refunding it would
        have the platform eat the print cost with nothing recording it."""
        for state in (PrintOrder.STATUS_IN_PRODUCTION, PrintOrder.STATUS_SHIPPED):
            order = self._order()
            pod.advance(order, state)
            self.assertFalse(pod.refundable(order))
            ok, detail = pod.refund_order(order)
            self.assertFalse(ok)
            self.assertIn("can't be refunded here", detail)
            self.assertEqual(order.status, state)

    def test_a_refund_cannot_be_run_twice(self):
        order = self._order()
        self.assertTrue(pod.refund_order(order)[0])
        paid_back = wallet_for(self.buyer).money_cents
        ok, detail = pod.refund_order(order)
        self.assertFalse(ok)
        self.assertIn("already cancelled", detail)
        # and no second credit landed
        self.assertEqual(wallet_for(self.buyer).money_cents, paid_back)

    def test_the_buyer_gets_their_money_back_even_if_the_seller_spent_theirs(self):
        """Wallets can't go negative on this platform, so the clawback takes what
        is there and the shortfall is RECORDED rather than swallowed. The buyer is
        owed their money back regardless of what the seller did with theirs."""
        order = self._order()
        sw = wallet_for(self.seller)
        sw.money_cents = 0                    # seller already spent it
        sw.save()

        self.assertTrue(pod.refund_order(order)[0])
        self.assertEqual(wallet_for(self.buyer).money_cents, 20_000)   # whole again
        self.assertEqual(wallet_for(self.seller).money_cents, 0)       # not negative
        order.refresh_from_db()
        self.assertEqual(order.clawback_shortfall_cents, order.seller_cents)
        self.assertIn("not recovered", order.note)

    def test_a_partial_clawback_takes_what_is_there(self):
        order = self._order()
        sw = wallet_for(self.seller)
        sw.money_cents = 100                  # some, not all
        sw.save()
        pod.refund_order(order)
        order.refresh_from_db()
        self.assertEqual(wallet_for(self.seller).money_cents, 0)
        self.assertEqual(order.clawback_shortfall_cents, order.seller_cents - 100)

    def test_a_normal_refund_records_no_shortfall(self):
        order = self._order()
        pod.refund_order(order)
        order.refresh_from_db()
        self.assertEqual(order.clawback_shortfall_cents, 0)
        self.assertNotIn("not recovered", order.note)

    def test_either_side_can_refund_but_a_stranger_cannot(self):
        for user, expected in ((self.buyer, 200), (self.seller, 200), (self.other, 404)):
            order = self._order()
            self.client.force_authenticate(user)
            resp = self.client.post(f"/api/economy/pod/orders/{order.id}/refund/",
                                    {"reason": "test"}, format="json")
            self.assertEqual(resp.status_code, expected, user.username)

    def test_the_endpoint_reports_refundability_when_it_refuses(self):
        order = self._order()
        pod.advance(order, PrintOrder.STATUS_SHIPPED)
        self.client.force_authenticate(self.seller)
        resp = self.client.post(f"/api/economy/pod/orders/{order.id}/refund/", {},
                                format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.data["refundable"])

    def test_orders_advertise_whether_they_can_be_refunded(self):
        self._order()
        self.client.force_authenticate(self.buyer)
        order = self.client.get("/api/economy/pod/orders/").data["orders"][0]
        self.assertTrue(order["refundable"])


class ArtworkCheckTests(TestCase):
    """Warn about artwork that won't survive the process — before it's printed."""

    def setUp(self):
        pod.seed_blanks()
        self.client = APIClient()
        self.seller = User.objects.create_user("maker", "m@e.com", "pw12345678")
        self.client.force_authenticate(self.seller)

    def _design(self, width, height, alpha=False, title="Art"):
        d = MerchDesign.objects.create(owner=self.seller, title=title, image=a_png())
        d.width, d.height, d.has_alpha = width, height, alpha
        d.save(update_fields=["width", "height", "has_alpha"])
        return d

    def test_upload_measures_the_image(self):
        resp = self.client.post("/api/economy/pod/designs/",
                                {"title": "Logo", "image": a_png()}, format="multipart")
        self.assertEqual(resp.status_code, 201)
        # the 1x1 test PNG — tiny, but measured
        self.assertEqual(resp.data["design"]["width"], 1)
        self.assertEqual(resp.data["design"]["height"], 1)
        self.assertTrue(resp.data["suitability"]["measured"])
        # and 1px is good enough for nothing
        self.assertEqual(resp.data["suitability"]["good_for"], [])

    def test_a_big_square_design_passes_the_forgiving_processes(self):
        d = self._design(4500, 4500, alpha=True)
        poster = PrintProduct.objects.get(key="poster")
        ok, problems = d.check_for(poster)
        self.assertTrue(ok, problems)

    def test_a_low_res_design_is_flagged_for_a_big_print(self):
        d = self._design(900, 900, alpha=True)
        ok, problems = d.check_for(PrintProduct.objects.get(key="poster"))
        self.assertFalse(ok)
        self.assertIn("900px", problems[0])
        self.assertIn("look soft", problems[0])

    def test_the_short_side_is_what_counts(self):
        """A 6000x400 banner is not a 6000px design."""
        d = self._design(6000, 400, alpha=True)
        self.assertEqual(d.shortest_side, 400)
        ok, _ = d.check_for(PrintProduct.objects.get(key="tee"))
        self.assertFalse(ok)

    def test_all_over_print_wants_square_opaque_artwork(self):
        kimono = PrintProduct.objects.get(key="kimono")
        wrong = self._design(6000, 2000, alpha=True)
        ok, problems = wrong.check_for(kimono)
        self.assertFalse(ok)
        joined = " ".join(problems)
        self.assertIn("roughly square", joined)
        self.assertIn("bare fabric", joined)      # transparency warning

        right = self._design(4500, 4500, alpha=False)
        ok, problems = right.check_for(kimono)
        self.assertTrue(ok, problems)

    def test_embroidery_always_warns_about_colours(self):
        """Even a perfect file can't be a photograph on a cap."""
        d = self._design(4000, 4000, alpha=True)
        ok, problems = d.check_for(PrintProduct.objects.get(key="cap"))
        self.assertFalse(ok)
        self.assertIn("6 colours maximum", " ".join(problems))

    def test_an_unmeasured_legacy_design_is_not_judged(self):
        d = self._design(0, 0)
        ok, problems = d.check_for(PrintProduct.objects.get(key="poster"))
        self.assertTrue(ok)
        self.assertEqual(problems, [])

    def test_suitability_splits_the_catalog_into_good_and_warned(self):
        d = self._design(4500, 4500, alpha=False)
        s = pod.suitability(d)
        self.assertIn("kimono", s["good_for"])
        self.assertTrue(s["warnings_for"])
        warned = {r["product"] for r in s["warnings_for"]}
        self.assertIn("cap", warned)        # embroidery always warns
        self.assertEqual(s["shortest_side"], 4500)

    def test_listing_warns_but_does_not_refuse(self):
        """Image analysis can't tell a deliberately lo-fi design from a mistake,
        so a warning a creator can override beats a refusal that's wrong."""
        d = self._design(500, 500, alpha=True)
        resp = self.client.post("/api/economy/pod/listings/",
                                {"design_id": d.id, "product": "hoodie",
                                 "price_cents": 5500}, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertFalse(resp.data["artwork_ok"])
        self.assertTrue(resp.data["artwork_warnings"])
        self.assertTrue(PrintListing.objects.filter(pk=resp.data["listing"]["id"]).exists())

    def test_a_good_listing_reports_no_warnings(self):
        d = self._design(4500, 4500, alpha=True)
        resp = self.client.post("/api/economy/pod/listings/",
                                {"design_id": d.id, "product": "poster",
                                 "price_cents": 2999}, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.data["artwork_ok"])
        self.assertEqual(resp.data["artwork_warnings"], [])
