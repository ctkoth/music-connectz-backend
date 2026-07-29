from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from music_connectz.urls import INSTRUMENT_APP_KEYS

User = get_user_model()

# The frontend renders <InstrumentZ appKey="…"> and builds basePath as
# /api/<appKey>, so a key it renders without a mount here 404s the whole panel.
# Keep this list in step with TABS in the frontend's src/App.jsx.
FRONTEND_INSTRUMENT_KEYS = ["singz", "rapz"]


class InstrumentSkillZRoutesTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(User.objects.create_user("t", "t@e.com", "pw12345678"))

    def test_every_frontend_instrument_key_is_mounted(self):
        self.assertEqual(sorted(INSTRUMENT_APP_KEYS), sorted(FRONTEND_INSTRUMENT_KEYS))

    def test_skillz_panel_endpoints_answer_for_each_instrument(self):
        """The panel loads profile/drills/badges/leaderboard together — any one
        of them 404ing is what put a raw HTML error page on the RapZ screen."""
        for key in FRONTEND_INSTRUMENT_KEYS:
            for leaf in ("profile", "drills", "badges", "leaderboard"):
                with self.subTest(app=key, endpoint=leaf):
                    resp = self.client.get(f"/api/{key}/skillz/{leaf}/")
                    self.assertEqual(resp.status_code, 200, f"/api/{key}/skillz/{leaf}/")

    def test_unmounted_key_still_404s(self):
        self.assertEqual(self.client.get("/api/drumz/skillz/profile/").status_code, 404)
