"""A score card plays the take's recording only when the member chose that, only for
their own kept take, and never for a trial take (nothing of a stranger's is stored)."""
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.models import ScoreShare, TakeScore, Upload

User = get_user_model()


class ShareMediaTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user(username="singer", password="hunter2hunter2")
        self.c = APIClient(); self.c.force_authenticate(self.u)
        self.share = ScoreShare.objects.create(token="tok", app_key="singz", score=7, user=self.u, verdict="ok")

    def keep(self, missing=False, kind="audio/webm"):
        up = Upload(user=self.u, name="t.webm", size_bytes=3, content_type=kind,
                    missing_since=timezone.now() if missing else None)
        up.file.save("t.webm", ContentFile(b"abc"), save=False); up.save()
        TakeScore.objects.create(user=self.u, app_key="singz", overall=7, share_token="tok", upload=up)
        return up

    def public(self):
        return APIClient().get("/api/economy/scores/tok/").data

    def test_nothing_plays_until_the_member_says_so(self):
        self.keep()
        self.assertNotIn("audio", self.public())
        self.assertEqual(self.c.get("/api/economy/scores/tok/media/").data, {"play": False, "available": True})
        r = self.c.post("/api/economy/scores/tok/media/", {"play": True}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.public()["audio_kind"], "audio")
        self.c.post("/api/economy/scores/tok/media/", {"play": False}, format="json")
        self.assertNotIn("audio", self.public())

    def test_a_take_that_was_not_kept_is_refused_with_the_reason(self):
        r = self.c.post("/api/economy/scores/tok/media/", {"play": True}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("wasn't kept", r.data["detail"])

    def test_a_lost_file_stops_playing_rather_than_breaking(self):
        self.keep(missing=True)
        ScoreShare.objects.filter(pk=self.share.pk).update(payload={"media": True})
        self.assertNotIn("audio", self.public())

    def test_video_plays_as_video(self):
        self.keep(kind="video/webm")
        self.c.post("/api/economy/scores/tok/media/", {"play": True}, format="json")
        self.assertEqual(self.public()["audio_kind"], "video")

    def test_only_the_owner_decides(self):
        self.keep()
        other = APIClient(); other.force_authenticate(User.objects.create_user(username="x", password="hunter2hunter2"))
        self.assertEqual(other.post("/api/economy/scores/tok/media/", {"play": True}, format="json").status_code, 404)
        self.assertEqual(APIClient().post("/api/economy/scores/tok/media/", {"play": True}, format="json").status_code, 401)

    def test_a_trial_card_has_no_owner_and_never_plays(self):
        ScoreShare.objects.create(token="trial", app_key="singz", score=6, user=None, payload={"media": True})
        self.assertNotIn("audio", APIClient().get("/api/economy/scores/trial/").data)
