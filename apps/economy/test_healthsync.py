"""Steps from Health Connect: private, device-reported, and worth nothing."""
import pathlib
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy import healthsync
from apps.economy.models import HealthLink, StepDay

U = get_user_model()


def member(name):
    return U.objects.create_user(name, password="pw12345!x")


def client(u=None):
    c = APIClient()
    if u:
        c.force_authenticate(u)
    return c


def linked(u):
    code = client(u).post("/api/economy/health/pair/").json()["code"]
    return client().post("/api/economy/health/link/", {"code": code}, format="json").json()["token"]


class HealthSyncTests(TestCase):
    def setUp(self):
        cache.clear()
        self.u = member("walker")

    def sync(self, token, days):
        return client().post("/api/economy/health/steps/", {"days": days}, format="json", HTTP_X_HEALTH_TOKEN=token)

    def test_pair_link_sync_read(self):
        token = linked(self.u)
        today = timezone.localdate().isoformat()
        self.assertEqual(self.sync(token, [{"day": today, "steps": 8123}]).json()["saved"], 1)
        s = client(self.u).get("/api/economy/health/").json()
        self.assertTrue(s["linked"])
        self.assertEqual(s["days"][0], {"day": today, "steps": 8123})
        self.assertFalse(s["pays"])

    def test_a_later_sync_replaces_the_day(self):
        token = linked(self.u)
        today = timezone.localdate().isoformat()
        self.sync(token, [{"day": today, "steps": 100}])
        self.sync(token, [{"day": today, "steps": 900}])
        self.assertEqual(StepDay.objects.get(user=self.u).steps, 900)

    def test_code_is_single_use_and_expires(self):
        code = client(self.u).post("/api/economy/health/pair/").json()["code"]
        self.assertEqual(client().post("/api/economy/health/link/", {"code": code}, format="json").status_code, 200)
        self.assertEqual(client().post("/api/economy/health/link/", {"code": code}, format="json").status_code, 400)
        code = client(self.u).post("/api/economy/health/pair/").json()["code"]
        HealthLink.objects.filter(user=self.u).update(code_expires=timezone.now() - timedelta(seconds=1))
        self.assertEqual(client().post("/api/economy/health/link/", {"code": code}, format="json").status_code, 400)

    def test_wrong_codes_are_rate_limited(self):
        for _ in range(8):
            self.assertEqual(client().post("/api/economy/health/link/", {"code": "ZZZZZZZZ"}, format="json").status_code, 400)
        self.assertEqual(client().post("/api/economy/health/link/", {"code": "ZZZZZZZZ"}, format="json").status_code, 429)

    def test_no_token_or_wrong_token_is_refused(self):
        today = timezone.localdate().isoformat()
        self.assertEqual(self.sync("", [{"day": today, "steps": 5}]).status_code, 401)
        self.assertEqual(self.sync("nope", [{"day": today, "steps": 5}]).status_code, 401)
        self.assertEqual(StepDay.objects.count(), 0)

    def test_the_token_is_stored_only_as_a_hash(self):
        token = linked(self.u)
        self.assertNotIn(token, HealthLink.objects.get(user=self.u).token_hash)

    def test_junk_days_are_dropped_not_repaired(self):
        token = linked(self.u)
        t = timezone.localdate()
        rows = [{"day": t.isoformat(), "steps": 6000}, {"day": t.isoformat(), "steps": -4}, {"day": "x", "steps": 3},
                {"day": (t - timedelta(days=400)).isoformat(), "steps": 5}, {"day": t.isoformat(), "steps": 10**7}, "str"]
        self.assertEqual(self.sync(token, [rows[0]] + rows[1:]).json()["saved"], 1)
        self.assertEqual(list(StepDay.objects.values_list("steps", flat=True)), [6000])

    def test_steps_are_private_to_their_owner(self):
        token = linked(self.u)
        self.sync(token, [{"day": timezone.localdate().isoformat(), "steps": 777}])
        other = member("nosy")
        self.assertEqual(client(other).get("/api/economy/health/").json()["days"], [])

    def test_unlink_deletes_everything_and_kills_the_token(self):
        token = linked(self.u)
        today = timezone.localdate().isoformat()
        self.sync(token, [{"day": today, "steps": 5}])
        self.assertFalse(client(self.u).delete("/api/economy/health/").json()["linked"])
        self.assertEqual(StepDay.objects.count(), 0)
        self.assertEqual(self.sync(token, [{"day": today, "steps": 5}]).status_code, 401)

    def test_deleting_the_account_takes_the_steps(self):
        token = linked(self.u)
        self.sync(token, [{"day": timezone.localdate().isoformat(), "steps": 5}])
        self.u.delete()
        self.assertEqual((StepDay.objects.count(), HealthLink.objects.count()), (0, 0))

    def test_steps_are_read_by_nothing_else(self):
        """They pay nothing and move nothing: no other module may name the table."""
        here = pathlib.Path(__file__).parent
        for f in here.rglob("*.py"):
            if f.name in ("healthsync.py", "models.py", "test_healthsync.py") or "migrations" in f.parts:
                continue
            self.assertNotIn("StepDay", f.read_text(), f.name)
            self.assertNotIn("step_days", f.read_text(), f.name)


class AndroidScopeTests(TestCase):
    """The health permission lives in the two apps that carry the steps screen, and nowhere else."""
    ROOT = pathlib.Path(__file__).resolve().parents[2] / "android" / "app" / "src"

    def test_only_mcz_and_bodiez_declare_it(self):
        for flavor in ("mcz", "bodiez"):
            self.assertIn("health.READ_STEPS", (self.ROOT / flavor / "AndroidManifest.xml").read_text())
        for other in ("main", "skillz", "intelligencez"):
            m = self.ROOT / other / "AndroidManifest.xml"
            if m.exists():
                self.assertNotIn("health", m.read_text().lower().replace("healthsync", ""), other)

    def test_only_steps_are_requested(self):
        text = (self.ROOT / "health" / "java" / "net" / "musicconnectz" / "app" / "HealthLinkActivity.kt").read_text()
        self.assertIn("StepsRecord", text)
        for banned in ("HeartRate", "ExerciseSession", "Location", "Sleep", "Weight"):
            self.assertNotIn(banned, text)

    def test_the_gradle_wiring_names_only_those_two(self):
        g = (self.ROOT.parent / "build.gradle.kts").read_text()
        self.assertIn('getByName("mcz").java.srcDir("src/health/java")', g)
        self.assertIn('getByName("bodiez").java.srcDir("src/health/java")', g)
        self.assertNotIn("skillzImplementation", g)
        self.assertNotIn("intelligencezImplementation", g)
