"""The Stripe webhook — the events, and the shapes they actually arrive in.

Written after every handled event had been answering 500 in production. Two
separate causes, both invisible from inside the app:

1. `stripe.Webhook.construct_event` returns a `StripeObject`, and StripeObject
   stopped being a `dict` subclass. It kept `__getitem__` and lost `.get()`, so
   every `obj.get("metadata")` in the view raised AttributeError. Nothing
   pinned the library — `requirements.txt` said `stripe>=8.0` — so this
   arrived on a deploy that changed no code.
2. Stripe moved `invoice.subscription` under `parent.subscription_details` in
   API version 2025-03-31.basil, and the webhook destination is pinned to
   2026-04-22.dahlia.

So these tests go through the REAL view with a REAL `stripe.Event`, not a
hand-made dict. A dict fixture passes happily against code that 500s against
Stripe, which is exactly how this got to production — the fixture, not the
handler, was doing the work.

Only the signature check is faked. Verifying it would mean HMACing with a test
secret, which tests the library rather than us.
"""
import json
from unittest import mock

import stripe
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from .models import (
    AutoTopUp, Membership, PaymentIntent, Transaction, membership_for,
    profile_for, wallet_for,
)

URL = "/api/economy/webhooks/stripe/"
CONFIGURED = dict(STRIPE_SECRET_KEY="sk_test_x", STRIPE_WEBHOOK_SECRET="whsec_x")


def _as_stripe_event(payload):
    """What `construct_event` really hands the view: a StripeObject tree."""
    return stripe.Event.construct_from(json.loads(payload), "sk_test_x")


class WebhookCase(TestCase):
    """Posts a real event through the real URL, signature check stubbed."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="corey", email="c@example.com", password="supersecret1")

    def send(self, event):
        raw = json.dumps(event)

        def construct(payload, sig, secret, *a, **kw):
            # Same object type the SDK returns, built from the same bytes.
            return _as_stripe_event(payload)

        with override_settings(**CONFIGURED):
            with mock.patch.object(stripe.Webhook, "construct_event",
                                   staticmethod(construct)):
                return self.client.post(URL, data=raw, content_type="application/json",
                                        HTTP_STRIPE_SIGNATURE="t=1,v1=deadbeef")

    def invoice_event(self, etype, invoice):
        return {"id": "evt_1", "object": "event", "api_version": "2026-04-22.dahlia",
                "type": etype, "data": {"object": invoice}}


class EventShapeTests(WebhookCase):
    """The library's object, not a dict — the bug the dict fixtures hid."""

    def test_a_stripe_object_event_does_not_500(self):
        # This is the whole regression. Before the fix every one of these was
        # an AttributeError on `.get`, and Stripe retried until it gave up.
        r = self.send({"id": "evt_1", "object": "event", "type": "checkout.session.completed",
                       "data": {"object": {"id": "cs_1", "metadata": {}}}})
        self.assertEqual(r.status_code, 200, r.content[:300])

    def test_an_unhandled_event_is_answered_not_refused(self):
        # 241 event types are subscribed; the endpoint must be boring about
        # the ones it doesn't act on rather than looking broken in Stripe.
        r = self.send({"id": "evt_1", "object": "event", "type": "charge.succeeded",
                       "data": {"object": {"id": "ch_1"}}})
        self.assertEqual(r.status_code, 200)

    @override_settings(STRIPE_SECRET_KEY="", STRIPE_WEBHOOK_SECRET="")
    def test_unconfigured_says_so_instead_of_erroring(self):
        r = self.client.post(URL, data="{}", content_type="application/json")
        self.assertEqual(r.status_code, 503)


