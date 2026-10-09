"""Deleting an account stops its Stripe billing first, and refuses if it can't.

The fake here is a Stripe that answers over the SDK's OWN HTTP seam, so every
object `stripe_cancel` touches is the real `stripe.Subscription` the library
builds from real response JSON — not a `SimpleNamespace` that passes against code
that breaks against Stripe. That is the lesson `test_stripe_webhook` was written
from: the fixture, not the handler, was doing the work.

Only the network is faked. The wire format (`DELETE /v1/subscriptions/{id}`, a
list object with `data`/`has_more`, an error body with `code: resource_missing`)
is Stripe's.
"""
import json
import shutil
import tempfile
from unittest import mock
from urllib.parse import parse_qs, urlparse

import stripe
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.economy import stripe_cancel
from apps.economy.models import AutoTopUp, StripeSubscription, Upload, membership_for, wallet_for
from apps.economy.test_stripe_webhook import WebhookCase

User = get_user_model()


class FakeStripe(stripe.HTTPClient):
    """Stripe's subscriptions API, over the SDK's HTTP seam.

    `subs` is {id: {"customer": ..., "status": ...}}. `fail` maps an id (or
    "list") to an HTTP status that call should answer instead of working;
    `fail_with` maps an id to (status, code, message) when the wording matters.
    `sessions` are completed Checkout Sessions, for the backfill.
    """

    name = "fake"      # the SDK puts the client's name in its request headers

    def __init__(self, subs=None, fail=None, on_cancel=None, fail_with=None, sessions=None):
        super().__init__()
        self.subs = {k: dict(v) for k, v in (subs or {}).items()}
        self.fail = dict(fail or {})
        self.fail_with = dict(fail_with or {})
        self.sessions = list(sessions or [])
        self.on_cancel = on_cancel
        self.calls = []

    def _sub(self, sid):
        s = self.subs[sid]
        return {"id": sid, "object": "subscription", "customer": s["customer"], "status": s["status"]}

    @staticmethod
    def _error(status, code, message):
        return json.dumps({"error": {"type": "invalid_request_error" if status < 500 else "api_error",
                                     "code": code, "message": message}}), status, {}

    def request(self, method, url, headers, post_data=None, *, _usage=None):
        method = method.upper()            # the SDK hands over "get" / "delete"
        path = urlparse(url).path
        query = parse_qs(urlparse(url).query)
        self.calls.append((method, path))
        if path == "/v1/checkout/sessions" and method == "GET":
            expand = any(k.startswith("expand") for k in query)
            data = []
            for sess in self.sessions:
                row = dict(sess, object="checkout.session", status="complete")
                if expand and row.get("subscription") in self.subs:
                    row["subscription"] = self._sub(row["subscription"])
                data.append(row)
            return json.dumps({"object": "list", "data": data, "has_more": False,
                               "url": "/v1/checkout/sessions"}), 200, {}
        if path == "/v1/subscriptions" and method == "GET":
            if "list" in self.fail:
                return self._error(self.fail["list"], "api_error", "boom")
            cust = (query.get("customer") or [""])[0]
            want_all = (query.get("status") or [""])[0] == "all"
            data = [self._sub(i) for i, s in self.subs.items()
                    if s["customer"] == cust and (want_all or s["status"] != "canceled")]
            return json.dumps({"object": "list", "data": data, "has_more": False,
                               "url": "/v1/subscriptions"}), 200, {}
        sid = path.rsplit("/", 1)[-1]
        if path.startswith("/v1/subscriptions/"):
            if sid in self.fail_with:
                return self._error(*self.fail_with[sid])
            if sid in self.fail:
                return self._error(self.fail[sid], "api_error", "boom")
            if sid not in self.subs:
                return self._error(404, "resource_missing", f"No such subscription: '{sid}'")
            if method == "GET":
                return json.dumps(self._sub(sid)), 200, {}
            if method == "DELETE":
                if self.on_cancel:
                    self.on_cancel(sid)
                self.subs[sid]["status"] = "canceled"
                return json.dumps(self._sub(sid)), 200, {}
        raise AssertionError(f"unexpected Stripe call {method} {url}")

    def close(self):
        pass

    def cancelled(self):
        return [p.rsplit("/", 1)[-1] for m, p in self.calls if m == "DELETE"]


