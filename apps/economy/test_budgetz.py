from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .models import BudgetLine, membership_for

User = get_user_model()


class BudgetTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("saver", "s@e.com", "pw-Long-enough-1")
        self.c = APIClient(); self.c.force_authenticate(self.u)

    def _add(self, **kw):
        return self.c.post("/api/economy/budgetz/", {"on": "2026-10-05", **kw}, format="json")

    def test_it_adds_up_what_was_entered_and_nothing_else(self):
        self._add(kind="income", amount="1500", category="Gigs")
        r = self._add(kind="expense", amount="40.50", category="Food")
        d = r.data
        self.assertEqual((d["income_cents"], d["spent_cents"], d["left_cents"]), (150000, 4050, 145950))

    def test_limits_flag_over_and_clear(self):
        self._add(kind="expense", amount="60", category="Food")
        r = self.c.put("/api/economy/budgetz/limit/?month=2026-10", {"category": "Food", "amount": "50"}, format="json")
        food = next(c for c in r.data["categories"] if c["category"] == "Food")
        self.assertTrue(food["over"])
        r = self.c.put("/api/economy/budgetz/limit/?month=2026-10", {"category": "Food", "amount": ""}, format="json")
        self.assertIsNone(next(c for c in r.data["categories"] if c["category"] == "Food")["limit_cents"])

    def test_bad_amounts_are_refused_and_lines_are_the_owners(self):
        self.assertEqual(self._add(amount="-5").status_code, 400)
        self.assertEqual(self._add(amount="abc").status_code, 400)
        self._add(amount="5")
        other = User.objects.create_user("o", "o@e.com", "pw-Long-enough-1")
        oc = APIClient(); oc.force_authenticate(other)
        line = BudgetLine.objects.get()
        self.assertEqual(oc.delete(f"/api/economy/budgetz/line/{line.id}/").status_code, 404)
        self.assertEqual(self.c.delete(f"/api/economy/budgetz/line/{line.id}/").status_code, 204)

    def test_the_bank_is_statz_and_the_budget_is_free(self):
        self.assertFalse(self.c.get("/api/economy/budgetz/").data["can_link"])
        self.assertEqual(self.c.post("/api/economy/budgetz/bank/session/").status_code, 403)
        m = membership_for(self.u); m.tier = "statz"; m.save()
        self.assertTrue(self.c.get("/api/economy/budgetz/").data["can_link"])
        with self.settings(STRIPE_SECRET_KEY=""):
            self.assertEqual(self.c.post("/api/economy/budgetz/bank/session/").status_code, 503)
            self.assertEqual(self.c.post("/api/economy/budgetz/bank/sync/").status_code, 503)

    def test_only_stripe_account_ids_are_kept(self):
        m = membership_for(self.u); m.tier = "statz"; m.save()
        r = self.c.post("/api/economy/budgetz/bank/link/", {"accounts": [{"id": "fca_123", "label": "Checking"},
                                                                          {"id": "password123"}]}, format="json")
        self.assertEqual([b["label"] for b in r.data["banks"]], ["Checking"])


class LilithGoAheadTests(TestCase):
    """BudgetZ says whether an upgrade is affordable; Lilith brings it to Today only on a yes."""

    def setUp(self):
        from .models import LilithTask
        self.T = LilithTask
        self.u = User.objects.create_user("upg", "u@e.com", "pw-Long-enough-1")
        self.c = APIClient(); self.c.force_authenticate(self.u)

    def _task(self, cost, cat="Gear"):
        r = self.c.post("/api/economy/lilith/tasks/", {"title": "Buy a U87", "bucket": "someday",
                                                      "cost": cost, "budget_category": cat}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data["id"]

    def _money(self, income, spent=0, limit=None):
        import datetime as dt
        on = dt.date.today().isoformat()
        self.c.post("/api/economy/budgetz/", {"kind": "income", "amount": income, "on": on}, format="json")
        if spent:
            self.c.post("/api/economy/budgetz/", {"kind": "expense", "amount": spent, "category": "Gear", "on": on}, format="json")
        if limit:
            self.c.put("/api/economy/budgetz/limit/", {"category": "Gear", "amount": limit}, format="json")

    def test_a_yes_moves_it_to_today_and_spends_nothing(self):
        self._money(1000)
        tid = self._task("400")
        r = self.c.post(f"/api/economy/lilith/tasks/{tid}/goahead/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.T.objects.get(pk=tid).bucket, "today")
        self.assertEqual(self.c.get("/api/economy/budgetz/").data["spent_cents"], 0)

    def test_no_income_or_too_dear_or_over_the_category_limit_is_a_no_that_moves_nothing(self):
        tid = self._task("50")
        self.assertEqual(self.c.post(f"/api/economy/lilith/tasks/{tid}/goahead/").status_code, 409)   # nothing in
        self._money(100)
        dear = self._task("500")
        self.assertEqual(self.c.post(f"/api/economy/lilith/tasks/{dear}/goahead/").status_code, 409)
        self.c.put("/api/economy/budgetz/limit/", {"category": "Gear", "amount": "20"}, format="json")
        r = self.c.post(f"/api/economy/lilith/tasks/{tid}/goahead/")
        self.assertEqual(r.status_code, 409)
        self.assertIn("limit", r.data["detail"])
        self.assertEqual(self.T.objects.get(pk=tid).bucket, "someday")

    def test_the_board_verdicts_come_in_one_read_and_are_the_owners(self):
        self._money(1000)
        self._task("100")
        v = self.c.get("/api/economy/lilith/budget/").data
        self.assertTrue(v["tasks"][0]["verdict"]["affordable"])
        other = User.objects.create_user("x", "x@e.com", "pw-Long-enough-1")
        oc = APIClient(); oc.force_authenticate(other)
        self.assertEqual(oc.get("/api/economy/lilith/budget/").data["tasks"], [])