class IdentityVerifiedTests(WebhookCase):
    """The live event that was failing: Corey's own 18+ check, retried for a week."""

    def session_event(self, session):
        return {"id": "evt_1", "object": "event", "type": "identity.verification_session.verified",
                "data": {"object": session}}

    # The real payload, copied from the failing delivery attempt in the Stripe
    # dashboard. Note what is NOT in it: `verified_outputs`. Stripe withholds
    # every personal field from the event body, which is why the flag has to be
    # fetched rather than read.
    REAL = {
        "id": "vs_1U1u0LPHdBXq957OAhfG5WGq",
        "object": "identity.verification_session",
        "client_reference_id": None, "client_secret": None,
        "last_error": None, "last_verification_report": "vr_1U1u2a",
        "livemode": True, "metadata": {"user_id": "REPLACED"},
        "options": {"document": {"require_matching_selfie": True}},
        "redaction": None, "related_customer": None,
        "status": "verified", "type": "document", "url": None,
    }

    def real_event(self):
        session = dict(self.REAL, metadata={"user_id": str(self.user.pk)})
        return self.session_event(session)

    def retrieving(self, dob):
        """Stub the expand-retrieve that the real payload forces."""
        def retrieve(session_id, **kw):
            assert "verified_outputs" in (kw.get("expand") or []), kw
            return stripe.identity.VerificationSession.construct_from(
                {"id": session_id, "verified_outputs": {"dob": dob}}, "sk_test_x")
        return mock.patch.object(
            stripe.identity.VerificationSession, "retrieve", staticmethod(retrieve))

    def test_the_real_failing_payload_is_answered(self):
        with self.retrieving({"day": 2, "month": 3, "year": 1990}):
            r = self.send(self.real_event())
        self.assertEqual(r.status_code, 200, r.content[:300])

    def test_the_real_payload_marks_an_adult_by_fetching_the_outputs(self):
        # The event carries no dob, so a handler that only reads the body can
        # never set this — which is why a passed verification sat unrecorded.
        with self.retrieving({"day": 2, "month": 3, "year": 1990}):
            self.send(self.real_event())
        self.assertTrue(profile_for(self.user).verified_18plus)

    def test_the_real_payload_does_not_mark_a_minor(self):
        with self.retrieving({"day": 2, "month": 3, "year": 2015}):
            self.send(self.real_event())
        self.assertFalse(profile_for(self.user).verified_18plus)

    def test_a_retrieve_that_fails_leaves_the_member_unverified(self):
        # Failing open on an age gate would be the worst possible default.
        def boom(session_id, **kw):
            raise RuntimeError("stripe down")

        with mock.patch.object(stripe.identity.VerificationSession, "retrieve",
                               staticmethod(boom)):
            r = self.send(self.real_event())
        self.assertEqual(r.status_code, 200)
        self.assertFalse(profile_for(self.user).verified_18plus)

    def test_a_verified_adult_is_marked(self):
        r = self.send(self.session_event({
            "id": "vs_1", "metadata": {"user_id": str(self.user.pk)},
            "status": "verified",
            "verified_outputs": {"dob": {"day": 2, "month": 3, "year": 1990}},
        }))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(profile_for(self.user).verified_18plus)

    def test_a_verified_minor_is_not(self):
        # The gate is the point of the whole flow — a verified session is not
        # the same fact as a verified adult.
        r = self.send(self.session_event({
            "id": "vs_1", "metadata": {"user_id": str(self.user.pk)},
            "status": "verified",
            "verified_outputs": {"dob": {"day": 2, "month": 3, "year": 2015}},
        }))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(profile_for(self.user).verified_18plus)


