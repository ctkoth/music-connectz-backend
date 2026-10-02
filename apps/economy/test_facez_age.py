"""Rating a face is rating somebody on looks, so FaceZ follows the same adult
wall as AttractivenessRateView: a known minor neither rates faces nor appears
in anybody's feed to be rated. It had no wall at all."""
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.models import Face, profile_for

User = get_user_model()
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


def member(name, birthday=""):
    u = User.objects.create_user(name, f"{name}@e.com", "pw-Long-enough-1")
    p = profile_for(u); p.birthday = birthday; p.save()
    return u


def face(owner):
    return Face.objects.create(owner=owner, image=SimpleUploadedFile("f.png", PNG, content_type="image/png"))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class FaceAgeWallTests(TestCase):
    def setUp(self):
        teen = f"{timezone.localdate().year - 15}-01-15"
        self.adult = member("adult", "1990-01-01")
        self.other = member("other", "1991-01-01")
        self.teen = member("teen", teen)
        self.adult_face, self.teen_face = face(self.other), face(self.teen)

    def client_for(self, u):
        c = APIClient(); c.force_authenticate(u); return c

    def test_a_minors_face_is_never_in_the_feed(self):
        feed = self.client_for(self.adult).get("/api/economy/facez/").json()["feed"]
        ids = {f["id"] for f in feed}
        self.assertIn(self.adult_face.id, ids)
        self.assertNotIn(self.teen_face.id, ids)

    def test_a_minor_gets_no_feed_and_the_reason(self):
        d = self.client_for(self.teen).get("/api/economy/facez/").json()
        self.assertEqual(d["feed"], [])
        self.assertTrue(d["feed_locked"])

    def test_rating_needs_two_adults(self):
        r = self.client_for(self.adult).post(f"/api/economy/facez/{self.teen_face.id}/rate/", {"score": 7}, format="json")
        self.assertEqual(r.status_code, 403)
        r = self.client_for(self.teen).post(f"/api/economy/facez/{self.adult_face.id}/rate/", {"score": 7}, format="json")
        self.assertEqual(r.status_code, 403)
        r = self.client_for(self.adult).post(f"/api/economy/facez/{self.adult_face.id}/rate/", {"score": 7}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
