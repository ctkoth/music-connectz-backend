"""ViewZ — the number a creator asks for first, made honest.

The test this whole app holds a number to: *could somebody get a good one
without getting good?* A hit counter fails it in one refresh. So the rows
below pin the four things that make a view mean something:

  a view is a viewer-day, your own looks never count, "watching" is live and
  separate from the total, and the timeline reports the quiet hours too.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.models import Post, ViewSession
from apps.economy.viewz import (WATCHING_SECONDS, clean_target, lanes_for,
                                local_day)

User = get_user_model()
URL = "/api/economy/viewz/"


class TargetTests(TestCase):
    def test_it_takes_the_shapes_the_app_uses(self):
        for good in ("post:12", "tab:postz", "member:NovaBeatz", "work:9"):
            self.assertEqual(clean_target(good), good)

    def test_it_refuses_anything_else(self):
        # It is a database key written by a client and echoed to other
        # clients, so it is validated rather than trusted.
        for bad in ("", "nope", "post:", ":12", "POST:12", "post:12 or 1=1",
                    "<script>:1", "a" * 200):
            self.assertEqual(clean_target(bad), "", bad)


class CountingTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user("author", "a@e.com", "pw12345678")
        self.fan = User.objects.create_user("fan", "f@e.com", "pw12345678")
        self.post = Post.objects.create(author=self.author, title="a track")
        self.target = f"post:{self.post.id}"

    def look(self, user=None, viewer_id=None):
        c = APIClient()
        if user:
            c.force_authenticate(user)
        if viewer_id:
            c.credentials(HTTP_X_MCZ_VIEWER=viewer_id)
        return c.post(URL, {"target": self.target}, format="json")

    def test_a_view_is_a_person_not_a_page_load(self):
        for _ in range(5):
            r = self.look(self.fan)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["views"], 1)
        self.assertEqual(r.data["viewers"], 1)

    def test_only_the_first_look_of_the_day_is_counted_as_new(self):
        self.assertTrue(self.look(self.fan).data["counted"])
        self.assertFalse(self.look(self.fan).data["counted"])

    def test_coming_back_tomorrow_does_count(self):
        self.look(self.fan)
        # The app's own "today" — the 04:20 day Energy resets on, so views
        # and ⚡ never disagree about which day it is.
        ViewSession.objects.filter(target=self.target).update(
            day=local_day() - timedelta(days=1))
        self.assertEqual(self.look(self.fan).data["views"], 2)

    def test_the_author_looking_at_their_own_post_is_not_reach(self):
        r = self.look(self.author)
        self.assertFalse(r.data["counted"])
        self.assertEqual(r.data["views"], 0)

    def test_a_logged_out_viewer_counts_once_per_browser(self):
        self.look(viewer_id="browser-a")
        self.look(viewer_id="browser-a")
        r = self.look(viewer_id="browser-b")
        self.assertEqual(r.data["views"], 2)
        self.assertEqual(r.data["viewers"], 2)

    def test_a_logged_out_viewer_with_no_id_is_not_counted_at_all(self):
        """A viewer we cannot tell from the next one is a hit counter wearing
        a viewer count's clothes."""
        r = self.look()
        self.assertFalse(r.data["counted"])
        self.assertEqual(r.data["views"], 0)

    def test_watching_is_live_and_separate_from_the_total(self):
        self.look(self.fan)
        self.assertEqual(self.look(self.fan).data["watching"], 1)
        ViewSession.objects.filter(target=self.target).update(
            last_beat_at=timezone.now() - timedelta(seconds=WATCHING_SECONDS + 60))
        r = APIClient().get(URL, {"target": self.target})
        self.assertEqual(r.data["watching"], 0)
        self.assertEqual(r.data["views"], 1, "the total does not decay, only 'watching' does")

    def test_a_missing_target_is_a_400_not_a_silent_zero(self):
        self.assertEqual(APIClient().post(URL, {}, format="json").status_code, 400)
        self.assertEqual(APIClient().get(URL).status_code, 400)

    def test_the_read_says_what_it_is_counting(self):
        # A viewer count built partly from a clearable browser id is a floor.
        # Presenting a floor as a total is decoration wearing a measurement's
        # clothes, which is the one thing this codebase will not ship.
        r = APIClient().get(URL, {"target": self.target})
        self.assertIn("floor", r.data["note"])
        self.assertIn("per day", r.data["note"])


class TimelineTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("t", "t@e.com", "pw12345678")

    def test_every_hour_is_returned_including_the_quiet_ones(self):
        """The flat stretch is half of what makes the spike legible."""
        out = lanes_for("tab:postz")
        self.assertEqual(len(out["lanes"]), out["hours"])
        self.assertTrue(all("at" in l and "views" in l for l in out["lanes"]))

    def test_a_day_with_nothing_in_it_is_flat_not_stretched(self):
        out = lanes_for("tab:postz")
        self.assertEqual(out["peak"], 0)
        self.assertTrue(all(l["level"] == 0.0 for l in out["lanes"]))

    def test_the_level_is_scaled_against_the_peak(self):
        now = timezone.now()
        for i, n in ((1, 4), (3, 1)):
            for k in range(n):
                ViewSession.objects.create(
                    target="tab:postz", viewer=None, anon_key=f"{i}-{k}",
                    day=now.date(), started_at=now - timedelta(hours=i, minutes=5),
                    last_beat_at=now)
        out = lanes_for("tab:postz")
        self.assertEqual(out["peak"], 4)
        self.assertEqual(max(l["level"] for l in out["lanes"]), 1.0)
        self.assertIn(0.25, [l["level"] for l in out["lanes"]])


class MineTests(TestCase):
    def test_it_lists_my_posts_with_a_way_back_to_each(self):
        me = User.objects.create_user("m", "m@e.com", "pw12345678")
        fan = User.objects.create_user("f2", "f2@e.com", "pw12345678")
        quiet = Post.objects.create(author=me, title="quiet one")
        loud = Post.objects.create(author=me, title="loud one")
        c = APIClient(); c.force_authenticate(fan)
        c.post(URL, {"target": f"post:{loud.id}"}, format="json")
        mine = APIClient(); mine.force_authenticate(me)
        rows = mine.get("/api/economy/viewz/mine/").data["items"]
        self.assertEqual(rows[0]["title"], "loud one")
        self.assertEqual(rows[0]["views"], 1)
        self.assertTrue(all(r["open_in"] == "postz" for r in rows))
        self.assertIn("quiet one", [r["title"] for r in rows],
                      "a post with no views still has to be listed — "
                      "silence is the answer, not the absence of one")
