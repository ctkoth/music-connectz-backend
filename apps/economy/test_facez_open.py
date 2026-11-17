from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import Face, Membership, TIER_STATZ

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x35\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82"


def up(c, **extra):
    return c.post("/api/economy/facez/", {"image": SimpleUploadedFile("f.png", PNG, "image/png"), **extra}, format="multipart")


class FaceZOpenTests(TestCase):
    def setUp(self):
        U = get_user_model()
        self.me = U.objects.create_user("faceme", password="pw12345!x")
        self.c = APIClient(); self.c.force_authenticate(self.me)

    def test_a_new_face_is_closed_to_ratings_unless_asked(self):
        self.assertFalse(up(self.c).data["face"]["open_to_ratings"])
        self.assertTrue(up(self.c, open_to_ratings="1").data["face"]["open_to_ratings"])

    def test_a_closed_face_cannot_be_rated_and_the_switch_is_the_owners(self):
        fid = up(self.c).data["face"]["id"]
        other = get_user_model().objects.create_user("rater", password="pw12345!x")
        rc = APIClient(); rc.force_authenticate(other)
        self.assertEqual(rc.post(f"/api/economy/facez/{fid}/rate/", {"score": 7}, format="json").status_code, 403)
        self.assertEqual(rc.patch(f"/api/economy/facez/{fid}/", {"open_to_ratings": True}, format="json").status_code, 404)
        r = self.c.patch(f"/api/economy/facez/{fid}/", {"open_to_ratings": True}, format="json")
        self.assertTrue(r.data["face"]["open_to_ratings"])

    def test_free_keeps_three_faces_and_statz_is_unlimited(self):
        for _ in range(3):
            self.assertEqual(up(self.c).status_code, 201)
        r = up(self.c)
        self.assertEqual(r.status_code, 403)
        self.assertIn("3 faces", r.data["detail"])
        self.assertEqual(Face.objects.filter(owner=self.me).count(), 3)
        Membership.objects.update_or_create(user=self.me, defaults={"tier": TIER_STATZ})
        self.assertEqual(up(self.c).status_code, 201)
        self.assertIsNone(self.c.get("/api/economy/facez/").data["faces_limit"])
