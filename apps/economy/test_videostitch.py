"""Stitched music video: priced before it starts, all-or-nothing at the start,
built from the shots that landed, with the member's own track under it."""
import os
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.economy import videostitch
from apps.economy.models import Upload, VideoStitch, VideoWork, wallet_for

User = get_user_model()
URL = "/api/economy/videoz/stitch/"
EXE = videostitch.ffmpeg_exe()


def ok(op="operations/x"):
    r = MagicMock(status_code=200, text="{}")
    r.json.return_value = {"name": op}
    return r


def media(kind, tmp):
    path = os.path.join(tmp, "m." + ("mp4" if kind == "v" else "m4a"))
    src = ["-f", "lavfi", "-i", "testsrc=duration=2:size=160x90:rate=24"] if kind == "v" \
        else ["-f", "lavfi", "-i", "sine=frequency=440:duration=12"]
    codec = ["-c:v", "libx264", "-pix_fmt", "yuv420p"] if kind == "v" else ["-c:a", "aac"]
    subprocess.run([EXE, "-y", *src, *codec, path], capture_output=True, check=True)
    return open(path, "rb").read()


@patch.dict(os.environ, {"VIDEO_CONNECTZ_CENTS": "400"})
@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
@patch("apps.economy.videoz._key", return_value="K")
class VideoStitchTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("maker", "m@e.com", "pw-Long-enough-1")
        w = wallet_for(self.u); w.promptz = 0; w.money_cents = 5000; w.save()
        self.c = APIClient(); self.c.force_authenticate(self.u)
        self.track = Upload.objects.create(user=self.u, name="song.mp3", content_type="audio/mpeg")
        self.track.file.save("song.mp3", ContentFile(b"x"), save=True)

    def body(self, **kw):
        return {"track_id": self.track.id, "shots": ["rooftop", "crowd", "close up"], "look": "neon", **kw}

    def start(self, **kw):
        with patch("apps.economy.videoz.requests.post", return_value=ok()):
            return self.c.post(URL, self.body(**kw), format="json")

    def test_the_total_is_published_before_anything_starts(self, _):
        d = self.c.get(URL).json()
        self.assertEqual(d["prices"]["3"], 3 * d["clip_price_cents"])
        self.assertEqual([t["id"] for t in d["tracks"]], [self.track.id])

    def test_starting_holds_every_shot(self, _):
        r = self.start()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(VideoWork.objects.count(), 3)
        self.assertEqual(wallet_for(self.u).money_cents, 5000 - 3 * 400)

    def test_a_shot_that_cannot_start_refunds_the_rest(self, _):
        bad = MagicMock(status_code=400, text="{}"); bad.json.return_value = {"error": {"message": "x"}}
        with patch("apps.economy.videoz.requests.post", side_effect=[ok(), bad]):
            r = self.c.post(URL, self.body(), format="json")
        self.assertEqual(r.status_code, 502)
        self.assertIn("Nothing was charged", r.json()["detail"])
        self.assertEqual(wallet_for(self.u).money_cents, 5000)
        self.assertFalse(VideoStitch.objects.exists())

    def test_too_poor_for_all_shots_holds_nothing(self, _):
        w = wallet_for(self.u); w.money_cents = 900; w.save()
        r = self.start()
        self.assertEqual(r.status_code, 402)
        self.assertEqual(VideoWork.objects.count(), 0)

    def test_the_track_must_be_your_own_audio(self, _):
        other = User.objects.create_user("other", "o@e.com", "pw-Long-enough-1")
        theirs = Upload.objects.create(user=other, name="t.mp3", content_type="audio/mpeg")
        self.assertEqual(self.start(track_id=theirs.id).status_code, 400)
        pic = Upload.objects.create(user=self.u, name="p.png", content_type="image/png")
        self.assertEqual(self.start(track_id=pic.id).status_code, 400)

    def test_shot_count_is_bounded(self, _):
        self.assertEqual(self.start(shots=["one"]).status_code, 400)
        self.assertEqual(self.start(shots=["a"] * 7).status_code, 400)

    @unittest.skipUnless(EXE, "no ffmpeg available")
    def test_landed_shots_are_joined_with_the_track_and_a_failed_one_is_left_out(self, _):
        tmp = tempfile.mkdtemp()
        clip, song = media("v", tmp), media("a", tmp)
        self.track.file.save("song.m4a", ContentFile(song), save=True)
        self.start()
        st = VideoStitch.objects.get()
        works = list(VideoWork.objects.order_by("id"))
        for w in works[:2]:
            up = Upload(user=self.u, name="c.mp4", content_type="video/mp4")
            up.file.save("c.mp4", ContentFile(clip), save=False); up.save()
            VideoWork.objects.filter(pk=w.pk).update(status="done", upload=up)
        VideoWork.objects.filter(pk=works[2].pk).update(status="failed")
        with patch("apps.economy.videostitch.poll"):
            d = self.c.get(f"{URL}{st.id}/").json()
        self.assertEqual(d["status"], "done", d)
        self.assertEqual((d["rendered"], d["failed"]), (2, 1))
        st.refresh_from_db()
        self.assertGreater(st.upload.size_bytes, 1000)
        self.assertEqual(st.upload.content_type, "video/mp4")

    def test_nothing_landed_fails_without_inventing_a_video(self, _):
        self.start()
        st = VideoStitch.objects.get()
        VideoWork.objects.update(status="failed")
        with patch("apps.economy.videostitch.poll"):
            d = self.c.get(f"{URL}{st.id}/").json()
        self.assertEqual(d["status"], "failed")
        self.assertIsNone(d["video_url"])


