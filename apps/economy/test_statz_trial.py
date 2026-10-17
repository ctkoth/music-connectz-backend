"""The StatZ sample: once per member, a real end time, and only the features
that can switch off again."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy import statz_trial
from apps.economy.models import StatzTrial, membership_for

URL = "/api/economy/statz-trial/"


class StatzTrialTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("t", "t@e.com", "pw-Long-enough-1")
        self.c = APIClient(); self.c.force_authenticate(self.user)

    def test_offered_then_started_then_counting_down(self):
        s = self.c.get(URL).json()
        self.assertTrue(s["available"]); self.assertFalse(s["active"])
        self.assertFalse(statz_trial.has_statz(self.user))
        s = self.c.post(URL).json()
        self.assertTrue(s["active"]); self.assertFalse(s["available"])
        self.assertGreater(s["seconds_left"], 59 * 60)
        self.assertTrue(statz_trial.has_statz(self.user))

    def test_once_ever(self):
        self.c.post(URL)
        self.assertEqual(self.c.post(URL).status_code, 409)

    def test_it_really_ends(self):
        self.c.post(URL)
        StatzTrial.objects.filter(user=self.user).update(ends_at=timezone.now() - timedelta(seconds=1))
        s = self.c.get(URL).json()
        self.assertFalse(s["active"]); self.assertTrue(s["used"]); self.assertEqual(s["seconds_left"], 0)
        self.assertFalse(statz_trial.has_statz(self.user))
        self.assertEqual(self.c.get("/api/economy/instrumentalz/moods/?q=dark").status_code, 403)

    def test_it_unlocks_mood_search_while_running(self):
        self.c.post(URL)
        self.assertEqual(self.c.get("/api/economy/instrumentalz/moods/?q=dark").status_code, 200)

    def test_it_never_changes_the_real_tier(self):
        before = membership_for(self.user).tier
        self.c.post(URL)
        self.assertEqual(membership_for(self.user).tier, before)
        self.assertEqual(statz_trial.feature_tier(self.user), "statz")

    def test_statz_members_are_not_offered_one(self):
        m = membership_for(self.user); m.tier = "statz"; m.save()
        s = self.c.get(URL).json()
        self.assertFalse(s["available"]); self.assertTrue(s["is_statz"])
        self.assertEqual(self.c.post(URL).status_code, 400)


class StatzDriversAuditTests(TestCase):
    """Every place StatZ is the difference is on one list, with whether the free hour
    covers it and why not when it doesn't — and the list cannot drift from the code."""

    def test_the_sampled_rows_are_exactly_the_features_the_screen_lists(self):
        from apps.economy.statz_trial import DRIVERS, FEATURES
        self.assertEqual({d["key"] for d in DRIVERS if d["sampled"]}, {f["key"] for f in FEATURES})

    def test_every_unsampled_driver_says_why(self):
        from apps.economy.statz_trial import DRIVERS
        for d in DRIVERS:
            if not d["sampled"]:
                self.assertTrue(len(d.get("why_not", "")) > 20, d["key"])

    def test_a_module_that_asks_for_statz_must_be_on_the_list(self):
        """Walk the source: any module calling has_statz()/feature_tier() that the
        audit does not name is a StatZ gate nobody decided about."""
        import re
        from pathlib import Path
        from apps.economy.statz_trial import FEATURE_MODULES
        root = Path(__file__).parent
        callers = set()
        for f in root.glob("*.py"):
            if f.name.startswith("test_") or f.name == "statz_trial.py":
                continue
            if re.search(r"\b(has_statz|feature_tier)\(", f.read_text(encoding="utf-8")):
                callers.add(f.stem)
        self.assertEqual(callers - FEATURE_MODULES, set(), "a StatZ gate is not on the audit list")
        self.assertEqual({m for m in FEATURE_MODULES if (root / f"{m}.py").exists()} - callers - {"coachvoice", "voicez", "modal_sandbox", "lessonz", "catalog"}, set(),
                         "the audit names a module that no longer gates anything")

    def test_the_state_publishes_what_the_hour_leaves_out_and_when_it_warns(self):
        from django.contrib.auth import get_user_model
        from apps.economy.statz_trial import WARN_AT_SECONDS, state
        u = get_user_model().objects.create_user("auditee", "a@e.com", "pw-Long-enough-1")
        s = state(u)
        self.assertIn("viewz_tracks", [f["key"] for f in s["features"]])
        self.assertIn("custom_voices", [d["key"] for d in s["also_in_statz"]])
        self.assertEqual(s["warn_at_seconds"], WARN_AT_SECONDS)
        self.assertTrue(all(w < 60 * 60 for w in WARN_AT_SECONDS))
