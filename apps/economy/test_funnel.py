"""The join funnel — the one thing that turns "why isn't anybody joining"
from a guess into a number. FunnelEventView takes a step from a visitor who
may have no account; FunnelSummaryView reads the counts back, owner-only.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import FunnelEvent, membership_for

User = get_user_model()
PW = "hunter2hunter2"
EVENT = "/api/auth/funnel/"
SUMMARY = "/api/auth/funnel/summary/"


class FunnelEventTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_logs_a_known_kind_with_no_session(self):
        r = self.client.post(EVENT, {"kind": "landing_view", "anon_id": "abc123"}, format="json")
        self.assertEqual(r.status_code, 204)
        self.assertEqual(FunnelEvent.objects.filter(kind="landing_view", anon_id="abc123").count(), 1)

    def test_rejects_an_unknown_kind(self):
        r = self.client.post(EVENT, {"kind": "made_up_step", "anon_id": "abc123"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(FunnelEvent.objects.count(), 0)

    def test_rejects_a_missing_anon_id(self):
        r = self.client.post(EVENT, {"kind": "landing_view"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(FunnelEvent.objects.count(), 0)

    def test_meta_is_filtered_to_the_allowed_shape(self):
        r = self.client.post(EVENT, {
            "kind": "try_view",
            "anon_id": "abc123",
            "meta": {"app_key": "singz", "evil": "<script>drop table</script>", "user_id": 99999},
        }, format="json")
        self.assertEqual(r.status_code, 204)
        row = FunnelEvent.objects.get()
        self.assertEqual(row.meta, {"app_key": "singz"})

    def test_an_invalid_app_key_is_dropped_not_stored(self):
        r = self.client.post(EVENT, {
            "kind": "try_view", "anon_id": "abc123", "meta": {"app_key": "not-a-real-app"},
        }, format="json")
        self.assertEqual(r.status_code, 204)
        self.assertEqual(FunnelEvent.objects.get().meta, {})

    def test_a_kind_with_no_declared_shape_stores_no_meta(self):
        r = self.client.post(EVENT, {
            "kind": "landing_view", "anon_id": "abc123", "meta": {"app_key": "singz"},
        }, format="json")
        self.assertEqual(r.status_code, 204)
        self.assertEqual(FunnelEvent.objects.get().meta, {})


class FunnelSummaryTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        # is_owner() checks is_staff/is_superuser directly — set them here
        # rather than relying on ensure_owner()'s OWNER_EMAILS promotion,
        # which needs the setting active for the life of the request, not
        # just while the client is built.
        self.owner = User.objects.create_user(
            username="boss", email="boss@test.test", password=PW,
            is_staff=True, is_superuser=True,
        )
        membership_for(self.owner)
        self.member = User.objects.create_user(username="rando", email="rando@test.test", password=PW)
        membership_for(self.member)

    def owner_client(self):
        c = APIClient()
        c.force_authenticate(self.owner)
        return c

    def test_requires_a_session(self):
        r = self.client.get(SUMMARY)
        self.assertEqual(r.status_code, 401)

    def test_a_normal_member_is_refused(self):
        c = APIClient()
        c.force_authenticate(self.member)
        r = c.get(SUMMARY)
        self.assertEqual(r.status_code, 403)

    def test_counts_events_and_unique_visitors_separately(self):
        FunnelEvent.objects.create(kind="landing_view", anon_id="a")
        FunnelEvent.objects.create(kind="landing_view", anon_id="a")  # same visitor, twice
        FunnelEvent.objects.create(kind="landing_view", anon_id="b")
        FunnelEvent.objects.create(kind="register_success", anon_id="a")

        r = self.owner_client().get(SUMMARY)
        self.assertEqual(r.status_code, 200)
        steps = r.data["steps"]
        self.assertEqual(steps["landing_view"]["events"], 3)
        self.assertEqual(steps["landing_view"]["unique"], 2)
        self.assertEqual(steps["register_success"]["unique"], 1)
        # Every visitor who landed converted through to a real account here —
        # register_success unique (1) over landing_view unique (2) is 50%.
        self.assertEqual(steps["register_success"]["pct_of_base"], 50.0)

    def test_every_declared_kind_is_present_even_with_zero_events(self):
        r = self.owner_client().get(SUMMARY)
        from apps.economy.models import FUNNEL_KINDS
        for kind, _ in FUNNEL_KINDS:
            self.assertIn(kind, r.data["steps"])
            self.assertEqual(r.data["steps"][kind]["events"], 0)
