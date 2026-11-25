"""HealthZ: sleep and conditions are the member's own words, private, and never inferred."""
import datetime
import pathlib

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import HealthCondition, SleepLog

User = get_user_model()
BASE = "/api/economy/healthz/"


def client(name):
    u = User.objects.create_user(name, f"{name}@x.test", "hunter2hunter2")
    c = APIClient(); c.force_authenticate(u)
    return u, c


class Sleep(TestCase):
    def test_an_empty_log_has_no_average_not_a_zero(self):
        _, c = client("hz_empty")
        r = c.get(BASE).data
        self.assertIsNone(r["avg_hours_7d"]); self.assertEqual(r["sleep"], [])
        self.assertIn("doesn't diagnose", r["note"])

    def test_average_is_the_mean_of_what_was_logged(self):
        _, c = client("hz_avg")
        today = timezone.localdate()
        for i, h in enumerate((6, 8)):
            c.post(BASE + "sleep/", {"night": (today - datetime.timedelta(days=i)).isoformat(), "hours": h}, format="json")
        self.assertEqual(c.get(BASE).data["avg_hours_7d"], 7.0)

    def test_logging_a_night_again_edits_it(self):
        u, c = client("hz_edit")
        n = timezone.localdate().isoformat()
        c.post(BASE + "sleep/", {"night": n, "hours": 5}, format="json")
        c.post(BASE + "sleep/", {"night": n, "hours": 7, "quality": 4}, format="json")
        self.assertEqual(SleepLog.objects.filter(user=u).count(), 1)
        self.assertEqual(SleepLog.objects.get(user=u).hours, 7)

    def test_bad_input_is_refused_with_a_reason(self):
        _, c = client("hz_bad")
        self.assertEqual(c.post(BASE + "sleep/", {"hours": 0}, format="json").status_code, 400)
        self.assertEqual(c.post(BASE + "sleep/", {"hours": 25}, format="json").status_code, 400)
        self.assertEqual(c.post(BASE + "sleep/", {"hours": 7, "quality": 9}, format="json").status_code, 400)
        future = (timezone.localdate() + datetime.timedelta(days=5)).isoformat()
        self.assertEqual(c.post(BASE + "sleep/", {"night": future, "hours": 7}, format="json").status_code, 400)


class Conditions(TestCase):
    def test_a_condition_is_the_members_own_words(self):
        _, c = client("hz_cond")
        r = c.post(BASE + "conditions/", {"name": "Asthma", "since_year": 2015, "note": "inhaler"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["conditions"][0]["name"], "Asthma")
        self.assertEqual(c.post(BASE + "conditions/", {"name": " "}, format="json").status_code, 400)
        self.assertEqual(c.post(BASE + "conditions/", {"name": "x", "since_year": 1800}, format="json").status_code, 400)


class Private(TestCase):
    def test_nobody_else_can_read_or_delete_it(self):
        a, ca = client("hz_a"); b, cb = client("hz_b")
        ca.post(BASE + "sleep/", {"hours": 7}, format="json")
        ca.post(BASE + "conditions/", {"name": "Migraine"}, format="json")
        self.assertEqual(cb.get(BASE).data["sleep"], [])
        self.assertEqual(cb.get(BASE).data["conditions"], [])
        cb.delete(BASE + f"sleep/{SleepLog.objects.get(user=a).id}/")
        cb.delete(BASE + f"conditions/{HealthCondition.objects.get(user=a).id}/")
        self.assertEqual(SleepLog.objects.filter(user=a).count(), 1)
        self.assertEqual(HealthCondition.objects.filter(user=a).count(), 1)

    def test_deleting_the_account_deletes_both(self):
        a, ca = client("hz_gone")
        ca.post(BASE + "sleep/", {"hours": 7}, format="json")
        ca.post(BASE + "conditions/", {"name": "Migraine"}, format="json")
        a.delete()
        self.assertEqual(SleepLog.objects.count(), 0); self.assertEqual(HealthCondition.objects.count(), 0)

    def test_no_other_module_reads_these_tables(self):
        # A condition or a night's sleep must never reach a rating, price, search or recommendation.
        here = pathlib.Path(__file__).parent
        for f in here.glob("*.py"):
            if f.name in ("healthz.py", "models.py", "urls.py") or f.name.startswith("test_") or f.name == "test_healthz.py":
                continue
            src = f.read_text()
            self.assertNotIn("SleepLog", src, f.name)
            self.assertNotIn("HealthCondition", src, f.name)
