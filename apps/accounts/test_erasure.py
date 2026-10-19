"""Deleting an account takes the files with the rows.

Each test saves REAL bytes into a throwaway MEDIA_ROOT and asks storage, not the
database, whether they are still there — a test that only checked the rows would
pass on the bug it exists for.
"""
import shutil
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.erasure import collect_files, purge_files
from apps.economy.models import Face, Profile, Upload, profile_for

User = get_user_model()


class ErasureTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls._root = tempfile.mkdtemp()
        cls._override = override_settings(MEDIA_ROOT=cls._root)
        cls._override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._override.disable()
        shutil.rmtree(cls._root, ignore_errors=True)

    def _member(self, name):
        u = User.objects.create_user(username=name, email=f"{name}@x.test", password="pw12345!pw")
        up = Upload(user=u, name="take.wav", size_bytes=4, content_type="audio/wav")
        up.file.save(f"{name}-take.wav", ContentFile(b"riff"), save=True)
        face = Face(owner=u, name="me")
        face.image.save(f"{name}-face.png", ContentFile(b"png!"), save=True)
        p = profile_for(u)
        p.avatar.save(f"{name}-avatar.png", ContentFile(b"png!"), save=True)
        return u, [up.file.name, face.image.name, p.avatar.name]

    def _delete_me(self, user):
        client = APIClient()
        client.force_authenticate(user)
        # A TestCase never commits, so on_commit hooks only run when asked to.
        with self.captureOnCommitCallbacks(execute=True):
            return client.delete("/api/auth/me/")

    def test_the_files_go_with_the_account(self):
        gone, names = self._member("leaver")
        for n in names:
            self.assertTrue(default_storage.exists(n), n)
        resp = self._delete_me(gone)
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(User.objects.filter(username="leaver").exists())
        for n in names:
            self.assertFalse(default_storage.exists(n), f"{n} survived the account that owned it")

    def test_nobody_elses_files_are_touched(self):
        gone, _ = self._member("leaver")
        _, kept_names = self._member("stayer")
        self._delete_me(gone)
        for n in kept_names:
            self.assertTrue(default_storage.exists(n), n)

    def test_a_face_that_only_tags_the_member_is_kept(self):
        # `Face.tagged` is SET_NULL: that row belongs to somebody else and
        # survives the deletion, so its picture must too.
        owner, _ = self._member("owner")
        tagged, _ = self._member("tagged")
        face = Face(owner=owner, tagged=tagged, name="duet")
        face.image.save("duet.png", ContentFile(b"png!"), save=True)
        self._delete_me(tagged)
        face.refresh_from_db()
        self.assertIsNone(face.tagged)
        self.assertTrue(default_storage.exists(face.image.name))

    def test_files_are_found_before_the_rows_vanish(self):
        u, names = self._member("finder")
        self.assertEqual({name for _, name in collect_files(u)}, set(names))

    def test_a_storage_error_never_blocks_the_deletion(self):
        # The member asked to be deleted; a bucket having a bad minute is not a
        # reason to 500 and leave a half-deleted account behind.
        u, _ = self._member("unlucky")
        with mock.patch("django.core.files.storage.FileSystemStorage.delete", side_effect=OSError("bucket down")), \
                self.assertLogs("apps.accounts.erasure", level="ERROR") as logs:
            resp = self._delete_me(u)
        self.assertTrue(any("could not remove stored file" in m for m in logs.output))
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(User.objects.filter(username="unlucky").exists())

    def test_a_delete_that_rolls_back_removes_no_files(self):
        u, names = self._member("rollback")
        with mock.patch.object(User, "delete", side_effect=RuntimeError("db said no")):
            with self.assertRaises(RuntimeError):
                with self.captureOnCommitCallbacks(execute=True):
                    from apps.accounts.erasure import delete_user
                    delete_user(u)
        self.assertTrue(User.objects.filter(username="rollback").exists())
        for n in names:
            self.assertTrue(default_storage.exists(n), n)

    def test_the_other_delete_paths_use_it(self):
        # Four doors delete an account. The one nobody remembers is the one that
        # leaves the files behind, so each is held to the same behaviour.
        import inspect
        from apps.accounts import views
        from apps.economy import account, dupez
        for fn in (views.MeView.delete, views.UsersView.delete, account.AccountDeleteView.post, dupez.delete_duplicate):
            self.assertIn("delete_user", inspect.getsource(fn), fn.__qualname__)

    def test_purge_never_raises(self):
        class Boom:
            def delete(self, name):
                raise OSError("nope")
        with self.assertLogs("apps.accounts.erasure", level="ERROR"):
            purge_files([(Boom(), "x"), (default_storage, "does-not-exist.bin")])