def patched(fake):
    """Make `stripe_cancel` talk to `fake` through the real SDK client."""
    return mock.patch.object(
        stripe_cancel, "_client",
        lambda key: stripe.StripeClient(key, http_client=fake, max_network_retries=0))


KEY = override_settings(STRIPE_SECRET_KEY="sk_test_x")


def _member(name="payer"):
    return User.objects.create_user(username=name, email=f"{name}@x.test", password="pw12345!pw")


def _premium(user, customer="cus_1", sub="sub_1"):
    m = membership_for(user)
    m.tier = "premium"
    m.stripe_customer_id = customer
    m.last_payment_ref = sub
    m.last_payment_kind = "premium_month"
    m.save()
    return m


@KEY
class CancelForTests(TestCase):
    def test_a_live_premium_subscription_is_cancelled(self):
        u = _member()
        _premium(u)
        fake = FakeStripe({"sub_1": {"customer": "cus_1", "status": "active"}})
        with patched(fake):
            done = stripe_cancel.cancel_for(u)
        self.assertEqual(done, ["sub_1"])
        self.assertEqual(fake.cancelled(), ["sub_1"])
        self.assertEqual(fake.subs["sub_1"]["status"], "canceled")

    def test_it_finds_a_subscription_the_membership_row_forgot(self):
        # The row keeps only the LAST subscription id; a member who switched plans
        # may have an older one still running on the same customer.
        u = _member()
        _premium(u, sub="sub_new")
        fake = FakeStripe({"sub_new": {"customer": "cus_1", "status": "active"},
                           "sub_old": {"customer": "cus_1", "status": "past_due"}})
        with patched(fake):
            done = stripe_cancel.cancel_for(u)
        self.assertEqual(sorted(done), ["sub_new", "sub_old"])

    def test_an_auto_topup_marked_inactive_is_still_checked(self):
        # AutoTopUpCancelView flips `active` to False even when its Stripe call
        # failed. A local "off" is not evidence the billing stopped.
        u = _member()
        # No customer id on the row, so the listing cannot find it: only the stored
        # subscription id can, which is the path an "inactive" row must still take.
        AutoTopUp.objects.create(user=u, stripe_subscription_id="sub_top", stripe_customer_id="",
                                 amount_cents=500, active=False)
        fake = FakeStripe({"sub_top": {"customer": "cus_9", "status": "active"}})
        with patched(fake):
            done = stripe_cancel.cancel_for(u)
        self.assertEqual(done, ["sub_top"])

    def test_a_stale_id_that_stripe_already_cancelled_never_blocks_a_delete(self):
        # Otherwise one dead id would answer an error forever and the member could
        # never delete their account.
        u = _member()
        _premium(u, sub="sub_dead")
        fake = FakeStripe({"sub_dead": {"customer": "cus_1", "status": "canceled"}})
        with patched(fake):
            done = stripe_cancel.cancel_for(u)
        self.assertEqual(done, [])
        self.assertEqual(fake.cancelled(), [])

    def test_a_subscription_stripe_has_never_heard_of_is_not_a_failure(self):
        u = _member()
        _premium(u, sub="sub_gone")
        with patched(FakeStripe({})):
            self.assertEqual(stripe_cancel.cancel_for(u), [])

    def test_a_lifetime_member_has_nothing_to_cancel(self):
        u = _member()
        m = membership_for(u)
        m.lifetime = True
        m.last_payment_ref = "pi_123"          # a PaymentIntent, not a subscription
        m.last_payment_kind = "lifetime"
        m.save()
        with mock.patch.object(stripe_cancel, "_client", side_effect=AssertionError("no call expected")):
            self.assertEqual(stripe_cancel.cancel_for(u), [])

    def test_ids_on_file_and_no_key_refuses_rather_than_leaving_the_billing_running(self):
        # Rows that name Stripe ids are proof billing may exist; with no key
        # nobody can reach it. Passing here would turn an unset variable into
        # every delete going through and nothing being cancelled.
        u = _member()
        _premium(u)
        with override_settings(STRIPE_SECRET_KEY=""), \
                mock.patch.object(stripe_cancel, "_client", side_effect=AssertionError("no call expected")), \
                self.assertLogs("apps.economy.stripe_cancel", level="ERROR"):
            with self.assertRaises(stripe_cancel.CancelFailed):
                stripe_cancel.cancel_for(u)

    def test_no_ids_and_no_key_is_a_dev_box_with_nothing_to_cancel(self):
        u = _member()
        with override_settings(STRIPE_SECRET_KEY=""), \
                mock.patch.object(stripe_cancel, "_client", side_effect=AssertionError("no call expected")):
            self.assertEqual(stripe_cancel.cancel_for(u), [])

    def test_a_key_that_cannot_see_the_object_is_not_read_as_gone(self):
        # Stripe answers `resource_missing` for a live-mode id asked of a
        # test-mode key. Reading that as "already cancelled" would make a wrong
        # key look like a platform where every delete succeeds.
        u = _member()
        _premium(u, sub="sub_live")
        msg = ("No such subscription: 'sub_live'; a similar object exists in live mode, "
               "but a test mode key was used to make this request.")
        fake = FakeStripe({}, fail_with={"sub_live": (404, "resource_missing", msg)})
        with patched(fake), self.assertLogs("apps.economy.stripe_cancel", level="ERROR"):
            with self.assertRaises(stripe_cancel.CancelFailed):
                stripe_cancel.cancel_for(u)

    def test_accepting_resource_missing_leaves_a_line_in_the_log(self):
        u = _member()
        _premium(u, sub="sub_gone")
        with patched(FakeStripe({})), self.assertLogs("apps.economy.stripe_cancel", level="WARNING") as cm:
            self.assertEqual(stripe_cancel.cancel_for(u), [])
        self.assertTrue(any("sub_gone" in line for line in cm.output))

    def test_the_whole_pass_fits_inside_the_wait_the_screen_allows(self):
        # api.js gives up at 30s. The budget is only checked BETWEEN calls, so
        # the worst pass is the budget plus one stalled call, and a stalled call
        # is two attempts (the SDK retries once) plus its pause.
        worst = stripe_cancel.BUDGET_SECONDS + 2 * stripe_cancel.CALL_TIMEOUT_SECONDS + 1
        self.assertLessEqual(worst, 30)

    def test_a_customer_shared_with_another_account_is_not_swept(self):
        # Nothing makes stripe_customer_id unique. Deleting one of two accounts
        # that share a customer must not cancel the OTHER member's subscription.
        mine, theirs = _member("mine"), _member("theirs")
        _premium(mine, customer="cus_shared", sub="sub_mine")
        _premium(theirs, customer="cus_shared", sub="sub_theirs")
        fake = FakeStripe({"sub_mine": {"customer": "cus_shared", "status": "active"},
                           "sub_theirs": {"customer": "cus_shared", "status": "active"}})
        with patched(fake), self.assertLogs("apps.economy.stripe_cancel", level="WARNING"):
            done = stripe_cancel.cancel_for(mine)
        self.assertEqual(done, ["sub_mine"])
        self.assertEqual(fake.subs["sub_theirs"]["status"], "active")

    def test_one_failure_does_not_stop_the_others_being_cancelled(self):
        u = _member()
        _premium(u, sub="sub_a")
        fake = FakeStripe({"sub_a": {"customer": "cus_1", "status": "active"},
                           "sub_b": {"customer": "cus_1", "status": "active"}},
                          fail={"sub_a": 500})
        with patched(fake), self.assertLogs("apps.economy.stripe_cancel", level="ERROR"):
            with self.assertRaises(stripe_cancel.CancelFailed) as cm:
                stripe_cancel.cancel_for(u)
        # sub_a could not be cancelled; sub_b still was.
        self.assertEqual(fake.subs["sub_b"]["status"], "canceled")
        self.assertEqual(fake.subs["sub_a"]["status"], "active")
        # Stripe's webhook will drop them to Free for the one that went through,
        # so the refusal says so rather than leaving them to wonder why.
        self.assertEqual(cm.exception.cancelled, ["sub_b"])
        self.assertIn("may already show as Free", cm.exception.detail)

    def test_a_listing_failure_refuses_rather_than_assuming_nothing_is_live(self):
        u = _member()
        _premium(u, sub="")                  # a customer on file and no subscription id
        fake = FakeStripe({"sub_1": {"customer": "cus_1", "status": "active"}}, fail={"list": 500})
        with patched(fake), self.assertLogs("apps.economy.stripe_cancel", level="ERROR"):
            with self.assertRaises(stripe_cancel.CancelFailed) as cm:
                stripe_cancel.cancel_for(u)
        self.assertEqual(fake.cancelled(), [])
        self.assertNotIn("Free", cm.exception.detail)      # nothing was cancelled, so nothing to say

    def test_a_listing_failure_still_cancels_the_ids_it_holds_and_says_so(self):
        u = _member()
        _premium(u)
        fake = FakeStripe({"sub_1": {"customer": "cus_1", "status": "active"}}, fail={"list": 500})
        with patched(fake), self.assertLogs("apps.economy.stripe_cancel", level="ERROR"):
            with self.assertRaises(stripe_cancel.CancelFailed) as cm:
                stripe_cancel.cancel_for(u)
        self.assertEqual(fake.cancelled(), ["sub_1"])
        self.assertIn("may already show as Free", cm.exception.detail)

    def test_running_out_of_time_refuses(self):
        u = _member()
        _premium(u)
        fake = FakeStripe({"sub_1": {"customer": "cus_1", "status": "active"}})
        with patched(fake), mock.patch.object(stripe_cancel, "BUDGET_SECONDS", 0), \
                self.assertLogs("apps.economy.stripe_cancel", level="ERROR"):
            with self.assertRaises(stripe_cancel.CancelFailed):
                stripe_cancel.cancel_for(u)
        self.assertEqual(fake.cancelled(), [])

    def test_the_refusal_is_a_value_error_so_every_dupez_caller_already_handles_it(self):
        self.assertTrue(issubclass(stripe_cancel.CancelFailed, ValueError))
        self.assertIn("has not been deleted", stripe_cancel.CancelFailed().detail)

    def test_the_real_client_has_the_calls_this_module_makes(self):
        # A stub cannot tell you the SDK still has the method. `_client` builds
        # the real thing, so a rename in a future SDK fails here, not on a member.
        c = stripe_cancel._client("sk_test_x")
        self.assertIsInstance(c, stripe.StripeClient)
        for name in ("list", "retrieve", "cancel"):
            self.assertTrue(callable(getattr(c.v1.subscriptions, name)), name)


