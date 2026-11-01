"""FileZ says which files are gone, and the member can ask the server to look.

A lost file used to render as a player stuck at 0:00 / 0:00 — "corrupt" — when
the truth is that the bytes are not on the server. These pin: the list carries
the mark, the check stamps only what storage says is absent, clears what came
back, never marks on a backend that cannot answer, and only touches the
caller's own files.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.economy.models import Upload

import tempfile

User = get_user_model()
PW = "pw12345!"


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="mcz-check-"))
class UploadCheckTests(TestCase):

    def setUp(self):
        self.me = User.objects.create_user(username="maker", password=PW)
        self.other = User.objects.create_user(username="other", password=PW)
        self.c = APIClient()
        self.c.force_authenticate(self.me)

    def make(self, user, name="take.webm"):
        return Upload.objects.create(
            user=user, name=name, size_bytes=10, content_type="audio/webm",
            file=SimpleUploadedFile(name, b"0" * 10, content_type="audio/webm"))

    def lose(self, up):
        up.file.storage.delete(up.file.name)

    def row(self, up):
        rows = self.c.get("/api/economy/uploads/").json()["uploads"]
        return [r for r in rows if r["id"] == up.id][0]

    def test_list_serves_the_mark_and_a_present_file_is_not_flagged(self):
        up = self.make(self.me)
        self.assertFalse(self.row(up)["missing"])
        Upload.objects.filter(pk=up.pk).update(missing_since="2026-01-01T00:00:00Z")
        self.assertTrue(self.row(up)["missing"])

    def test_listing_never_asks_storage(self):
        self.make(self.me)
        with patch("django.core.files.storage.FileSystemStorage.exists",
                   side_effect=AssertionError("a read path must not look")):
            self.assertEqual(self.c.get("/api/economy/uploads/").status_code, 200)

    def test_check_stamps_only_what_is_gone(self):
        here, gone = self.make(self.me, "here.webm"), self.make(self.me, "gone.webm")
        self.lose(gone)
        r = self.c.post("/api/economy/uploads/check/").json()
        self.assertEqual((r["checked"], r["present"], r["gone"]), (2, 1, 1))
        self.assertFalse(self.row(here)["missing"])
        self.assertTrue(self.row(gone)["missing"])

    def test_a_lost_file_stops_counting_against_storage(self):
        from apps.economy.models import storage_used_bytes
        gone = self.make(self.me)
        self.lose(gone)
        self.assertEqual(storage_used_bytes(self.me), 10)
        self.c.post("/api/economy/uploads/check/")
        self.assertEqual(storage_used_bytes(self.me), 0)

    def test_a_file_that_came_back_is_cleared(self):
        up = self.make(self.me)
        Upload.objects.filter(pk=up.pk).update(missing_since="2026-01-01T00:00:00Z")
        r = self.c.post("/api/economy/uploads/check/").json()
        self.assertEqual(r["came_back"], 1)
        self.assertFalse(self.row(up)["missing"])

    def test_a_storage_error_marks_nothing(self):
        up = self.make(self.me)
        with patch("django.core.files.storage.FileSystemStorage.exists",
                   side_effect=OSError("bucket unreachable")):
            r = self.c.post("/api/economy/uploads/check/").json()
        self.assertEqual((r["gone"], r["unreadable"]), (0, 1))
        self.assertFalse(self.row(up)["missing"])

    def test_it_never_touches_anybody_elses_files(self):
        theirs = self.make(self.other)
        self.lose(theirs)
        r = self.c.post("/api/economy/uploads/check/").json()
        self.assertEqual(r["checked"], 0)
        theirs.refresh_from_db()
        self.assertIsNone(theirs.missing_since)

    def test_it_needs_a_login(self):
        self.assertIn(APIClient().post("/api/economy/uploads/check/").status_code, (401, 403))

    def test_nothing_is_deleted(self):
        gone = self.make(self.me)
        self.lose(gone)
        self.c.post("/api/economy/uploads/check/")
        self.assertTrue(Upload.objects.filter(pk=gone.pk).exists())
