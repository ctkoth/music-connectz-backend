"""A member puts back a lost file from their own device's copy, behind the same row and the same stored name."""
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.economy.models import Membership, Upload, membership_for

User = get_user_model()
PW = "pw12345!"
BYTES = b"RIFF" + b"\x01" * 2000


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="mcz-restore-"))
class UploadRestoreTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_user(username="maker", password=PW)
        self.other = User.objects.create_user(username="other", password=PW)
        self.c = APIClient()
        self.c.force_authenticate(self.me)

    def make(self, user=None, data=BYTES, name="take.wav"):
        return Upload.objects.create(user=user or self.me, name=name, size_bytes=len(data), content_type="audio/wav",
                                     file=SimpleUploadedFile(name, data, content_type="audio/wav"))

    def lose(self, up):
        up.file.storage.delete(up.file.name)
        Upload.objects.filter(pk=up.pk).update(missing_since="2026-01-01T00:00:00Z")

    def send(self, up, data=BYTES, name="take.wav"):
        return self.c.post(f"/api/economy/uploads/{up.pk}/restore/", {"file": SimpleUploadedFile(name, data, content_type="audio/wav")}, format="multipart")

    def test_a_lost_file_goes_back_behind_its_own_row_under_its_own_name(self):
        up = self.make()
        stored = up.file.name
        self.lose(up)
        r = self.send(up)
        self.assertEqual(r.status_code, 200, r.content)
        up.refresh_from_db()
        self.assertEqual(up.file.name, stored)                       # the same stored name, so every existing link works
        self.assertTrue(up.file.storage.exists(stored))
        self.assertIsNone(up.missing_since)
        with up.file.open("rb") as fh:
            self.assertEqual(fh.read(), BYTES)
        self.assertFalse(r.json()["upload"]["missing"])

    def test_a_file_still_on_the_server_is_never_replaced(self):
        up = self.make()
        r = self.send(up, data=b"x" * len(BYTES))
        self.assertEqual(r.status_code, 409)
        with up.file.open("rb") as fh:
            self.assertEqual(fh.read(), BYTES)

    def test_a_different_size_is_a_different_file_and_changes_nothing(self):
        up = self.make()
        self.lose(up)
        r = self.send(up, data=BYTES + b"extra")
        self.assertEqual(r.status_code, 400)
        self.assertIn("isn't the same file", r.json()["detail"])
        self.assertIn(str(len(BYTES)), r.json()["detail"])
        up.refresh_from_db()
        self.assertIsNotNone(up.missing_since)
        self.assertFalse(up.file.storage.exists(up.file.name))

    def test_it_is_the_members_own_file_only(self):
        theirs = self.make(user=self.other)
        self.lose(theirs)
        self.assertEqual(self.send(theirs).status_code, 404)
        self.assertEqual(self.c.post("/api/economy/uploads/999999/restore/").status_code, 404)

    def test_it_needs_a_login_and_a_file(self):
        up = self.make()
        self.lose(up)
        self.assertIn(APIClient().post(f"/api/economy/uploads/{up.pk}/restore/").status_code, (401, 403))
        self.assertEqual(self.c.post(f"/api/economy/uploads/{up.pk}/restore/", {}, format="multipart").status_code, 400)

    def test_the_plans_storage_quota_still_applies(self):
        up = self.make()
        self.lose(up)
        with patch("apps.economy.uploadrestore.storage_used_bytes", return_value=10 ** 15):
            r = self.send(up)
        self.assertEqual(r.status_code, 409)
        self.assertIn("quota", r.json()["detail"])
        up.refresh_from_db()
        self.assertIsNotNone(up.missing_since)

    def test_a_write_that_lands_under_another_name_is_undone_not_reported_as_success(self):
        up = self.make()
        stored = up.file.name
        self.lose(up)
        storage = up.file.storage
        real_save = FileSystemStorage.save
        with patch.object(FileSystemStorage, "save", lambda self, name, content, max_length=None: real_save(self, name + "_other", content)):
            r = self.send(up)
        self.assertEqual(r.status_code, 503)
        up.refresh_from_db()
        self.assertIsNotNone(up.missing_since)
        self.assertFalse(storage.exists(stored + "_other"))          # the stray copy is cleaned up
        self.assertFalse(storage.exists(stored))

    def test_a_storage_that_cannot_answer_is_not_a_reason_to_replace_a_file(self):
        up = self.make()
        with patch.object(FileSystemStorage, "exists", side_effect=OSError("bucket unreachable")):
            r = self.send(up)
        self.assertEqual(r.status_code, 409)
