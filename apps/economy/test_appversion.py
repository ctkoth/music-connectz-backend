from unittest.mock import patch

from django.test import SimpleTestCase
from rest_framework.test import APIClient

from apps.economy.appversion import build_info


class AppVersionTests(SimpleTestCase):
    def test_the_commit_comes_from_the_host_and_is_seven_characters(self):
        with patch.dict("os.environ", {"RENDER_GIT_COMMIT": "a1b2c3d4e5f6a7b8c9d0"}, clear=True):
            self.assertEqual(build_info()["commit"], "a1b2c3d")

    def test_with_nothing_set_it_says_dev_instead_of_inventing_one(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(build_info()["commit"], "dev")

    def test_it_is_open_logged_out_and_never_cached(self):
        r = APIClient().get("/api/economy/version/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("commit", r.json())
        self.assertEqual(r["Cache-Control"], "no-store")
