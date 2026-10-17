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


class VisitorLaneTests(TestCase):
    def test_each_visitor_is_their_own_track_with_device_and_source(self):
        owner = User.objects.create_user("own", "o@e.com", "pw-Long-enough-1")
        post = Post.objects.create(author=owner, title="Drop")
        t = f"post:{post.id}"
        anon = APIClient()
        anon.post(f"{V}start/", {"target": t, "anon_id": "aaa", "src": "instagram", "dev": "phone"}, format="json")
        anon.post(f"{V}start/", {"target": t, "anon_id": "bbb", "src": "BAD src!", "dev": "toaster"}, format="json")
        o = APIClient(); o.force_authenticate(owner)
        with patch("apps.economy.statz_trial.has_statz", return_value=True):
            d = o.get(f"{V}timeline/").json()
        lanes = {l["viewer"]: l for l in d["lanes"]}
        self.assertEqual(set(lanes), {"Visitor 1", "Visitor 2"})
        self.assertEqual((lanes["Visitor 1"]["dev"], lanes["Visitor 1"]["src"]), ("phone", "instagram"))
        self.assertEqual((lanes["Visitor 2"]["dev"], lanes["Visitor 2"]["src"]), ("", ""))
        self.assertEqual((d["members"], d["visitors"]), (0, 2))
        self.assertNotIn("aaa", str(d))


class ResultsTests(TestCase):
    """How a post did: numbers for everybody, names and tracks for StatZ — live and
    over time, derived from the sessions so the past is as true as now."""

    def setUp(self):
        from apps.economy.models import ItemRating, Message, ScoreShare, SocialComment
        self.owner = User.objects.create_user("poster", "p@e.com", "pw-Long-enough-1")
        self.fan = User.objects.create_user("listener", "l@e.com", "pw-Long-enough-1")
        self.post = Post.objects.create(author=self.owner, title="Hook one")
        self.t = f"post:{self.post.id}"
        now = timezone.now()

        def sess(viewer=None, anon="", started=None, secs=20, **kw):
            started = started or now - timedelta(minutes=5)
            row = ViewSession.objects.create(viewer=viewer, anon_id=anon, target=self.t, owner=self.owner,
                                             ended_at=started + timedelta(seconds=secs), **kw)
            # started_at is auto_now_add, so a past start has to be written after.
            ViewSession.objects.filter(pk=row.pk).update(started_at=started)
            return row

        sess(self.fan, started=now - timedelta(hours=3), secs=40)
        sess(self.fan, started=now - timedelta(minutes=2), secs=30, src="instagram", dev="phone")   # came back
        sess(None, anon="aaa", secs=2)                                                              # a bounce
        sess(None, anon="bbb", secs=60, src="tiktok", dev="phone")
        ItemRating.objects.create(user=self.fan, item_id=self.t, score=8)
        SocialComment.objects.create(user=self.fan, item_id=self.t, body="hot")
        Message.objects.create(sender=self.fan, recipient=self.owner, body="nice one")
        self.o = APIClient(); self.o.force_authenticate(self.owner)

    def test_only_the_author_reads_a_posts_results(self):
        other = APIClient(); other.force_authenticate(self.fan)
        self.assertEqual(other.get(f"{V}post/{self.post.id}/").status_code, 404)
        self.assertIn(APIClient().get(f"{V}post/{self.post.id}/").status_code, (401, 403))

    def test_the_numbers_are_every_tiers_and_are_defined_on_the_screen(self):
        d = self.o.get(f"{V}post/{self.post.id}/").json()
        self.assertEqual((d["visits"], d["views"], d["people"], d["members"], d["visitors"]), (4, 3, 3, 1, 2))
        self.assertEqual(d["stayed_pct"], 75)             # 3 of 4 visits lasted
        self.assertEqual(d["came_back_pct"], 33)          # 1 of 3 people
        self.assertEqual(d["actions"]["rated"], 1)
        self.assertEqual(d["actions"]["commented"], 1)
        self.assertEqual(d["actions"]["messaged"], 1)
        self.assertEqual(d["actions"]["acted"], 1)
        self.assertIn("stayed", d["definitions"])
        self.assertIsNone(d["viewers"])                   # names are StatZ's
        self.assertIn("StatZ", d["viewers_locked"])
        self.assertEqual(len(d["by_day"]), 14)

    def test_statz_sees_each_viewer_as_a_track_with_what_they_did(self):
        with patch("apps.economy.statz_trial.has_statz", return_value=True):
            d = self.o.get(f"{V}post/{self.post.id}/").json()
        by = {v["viewer"]: v for v in d["viewers"]}
        self.assertEqual(set(by), {"listener", "Visitor 1", "Visitor 2"})
        fan = by["listener"]
        self.assertEqual((fan["sessions"], fan["came_back"], fan["rated"], fan["commented"], fan["messaged"]),
                         (2, True, 8, 1, 1))
        self.assertEqual(len(fan["clips"]), 2)
        self.assertEqual(sum(c["seconds"] for c in fan["clips"]), fan["seconds"])
        self.assertIn("start", fan["clips"][0])
        self.assertTrue(d["from"] < d["to"])
        self.assertNotIn("aaa", str(d))                   # a browser's id never leaves the server

    def test_nobody_has_viewed_is_none_not_zero(self):
        empty = Post.objects.create(author=self.owner, title="Quiet")
        d = self.o.get(f"{V}post/{empty.id}/").json()
        self.assertEqual(d["views"], 0)
        self.assertIsNone(d["stayed_pct"])
        self.assertIsNone(d["came_back_pct"])
        self.assertIsNone(d["avg_seconds"])

    def test_live_now_counts_only_sessions_still_beating(self):
        ViewSession.objects.filter(anon_id="bbb").update(ended_at=timezone.now())
        self.assertEqual(self.o.get(f"{V}post/{self.post.id}/").json()["live_now"], 1)

    def test_the_list_carries_every_post_and_every_link_with_its_opens(self):
        from apps.economy.models import ScoreShare
        ScoreShare.objects.create(token="tok1", app_key="rapz", score=7, user=self.owner, views=5)
        ScoreShare.objects.create(token="tok2", app_key="rapz", score=6, user=self.fan, views=99)
        d = self.o.get(f"{V}mine/").json()
        self.assertEqual([p["id"] for p in d["posts"]], [self.post.id])
        self.assertEqual([l["token"] for l in d["links"]], ["tok1"])      # yours only
        self.assertEqual(d["links_opens"], 5)
        self.assertEqual(d["posts"][0]["views"], 3)


