"""SpecZ — the marketplace that took no payment, and sold what nothing made.

Two bugs facing opposite directions, and connecting them would have been worse
than either:

  * The TAB let a member write a SpecZ — a label and a value attached to an
    app — and saved it to `localStorage`. No API call, no balance touched,
    nothing on the server. It did not survive a new browser.
  * The ENDPOINT sold six analytics products ("Audience Demographics",
    "Engagement Heatmap"…) for money. Nothing in the codebase generated any of
    them, and nothing read `specz_purchases` except the endpoint that wrote
    it, so buying one bought a row in a table.

Meanwhile MembershipZ sold the SpecZ marketplace as THE StatZ-only perk. So the
one thing advertised as worth a subscription was the one thing that charged
nothing — and the fix was not to wire the tab to that catalog, because that
would have taken 999 real SpinaZ for a report that does not exist.

SpecZ is the thing that delivers, and it charges now. There are tests because
the absence of them is why neither half was noticed.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.catalog import (SPECZ_APP_KEYS, SPECZ_LABEL_MAX,
                                  SPECZ_PRICE_SPINAZ, SPECZ_VALUE_MAX)
from apps.economy.models import (SpecZPurchase, TIER_FREE, TIER_STATZ, Transaction,
                                 membership_for, wallet_for)

User = get_user_model()
PW = "hunter2hunter2"
URL = "/api/economy/specz/"
BUY = "/api/economy/specz/buy/"
SPEC = {"app_key": "postz", "label": "Preferred BPM", "value": "140-150, dark strings"}


class SpecZTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("s", "s@e.com", PW)
        m = membership_for(self.user)
        m.tier = TIER_STATZ
        m.save(update_fields=["tier"])
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def bank(self, spinaz):
        w = wallet_for(self.user)
        w.spinaz = spinaz
        w.save(update_fields=["spinaz"])
        return w

    # ---- the bug itself: it charges, and it persists ----

    def test_writing_a_specz_takes_the_spinaz(self):
        self.bank(1000)
        r = self.client.post(BUY, SPEC, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(wallet_for(self.user).spinaz, 1000 - SPECZ_PRICE_SPINAZ)

    def test_it_lives_on_the_server_not_in_a_browser(self):
        self.bank(1000)
        self.client.post(BUY, SPEC, format="json")
        p = SpecZPurchase.objects.get(user=self.user)
        self.assertEqual((p.app_key, p.label, p.value),
                         (SPEC["app_key"], SPEC["label"], SPEC["value"]))
        self.assertEqual(p.price_spinaz, SPECZ_PRICE_SPINAZ)
        # And it reads back, which localStorage could not do across devices.
        self.assertEqual(self.client.get(URL).data["items"][0]["label"], SPEC["label"])

    def test_the_spend_lands_in_logz_with_its_reason(self):
        self.bank(1000)
        self.client.post(BUY, SPEC, format="json")
        t = Transaction.objects.filter(user=self.user,
                                       resource=Transaction.RES_SPINAZ).latest("created_at")
        self.assertEqual(t.amount, -SPECZ_PRICE_SPINAZ)
        self.assertIn("SpecZ", t.note)

    def test_money_is_never_touched(self):
        # The old endpoint charged money_cents. Nothing should now.
        w = self.bank(1000)
        w.money_cents = 5000
        w.save(update_fields=["money_cents"])
        self.client.post(BUY, SPEC, format="json")
        self.assertEqual(wallet_for(self.user).money_cents, 5000)

    def test_a_member_may_write_more_than_one(self):
        # The old unique_together meant "buy each catalog product once".
        self.bank(1000)
        self.client.post(BUY, SPEC, format="json")
        r = self.client.post(BUY, {**SPEC, "label": "Session length"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(SpecZPurchase.objects.filter(user=self.user).count(), 2)
        self.assertEqual(wallet_for(self.user).spinaz, 1000 - 2 * SPECZ_PRICE_SPINAZ)

    # ---- nothing is charged for a refusal ----

    def test_too_little_spinaz_is_refused_and_names_both_numbers(self):
        self.bank(SPECZ_PRICE_SPINAZ - 1)
        r = self.client.post(BUY, SPEC, format="json")
        self.assertEqual(r.status_code, 402)
        self.assertEqual(r.data["price_spinaz"], SPECZ_PRICE_SPINAZ)
        self.assertEqual(r.data["spinaz"], SPECZ_PRICE_SPINAZ - 1)
        self.assertEqual(wallet_for(self.user).spinaz, SPECZ_PRICE_SPINAZ - 1)

    def test_a_missing_label_costs_nothing(self):
        self.bank(1000)
        r = self.client.post(BUY, {**SPEC, "label": "  "}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(wallet_for(self.user).spinaz, 1000)
        self.assertFalse(SpecZPurchase.objects.exists())

    def test_an_app_that_is_not_on_the_list_costs_nothing(self):
        self.bank(1000)
        r = self.client.post(BUY, {**SPEC, "app_key": "nowhere"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(wallet_for(self.user).spinaz, 1000)

    def test_over_length_is_refused_not_silently_cut(self):
        # A save handler that quietly truncates what somebody typed and answers
        # "saved" is the worst bug class in this app.
        self.bank(1000)
        r = self.client.post(BUY, {**SPEC, "value": "x" * (SPECZ_VALUE_MAX + 1)}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["value_max"], SPECZ_VALUE_MAX)
        self.assertEqual(wallet_for(self.user).spinaz, 1000)

    def test_a_free_member_is_refused_and_charged_nothing(self):
        m = membership_for(self.user)
        m.tier = TIER_FREE
        m.save(update_fields=["tier"])
        self.bank(1000)
        r = self.client.post(BUY, SPEC, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(wallet_for(self.user).spinaz, 1000)

    # ---- the price is stated before the button ----

    def test_the_price_and_the_balance_arrive_together(self):
        self.bank(600)
        d = self.client.get(URL).data
        self.assertEqual(d["price_spinaz"], SPECZ_PRICE_SPINAZ)
        self.assertEqual(d["spinaz"], 600)
        self.assertTrue(d["affordable"])

    def test_affordability_is_answered_by_the_server(self):
        self.bank(SPECZ_PRICE_SPINAZ - 1)
        self.assertFalse(self.client.get(URL).data["affordable"])

    def test_the_app_list_comes_from_the_server(self):
        # So the tab cannot offer an app the server would refuse.
        apps = self.client.get(URL).data["apps"]
        self.assertEqual({a["key"] for a in apps}, SPECZ_APP_KEYS)
        self.assertTrue(all(a["name"] and a["icon"] for a in apps))

    def test_the_limits_come_from_the_server_too(self):
        d = self.client.get(URL).data
        self.assertEqual(d["label_max"], SPECZ_LABEL_MAX)
        self.assertEqual(d["value_max"], SPECZ_VALUE_MAX)

    # ---- removing one ----

    def test_deleting_removes_it_and_refunds_nothing(self):
        self.bank(1000)
        pk = self.client.post(BUY, SPEC, format="json").data["item"]["id"]
        after_buy = wallet_for(self.user).spinaz
        r = self.client.delete(f"/api/economy/specz/{pk}/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["refunded_spinaz"], 0)
        self.assertFalse(SpecZPurchase.objects.filter(pk=pk).exists())
        # A delete that quietly returned the SpinaZ would make the price
        # meaningless — write, delete, repeat, free forever.
        self.assertEqual(wallet_for(self.user).spinaz, after_buy)

    def test_you_cannot_delete_somebody_else_s(self):
        other = User.objects.create_user("o", "o@e.com", PW)
        m = membership_for(other); m.tier = TIER_STATZ; m.save(update_fields=["tier"])
        w = wallet_for(other); w.spinaz = 1000; w.save(update_fields=["spinaz"])
        c = APIClient(); c.force_authenticate(other)
        pk = c.post(BUY, SPEC, format="json").data["item"]["id"]

        r = self.client.delete(f"/api/economy/specz/{pk}/")
        self.assertEqual(r.status_code, 404)
        self.assertTrue(SpecZPurchase.objects.filter(pk=pk).exists())

    def test_you_only_see_your_own(self):
        other = User.objects.create_user("o", "o@e.com", PW)
        SpecZPurchase.objects.create(user=other, app_key="postz", label="Theirs",
                                     value="v", price_spinaz=SPECZ_PRICE_SPINAZ)
        self.assertEqual(self.client.get(URL).data["items"], [])

    # ---- the catalog that sold what nothing made is gone ----

    def test_the_fake_analytics_catalog_is_not_coming_back(self):
        from apps.economy import catalog
        self.assertFalse(hasattr(catalog, "SPECZ_CATALOG"))
