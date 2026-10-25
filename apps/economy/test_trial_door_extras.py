"""The trial door shows a real example before anybody performs, and can email the
score so closing the tab during the wait does not lose it."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.economy.models import RetakeReminder, ScoreShare

User = get_user_model()
SMTP = override_settings(EMAIL_HOST="smtp.example.com",
                         EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")


class ExampleIsTheOwnersOwnTests(TestCase):
    def test_only_an_owner_share_on_this_coach_is_shown(self):
        member = User.objects.create_user(username="m", password="hunter2hunter2")
        owner = User.objects.create_superuser(username="koth", password="hunter2hunter2", email="o@x.com")
        ScoreShare.objects.create(token="mem", app_key="rapz", score=9, user=member, verdict="member's")
        self.assertIsNone(APIClient().get("/api/rapz/trial/").data["example"])     # a member's card is never featured
        ScoreShare.objects.create(token="sing", app_key="singz", score=8, user=owner, verdict="other coach")
        ScoreShare.objects.create(token="climb", app_key="rapz", score=8, user=owner, payload={"progress": {"x": 1}})
        self.assertIsNone(APIClient().get("/api/rapz/trial/").data["example"])     # wrong coach, or a climb
        ScoreShare.objects.create(token="own", app_key="rapz", score=7, user=owner, verdict="Tight flow.")
        ex = APIClient().get("/api/rapz/trial/").data["example"]
        self.assertEqual((ex["token"], ex["username"], ex["score"]), ("own", "koth", 7))


class ExampleCanBeHeardTests(TestCase):
    """The example plays the real recording when the owner kept it, so a stranger can hear
    what earned the number before performing — and the card alone otherwise."""

    def setUp(self):
        from django.core.files.base import ContentFile
        from apps.economy.models import TakeScore, Upload
        self.owner = User.objects.create_superuser(username="koth", password="hunter2hunter2", email="o@x.com")
        self.TakeScore, self.Upload, self.ContentFile = TakeScore, Upload, ContentFile

    def kept(self, token, missing=False):
        from django.utils import timezone
        up = self.Upload(user=self.owner, name=f"{token}.webm", size_bytes=3, content_type="audio/webm",
                         missing_since=timezone.now() if missing else None)
        up.file.save(f"{token}.webm", self.ContentFile(b"abc"), save=False); up.save()
        self.TakeScore.objects.create(user=self.owner, app_key="rapz", overall=7, share_token=token, upload=up)
        return up

    def test_a_kept_take_is_preferred_and_playable(self):
        ScoreShare.objects.create(token="newer", app_key="rapz", score=8, user=self.owner, verdict="no audio")
        ScoreShare.objects.create(token="heard", app_key="rapz", score=7, user=self.owner, verdict="kept")
        up = self.kept("heard")
        ex = APIClient().get("/api/rapz/trial/").data["example"]
        self.assertEqual(ex["token"], "heard")
        self.assertEqual(ex["audio_kind"], "audio")
        self.assertTrue(ex["audio"].endswith(f"/api/economy/media/{up.id}/{up.file.name.rsplit('/', 1)[-1]}"))

    def test_a_lost_file_is_not_offered_and_the_card_still_shows(self):
        ScoreShare.objects.create(token="gone", app_key="rapz", score=7, user=self.owner, verdict="lost")
        self.kept("gone", missing=True)
        ex = APIClient().get("/api/rapz/trial/").data["example"]
        self.assertEqual(ex["token"], "gone")
        self.assertNotIn("audio", ex)


@SMTP
class EmailBeforeSendingTests(TestCase):
    def send(self, score, email):
        with patch("apps.economy.trial.score_take", lambda *a, **k: ({"score": score, "verdict": "ok"}, None)), \
             patch("apps.economy.trial._key", lambda: "k"):
            return APIClient().post("/api/singz/trial/", {
                "take": SimpleUploadedFile("t.m4a", b"x" * 64, content_type="audio/mp4"),
                "email": email, "anon_id": "browser-1"}, format="multipart")

    def test_the_get_says_whether_the_field_may_render(self):
        self.assertTrue(APIClient().get("/api/singz/trial/").data["remind"]["ready"])

    def test_a_scored_take_is_emailed_as_soon_as_it_exists(self):
        r = self.send(7, "v@example.com")
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.data["emailed"]["sent"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(RetakeReminder.objects.get().email, "v@example.com")

    def test_a_bad_address_never_costs_the_score(self):
        r = self.send(7, "not-an-email")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["score"], 7)
        self.assertNotIn("sent", r.data["emailed"])
        self.assertEqual(len(mail.outbox), 0)

    def test_no_score_means_no_email(self):
        r = self.send(None, "v@example.com")
        self.assertIsNone(r.data["emailed"])
        self.assertEqual(len(mail.outbox), 0)
