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

from apps.economy import pod
from apps.economy.models import (TIER_FREE, MerchDesign, PrintListing,
                                 PrintOrder, PrintProduct, membership_for,
                                 wallet_for)

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
