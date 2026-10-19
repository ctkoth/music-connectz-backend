"""GET / answers the two questions you otherwise need a Render login to ask.

Uploads durability was already reported here, for a reason the view states:
a service that says "ok" while quietly deleting everyone's music is not
telling the whole truth about itself. Whether the AI key is configured is the
same kind of fact — it decides whether the coach, OCC, DirectZ craft and the
KeyConnectZ voice work at all, and until this existed the only ways to find
out were the Render dashboard or pressing the button and getting a 503.

The test that matters most here is the one asserting it publishes a BOOLEAN.
This endpoint is open to anybody.
"""
import json

from django.test import TestCase, override_settings


class HealthTests(TestCase):
    def _body(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        return json.loads(r.content)

    def test_reports_uploads_and_ai(self):
        body = self._body()
        self.assertEqual(body["status"], "ok")
        self.assertIn("uploads", body)
        self.assertIn("ai", body)

    @override_settings(GEMINI_API_KEY="")
    def test_says_so_when_the_key_is_missing(self):
        import os
        # _key() falls back to the process environment, so a stray real key on
        # the machine running the suite must not make this assert the opposite
        # of what it means to.
        old = os.environ.pop("GEMINI_API_KEY", None)
        try:
            ai = self._body()["ai"]
            self.assertIs(ai["configured"], False)
            self.assertIn("NOT set", ai["detail"])
        finally:
            if old is not None:
                os.environ["GEMINI_API_KEY"] = old

    @override_settings(GEMINI_API_KEY="sk-not-a-real-key-000111222")
    def test_says_so_when_the_key_is_present(self):
        ai = self._body()["ai"]
        self.assertIs(ai["configured"], True)

    @override_settings(GEMINI_API_KEY="sk-not-a-real-key-000111222")
    def test_never_publishes_the_key_or_its_length(self):
        """The whole question is "configured". Anything more is a leak."""
        raw = self.client.get("/").content.decode()
        self.assertNotIn("sk-not-a-real-key-000111222", raw)
        self.assertNotIn("000111222", raw)
        # Not the length either — it narrows a brute force and answers nothing
        # a boolean has not already answered.
        self.assertNotIn(str(len("sk-not-a-real-key-000111222")), json.dumps(
            json.loads(raw)["ai"]))

    @override_settings(GEMINI_API_KEY="sk-not-a-real-key-000111222")
    def test_configured_is_not_a_claim_that_it_works(self):
        """A set key can still be revoked, out of quota, or wrongly scoped.

        Only tools/coach_live_check.sh can tell the difference, so the copy
        has to point at it rather than let "configured" read as "working".
        """
        self.assertIn("coach_live_check", self._body()["ai"]["detail"])

    def test_reports_whether_copyright_scanning_can_run(self):
        """A surface that silently never scans is the link-scanner bug again.

        readiness() already names which half is missing — a provider or
        ffmpeg — so the health endpoint carries it rather than leaving "is
        copyright checking on?" answerable only from the Render dashboard.
        """
        body = self._body()
        self.assertIn("copyright", body)
        self.assertIn("ready", body["copyright"])
        # Not configured here, and it must say so rather than imply clear.
        if body["copyright"]["ready"] is False:
            self.assertTrue(body["copyright"]["why"])

    def test_the_acrcloud_secret_is_never_published(self):
        from django.test import override_settings
        with override_settings(ACRCLOUD_ACCESS_KEY="ak-live-999",
                               ACRCLOUD_ACCESS_SECRET="sec-live-888"):
            raw = self.client.get("/").content.decode()
        self.assertNotIn("sec-live-888", raw)
        self.assertNotIn("ak-live-999", raw)
