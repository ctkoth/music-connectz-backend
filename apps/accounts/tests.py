from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.economy.models import profile_for

User = get_user_model()

PASSWORD = "hunter2hunter2"


class AuthFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_register_sets_zodiac_from_birthday(self):
        resp = self.client.post(
            "/api/auth/register/",
            {"username": "tester", "email": "t@example.com", "password": PASSWORD,
             "birthday": "1990-01-20"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["user"]["zodiac"], "Aquarius")
        self.assertEqual(resp.data["user"]["birthday"], "1990-01-20")

    def test_login_by_email_then_patch_overlong_profile(self):
        self.client.post(
            "/api/auth/register/",
            {"username": "tester", "email": "t@example.com", "password": PASSWORD},
            format="json",
        )
        resp = self.client.post(
            "/api/auth/login/",
            {"identifier": "t@example.com", "password": PASSWORD},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")

        # Values longer than the column must be truncated to that column's own
        # width. Slicing everything to 500 raised a DataError (500) on Postgres.
        resp = self.client.patch(
            "/api/auth/me/",
            {"display_name": "D" * 400, "location": "L" * 400,
             "gender": "G" * 400, "bio": "B" * 900},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        profile = profile_for(User.objects.get(username="tester"))
        self.assertEqual(len(profile.display_name), 80)
        self.assertEqual(len(profile.location), 120)
        self.assertEqual(len(profile.gender), 24)
        self.assertEqual(len(profile.bio), 500)

    def test_me_does_not_fan_out_queries(self):
        """The profile/wallet/membership rows behind /api/auth/me/ are read once
        each. Resolving them per-field cost 11 round-trips on every page load."""
        user = User.objects.create_user("q", "q@example.com", PASSWORD)
        self.client.force_authenticate(user)
        self.client.get("/api/auth/me/")  # create the rows first
        with CaptureQueriesContext(connection) as queries:
            resp = self.client.get("/api/auth/me/")
        self.assertEqual(resp.status_code, 200)
        self.assertLessEqual(len(queries), 6, [q["sql"] for q in queries])
