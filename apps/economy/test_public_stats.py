"""PublicStatsView — the landing page's real member count, no session required.

Two things distinguish it from StatsView (the authenticated one): it must
answer with no caller identity at all, and it must never mark anybody as
"seen" as a side effect of being read — a public endpoint that mutated
presence on every anonymous hit would let a visitor manufacture "online now".
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.models import membership_for

User = get_user_model()
PW = "hunter2hunter2"
PUBLIC_STATS = "/api/auth/public-stats/"


class PublicStatsTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_answers_with_no_session_at_all(self):
        r = self.client.get(PUBLIC_STATS)
        self.assertEqual(r.status_code, 200)
        self.assertIn("total_members", r.data)
        self.assertIn("online_now", r.data)

    def test_counts_are_real_not_seeded_by_the_request(self):
        u = User.objects.create_user(username="seen", password=PW)
        m = membership_for(u)
        m.last_seen = timezone.now() - timedelta(minutes=1)
        m.save(update_fields=["last_seen"])

        r = self.client.get(PUBLIC_STATS)
        self.assertEqual(r.data["total_members"], User.objects.count())
        self.assertEqual(r.data["online_now"], 1)

    def test_stale_presence_does_not_count_as_online(self):
        u = User.objects.create_user(username="stale", password=PW)
        m = membership_for(u)
        m.last_seen = timezone.now() - timedelta(minutes=30)
        m.save(update_fields=["last_seen"])

        r = self.client.get(PUBLIC_STATS)
        self.assertEqual(r.data["online_now"], 0)

    def test_only_the_two_fields_are_exposed(self):
        # No username list, no wallet, no per-member anything — this is the
        # one thing that separates it from StatsView being reachable by
        # anyone. A field creeping in here would leak member data to a
        # visitor with no account.
        u = User.objects.create_user(username="member", password=PW)
        membership_for(u)
        r = self.client.get(PUBLIC_STATS)
        self.assertEqual(set(r.data.keys()), {"total_members", "online_now"})

    def test_does_not_mark_the_anonymous_caller_as_seen(self):
        before = User.objects.count()
        self.client.get(PUBLIC_STATS)
        # A read with no session must create no rows at all.
        self.assertEqual(User.objects.count(), before)
