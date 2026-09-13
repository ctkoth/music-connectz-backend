"""The trial doors — every coach a stranger can reach.

`test_instrument_routes` pins that a scored profile becomes a route. This
pins the layer above it: that a route becomes a DOOR. Five instruments had a
working no-account coach that nothing linked to, which converts nobody and
is invisible from the funnel — a step no visitor can reach never shows up as
a drop-off.
"""
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.economy.trialdoorz import door_keys, doors
from music_connectz.urls import INSTRUMENT_APP_KEYS

DOORS = "/api/economy/trialdoorz/"


class TrialDoorsTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_it_opens_logged_out(self):
        # The screen that needs it most is the one nobody is signed in on.
        self.assertEqual(self.client.get(DOORS).status_code, 200)

    def test_every_mounted_trial_route_is_a_door(self):
        keys = [d["app_key"] for d in self.client.get(DOORS).data["doors"]]
        self.assertEqual(keys, list(INSTRUMENT_APP_KEYS))

    def test_the_five_that_were_unreachable_are_in_it(self):
        # Built, scored, routed — and linked from nothing.
        keys = set(door_keys())
        for key in ("guitarz", "bassz", "keyz", "drumz", "violinz"):
            self.assertIn(key, keys)

    def test_each_door_says_what_it_scores(self):
        # A drummer reading "pitch, breath, range" correctly concludes this
        # place is not for drummers.
        by_key = {d["app_key"]: d for d in doors()}
        self.assertTrue(by_key["drumz"]["scores"])
        self.assertNotEqual(by_key["drumz"]["scores"], by_key["singz"]["scores"])

    def test_the_route_it_names_actually_resolves(self):
        # A door onto a 404 is worse than no door.
        for key in door_keys():
            self.assertTrue(reverse(f"{key}-trial"))


class FunnelAcceptsEveryDoorTests(TestCase):
    """A new door's events must not arrive with the app dropped.

    The funnel's allowlist was the pair `("singz", "rapz")` typed into
    views.py, so the day a GuitarZ door opened its traffic would have read as
    no traffic — the drop-off you cannot see is the one you cannot fix.
    """

    def setUp(self):
        self.client = APIClient()

    def test_every_door_is_a_valid_app_key_on_a_funnel_event(self):
        from apps.economy.models import FunnelEvent
        for i, key in enumerate(door_keys()):
            self.client.post("/api/auth/funnel/", {
                "kind": "try_view", "anon_id": f"v{i}", "meta": {"app_key": key},
            }, format="json")
        stored = {e.meta.get("app_key") for e in FunnelEvent.objects.all()}
        self.assertEqual(stored, set(door_keys()))