class PromoLinkResultsInTheLedgerTests(TestCase):
    """A promo post's LogZ row shows how its link is doing — read now, so the same
    row answers differently tomorrow, and only ever for the member's own take."""

    def test_the_row_carries_the_links_opens_and_nothing_for_a_forged_ref(self):
        from apps.economy.logz_outcomes import outcomes_for
        from apps.economy.models import ScoreShare, SentenceWork, TakeScore
        u = User.objects.create_user("promoter", "pr@e.com", "pw-Long-enough-1")
        other = User.objects.create_user("nosy", "n@e.com", "pw-Long-enough-1")
        take = TakeScore.objects.create(user=u, app_key="rapz", overall=6, share_token="tokx")
        ScoreShare.objects.create(token="tokx", app_key="rapz", score=6, user=u, views=7)
        w = SentenceWork.objects.create(user=u, kind="post", topic="t", text="post body",
                                        inputs={"promo_take": take.pk})
        plain = SentenceWork.objects.create(user=u, kind="post", topic="t", text="x", inputs={})
        rows = [{"ref": f"sentence:{w.pk}"}, {"ref": f"sentence:{plain.pk}"}]
        out = outcomes_for(u, rows)
        self.assertEqual(out[f"sentence:{w.pk}"]["results"]["opens"], 7)
        self.assertEqual(out[f"sentence:{w.pk}"]["results"]["url"], "/s/tokx")
        self.assertIsNone(out[f"sentence:{plain.pk}"]["results"])
        ScoreShare.objects.filter(token="tokx").update(views=9)          # later, the same row says more
        self.assertEqual(outcomes_for(u, rows)[f"sentence:{w.pk}"]["results"]["opens"], 9)
        self.assertEqual(outcomes_for(other, rows), {})                   # a forged ref reads as nothing
