from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from . import geo

User = get_user_model()


class GeocodeTests(TestCase):
    @override_settings(GOOGLE_MAPS_API_KEY="")
    def test_no_key_means_no_pin_and_no_request(self):
        with mock.patch("apps.economy.geo.requests.get") as get:
            self.assertIsNone(geo.geocode("1 Main St, Fort Collins, CO"))
            get.assert_not_called()

    @override_settings(GOOGLE_MAPS_API_KEY="k")
    def test_returns_lat_lng_on_ok(self):
        resp = mock.Mock()
        resp.json.return_value = {"status": "OK", "results": [
            {"geometry": {"location": {"lat": 40.58, "lng": -105.08}}}]}
        with mock.patch("apps.economy.geo.requests.get", return_value=resp):
            self.assertEqual(geo.geocode("1 Main St"), (40.58, -105.08))

    @override_settings(GOOGLE_MAPS_API_KEY="k")
    def test_zero_results_and_errors_are_none(self):
        resp = mock.Mock()
        resp.json.return_value = {"status": "ZERO_RESULTS", "results": []}
        with mock.patch("apps.economy.geo.requests.get", return_value=resp):
            self.assertIsNone(geo.geocode("nowhere"))
        with mock.patch("apps.economy.geo.requests.get", side_effect=OSError("down")):
            self.assertIsNone(geo.geocode("1 Main St"))
