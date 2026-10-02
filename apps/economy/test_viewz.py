"""ViewZ: a view is a session that lasted, owners don't count themselves,
the count is public and the timeline is StatZ."""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.models import Post, ViewSession

User = get_user_model()
V = "/api/economy/views/"


class ViewzTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("maker", "m@e.com", "pw-Long-enough-1")
        self.fan = User.objects.create_user("fan", "f@e.com", "pw-Long-enough-1")
        self.post = Post.objects.create(author=self.owner, title="Night drive")
        self.t = f"post:{self.post.id}"
        self.c = APIClient(); self.c.force_authenticate(self.fan)

    def age(self, seconds):
        ViewSession.objects.update(started_at=timezone.now() - timedelta(seconds=seconds))

    def count(self):
        return APIClient().get(f"{V}counts/", {"t": self.t}).json()["counts"][self.t]

    def test_a_view_counts_once_it_has_lasted(self):
        sid = self.c.post(f"{V}start/", {"target": self.t}, format="json").json()["id"]
        self.assertEqual(self.count(), 0)          # loaded, not yet a view
        self.age(10)
        self.c.post(f"{V}beat/", {"ids": [sid]}, format="json")
        self.assertEqual(self.count(), 1)

    def test_a_refresh_is_not_a_second_view(self):
        a = self.c.post(f"{V}start/", {"target": self.t}, format="json").json()["id"]
        b = self.c.post(f"{V}start/", {"target": self.t}, format="json").json()["id"]
        self.assertEqual(a, b)
        self.assertEqual(ViewSession.objects.count(), 1)

    def test_owners_never_count_themselves(self):
        o = APIClient(); o.force_authenticate(self.owner)
        self.assertFalse(o.post(f"{V}start/", {"target": self.t}, format="json").json()["counted"])
        self.assertFalse(ViewSession.objects.exists())

    def test_only_your_own_sessions_beat(self):
        sid = self.c.post(f"{V}start/", {"target": self.t}, format="json").json()["id"]
        other = APIClient(); other.force_authenticate(self.owner)
        self.assertEqual(other.post(f"{V}beat/", {"ids": [sid]}, format="json").json()["moved"], 0)

    def test_visitors_count_by_browser_and_are_capped_per_address(self):
        anon = APIClient()
        r = anon.post(f"{V}start/", {"target": self.t, "anon_id": "abc"}, format="json").json()
        self.assertTrue(r["counted"])
        with patch("apps.economy.viewz.ANON_STARTS_PER_HOUR", 1):
            r2 = anon.post(f"{V}start/", {"target": self.t, "anon_id": "zzz"}, format="json").json()
        self.assertFalse(r2["counted"])

    def test_junk_targets_are_refused(self):
        for t in ("post:x", "tab:../../etc", "profile:nobody-here!", "post:99999"):
            self.assertIn(self.c.post(f"{V}start/", {"target": t}, format="json").status_code, (400, 404))

    def test_timeline_is_statz_and_shows_viewers_as_tracks(self):
        self.c.post(f"{V}start/", {"target": self.t}, format="json")
        o = APIClient(); o.force_authenticate(self.owner)
        self.assertEqual(o.get(f"{V}timeline/").status_code, 403)
        with patch("apps.economy.statz_trial.has_statz", return_value=True):
            d = o.get(f"{V}timeline/", {"range": "24h"}).json()
        self.assertEqual(d["lanes"][0]["viewer"], "fan")
        self.assertEqual(d["lanes"][0]["clips"][0]["label"], "Night drive")
        self.assertIn("StatZ creators can see who viewed", d["notice"])

    def test_only_the_platform_owner_reads_every_tab(self):
        self.owner.is_staff = True; self.owner.save()
        self.c.post(f"{V}start/", {"target": "tab:postz"}, format="json")
        o = APIClient(); o.force_authenticate(self.owner)
        with patch("apps.economy.statz_trial.has_statz", return_value=True):
            mine = o.get(f"{V}timeline/").json()
            every = o.get(f"{V}timeline/", {"scope": "all"}).json()
        self.assertEqual(mine["total_views"], 0)
        self.assertEqual(every["total_views"], 1)
        with patch("apps.economy.statz_trial.has_statz", return_value=True):
            self.assertEqual(self.c.get(f"{V}timeline/", {"scope": "all"}).json()["scope"], "mine")
