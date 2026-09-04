"""The app has to say when it is about to eat everyone's music.

Render's web filesystem is ephemeral. With no bucket configured, `MEDIA_ROOT`
is a directory inside the container, and every deploy rebuilds the container —
so every uploaded track, video and cover is destroyed. The `Upload` rows live
in Postgres and survive, so the app carries on serving links to files that are
no longer there, and the member is told "Something went wrong on our side"
about their own missing recording.

Nothing here prevents that; the fix is a bucket. What these pin is that the
app stops being QUIET about it, in all three places somebody might look.
"""
from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.economy.apps import uploads_are_durable
from apps.economy.storage_health import upload_storage_state, warn_once

LOCAL = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
         "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}
BUCKET = {"default": {"BACKEND": "storages.backends.s3boto3.S3Boto3Storage"},
          "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}


class WhenUploadsAreNotDurableTests(TestCase):

    @override_settings(STORAGES=LOCAL)
    def test_local_disk_on_render_is_ephemeral(self):
        with patch.dict("os.environ", {"RENDER": "true"}):
            state = upload_storage_state()
        self.assertTrue(state["ephemeral"])
        self.assertFalse(state["durable"])
        self.assertIn("deleted the next time anything ships", state["detail"])

    @override_settings(STORAGES=LOCAL)
    def test_the_same_local_disk_off_render_is_fine(self):
        """A laptop keeps its files. Warning here is noise, and a warning that
        cries wolf in dev is one nobody reads in production."""
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("RENDER", None)
            state = upload_storage_state()
        self.assertFalse(state["ephemeral"])
        self.assertTrue(state["durable"])
        self.assertEqual(state["detail"], "")

    @override_settings(STORAGES=LOCAL)
    def test_a_mounted_persistent_disk_is_durable_too(self):
        """The credential-free fix. A Render disk is local storage that
        survives a deploy, and from in here it is indistinguishable from the
        container's own directory — so it is an assertion by whoever mounted
        it, and nothing else will be taken as one."""
        with patch.dict("os.environ", {"RENDER": "true", "MEDIA_DURABLE": "1"}):
            state = upload_storage_state()
        self.assertTrue(state["durable"])
        self.assertFalse(state["ephemeral"])
        self.assertEqual(state["kept_by"], "a persistent disk")

    @override_settings(STORAGES=LOCAL)
    def test_saying_nothing_is_not_saying_it_is_durable(self):
        """MEDIA_DURABLE has to be set deliberately. Anything short of that —
        unset, empty, "0" — leaves the warning standing, because the cost of a
        false "durable" is somebody's only copy of a take."""
        for value in ("", "0", "no", "maybe"):
            with patch.dict("os.environ", {"RENDER": "true", "MEDIA_DURABLE": value}):
                self.assertTrue(upload_storage_state()["ephemeral"], value)

    @override_settings(STORAGES=BUCKET)
    def test_a_bucket_is_durable_even_on_render(self):
        with patch.dict("os.environ", {"RENDER": "true", "S3_BUCKET_NAME": "mcz"}):
            state = upload_storage_state()
        self.assertTrue(state["durable"])
        self.assertEqual(state["bucket"], "mcz")


class ItSaysSoInEveryPlaceSomebodyLooksTests(TestCase):

    @override_settings(STORAGES=LOCAL)
    def test_the_deploy_log_gets_a_system_check(self):
        """`migrate` runs the checks and build.sh runs migrate on every deploy,
        so this lands in the Render build output as it ships."""
        with patch.dict("os.environ", {"RENDER": "true"}):
            found = uploads_are_durable(None)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].id, "economy.W001")
        self.assertIn("DELETED on the next deploy", found[0].msg)
        self.assertIn("S3_BUCKET_NAME", found[0].hint)

    @override_settings(STORAGES=LOCAL)
    def test_it_warns_and_never_fails_the_deploy(self):
        """A Warning, not an Error. build.sh runs under `set -o errexit`, so an
        Error would turn "your uploads aren't durable" into "the site is down"
        — which is a worse outcome than the thing being warned about."""
        from django.core.checks import Warning as CheckWarning
        with patch.dict("os.environ", {"RENDER": "true"}):
            found = uploads_are_durable(None)
        self.assertIsInstance(found[0], CheckWarning)

    @override_settings(STORAGES=BUCKET)
    def test_a_durable_setup_says_nothing_at_all(self):
        with patch.dict("os.environ", {"RENDER": "true"}):
            self.assertEqual(uploads_are_durable(None), [])

    @override_settings(STORAGES=LOCAL)
    def test_the_running_service_logs_it_at_startup(self):
        """gunicorn does not run system checks, so without this the only place
        the warning exists is a build log nobody reads twice."""
        with patch.dict("os.environ", {"RENDER": "true"}):
            with self.assertLogs("apps.economy.storage_health", "WARNING") as logs:
                warn_once()
        self.assertIn("MEMBER UPLOADS ARE NOT DURABLE", logs.output[0])

    @override_settings(STORAGES=LOCAL)
    def test_a_broken_check_never_takes_the_app_down(self):
        with patch("apps.economy.storage_health.upload_storage_state",
                   side_effect=RuntimeError("boom")):
            warn_once()          # must not raise

    def test_the_health_endpoint_reports_it_without_a_dashboard_login(self):
        """The one place the answer can be read from a browser."""
        uploads = self.client.get("/").json()["uploads"]
        self.assertIn("durable", uploads)
        self.assertIn("backend", uploads)
