"""CharacterZ: anyone can make one, the tier says how many, a look is a drawing or you."""
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.economy.characterz import prompt_block
from apps.economy.models import Character, Face, Upload

User = get_user_model()
URL = "/api/economy/characterz/"


@override_settings(MEDIA_ROOT="/tmp/mcz-test-media")
class CharacterZTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_user("me", "m@e.com", "pw12345678")
        self.other = User.objects.create_user("bo", "b@e.com", "pw12345678")
        self.c = APIClient(); self.c.force_authenticate(self.me)

    def img(self, owner):
        return Upload.objects.create(user=owner, file=SimpleUploadedFile("a.png", b"x", content_type="image/png"),
                                     name="a.png", size_bytes=1, content_type="image/png")

    def test_make_one_with_a_voice_and_it_describes_itself_as_data(self):
        r = self.c.post(URL, {"name": "Lemur Lou", "bio": "Talks fast, loves puns", "personality": "EN--",
                              "spec": {"energy": "high"}, "looks": "ringtailed lemur, blue hoodie"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        block = prompt_block(Character.objects.get())
        self.assertIn("<voice_description>", block)
        self.assertIn("ringtailed lemur", block)

    def test_free_tier_holds_three(self):
        for i in range(3):
            self.assertEqual(self.c.post(URL, {"name": f"C{i}"}, format="json").status_code, 201)
        self.assertEqual(self.c.post(URL, {"name": "C4"}, format="json").status_code, 400)

    def test_a_look_needs_the_attestation_and_must_be_yours(self):
        mine = self.img(self.me)
        self.assertEqual(self.c.post(URL, {"name": "A", "upload_id": mine.id}, format="json").status_code, 400)
        self.assertEqual(self.c.post(URL, {"name": "A", "upload_id": mine.id, "look_attested": True}, format="json").status_code, 201)
        theirs = self.img(self.other)
        self.assertEqual(self.c.post(URL, {"name": "B", "upload_id": theirs.id, "look_attested": True}, format="json").status_code, 400)

    def test_a_face_tagged_as_someone_else_is_refused(self):
        f = Face.objects.create(owner=self.me, image=SimpleUploadedFile("f.png", b"x", content_type="image/png"), tagged=self.other)
        r = self.c.post(URL, {"name": "X", "face_id": f.id, "look_attested": True}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("never another real person", r.data["detail"])

    def test_bad_dial_is_refused_with_the_reason(self):
        r = self.c.post(URL, {"name": "Z", "spec": {"energy": "nuclear"}}, format="json")
        self.assertEqual(r.status_code, 400)