@patch.dict(os.environ, {"VIDEO_CONNECTZ_CENTS": "400"})
@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
@patch("apps.economy.videoz._key", return_value="K")
class OwnerShortBalanceTests(TestCase):
    """The superuser can render and run prompts with a short balance; nobody else can."""

    def make(self, **kw):
        name = kw.pop("name")
        u = User.objects.create_user(name, f"{name}@e.com", "pw-Long-enough-1", **kw)
        w = wallet_for(u); w.promptz = 0; w.money_cents = 0; w.save()
        t = Upload.objects.create(user=u, name="s.mp3", content_type="audio/mpeg")
        c = APIClient(); c.force_authenticate(u)
        return u, t, c

    def post(self, c, t):
        with patch("apps.economy.videoz.requests.post", return_value=ok()):
            return c.post(URL, {"track_id": t.id, "shots": ["a", "b"]}, format="json")

    def test_owner_renders_with_nothing_held(self, _):
        u, t, c = self.make(name="boss", is_superuser=True)
        self.assertEqual(self.post(c, t).status_code, 201)
        self.assertEqual(wallet_for(u).money_cents, 0)
        self.assertEqual(VideoWork.objects.filter(user=u).count(), 2)
        self.assertTrue(c.get("/api/economy/videoz/").json()["can_afford"])

    def test_everyone_else_is_still_refused(self, _):
        u, t, c = self.make(name="member")
        self.assertEqual(self.post(c, t).status_code, 402)
        self.assertFalse(c.get("/api/economy/videoz/").json()["can_afford"])

    def test_owner_prompts_run_when_short_and_leave_a_zero_ledger_line(self, _):
        from apps.economy.models import Transaction, charge_ai_usage
        owner, _t, _c = self.make(name="boss2", is_superuser=True)
        member, _t2, _c2 = self.make(name="member2")
        self.assertIsNotNone(charge_ai_usage(owner, 300, "Test run"))
        self.assertTrue(Transaction.objects.filter(user=owner, amount_cents=0, note__contains="owner").exists())
        self.assertIsNone(charge_ai_usage(member, 300, "Test run"))


class VideoPriceIsSmallTests(TestCase):
    def test_a_clip_costs_one_promptz_and_a_stitched_video_one_per_shot(self):
        from apps.economy.videoz import price_cents
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VIDEO_CONNECTZ_CENTS", None)
            self.assertEqual(price_cents(), 1)
            # Common sense: the dearest video must cost less than the best tier's
            # whole day of prompts, or nobody could ever make it.
            from apps.economy.models import PROMPT_ALLOWANCE
            self.assertLess(videostitch.MAX_SHOTS * price_cents(), PROMPT_ALLOWANCE["statz"])