class AutoTopUpInvoiceTests(WebhookCase):
    """A paid recurring invoice has to move the wallet, once."""

    def setUp(self):
        super().setUp()
        self.ato = AutoTopUp.objects.create(
            user=self.user, stripe_subscription_id="sub_1",
            stripe_customer_id="cus_1", amount_cents=1000,
            interval="month", active=True)

    def dahlia_invoice(self, **over):
        """Invoice as 2026-04-22.dahlia sends it — subscription under parent."""
        inv = {"id": "in_1", "object": "invoice", "customer": "cus_1",
               "parent": {"type": "subscription_details",
                          "subscription_details": {"subscription": "sub_1"}}}
        inv.update(over)
        return inv

    def legacy_invoice(self, **over):
        """Invoice as pre-basil sends it — subscription at the root."""
        inv = {"id": "in_1", "object": "invoice", "customer": "cus_1",
               "subscription": "sub_1"}
        inv.update(over)
        return inv

    def balance(self):
        return wallet_for(self.user).money_cents

    def test_a_dahlia_invoice_credits_the_wallet(self):
        # The one that fails today: `invoice.get("subscription")` is None on
        # this shape, so the card was charged and nothing arrived.
        before = self.balance()
        r = self.send(self.invoice_event("invoice.payment_succeeded", self.dahlia_invoice()))
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertGreater(self.balance(), before)

    def test_a_pre_basil_invoice_still_credits(self):
        # Queued or replayed events can carry the old shape; both must work.
        before = self.balance()
        self.send(self.invoice_event("invoice.payment_succeeded", self.legacy_invoice()))
        self.assertGreater(self.balance(), before)

    def test_an_expanded_subscription_object_is_understood(self):
        # `subscription` is an ExpandableField — it is an id string normally
        # and a whole object when expanded. Reading `.id` off a string would
        # be the same class of bug all over again.
        inv = {"id": "in_1", "object": "invoice", "customer": "cus_1",
               "parent": {"type": "subscription_details", "subscription_details": {
                   "subscription": {"id": "sub_1", "object": "subscription"}}}}
        before = self.balance()
        self.send(self.invoice_event("invoice.payment_succeeded", inv))
        self.assertGreater(self.balance(), before)

    def test_a_replayed_invoice_credits_once(self):
        event = self.invoice_event("invoice.payment_succeeded", self.dahlia_invoice())
        self.send(event)
        after_first = self.balance()
        self.send(event)
        self.assertEqual(self.balance(), after_first)
        self.assertEqual(
            PaymentIntent.objects.filter(provider_ref="in_1").count(), 1)

    def test_energy_lands_with_the_money(self):
        self.send(self.invoice_event("invoice.payment_succeeded", self.dahlia_invoice()))
        self.assertTrue(
            Transaction.objects.filter(user=self.user, note__contains="energy").exists())

    def test_an_invoice_for_an_unknown_subscription_is_ignored(self):
        before = self.balance()
        inv = self.dahlia_invoice(id="in_2")
        inv["parent"]["subscription_details"]["subscription"] = "sub_nope"
        self.send(self.invoice_event("invoice.payment_succeeded", inv))
        self.assertEqual(self.balance(), before)


class FailedInvoiceTests(WebhookCase):
    """A dead renewal downgrades — but only the right kind of renewal."""

    def setUp(self):
        super().setUp()
        m = membership_for(self.user)
        m.tier = "statz"
        m.stripe_customer_id = "cus_1"
        m.save(update_fields=["tier", "stripe_customer_id", "updated_at"])

    def failed(self, invoice):
        return self.invoice_event("invoice.payment_failed", invoice)

    def test_a_dead_membership_renewal_downgrades(self):
        self.send(self.failed({"id": "in_1", "customer": "cus_1",
                               "next_payment_attempt": None}))
        self.assertEqual(Membership.objects.get(user=self.user).tier, "free")

    def test_a_retry_still_scheduled_does_not_downgrade(self):
        self.send(self.failed({"id": "in_1", "customer": "cus_1",
                               "next_payment_attempt": 1786133214}))
        self.assertEqual(Membership.objects.get(user=self.user).tier, "statz")

    def test_a_failed_top_up_does_not_touch_the_tier(self):
        # A declined top-up card is not a lapsed membership. The
        # customer.subscription.deleted handler already knows the difference;
        # this path matched on customer alone and dropped a paying member to
        # Free for a $5 card decline.
        AutoTopUp.objects.create(
            user=self.user, stripe_subscription_id="sub_top",
            stripe_customer_id="cus_1", amount_cents=500,
            interval="month", active=True)
        self.send(self.failed({
            "id": "in_1", "customer": "cus_1", "next_payment_attempt": None,
            "parent": {"type": "subscription_details",
                       "subscription_details": {"subscription": "sub_top"}}}))
        self.assertEqual(Membership.objects.get(user=self.user).tier, "statz")


