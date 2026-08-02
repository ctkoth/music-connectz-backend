"""Tests for Google Play Billing verification.

Google is stubbed, not called — a test that needs a service account isn't a test.
What's asserted is the part that would cost real money if it were wrong: the
client is never trusted, a token grants exactly once, and a purchase Google
doesn't fully vouch for grants nothing.
"""
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import play_billing as pb
from apps.economy.models import (TIER_FREE, TIER_PREMIUM, TIER_STATZ,
                                 PlayPurchase, membership_for, wallet_for)

User = get_user_model()

FAKE_SA = json.dumps({
    "type": "service_account",
    "client_email": "play@example.iam.gserviceaccount.com",
    "private_key": "-----BEGIN PRIVATE KEY-----\nnot-a-real-key\n-----END PRIVATE KEY-----\n",
})


def product_ok(account_id="", state=pb.STATE_PURCHASED, acknowledged=0):
    return {
        "purchaseState": state,
        "orderId": "GPA.1234-5678",
        "obfuscatedExternalAccountId": account_id,
        "acknowledgementState": acknowledged,
        "purchaseTimeMillis": "1770000000000",
    }


def sub_ok(product="premium_month", account_id="",
           state="SUBSCRIPTION_STATE_ACTIVE"):
    return {
        "subscriptionState": state,
        "latestOrderId": "GPA.9999",
        "externalAccountIdentifiers": {"obfuscatedExternalAccountId": account_id},
        "lineItems": [{"productId": product, "expiryTime": "2027-01-01T00:00:00Z"}],
        "acknowledgementState": "ACKNOWLEDGEMENT_STATE_PENDING",
    }


class _Resp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class ConfigTests(TestCase):
    def test_not_configured_without_a_service_account(self):
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("PLAY_SERVICE_ACCOUNT_JSON", None)
            os.environ.pop("PLAY_SERVICE_ACCOUNT_FILE", None)
            self.assertFalse(pb.configured())

    def test_configured_with_inline_json(self):
        with patch.dict("os.environ", {"PLAY_SERVICE_ACCOUNT_JSON": FAKE_SA}):
            self.assertTrue(pb.configured())
            self.assertEqual(pb.service_account()["client_email"],
                             "play@example.iam.gserviceaccount.com")

    def test_malformed_or_incomplete_json_is_not_configured(self):
        for bad in ("not json", "{}", json.dumps({"client_email": "x"})):
            with patch.dict("os.environ", {"PLAY_SERVICE_ACCOUNT_JSON": bad}):
                self.assertFalse(pb.configured(), bad)

    def test_the_package_name_defaults_to_the_android_app(self):
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("PLAY_PACKAGE_NAME", None)
            self.assertEqual(pb.package_name(), "net.musicconnectz.app")


class CatalogTests(TestCase):
    def test_every_product_is_complete_and_typed(self):
        for pid, spec in pb.PLAY_PRODUCTS.items():
            self.assertEqual(pid, pid.strip().lower(), pid)
            self.assertIn(spec["kind"], (pb.KIND_WALLET, pb.KIND_PREMIUM,
                                         pb.KIND_STATZ, pb.KIND_LIFETIME), pid)
            self.assertIn(spec["type"], ("product", "subscription"), pid)
            self.assertGreater(spec["cents"], 0, pid)
            self.assertTrue(spec["name"].strip(), pid)

    def test_subscription_products_are_the_tier_ones(self):
        subs = {p for p, s in pb.PLAY_PRODUCTS.items() if s["type"] == "subscription"}
        self.assertEqual(subs, {"premium_month", "premium_year",
                                "statz_month", "statz_year"})
        # lifetime is a one-time product, not a subscription
        self.assertEqual(pb.PLAY_PRODUCTS["statz_lifetime"]["type"], "product")

    def test_grant_values_match_the_platform_catalog(self):
        """A Play product that grants a different amount than the web price is a
        pricing bug nobody notices until a member complains."""
        from apps.economy.catalog import (LIFETIME_PRICE_CENTS,
                                          PREMIUM_MONTH_CENTS, PREMIUM_YEAR_CENTS)
        self.assertEqual(pb.PLAY_PRODUCTS["premium_month"]["cents"], PREMIUM_MONTH_CENTS)
        self.assertEqual(pb.PLAY_PRODUCTS["premium_year"]["cents"], PREMIUM_YEAR_CENTS)
        self.assertEqual(pb.PLAY_PRODUCTS["statz_lifetime"]["cents"], LIFETIME_PRICE_CENTS)

    def test_the_products_endpoint_is_public(self):
        resp = APIClient().get("/api/economy/play/products/")
        self.assertEqual(resp.status_code, 200)
        ids = [p["product_id"] for p in resp.data["products"]]
        self.assertIn("topup_1000", ids)
        self.assertIn("premium_month", ids)


class RedeemTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("fan", "f@e.com", "pw12345678")
        self.client.force_authenticate(self.user)
        self.env = patch.dict("os.environ", {
            "PLAY_SERVICE_ACCOUNT_JSON": FAKE_SA,
            "PLAY_PACKAGE_NAME": "net.musicconnectz.app",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.token = patch.object(pb, "access_token", return_value="ya29.fake")
        self.token.start()
        self.addCleanup(self.token.stop)

    def _verify(self, product_id, token="tok-1"):
        return self.client.post("/api/economy/play/verify/",
                                {"product_id": product_id, "purchase_token": token},
                                format="json")

    # ------------------------------------------------------------ happy paths
    def test_a_wallet_topup_credits_the_wallet_once(self):
        before = wallet_for(self.user).money_cents
        with patch("requests.get", return_value=_Resp(product_ok())), \
                patch("requests.post", return_value=_Resp({})):
            resp = self._verify("topup_1000")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.data["purchase"]["granted"])
        self.assertFalse(resp.data["purchase"]["duplicate"])
        self.assertGreater(wallet_for(self.user).money_cents, before)
        self.assertEqual(PlayPurchase.objects.count(), 1)

    def test_a_subscription_sets_the_tier(self):
        self.assertEqual(membership_for(self.user).tier, TIER_FREE)
        with patch("requests.get", return_value=_Resp(sub_ok("premium_month"))), \
                patch("requests.post", return_value=_Resp({})):
            resp = self._verify("premium_month")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(membership_for(self.user).tier, TIER_PREMIUM)
        self.assertEqual(membership_for(self.user).last_payment_kind, "play_premium_month")

    def test_a_statz_subscription_sets_statz(self):
        with patch("requests.get", return_value=_Resp(sub_ok("statz_year"))), \
                patch("requests.post", return_value=_Resp({})):
            self._verify("statz_year")
        self.assertEqual(membership_for(self.user).tier, TIER_STATZ)

    def test_lifetime_is_granted_as_lifetime(self):
        with patch("requests.get", return_value=_Resp(product_ok())), \
                patch("requests.post", return_value=_Resp({})):
            resp = self._verify("statz_lifetime")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(membership_for(self.user).lifetime)

    def test_a_purchase_is_acknowledged_after_it_is_granted(self):
        """Play auto-refunds anything unacknowledged for three days."""
        with patch("requests.get", return_value=_Resp(product_ok())), \
                patch("requests.post", return_value=_Resp({})) as post:
            self._verify("topup_500")
        acked = [c for c in post.call_args_list if ":acknowledge" in c.args[0]]
        self.assertEqual(len(acked), 1)
        self.assertTrue(PlayPurchase.objects.get().acknowledged)

    # ------------------------------------------------------------ trust
    def test_the_client_cannot_declare_its_own_value(self):
        """The product id maps to a value server-side. A client claiming a $50
        pack gets whatever PLAY_PRODUCTS says that id is worth."""
        with patch("requests.get", return_value=_Resp(product_ok())), \
                patch("requests.post", return_value=_Resp({})):
            self.client.post("/api/economy/play/verify/",
                             {"product_id": "topup_500", "purchase_token": "t",
                              "cents": 500_000, "value_cents": 500_000,
                              "amount": 999}, format="json")
        self.assertEqual(PlayPurchase.objects.get().value_cents, 500)

    def test_an_unknown_product_is_refused(self):
        resp = self._verify("topup_1000000")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Unknown product", resp.data["detail"])
        self.assertEqual(PlayPurchase.objects.count(), 0)

    def test_a_purchase_bound_to_another_account_is_refused(self):
        """A leaked token must not be redeemable by whoever holds it."""
        other = User.objects.create_user("thief", "t@e.com", "pw12345678")
        with patch("requests.get", return_value=_Resp(product_ok(account_id=str(other.id)))):
            resp = self._verify("topup_1000")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("different account", resp.data["detail"])
        self.assertEqual(PlayPurchase.objects.count(), 0)

    def test_a_purchase_bound_to_this_account_is_accepted(self):
        with patch("requests.get",
                   return_value=_Resp(product_ok(account_id=str(self.user.id)))), \
                patch("requests.post", return_value=_Resp({})):
            self.assertEqual(self._verify("topup_1000").status_code, 200)

    def test_a_subscription_token_for_a_different_product_is_refused(self):
        """The token proves entitlement to what Google lists on it, not to what
        the client typed — otherwise a cheap sub could claim an expensive tier."""
        with patch("requests.get", return_value=_Resp(sub_ok("premium_month"))):
            resp = self._verify("statz_year")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("premium_month", resp.data["detail"])
        self.assertEqual(membership_for(self.user).tier, TIER_FREE)

    # ------------------------------------------------------------ bad purchases
    def test_a_pending_purchase_grants_nothing(self):
        """purchaseState 2 = the member chose cash at a shop. Not a sale yet."""
        before = wallet_for(self.user).money_cents
        with patch("requests.get",
                   return_value=_Resp(product_ok(state=pb.STATE_PENDING))):
            resp = self._verify("topup_2500")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("still pending", resp.data["detail"])
        self.assertEqual(wallet_for(self.user).money_cents, before)

    def test_a_cancelled_purchase_grants_nothing(self):
        with patch("requests.get",
                   return_value=_Resp(product_ok(state=pb.STATE_CANCELLED))):
            resp = self._verify("topup_2500")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("cancelled or refunded", resp.data["detail"])

    def test_an_expired_subscription_grants_nothing(self):
        with patch("requests.get",
                   return_value=_Resp(sub_ok(state="SUBSCRIPTION_STATE_EXPIRED"))):
            resp = self._verify("premium_month")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("not active", resp.data["detail"])
        self.assertEqual(membership_for(self.user).tier, TIER_FREE)

    def test_a_grace_period_subscription_still_counts(self):
        """Their card failed but Play is retrying. Cutting a paying member off
        mid-retry turns a billing blip into a cancellation."""
        with patch("requests.get", return_value=_Resp(
                sub_ok(state="SUBSCRIPTION_STATE_IN_GRACE_PERIOD"))), \
                patch("requests.post", return_value=_Resp({})):
            resp = self._verify("premium_month")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(membership_for(self.user).tier, TIER_PREMIUM)

    def test_a_token_google_does_not_know_is_refused(self):
        with patch("requests.get", return_value=_Resp({}, status_code=404)):
            resp = self._verify("topup_1000")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("does not recognise", resp.data["detail"])

    def test_google_being_unreachable_does_not_grant_anything(self):
        import requests as rq
        with patch("requests.get", side_effect=rq.RequestException("timeout")):
            resp = self._verify("topup_1000")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(PlayPurchase.objects.count(), 0)

    # ------------------------------------------------------------ idempotency
    def test_the_same_token_credits_exactly_once(self):
        """A client that doesn't get our response WILL retry."""
        with patch("requests.get", return_value=_Resp(product_ok())), \
                patch("requests.post", return_value=_Resp({})):
            first = self._verify("topup_1000", token="same")
            after_first = wallet_for(self.user).money_cents
            second = self._verify("topup_1000", token="same")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertFalse(first.data["purchase"]["duplicate"])
        self.assertTrue(second.data["purchase"]["duplicate"])
        self.assertEqual(wallet_for(self.user).money_cents, after_first)
        self.assertEqual(PlayPurchase.objects.count(), 1)

    def test_a_replay_by_a_different_member_cannot_double_grant(self):
        with patch("requests.get", return_value=_Resp(product_ok())), \
                patch("requests.post", return_value=_Resp({})):
            self._verify("topup_1000", token="shared")
            other = User.objects.create_user("other", "o@e.com", "pw12345678")
            self.client.force_authenticate(other)
            resp = self._verify("topup_1000", token="shared")
        # the token is already spent, so nothing new is granted
        self.assertTrue(resp.data["purchase"]["duplicate"])
        self.assertEqual(wallet_for(other).money_cents, 0)
        self.assertEqual(PlayPurchase.objects.count(), 1)

    def test_a_failed_acknowledge_does_not_undo_the_grant(self):
        """The member has their goods. A refundable purchase is recoverable; a
        granted-but-unrecorded one is not."""
        import requests as rq
        with patch("requests.get", return_value=_Resp(product_ok())), \
                patch("requests.post", side_effect=rq.RequestException("boom")):
            resp = self._verify("topup_1000")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["purchase"]["granted"])
        self.assertFalse(resp.data["purchase"]["acknowledged"])
        self.assertTrue(PlayPurchase.objects.get().granted)

    # ------------------------------------------------------------ endpoint
    def test_verify_needs_a_login(self):
        self.assertEqual(APIClient().post("/api/economy/play/verify/", {},
                                          format="json").status_code, 401)

    def test_missing_fields_are_refused(self):
        for body in ({}, {"product_id": "topup_500"}, {"purchase_token": "t"}):
            resp = self.client.post("/api/economy/play/verify/", body, format="json")
            self.assertEqual(resp.status_code, 400, body)

    def test_purchases_are_listed_back_as_receipts(self):
        with patch("requests.get", return_value=_Resp(product_ok())), \
                patch("requests.post", return_value=_Resp({})):
            self._verify("topup_2500")
        rows = self.client.get("/api/economy/play/purchases/").data["purchases"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["product_id"], "topup_2500")
        self.assertEqual(rows[0]["value_cents"], 2500)
        self.assertEqual(rows[0]["order_id"], "GPA.1234-5678")


class UnconfiguredTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(
            User.objects.create_user("fan", "f@e.com", "pw12345678"))

    def test_verify_reports_503_so_the_client_falls_back_to_web_checkout(self):
        import os
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("PLAY_SERVICE_ACCOUNT_JSON", None)
            os.environ.pop("PLAY_SERVICE_ACCOUNT_FILE", None)
            resp = self.client.post("/api/economy/play/verify/",
                                    {"product_id": "topup_500",
                                     "purchase_token": "t"}, format="json")
        self.assertEqual(resp.status_code, 503)
        self.assertFalse(resp.data["configured"])
        self.assertEqual(PlayPurchase.objects.count(), 0)
