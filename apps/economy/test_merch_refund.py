"""MerchZ had no refund path at all — once a `MerchPurchase` row existed
there was nowhere for "item misdescribed" or "buyer regrets it" to go.
Corey's call: the SELLER eats the developer tax. A refund gives the buyer
back the FULL price, and the seller's wallet is debited that same full
amount, not just the net they were paid — so the platform's cut is never
handed back to anyone on a refund.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .models import MerchItem, MerchPurchase, wallet_for

User = get_user_model()
PW = "hunter2hunter2"


class MerchRefundTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user("refundseller", "rs@x.test", PW)
        self.buyer = User.objects.create_user("refundbuyer", "rb@x.test", PW)
        # Prior earnings, unrelated to this sale — a seller who refunds a
        # sale has to come up with the tax gap from SOMEWHERE, since they
        # only ever received the net. A seller with nothing else is the
        # separate, deliberate case below (`test_a_seller_who_already_spent...`).
        self.seller_before_sale = 500
        sw = wallet_for(self.seller)
        sw.money_cents = self.seller_before_sale
        sw.save(update_fields=["money_cents"])
        w = wallet_for(self.buyer)
        w.money_cents = 1000
        w.save(update_fields=["money_cents"])
        self.item = MerchItem.objects.create(seller=self.seller, title="Hoodie",
                                             price_cents=1000, active=True)
        self.bc = APIClient(); self.bc.force_authenticate(self.buyer)
        self.sc = APIClient(); self.sc.force_authenticate(self.seller)
        r = self.bc.post(f"/api/economy/merch/{self.item.pk}/buy/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.purchase = MerchPurchase.objects.get(item=self.item, buyer=self.buyer)
        # Whatever the dev tax came out to, the seller only HOLDS the net.
        self.net = self.purchase.price_cents - self.purchase.dev_tax_cents

    def test_the_seller_sees_the_sale_in_their_own_list(self):
        r = self.sc.get("/api/economy/merch/sales/")
        self.assertEqual(r.status_code, 200)
        sale = r.data["sales"][0]
        self.assertEqual(sale["buyer"], "refundbuyer")
        self.assertEqual(sale["price_cents"], 1000)
        self.assertFalse(sale["refunded"])

    def test_someone_elses_sale_is_not_visible_or_refundable(self):
        stranger = User.objects.create_user("merchstranger", "mstr@x.test", PW)
        c = APIClient(); c.force_authenticate(stranger)
        self.assertEqual(c.get("/api/economy/merch/sales/").data["sales"], [])
        r = c.post(f"/api/economy/merch/purchases/{self.purchase.pk}/refund/", {}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_the_buyer_cannot_refund_their_own_purchase(self):
        r = self.bc.post(f"/api/economy/merch/purchases/{self.purchase.pk}/refund/", {}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_the_cost_preview_shows_the_full_price_not_just_net(self):
        r = self.sc.get(f"/api/economy/merch/purchases/{self.purchase.pk}/refund/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["price_cents"], 1000)
        self.assertEqual(r.data["net_received_cents"], self.net)

    def test_a_refund_gives_the_buyer_back_the_full_price(self):
        r = self.sc.post(f"/api/economy/merch/purchases/{self.purchase.pk}/refund/",
                         {"reason": "wrong size"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(wallet_for(self.buyer).money_cents, 1000)
        self.purchase.refresh_from_db()
        self.assertTrue(self.purchase.refunded)
        self.assertEqual(self.purchase.refund_reason, "wrong size")

    def test_the_seller_pays_back_the_full_price_not_just_what_they_received(self):
        """The dev tax eaten: the seller's wallet after a refund is worse
        off than before the SALE by exactly the tax amount, because they
        only ever held the net of the sale but must repay the full price."""
        self.assertEqual(wallet_for(self.seller).money_cents, self.seller_before_sale + self.net)
        self.sc.post(f"/api/economy/merch/purchases/{self.purchase.pk}/refund/", {}, format="json")
        self.assertEqual(wallet_for(self.seller).money_cents,
                        self.seller_before_sale - self.purchase.dev_tax_cents)

    def test_a_refund_cannot_happen_twice(self):
        self.sc.post(f"/api/economy/merch/purchases/{self.purchase.pk}/refund/", {}, format="json")
        r = self.sc.post(f"/api/economy/merch/purchases/{self.purchase.pk}/refund/", {}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_a_seller_who_already_spent_the_proceeds_is_refused_not_overdrawn(self):
        w = wallet_for(self.seller)
        w.money_cents = 0
        w.save(update_fields=["money_cents"])
        r = self.sc.post(f"/api/economy/merch/purchases/{self.purchase.pk}/refund/", {}, format="json")
        self.assertEqual(r.status_code, 402)
        self.purchase.refresh_from_db()
        self.assertFalse(self.purchase.refunded)
        self.assertEqual(wallet_for(self.buyer).money_cents, 0)

    def test_staff_can_refund_on_the_sellers_behalf(self):
        staff = User.objects.create_user("merchstaff", "mstf@x.test", PW, is_staff=True)
        c = APIClient(); c.force_authenticate(staff)
        r = c.post(f"/api/economy/merch/purchases/{self.purchase.pk}/refund/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
