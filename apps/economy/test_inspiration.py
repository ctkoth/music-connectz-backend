"""Inspiration on every maker that writes from a prompt: a sound or picture, checked before any
price, never kept, and only ever its feel — read into words for the video renders, because Veo
takes a picture as the first frame and would copy it."""
import base64
import json
import os
import tempfile
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.economy import refinput, sentencez
from apps.economy.models import Character, Membership, Upload, VideoWork, wallet_for

User = get_user_model()
PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG" + b"0" * 64).decode()
BAD = "data:application/pdf;base64,AAAA"


def text_reply(text):
    r = MagicMock(status_code=200, text="")
    r.json.return_value = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    return r


def op():
    r = MagicMock(status_code=200, text="{}")
    r.json.return_value = {"name": "operations/x"}
    return r


class Base(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("maker", "m@e.com", "pw-Long-enough-1")
        w = wallet_for(self.u); w.promptz = 100; w.money_cents = 5000; w.save()
        self.c = APIClient(); self.c.force_authenticate(self.u)


class DescribeTests(Base):
    def test_a_reference_becomes_a_capped_feel_line(self):
        ref, _ = refinput.parse(PNG)
        with patch("apps.economy.gemini.generate_content", return_value=(text_reply("Dusky  violet\nlight. " * 80), [])) as g:
            words, problem = refinput.describe(ref, "K")
        self.assertIsNone(problem)
        self.assertLessEqual(len(words), 400)
        self.assertNotIn("\n", words)
        prompt = g.call_args.args[1]["contents"][0]["parts"][0]["text"]
        self.assertIn("Never name a person", prompt)
        self.assertIn("feel only", refinput.video_line(words))

    def test_an_empty_read_is_a_sentence_not_a_blank_line(self):
        ref, _ = refinput.parse(PNG)
        with patch("apps.economy.gemini.generate_content", return_value=(text_reply("   "), [])):
            self.assertEqual(refinput.describe(ref, "K"), (None, refinput.DESCRIBE_FAILED))


class WriterTests(Base):
    def test_every_kind_but_a_legal_draft_takes_one(self):
        self.assertIn("resume", sentencez.REFERENCE_KINDS)
        self.assertIn("lyrics", sentencez.REFERENCE_KINDS)
        self.assertFalse(set(sentencez.REFERENCE_KINDS) & sentencez.LEGAL_KINDS)
        d = self.c.get("/api/economy/priorities/").json()["reference"]
        self.assertEqual(d["writer_kinds"], list(sentencez.REFERENCE_KINDS))
        self.assertIn("isn't kept", d["note"])

    def test_a_resume_sends_the_picture_with_the_guard(self):
        with patch.object(sentencez, "_key", return_value="K"), \
                patch.object(sentencez, "generate_content", return_value=(text_reply("A resume."), [])) as g:
            sentencez.write_piece(self.u, "resume", "ten years of sound engineering", reference=PNG)
        parts = g.call_args.args[1]["contents"][0]["parts"]
        self.assertIn("inspiration ONLY", parts[0]["text"])
        self.assertEqual(parts[1]["inlineData"]["mimeType"], "image/png")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
@patch.dict(os.environ, {"VIDEO_CONNECTZ_CENTS": "400"})
class VideoTests(Base):
    def setUp(self):
        super().setUp()
        for target in ("apps.economy.videoz._key", "apps.economy.videostitch._key"):
            p = patch(target, return_value="K"); p.start(); self.addCleanup(p.stop)

    def test_a_render_carries_the_feel_in_words_never_the_picture(self):
        with patch("apps.economy.gemini.generate_content", return_value=(text_reply("Violet dusk, slow pace."), [])), \
                patch("apps.economy.videoz.requests.post", return_value=op()) as veo:
            r = self.c.post("/api/economy/videoz/", {"kind": "music", "prompt": "a rooftop", "reference": PNG},
                            format="json")
        self.assertEqual(r.status_code, 201, r.content)
        instance = veo.call_args.kwargs["json"]["instances"][0]
        self.assertNotIn("image", instance)                         # not a first frame
        self.assertIn("Violet dusk, slow pace.", instance["prompt"])

    def test_a_bad_or_unreadable_reference_holds_nothing(self):
        r = self.c.post("/api/economy/videoz/", {"kind": "music", "prompt": "x", "reference": BAD}, format="json")
        self.assertEqual(r.status_code, 400)
        with patch("apps.economy.gemini.generate_content", return_value=(text_reply(""), [])):
            r = self.c.post("/api/economy/videoz/", {"kind": "music", "prompt": "x", "reference": PNG}, format="json")
        self.assertEqual(r.status_code, 502)
        self.assertIn("Nothing was", r.json()["detail"])
        self.assertFalse(VideoWork.objects.exists())
        self.assertEqual(wallet_for(self.u).money_cents, 5000)

    def test_the_unbilled_read_never_runs_for_someone_who_cannot_pay(self):
        w = wallet_for(self.u); w.promptz = 0; w.money_cents = 0; w.save()
        with patch("apps.economy.gemini.generate_content") as g:
            r = self.c.post("/api/economy/videoz/", {"kind": "music", "prompt": "x", "reference": PNG}, format="json")
        self.assertEqual(r.status_code, 402)
        g.assert_not_called()

    def test_every_stitched_shot_shares_one_read(self):
        track = Upload.objects.create(user=self.u, name="song.mp3", content_type="audio/mpeg")
        track.file.save("song.mp3", ContentFile(b"x"), save=True)
        with patch("apps.economy.videostitch.ffmpeg_exe", return_value="ffmpeg"), \
                patch("apps.economy.gemini.generate_content", return_value=(text_reply("Grainy gold."), [])) as g, \
                patch("apps.economy.videoz.requests.post", return_value=op()):
            r = self.c.post("/api/economy/videoz/stitch/", {"track_id": track.id, "shots": ["a", "b", "c"],
                                                             "reference": PNG}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(g.call_count, 1)
        self.assertTrue(all("Grainy gold." in w.prompt for w in VideoWork.objects.all()))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PlanAndMangaTests(Base):
    def test_develop_hears_the_track_and_sees_the_inspiration(self):
        from apps.economy.test_videodevelop import plan, reply
        Membership.objects.update_or_create(user=self.u, defaults={"tier": "statz"})
        track = Upload.objects.create(user=self.u, name="song.mp3", content_type="audio/mpeg")
        track.file.save("song.mp3", ContentFile(b"ID3 fake audio"), save=True)
        with patch("apps.economy.videodevelop._key", return_value="K"), \
                patch("apps.economy.videodevelop.generate_content", return_value=(reply(plan(3)), [])) as g:
            r = self.c.post("/api/economy/videoz/develop/", {"track_id": track.id, "shots": 3, "reference": PNG},
                            format="json")
        self.assertEqual(r.status_code, 200, r.data)
        parts = g.call_args.args[1]["contents"][0]["parts"]
        self.assertIn("inspiration ONLY", parts[0]["text"])
        self.assertEqual(len(parts), 3)                            # prompt, the track, the picture

    def test_a_manga_script_takes_one_too(self):
        ch = Character.objects.create(user=self.u, name="Kai")
        script = json.dumps({"title": "T", "panels": [{"scene": "rooftop", "lines": [{"who": "Kai", "says": "hey"}]}]})
        with patch("apps.economy.mangaz._key", return_value="K"), \
                patch("apps.economy.mangaz.generate_content", return_value=(text_reply(script), [])) as g:
            r = self.c.post("/api/economy/mangaz/", {"idea": "a chase", "character_ids": [ch.id], "panels": 2,
                                                           "reference": PNG}, format="json")
        parts = g.call_args.args[1]["contents"][0]["parts"]
        self.assertIn("inspiration ONLY", parts[0]["text"])
        self.assertEqual(parts[1]["inlineData"]["mimeType"], "image/png")
        self.assertIn(r.status_code, (201, 502))                   # the script shape is mangaz's own test

    def test_a_bad_reference_stops_manga_before_the_writer(self):
        ch = Character.objects.create(user=self.u, name="Kai")
        with patch("apps.economy.mangaz.generate_content") as g:
            r = self.c.post("/api/economy/mangaz/", {"idea": "a chase", "character_ids": [ch.id],
                                                           "reference": BAD}, format="json")
        self.assertEqual(r.status_code, 400)
        g.assert_not_called()
