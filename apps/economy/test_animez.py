"""Anime ConnectZ: an editable shot plan from the member's cast, then each shot rendered as a priced Video ConnectZ clip."""
import json
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import animez
from apps.economy.catalog import limits_for
from apps.economy.models import AnimeWork, Character, Membership, VideoWork, membership_for, wallet_for

User = get_user_model()
BASE = "/api/economy/animez/"


def plan_reply(shots):
    r = MagicMock(status_code=200)
    r.json.return_value = {"candidates": [{"content": {"parts": [{"text": json.dumps({"title": "Rooftop", "shots": shots})}]}}]}
    return r


def shots(n):
    return [{"camera": "wide", "setting": "a rooftop at dusk", "action": f"beat {i}", "characters": ["Lou", "Ghost"],
             "dialogue": [{"who": "Lou", "line": "Not today."}, {"who": "Nobody", "line": "x"}]} for i in range(n)]


def veo_ok():
    r = MagicMock(status_code=200)
    r.json.return_value = {"name": "operations/abc"}
    return r


class _Base(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("drawer", "d@e.com", "pw12345678")
        self.c = APIClient(); self.c.force_authenticate(self.u)
        w = wallet_for(self.u); w.promptz = 500; w.save()
        self.lou = Character.objects.create(user=self.u, name="Lou", bio="Talks in puns", looks="red scarf, silver hair")

    def tier(self, t):
        membership_for(self.u)
        Membership.objects.filter(user=self.u).update(tier=t)

    @patch("apps.economy.animez._key", return_value="k")
    @patch("apps.economy.gemini.requests.post")
    def plan(self, fmt, n, rq, _k, **extra):
        rq.return_value = plan_reply(shots(n))
        return self.c.post(f"{BASE}plan/", {"fmt": fmt, "idea": "a duel on a roof", "character_ids": [self.lou.id], "shots": n, **extra}, format="json")


class LadderTests(_Base):
    def test_shots_are_coreys_numbers(self):
        self.assertEqual([limits_for(t)["anime_shots"] for t in ("free", "premium", "statz")], [3, 6, None])

    def test_free_makes_promptz_and_short_reelz_and_is_told_why_not_the_rest(self):
        f = {x["key"]: x for x in self.c.get(BASE).data["formats"]}
        self.assertTrue(f["promptz"]["allowed"])
        self.assertEqual(f["reelz"]["shots_max"], 3)
        self.assertFalse(f["episodez"]["allowed"])
        self.assertIn("starts at 6 shots", f["episodez"]["locked"])
        self.assertEqual(self.plan("reelz", 4).status_code, 403)
        r = self.plan("episodez", 6)
        self.assertEqual(r.status_code, 403)
        self.assertIn("Premium holds 6", r.data["detail"])

    def test_statz_reaches_the_format_ceiling(self):
        self.tier("statz")
        f = {x["key"]: x for x in self.c.get(BASE).data["formats"]}
        self.assertEqual((f["episodez"]["shots_max"], f["moviez"]["shots_max"]), (24, 60))

    def test_the_price_is_said_before_either_button(self):
        d = self.c.get(BASE).data
        self.assertIn("cost_cents", d["plan"])
        self.assertEqual(d["clip_price_cents"], animez.price_cents())
        self.assertIn("8 s", d["length_note"])


class PlanTests(_Base):
    def test_the_plan_keeps_only_the_cast_and_is_billed_once(self):
        before = wallet_for(self.u).promptz
        r = self.plan("reelz", 3)
        self.assertEqual(r.status_code, 201, r.data)
        s = r.data["shots"][0]
        self.assertEqual(s["characters"], ["Lou"])                      # nobody invented
        self.assertEqual([d["who"] for d in s["dialogue"]], ["Lou"])    # an invented speaker's line is dropped
        self.assertEqual(r.data["aspect"], "9:16")                       # a reel is vertical
        self.assertEqual(r.data["render_price_cents"], 3 * animez.price_cents())
        self.assertLessEqual(wallet_for(self.u).promptz, before)

    @patch("apps.economy.animez._key", return_value="k")
    @patch("apps.economy.gemini.requests.post")
    def test_an_unusable_plan_is_free(self, rq, _k):
        rq.return_value = plan_reply([])
        before = wallet_for(self.u).promptz
        r = self.c.post(f"{BASE}plan/", {"fmt": "reelz", "idea": "x", "character_ids": [self.lou.id], "shots": 2}, format="json")
        self.assertEqual(r.status_code, 502)
        self.assertEqual(wallet_for(self.u).promptz, before)
        self.assertFalse(AnimeWork.objects.exists())

    def test_someone_elses_character_cannot_be_cast(self):
        other = User.objects.create_user("x", "x@e.com", "pw12345678")
        theirs = Character.objects.create(user=other, name="Theirs")
        r = self.c.post(f"{BASE}plan/", {"fmt": "promptz", "idea": "x", "character_ids": [theirs.id]}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_the_plan_is_editable_and_a_client_never_assigns_a_render(self):
        pid = self.plan("reelz", 2).data["id"]
        r = self.c.patch(f"{BASE}{pid}/", {"shots": [{"action": "a", "work_id": 999}, {"action": "b", "failed": True}]}, format="json")
        self.assertEqual(r.status_code, 200)
        row = AnimeWork.objects.get(pk=pid)
        self.assertEqual([s["work_id"] for s in row.shots], [None, None])
        self.assertEqual([s["failed"] for s in row.shots], [False, False])
        self.assertEqual(self.c.patch(f"{BASE}{pid}/", {"shots": [{"action": "only one"}]}, format="json").status_code, 400)

    def test_the_render_prompt_carries_each_characters_look_and_lines(self):
        w = AnimeWork(user=self.u, style="shonen")
        p = animez.render_prompt(w, {"camera": "close-up", "setting": "roof", "action": "Lou turns",
                                     "characters": ["Lou"], "dialogue": [{"who": "Lou", "line": "Not today."}]}, [self.lou])
        self.assertIn("red scarf", p)
        self.assertIn('Lou says: "Not today."', p)


@patch("apps.economy.videoz._key", return_value="K")
@patch("apps.economy.animez._key", return_value="K")
@patch("apps.economy.animez.ffmpeg_exe", return_value="/usr/bin/ffmpeg")
class RenderTests(_Base):
    def test_render_refuses_up_front_when_every_shot_cannot_be_paid(self, *_):
        pid = self.plan("reelz", 3).data["id"]
        w = wallet_for(self.u); w.promptz = 0; w.money_cents = 0; w.save()
        r = self.c.post(f"{BASE}{pid}/render/")
        self.assertEqual(r.status_code, 402)
        self.assertFalse(VideoWork.objects.exists())
        self.assertEqual(AnimeWork.objects.get(pk=pid).status, AnimeWork.STATUS_PLANNED)

    def test_shots_start_a_few_at_a_time_as_anime_renders(self, *_):
        self.tier("statz")
        from apps.economy.models import wallet_for
        w = wallet_for(self.u); w.promptz = 10 ** 6; w.save()   # 6 shots at the clip price must be affordable
        pid = self.plan("episodez", 6).data["id"]
        with patch("apps.economy.videoz.requests.post", return_value=veo_ok()) as post:
            r = self.c.post(f"{BASE}{pid}/render/")
        self.assertEqual(r.status_code, 202, r.data)
        self.assertEqual(VideoWork.objects.filter(kind="anime").count(), animez.CONCURRENT)
        self.assertEqual(r.data["queued"], 6 - animez.CONCURRENT)
        sent = post.call_args.kwargs["json"]["instances"][0]["prompt"]
        self.assertIn("anime", sent.lower())
        self.assertIn("red scarf", sent)
        self.assertEqual(self.c.post(f"{BASE}{pid}/render/").status_code, 409)   # never twice

    def test_a_finished_piece_is_one_video(self, *_):
        pid = self.plan("reelz", 2).data["id"]
        with patch("apps.economy.videoz.requests.post", return_value=veo_ok()):
            self.c.post(f"{BASE}{pid}/render/")
        from django.core.files.base import ContentFile
        from apps.economy.models import Upload
        for vw in VideoWork.objects.all():
            up = Upload(user=self.u, name=f"s{vw.pk}.mp4", size_bytes=3, content_type="video/mp4")
            up.file.save(up.name, ContentFile(b"abc"), save=False); up.save()
            VideoWork.objects.filter(pk=vw.pk).update(status=VideoWork.STATUS_DONE, upload=up)
        with patch("apps.economy.animez.join_clips", return_value=b"joined") as join:
            d = self.c.get(f"{BASE}{pid}/").data
        self.assertEqual(join.call_count, 1)
        self.assertEqual(d["status"], "done")
        self.assertTrue(d["video_url"])
        self.assertEqual(d["rendered"], 2)

    def test_when_no_shot_lands_nothing_is_joined(self, *_):
        pid = self.plan("reelz", 2).data["id"]
        with patch("apps.economy.videoz.requests.post", return_value=veo_ok()):
            self.c.post(f"{BASE}{pid}/render/")
        VideoWork.objects.update(status=VideoWork.STATUS_FAILED)
        d = self.c.get(f"{BASE}{pid}/").data
        self.assertEqual(d["status"], "failed")
        self.assertIn("refunded", d["error"])


class VideoConnectZGainsAnime(TestCase):
    def test_anime_is_a_video_connectz_kind(self):
        from apps.economy.videoz import KINDS
        self.assertIn("anime", KINDS)
        self.assertIn("Never photoreal", KINDS["anime"]["ask"])
