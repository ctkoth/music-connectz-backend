"""CoachZ best score, opened: the highest-scored take, the work behind it, and the coach's read.

Pins: highest is the number the member was shown; the read is the stored one, labelled; the work is
only ever something the viewer can open; and the member's `coach_best` setting gates all of it with
the same 404 as "nothing there".
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import Post, TakeScore, profile_for

User = get_user_model()
PW = "pw12345!"


def url(u, app="rapz"):
    return f"/api/economy/coachbest/{u.username}/{app}/"


class CoachBestTests(TestCase):
    def setUp(self):
        self.star = User.objects.create_user("star", "s@e.com", PW)
        self.fan = User.objects.create_user("fan", "f@e.com", PW)
        self.c = APIClient()
        self.c.force_authenticate(self.fan)

    def take(self, overall, **kw):
        read = {"verdict": f"verdict {overall}", "strengths": ["tight pocket"], "fixes": ["breathe earlier"]}
        read.update(kw.pop("read", {}))
        return TakeScore.objects.create(user=self.star, app_key=kw.pop("app_key", "rapz"), overall=overall,
                                        scores={"flow": overall, "timing": overall - 1, "invented": 3},
                                        read=read, **kw)

    def get(self, u=None, app="rapz", client=None):
        return (client or self.c).get(url(u or self.star, app))

    def test_it_opens_the_highest_take_with_its_labelled_read(self):
        self.take(6)
        best = self.take(9)
        self.take(7)
        r = self.get()
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertEqual(d["take"]["id"], best.pk)
        read = d["coach"]["read"]
        self.assertEqual(d["coach"]["state"], "shown")
        self.assertEqual(read["score"], 9)
        self.assertEqual(read["verdict"], "verdict 9")
        self.assertEqual(read["strengths"], ["tight pocket"])
        self.assertEqual(read["fixes"], ["breathe earlier"])
        # Every number has its label; a dimension the server cannot name is dropped.
        self.assertEqual(set(read["scores"]), {"flow", "timing"})
        self.assertEqual(set(read["labels"]), {"flow", "timing"})
        self.assertTrue(read["caveat"])

    def test_the_exact_score_breaks_a_tie_on_the_overall(self):
        self.take(8, read={"exact": 8.4})
        sharper = self.take(8, read={"exact": 8.7})
        self.take(8, read={"exact": 8.1})
        self.assertEqual(self.get().json()["take"]["id"], sharper.pk)

    def test_among_equals_the_one_with_work_to_open_wins(self):
        post = Post.objects.create(author=self.star, title="My verse", media_url="/m/a.mp3", media_type="audio")
        with_post = self.take(8, source="post", ref=f"post:{post.pk}")
        self.take(8)                                   # newer, nothing to open
        d = self.get().json()
        self.assertEqual(d["take"]["id"], with_post.pk)
        self.assertEqual(d["work"]["kind"], "post")
        self.assertEqual(d["work"]["id"], post.pk)
        self.assertEqual(d["work"]["media_url"], "/m/a.mp3")

    def test_a_post_carrying_the_takes_read_is_the_work(self):
        t = self.take(9, share_token="tok123")
        post = Post.objects.create(author=self.star, title="Posted take",
                                   score={"score": 9, "share_token": "tok123", "source": "share"})
        d = self.get().json()
        self.assertEqual(d["take"]["id"], t.pk)
        self.assertEqual(d["work"]["id"], post.pk)
        self.assertEqual(d["share_url"], "/s/tok123")

    def test_a_post_the_viewer_cannot_open_is_not_offered(self):
        post = Post.objects.create(author=self.star, title="Private", visibility="private")
        self.take(9, source="post", ref=f"post:{post.pk}")
        d = self.get().json()
        self.assertIsNone(d["work"])
        self.assertTrue(d["work_note"])

    def test_a_coach_recording_is_never_handed_to_somebody_else(self):
        from apps.economy.models import Upload
        up = Upload.objects.create(user=self.star, file="uploads/1/take.webm", name="take.webm",
                                   content_type="audio/webm", size_bytes=10)
        self.take(9, upload=up, source="upload")
        self.assertIsNone(self.get().json()["work"])
        # The member's own kept recording is theirs to open.
        own = APIClient()
        own.force_authenticate(self.star)
        self.assertEqual(self.get(client=own).json()["work"]["kind"], "file")

    def test_a_youtube_take_opens_its_public_address(self):
        self.take(9, source="link", ref="https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        w = self.get().json()["work"]
        self.assertEqual(w["kind"], "link")
        self.assertTrue(w["url"].startswith("https://www.youtube.com/"))

    def test_the_members_own_setting_hides_it_with_the_same_404_as_nothing(self):
        self.take(9)
        p = profile_for(self.star)
        p.visibility = {"coach_best": "private"}
        p.save(update_fields=["visibility"])
        hidden = self.get()
        nothing = self.get(app="drumz")
        self.assertEqual(hidden.status_code, 404)
        self.assertEqual(nothing.status_code, 404)
        self.assertEqual(hidden.json(), nothing.json())
        # …and the member still sees their own.
        own = APIClient()
        own.force_authenticate(self.star)
        self.assertEqual(self.get(client=own).status_code, 200)

    def test_unknown_member_or_coach_and_no_sign_in(self):
        self.assertEqual(self.c.get("/api/economy/coachbest/nobody/rapz/").status_code, 404)
        self.take(9)
        self.assertEqual(self.get(app="notacoach").status_code, 404)
        self.assertIn(self.get(client=APIClient()).status_code, (401, 403))

    def test_the_paid_gear_advice_is_not_served(self):
        self.take(9, upgrades={"summary": "buy this mic", "context": {"heard": [{"dim": "flow", "what": "x"}]}})
        self.assertNotIn("buy this mic", self.get().content.decode())