@KEY
class DeleteDoorsTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls._root = tempfile.mkdtemp()
        cls._media = override_settings(MEDIA_ROOT=cls._root)
        cls._media.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media.disable()
        shutil.rmtree(cls._root, ignore_errors=True)

    def _payer(self):
        u = _member()
        _premium(u)
        up = Upload(user=u, name="t.wav", size_bytes=4, content_type="audio/wav")
        up.file.save("t.wav", ContentFile(b"riff"), save=True)
        return u, up.file.name

    def _delete_me(self, u):
        c = APIClient()
        c.force_authenticate(u)
        with self.captureOnCommitCallbacks(execute=True):
            return c.delete("/api/auth/me/")

    def test_billing_is_cancelled_and_then_the_account_goes(self):
        u, name = self._payer()
        seen = {}
        fake = FakeStripe({"sub_1": {"customer": "cus_1", "status": "active"}},
                          on_cancel=lambda sid: seen.setdefault("alive", User.objects.filter(pk=u.pk).exists()))
        with patched(fake):
            resp = self._delete_me(u)
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(fake.cancelled(), ["sub_1"])
        self.assertTrue(seen["alive"], "the account must still exist when billing is cancelled")
        self.assertFalse(User.objects.filter(pk=u.pk).exists())
        self.assertFalse(default_storage.exists(name))

    def test_when_stripe_cannot_cancel_nothing_is_deleted(self):
        u, name = self._payer()
        fake = FakeStripe({"sub_1": {"customer": "cus_1", "status": "active"}}, fail={"sub_1": 500})
        with patched(fake), self.assertLogs("apps.economy.stripe_cancel", level="ERROR"):
            resp = self._delete_me(u)
        self.assertEqual(resp.status_code, 502)
        self.assertIn("has not been deleted", resp.json()["detail"])
        self.assertTrue(User.objects.filter(pk=u.pk).exists())
        self.assertTrue(default_storage.exists(name), "a refused delete must not remove files")
        self.assertTrue(Upload.objects.filter(user=u).exists())

    def test_the_other_account_delete_endpoint_refuses_the_same_way(self):
        u, _ = self._payer()
        fake = FakeStripe({"sub_1": {"customer": "cus_1", "status": "active"}}, fail={"sub_1": 500})
        c = APIClient()
        c.force_authenticate(u)
        with patched(fake), self.assertLogs("apps.economy.stripe_cancel", level="ERROR"):
            resp = c.post("/api/economy/account/delete/", {"confirm": "DELETE"}, format="json")
        self.assertEqual(resp.status_code, 502)
        self.assertTrue(User.objects.filter(pk=u.pk).exists())

    def test_the_other_account_delete_endpoint_cancels_then_deletes(self):
        u, _ = self._payer()
        fake = FakeStripe({"sub_1": {"customer": "cus_1", "status": "active"}})
        c = APIClient()
        c.force_authenticate(u)
        with patched(fake), self.captureOnCommitCallbacks(execute=True):
            resp = c.post("/api/economy/account/delete/", {"confirm": "DELETE"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(fake.cancelled(), ["sub_1"])
        self.assertFalse(User.objects.filter(pk=u.pk).exists())

    def test_a_delete_that_fails_after_the_cancel_leaves_the_member_not_paying(self):
        # The order is chosen so the wrong half to be left holding is "no longer
        # paying", never "still paying". Stripe's own webhook then drops them to Free.
        u, _ = self._payer()
        fake = FakeStripe({"sub_1": {"customer": "cus_1", "status": "active"}})
        with patched(fake), mock.patch.object(User, "delete", side_effect=RuntimeError("db said no")):
            with self.assertRaises(RuntimeError):
                self._delete_me(u)
        self.assertTrue(User.objects.filter(pk=u.pk).exists())
        self.assertEqual(fake.subs["sub_1"]["status"], "canceled")

    def test_every_door_that_deletes_an_account_handles_a_refusal(self):
        # A fifth door that calls delete_user without catching CancelFailed would
        # answer 500. Read the source of each, like test_erasure does for files.
        import inspect

        from apps.accounts import views
        from apps.economy import account, dupez
        for fn in (views.MeView.delete, views.UsersView.delete, account.AccountDeleteView.post):
            self.assertIn("CancelFailed", inspect.getsource(fn), fn.__qualname__)
        src = inspect.getsource(dupez)
        self.assertEqual(src.count("delete_duplicate("), src.count("except ValueError") + 1,
                         "every caller of delete_duplicate needs a ValueError handler (+1 for the def)")


@KEY
class DupezBillingTests(TestCase):
    def test_a_duplicate_with_live_billing_is_cancelled_before_anything_is_swept(self):
        from apps.economy import dupez
        dup, keep, by = _member("dup"), _member("keep"), _member("boss")
        _premium(dup)
        w = wallet_for(dup)
        w.money_cents = 700
        w.save()
        fake = FakeStripe({"sub_1": {"customer": "cus_1", "status": "active"}})
        with patched(fake):
            receipt = dupez.delete_duplicate(dup, keep, by=by, reason="test")
        self.assertEqual(fake.cancelled(), ["sub_1"])
        self.assertEqual(receipt["swept"]["money_cents"], 700)
        self.assertFalse(User.objects.filter(pk=dup.pk).exists())

    def test_a_cancel_that_fails_leaves_the_duplicate_and_its_money_untouched(self):
        from apps.economy import dupez
        dup, keep, by = _member("dup"), _member("keep"), _member("boss")
        _premium(dup)
        w = wallet_for(dup)
        w.money_cents = 700
        w.save()
        fake = FakeStripe({"sub_1": {"customer": "cus_1", "status": "active"}}, fail={"sub_1": 500})
        with patched(fake), self.assertLogs("apps.economy.stripe_cancel", level="ERROR"):
            with self.assertRaises(ValueError):
                dupez.delete_duplicate(dup, keep, by=by, reason="test")
        self.assertTrue(User.objects.filter(pk=dup.pk).exists())
        self.assertEqual(wallet_for(dup).money_cents, 700)
        self.assertEqual(wallet_for(keep).money_cents, 0)

    def test_cash_that_arrives_during_the_stripe_pass_is_swept_and_not_destroyed(self):
        # The Stripe pass is seconds, not milliseconds. An auto-top-up invoice
        # paid inside it credits the wallet AFTER the amount was first read, and
        # a stale figure swept nothing and then deleted the credit.
        from apps.economy import dupez
        dup, keep, by = _member("dup"), _member("keep"), _member("boss")
        _premium(dup)

        def credit(sid):
            w = wallet_for(dup)
            w.money_cents += 4500
            w.save()

        fake = FakeStripe({"sub_1": {"customer": "cus_1", "status": "active"}}, on_cancel=credit)
        with patched(fake):
            receipt = dupez.delete_duplicate(dup, keep, by=by, reason="test")
        self.assertEqual(receipt["swept"]["money_cents"], 4500)
        self.assertEqual(wallet_for(keep).money_cents, 4500)

    def test_cash_that_arrives_with_nowhere_to_go_refuses_the_delete(self):
        from apps.economy import dupez
        dup, by = _member("dup"), _member("boss")
        _premium(dup)

        def credit(sid):
            w = wallet_for(dup)
            w.money_cents += 4500
            w.save()

        fake = FakeStripe({"sub_1": {"customer": "cus_1", "status": "active"}}, on_cancel=credit)
        with patched(fake):
            with self.assertRaises(ValueError) as cm:
                dupez.delete_duplicate(dup, None, by=by, reason="test")
        self.assertIn("45.00", str(cm.exception))
        self.assertTrue(User.objects.filter(pk=dup.pk).exists())


def _checkout(kind, uid, customer, sub, plan="month"):
    """A `checkout.session.completed` for a subscription, as Stripe sends it."""
    return {"id": f"evt_{sub}", "object": "event", "type": "checkout.session.completed",
            "data": {"object": {
                "id": f"cs_{sub}", "mode": "subscription", "customer": customer, "subscription": sub,
                "client_reference_id": str(uid),
                "metadata": {"kind": kind, "user_id": str(uid), "plan": plan}}}}


@KEY
class LedgerTests(WebhookCase):
    """The ledger exists because the membership row forgets.

    Every Checkout creates a NEW Stripe customer and the webhook overwrites the
    membership's customer and subscription with the newest, so Premium followed
    by StatZ leaves Premium billing under a customer no row names. These go
    through the real webhook and the real delete, not a hand-built row.
    """

    def _upgrade(self):
        with mock.patch.object(stripe_cancel, "_client", side_effect=AssertionError("a paid checkout must not call Stripe")):
            self.assertEqual(self.send(_checkout("premium_sub", self.user.pk, "cus_A", "sub_A")).status_code, 200)
            self.assertEqual(self.send(_checkout("statz_sub", self.user.pk, "cus_B", "sub_B", "month")).status_code, 200)

    def test_the_membership_row_really_does_forget_the_first_subscription(self):
        # Pins the premise, so nobody "simplifies" the ledger away on the belief
        # that the row already holds everything.
        self._upgrade()
        m = membership_for(self.user)
        self.assertEqual((m.stripe_customer_id, m.last_payment_ref), ("cus_B", "sub_B"))

    def test_premium_then_statz_both_get_cancelled_when_the_account_is_deleted(self):
        self._upgrade()
        self.assertEqual(
            sorted(StripeSubscription.objects.filter(user=self.user).values_list("stripe_subscription_id", flat=True)),
            ["sub_A", "sub_B"])
        fake = FakeStripe({"sub_A": {"customer": "cus_A", "status": "active"},
                           "sub_B": {"customer": "cus_B", "status": "active"}})
        c = APIClient()
        c.force_authenticate(self.user)
        with patched(fake), self.captureOnCommitCallbacks(execute=True):
            resp = c.delete("/api/auth/me/")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(sorted(fake.cancelled()), ["sub_A", "sub_B"])
        self.assertEqual({s["status"] for s in fake.subs.values()}, {"canceled"})

    def test_the_same_event_delivered_twice_is_one_row(self):
        with mock.patch.object(stripe_cancel, "_client", side_effect=AssertionError("no call")):
            for _ in range(2):
                self.send(_checkout("premium_sub", self.user.pk, "cus_A", "sub_A"))
        self.assertEqual(StripeSubscription.objects.filter(user=self.user).count(), 1)

    def test_a_ledger_failure_never_undoes_the_tier_the_webhook_granted(self):
        with mock.patch.object(StripeSubscription.objects, "update_or_create", side_effect=RuntimeError("db")), \
                mock.patch.object(stripe_cancel, "_client", side_effect=AssertionError("no call")), \
                self.assertLogs("apps.economy.stripe_cancel", level="ERROR"):
            r = self.send(_checkout("premium_sub", self.user.pk, "cus_A", "sub_A"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(membership_for(self.user).tier, "premium")

    def test_a_wallet_funding_checkout_is_not_a_subscription(self):
        with mock.patch.object(stripe_cancel, "_client", side_effect=AssertionError("no call")):
            r = self.send({"id": "evt_p", "object": "event", "type": "checkout.session.completed",
                           "data": {"object": {"id": "cs_p", "mode": "payment", "customer": "cus_P",
                                               "client_reference_id": str(self.user.pk),
                                               "metadata": {"user_id": str(self.user.pk)}}}})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(StripeSubscription.objects.exists())


@KEY
class OrphanTests(WebhookCase):
    """A Checkout stays payable for hours after the account that opened it is gone."""

    GONE = 987654

    def test_a_subscription_paid_for_by_a_deleted_account_is_cancelled_on_sight(self):
        fake = FakeStripe({"sub_Z": {"customer": "cus_Z", "status": "active"}})
        with patched(fake):
            r = self.send(_checkout("premium_sub", self.GONE, "cus_Z", "sub_Z"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(fake.cancelled(), ["sub_Z"])

    def test_an_auto_topup_paid_for_by_a_deleted_account_is_cancelled_too(self):
        fake = FakeStripe({"sub_T": {"customer": "cus_T", "status": "active"}})
        with patched(fake):
            self.send(_checkout("autotopup", self.GONE, "cus_T", "sub_T"))
        self.assertEqual(fake.cancelled(), ["sub_T"])

    def test_a_cancel_that_fails_answers_5xx_so_stripe_retries(self):
        # Every other branch here answers 200 and lets the event go. This one
        # must not: a 200 is a subscription that bills forever.
        fake = FakeStripe({"sub_Z": {"customer": "cus_Z", "status": "active"}}, fail={"sub_Z": 500})
        self.client.raise_request_exception = False
        with patched(fake), self.assertLogs("apps.economy.stripe_cancel", level="ERROR"):
            r = self.send(_checkout("premium_sub", self.GONE, "cus_Z", "sub_Z"))
        self.assertGreaterEqual(r.status_code, 500)

    def test_an_already_ended_subscription_is_left_alone(self):
        fake = FakeStripe({"sub_Z": {"customer": "cus_Z", "status": "canceled"}})
        with patched(fake):
            r = self.send(_checkout("premium_sub", self.GONE, "cus_Z", "sub_Z"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(fake.cancelled(), [])

    def test_a_one_time_payment_from_a_deleted_account_calls_nothing(self):
        with mock.patch.object(stripe_cancel, "_client", side_effect=AssertionError("no call")):
            r = self.send({"id": "evt_p", "object": "event", "type": "checkout.session.completed",
                           "data": {"object": {"id": "cs_p", "mode": "payment",
                                               "client_reference_id": str(self.GONE),
                                               "metadata": {"user_id": str(self.GONE)}}}})
        self.assertEqual(r.status_code, 200)


@KEY
class AdminDoorTests(TestCase):
    """The Django admin deletes users too, and used to bypass all of it."""

    def setUp(self):
        self.owner = User.objects.create_superuser("boss", "boss@x.test", "pw12345!pw")
        self.client.force_login(self.owner)
        self.payer = _member()
        _premium(self.payer)

    def _delete(self):
        return self.client.post(f"/admin/auth/user/{self.payer.pk}/delete/", {"post": "yes"})

    def test_deleting_in_the_admin_cancels_the_billing_first(self):
        fake = FakeStripe({"sub_1": {"customer": "cus_1", "status": "active"}})
        with patched(fake), self.captureOnCommitCallbacks(execute=True):
            self._delete()
        self.assertEqual(fake.cancelled(), ["sub_1"])
        self.assertFalse(User.objects.filter(pk=self.payer.pk).exists())

    def test_a_refusal_in_the_admin_leaves_the_account_and_says_why(self):
        fake = FakeStripe({"sub_1": {"customer": "cus_1", "status": "active"}}, fail={"sub_1": 500})
        with patched(fake), self.assertLogs("apps.economy.stripe_cancel", level="ERROR"):
            r = self._delete()
        self.assertEqual(r.status_code, 302)
        self.assertTrue(User.objects.filter(pk=self.payer.pk).exists())
        from django.contrib.messages import get_messages
        said = " ".join(str(m) for m in get_messages(r.wsgi_request))
        self.assertIn("was not deleted", said)
        self.assertNotIn("deleted successfully", said)

    def test_bulk_delete_is_not_offered_for_accounts(self):
        from django.contrib import admin
        from django.test import RequestFactory
        req = RequestFactory().get("/admin/auth/user/")
        req.user = self.owner
        self.assertNotIn("delete_selected", admin.site._registry[User].get_actions(req))


@KEY
class BackfillTests(TestCase):
    """Recovering what the ledger could not have seen: the past."""

    def _run(self, fake, *args):
        from io import StringIO

        from django.core.management import call_command
        out = StringIO()
        with patched(fake):
            call_command("backfill_stripe_subscriptions", *args, stdout=out)
        return out.getvalue()

    def _session(self, uid, sub, cust, kind="premium_sub"):
        return {"id": f"cs_{sub}", "mode": "subscription", "client_reference_id": str(uid),
                "metadata": {"kind": kind, "user_id": str(uid)}, "customer": cust, "subscription": sub}

    def test_dry_run_reports_and_writes_nothing(self):
        u = _member()
        fake = FakeStripe({"sub_old": {"customer": "cus_A", "status": "active"}},
                          sessions=[self._session(u.pk, "sub_old", "cus_A")])
        out = self._run(fake)
        self.assertIn("sub_old", out)
        self.assertIn("would be written", out)
        self.assertFalse(StripeSubscription.objects.exists())

    def test_write_records_the_subscription_the_membership_row_forgot(self):
        u = _member()
        fake = FakeStripe({"sub_old": {"customer": "cus_A", "status": "active"}},
                          sessions=[self._session(u.pk, "sub_old", "cus_A")])
        self._run(fake, "--write")
        row = StripeSubscription.objects.get(stripe_subscription_id="sub_old")
        self.assertEqual((row.user_id, row.stripe_customer_id, row.kind), (u.pk, "cus_A", "premium_sub"))
        # and now deleting that account finds it, with the membership row empty
        done = None
        with patched(fake):
            done = stripe_cancel.cancel_for(u)
        self.assertEqual(done, ["sub_old"])

    def test_a_live_subscription_of_a_deleted_account_is_listed_but_not_cancelled_without_the_flag(self):
        fake = FakeStripe({"sub_o": {"customer": "cus_O", "status": "active"}},
                          sessions=[self._session(987654, "sub_o", "cus_O")])
        out = self._run(fake, "--write")
        self.assertIn("ORPHAN", out)
        self.assertEqual(fake.cancelled(), [])

    def test_cancel_orphans_ends_them(self):
        fake = FakeStripe({"sub_o": {"customer": "cus_O", "status": "active"}},
                          sessions=[self._session(987654, "sub_o", "cus_O")])
        self._run(fake, "--write", "--cancel-orphans")
        self.assertEqual(fake.cancelled(), ["sub_o"])

    def test_an_ended_subscription_of_a_deleted_account_is_not_an_orphan(self):
        fake = FakeStripe({"sub_o": {"customer": "cus_O", "status": "canceled"}},
                          sessions=[self._session(987654, "sub_o", "cus_O")])
        out = self._run(fake, "--write", "--cancel-orphans")
        self.assertNotIn("ORPHAN", out)
        self.assertEqual(fake.cancelled(), [])

    def test_a_one_time_payment_session_is_ignored(self):
        u = _member()
        fake = FakeStripe({}, sessions=[{"id": "cs_p", "mode": "payment", "client_reference_id": str(u.pk),
                                         "metadata": {"user_id": str(u.pk)}, "customer": "cus_P"}])
        self._run(fake, "--write")
        self.assertFalse(StripeSubscription.objects.exists())

    def test_cancelling_needs_write(self):
        from django.core.management import CommandError
        with self.assertRaises(CommandError):
            self._run(FakeStripe({}), "--cancel-orphans")

    def test_no_key_is_an_error_and_not_a_clean_bill(self):
        from django.core.management import CommandError
        with override_settings(STRIPE_SECRET_KEY=""), self.assertRaises(CommandError):
            self._run(FakeStripe({}))
