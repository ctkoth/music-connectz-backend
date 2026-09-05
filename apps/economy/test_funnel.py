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

    def test_the_share_step_is_accepted_and_carries_its_app(self):
        # The one outward-pointing step: somebody handing their score to
        # someone else is what widens the top of the funnel.
        r = self.client.post(EVENT, {
            "kind": "try_shared", "anon_id": "abc123", "meta": {"app_key": "rapz"},
        }, format="json")
        self.assertEqual(r.status_code, 204)
        row = FunnelEvent.objects.get()
        self.assertEqual(row.kind, "try_shared")
        self.assertEqual(row.meta, {"app_key": "rapz"})

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


class ChannelAttributionTests(TestCase):
    """`?src=` — which channel produced which arrival.

    Without it the funnel counts arrivals and cannot say which post, flyer or
    ad produced them, so every channel looks identical at zero — which is
    exactly the state this platform was in when the marketing plan was written.
    The first thing marketing money buys is otherwise an unanswerable question.
    """

    EVENT = "/api/auth/funnel/"
    SUMMARY = "/api/auth/funnel/summary/"

    def setUp(self):
        self.owner = User.objects.create_superuser("owner2", "o2@e.com", "hunter2hunter2")
        self.client = APIClient()

    def fire(self, kind, anon, src=None, **meta):
        body = {"kind": kind, "anon_id": anon, "meta": {**meta}}
        if src is not None:
            body["meta"]["src"] = src
        return self.client.post(self.EVENT, body, format="json")

    def summary(self):
        c = APIClient()
        c.force_authenticate(self.owner)
        return c.get(self.SUMMARY).data

    def test_a_source_is_stored_on_the_arrival(self):
        self.fire("landing_view", "a1", src="reddit")
        self.assertEqual(FunnelEvent.objects.get(kind="landing_view").meta["src"], "reddit")

    def test_a_source_is_a_channel_name_not_a_payload(self):
        # Short slug only. Anything else is somebody putting data in a URL.
        self.fire("landing_view", "a2", src="<script>alert(1)</script>")
        self.assertEqual(FunnelEvent.objects.get(kind="landing_view").meta, {})
        self.fire("landing_view", "a3", src="x" * 200)
        self.assertEqual(FunnelEvent.objects.filter(kind="landing_view").last().meta, {})

    def test_it_is_lowercased_so_two_spellings_are_one_channel(self):
        self.fire("landing_view", "a4", src="  Reddit  ")
        self.assertEqual(FunnelEvent.objects.last().meta["src"], "reddit")

    def test_the_summary_breaks_the_funnel_down_by_channel(self):
        # reddit sends people who score; flyer sends people who bounce. Those
        # need opposite responses, and one number cannot tell them apart.
        self.fire("landing_view", "r1", src="reddit")
        self.fire("try_scored", "r1", src="reddit")
        self.fire("landing_view", "f1", src="flyer")
        self.fire("landing_view", "f2", src="flyer")

        rows = {r["src"]: r for r in self.summary()["sources"]}
        self.assertEqual(rows["reddit"]["try_scored"], 1)
        self.assertEqual(rows["flyer"]["landing_view"], 2)
        self.assertEqual(rows["flyer"]["try_scored"], 0)

    def test_sources_are_ordered_by_how_many_people_they_sent(self):
        for i in range(3):
            self.fire("landing_view", f"b{i}", src="big")
        self.fire("landing_view", "s1", src="small")
        self.assertEqual([r["src"] for r in self.summary()["sources"]], ["big", "small"])

    def test_one_browser_is_one_person_per_channel(self):
        # Refreshing five times is not five people.
        for _ in range(5):
            self.fire("landing_view", "same", src="reddit")
        self.assertEqual(self.summary()["sources"][0]["landing_view"], 1)

    def test_untagged_traffic_is_still_counted_just_not_attributed(self):
        self.fire("landing_view", "u1")
        d = self.summary()
        self.assertEqual(d["steps"]["landing_view"]["unique"], 1)
        self.assertEqual(d["sources"], [])
        # And the empty list says which of the two problems it is.
        self.assertIn("Untagged", d["sources_note"])