class SubscriptionDeletedTests(WebhookCase):
    def test_a_cancelled_membership_downgrades(self):
        m = membership_for(self.user)
        m.tier = "premium"
        m.stripe_customer_id = "cus_1"
        m.save(update_fields=["tier", "stripe_customer_id", "updated_at"])
        self.send({"id": "evt_1", "object": "event", "type": "customer.subscription.deleted",
                   "data": {"object": {"id": "sub_1", "customer": "cus_1"}}})
        self.assertEqual(Membership.objects.get(user=self.user).tier, "free")

    def test_a_cancelled_top_up_stops_it_and_leaves_the_tier(self):
        m = membership_for(self.user)
        m.tier = "statz"
        m.stripe_customer_id = "cus_1"
        m.save(update_fields=["tier", "stripe_customer_id", "updated_at"])
        ato = AutoTopUp.objects.create(
            user=self.user, stripe_subscription_id="sub_1",
            stripe_customer_id="cus_1", amount_cents=500,
            interval="month", active=True)
        self.send({"id": "evt_1", "object": "event", "type": "customer.subscription.deleted",
                   "data": {"object": {"id": "sub_1", "customer": "cus_1"}}})
        ato.refresh_from_db()
        self.assertFalse(ato.active)
        self.assertEqual(Membership.objects.get(user=self.user).tier, "statz")


class CheckoutCompletedTests(WebhookCase):
    """The purchases. Each grants a tier from metadata.kind."""

    def completed(self, **obj):
        base = {"id": "cs_1", "object": "checkout.session", "customer": "cus_1"}
        base.update(obj)
        return {"id": "evt_1", "object": "event", "type": "checkout.session.completed",
                "data": {"object": base}}

    def test_a_statz_subscription_grants_the_tier(self):
        r = self.send(self.completed(
            subscription="sub_1",
            metadata={"kind": "statz_sub", "user_id": str(self.user.pk), "plan": "month"}))
        self.assertEqual(r.status_code, 200, r.content[:300])
        m = Membership.objects.get(user=self.user)
        self.assertEqual(m.tier, "statz")
        self.assertEqual(m.stripe_customer_id, "cus_1")

    def test_a_premium_subscription_grants_the_tier(self):
        self.send(self.completed(
            subscription="sub_1",
            metadata={"kind": "premium_sub", "user_id": str(self.user.pk), "plan": "month"}))
        self.assertEqual(Membership.objects.get(user=self.user).tier, "premium")

    def test_a_lifetime_purchase_grants_lifetime(self):
        self.send(self.completed(
            payment_intent="pi_1",
            metadata={"kind": "lifetime", "user_id": str(self.user.pk)}))
        self.assertTrue(Membership.objects.get(user=self.user).lifetime)

    def test_an_autotopup_setup_is_recorded(self):
        self.send(self.completed(
            subscription="sub_1",
            metadata={"kind": "autotopup", "user_id": str(self.user.pk),
                      "amount_cents": "1500", "interval": "month"}))
        ato = AutoTopUp.objects.get(stripe_subscription_id="sub_1")
        self.assertEqual(ato.user, self.user)
        self.assertEqual(ato.amount_cents, 1500)
        self.assertTrue(ato.active)

    def test_a_session_with_no_user_is_survivable(self):
        # client_reference_id and metadata can both be absent; that is a
        # no-op, not a crash.
        r = self.send(self.completed(metadata={}))
        self.assertEqual(r.status_code, 200)
