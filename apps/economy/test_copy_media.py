"""copy_media_to_bucket: moves what the database names, never overwrites, never deletes."""
import os
import tempfile
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.economy.models import Upload

User = get_user_model()


class CopyMediaTests(TestCase):
    def setUp(self):
        self.src = tempfile.mkdtemp(prefix="mcz-src-")
        self.dst = tempfile.mkdtemp(prefix="mcz-dst-")
        ov = override_settings(MEDIA_ROOT=self.dst)
        ov.enable(); self.addCleanup(ov.disable)
        self.u = User.objects.create_user("c", "c@e.com", "pw-Long-enough-1")

    def row(self, name, data=b"abc", on_source=True):
        up = Upload.objects.create(user=self.u, name=name, size_bytes=len(data), content_type="audio/wav")
        up.file.name = f"uploads/{up.pk}/{name}"
        up.save(update_fields=["file"])
        if on_source:
            path = os.path.join(self.src, up.file.name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(data)
        return up

    def run_cmd(self, *args):
        out, err = StringIO(), StringIO()
        call_command("copy_media_to_bucket", "--source", self.src, *args, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def dest_has(self, up):
        return os.path.exists(os.path.join(self.dst, up.file.name))

    def test_dry_run_copies_nothing_and_says_what_it_would(self):
        up = self.row("a.wav")
        out, _ = self.run_cmd()
        self.assertIn("would copy", out)
        self.assertFalse(self.dest_has(up))

    def test_write_copies_with_the_same_key_so_no_row_changes(self):
        up = self.row("a.wav", b"hello")
        before = up.file.name
        out, _ = self.run_cmd("--write")
        self.assertIn("1 file(s) copied", out)
        self.assertTrue(self.dest_has(up))
        up.refresh_from_db()
        self.assertEqual(up.file.name, before)
        with open(os.path.join(self.dst, before), "rb") as fh:
            self.assertEqual(fh.read(), b"hello")

    def test_it_never_overwrites_what_the_destination_has(self):
        up = self.row("a.wav", b"old-source")
        os.makedirs(os.path.dirname(os.path.join(self.dst, up.file.name)), exist_ok=True)
        with open(os.path.join(self.dst, up.file.name), "wb") as fh:
            fh.write(b"already-there")
        out, _ = self.run_cmd("--write")
        self.assertIn("1 already in the destination", out)
        with open(os.path.join(self.dst, up.file.name), "rb") as fh:
            self.assertEqual(fh.read(), b"already-there")

    def test_it_never_deletes_from_the_source(self):
        up = self.row("a.wav")
        self.run_cmd("--write")
        self.assertTrue(os.path.exists(os.path.join(self.src, up.file.name)))

    def test_a_file_already_lost_is_reported_not_invented(self):
        self.row("gone.wav", on_source=False)
        out, _ = self.run_cmd("--write")
        self.assertIn("1 not on the source", out)

    def test_same_folder_for_source_and_destination_is_refused(self):
        self.row("a.wav")
        out, err = StringIO(), StringIO()
        call_command("copy_media_to_bucket", "--source", self.dst, stdout=out, stderr=err)
        self.assertIn("same folder", err.getvalue())
