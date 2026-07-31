"""VSTZ — matching, not running.

The spec asks for "VST support with filtering based on users VST". These cover
the filtering. Nothing here executes a plugin, because a browser cannot, and a
test that pretended otherwise would be lying about the product.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from . import catalog
from .models import Rack, matches, missing_from, rack_for

User = get_user_model()


def member(name, plugins=(), scanned=()):
    u = User.objects.create_user(username=name, password="vstz-pass-1")
    rack = rack_for(u)
    if plugins:
        rack.set_plugins(plugins)
    if scanned:
        rack.record_scan(scanned)
    rack.save()
    return u


class CatalogTests(TestCase):
    def test_the_catalog_is_not_empty_and_every_row_is_complete(self):
        payload = catalog.catalog_payload()
        self.assertGreater(payload["count"], 30)
        for p in payload["plugins"]:
            with self.subTest(plugin=p["key"]):
                for field in ("name", "vendor", "kind", "formats", "price"):
                    self.assertTrue(p[field], f"{p['key']} missing {field}")
                self.assertIn(p["kind"], catalog.KIND_KEYS)
                self.assertIn(p["price"], catalog.PRICE_KEYS)
                for fmt in p["formats"]:
                    self.assertIn(fmt, catalog.FORMAT_KEYS)

    def test_only_web_audio_modules_claim_to_run_in_a_browser(self):
        """A native VST cannot run in a tab. The data must not imply it can."""
        for p in catalog.catalog_payload()["plugins"]:
            if p["browser_ok"]:
                with self.subTest(plugin=p["key"]):
                    self.assertIn("wam", p["formats"],
                                  f"{p['key']} claims browser_ok without a WAM build")

    def test_the_catalog_says_plainly_that_natives_need_the_desktop_app(self):
        note = catalog.catalog_payload()["note"].lower()
        self.assertIn("cannot run in a browser", note)


class NormaliseTests(TestCase):
    def test_a_key_resolves(self):
        self.assertEqual(catalog.normalize_key("serum"), "serum")

    def test_a_display_name_resolves(self):
        self.assertEqual(catalog.normalize_key("FabFilter Pro-Q 3"), "pro-q-3")

    def test_name_with_vendor_resolves(self):
        """The same label-vs-key trap that lost personas and genres."""
        self.assertEqual(catalog.normalize_key("Serum — Xfer Records"), "serum")
        self.assertEqual(catalog.normalize_key("Serum (Xfer Records)"), "serum")

    def test_case_and_spacing_do_not_matter(self):
        for sent in ("SERUM", "  serum  ", "Serum"):
            self.assertEqual(catalog.normalize_key(sent), "serum")

    def test_something_that_is_not_a_plugin_stays_unknown(self):
        for junk in ("", "   ", None, "not-a-plugin", "🎛️"):
            self.assertIsNone(catalog.normalize_key(junk))

    def test_normalise_keys_dedupes_and_keeps_order(self):
        got = catalog.normalize_keys(["Serum", "serum", "FabFilter Pro-Q 3", "junk"])
        self.assertEqual(got, ["serum", "pro-q-3"])


class MatchTests(TestCase):
    RACK = ["serum", "pro-q-3", "valhalla-supermassive"]

    def test_all_mode_needs_everything(self):
        self.assertTrue(matches(self.RACK, ["serum", "pro-q-3"], mode="all"))
        self.assertFalse(matches(self.RACK, ["serum", "ozone"], mode="all"))

    def test_any_mode_needs_one(self):
        self.assertTrue(matches(self.RACK, ["serum", "ozone"], mode="any"))
        self.assertFalse(matches(self.RACK, ["ozone", "kontakt"], mode="any"))

    def test_asking_for_nothing_matches_everybody(self):
        """Filtering on nothing must not quietly return nobody."""
        self.assertTrue(matches(self.RACK, []))
        self.assertTrue(matches([], []))

    def test_missing_from_reports_the_gap(self):
        self.assertEqual(missing_from(self.RACK, ["serum", "ozone"]), ["ozone"])


class RackTests(TestCase):
    def test_unknown_plugins_are_dropped_on_save(self):
        u = member("owner1")
        rack = rack_for(u)
        rack.set_plugins(["Serum", "definitely not a plugin"])
        self.assertEqual(rack.plugins, ["serum"])

    def test_a_scan_is_evidence_and_typing_is_a_claim(self):
        u = member("owner2", plugins=["serum", "ozone"], scanned=["Serum"])
        rack = rack_for(u)
        self.assertIn("serum", rack.verified)
        self.assertNotIn("ozone", rack.verified,
                         "typing a plugin in is not evidence you have it")

    def test_a_scan_adds_what_it_found(self):
        u = member("owner3", plugins=["serum"])
        rack = rack_for(u)
        rack.record_scan(["FabFilter Pro-Q 3"])
        self.assertIn("pro-q-3", rack.plugins)
        self.assertIn("pro-q-3", rack.verified)

    def test_a_scan_does_not_remove_what_was_claimed(self):
        """A member may own plugins the scanner couldn't see — a second machine,
        or a format it doesn't walk. Losing them on every scan would be worse
        than trusting the claim."""
        u = member("owner4", plugins=["serum", "ozone"])
        rack = rack_for(u)
        rack.record_scan(["Serum"])
        self.assertIn("ozone", rack.plugins)


class ApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.me = member("searcher")
        self.client.force_authenticate(self.me)

    def test_the_catalog_is_public(self):
        r = APIClient().get(reverse("vstz-catalog"))
        self.assertEqual(r.status_code, 200)
        self.assertGreater(r.json()["count"], 30)

    def test_the_catalog_filters(self):
        r = self.client.get(reverse("vstz-catalog"), {"kind": "synth", "price": "free"})
        rows = r.json()["plugins"]
        self.assertTrue(rows)
        for p in rows:
            self.assertEqual(p["kind"], "synth")
            self.assertEqual(p["price"], "free")

    def test_saving_a_rack_reports_what_it_could_not_recognise(self):
        r = self.client.put(reverse("vstz-rack"),
                            {"plugins": ["Serum", "made up plugin"]}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["plugins"], ["serum"])
        self.assertIn("made up plugin", r.json()["unrecognised"])

    def test_add_and_remove(self):
        self.client.put(reverse("vstz-rack"), {"plugins": ["serum"]}, format="json")
        r = self.client.post(reverse("vstz-rack"),
                             {"add": ["ozone"], "remove": ["serum"]}, format="json")
        self.assertEqual(r.json()["plugins"], ["ozone"])

    def test_search_finds_members_who_own_everything_asked_for(self):
        member("has_both", plugins=["serum", "pro-q-3"])
        member("has_one", plugins=["serum"])
        r = self.client.get(reverse("vstz-search"),
                            {"plugins": "serum,pro-q-3", "mode": "all"})
        names = [m["username"] for m in r.json()["matches"]]
        self.assertEqual(names, ["has_both"])

    def test_a_strict_search_still_shows_who_came_closest(self):
        """Nobody having all three shouldn't mean an empty screen."""
        member("close", plugins=["serum", "pro-q-3"])
        r = self.client.get(reverse("vstz-search"),
                            {"plugins": "serum,pro-q-3,ozone", "mode": "all"})
        body = r.json()
        self.assertEqual(body["matches"], [])
        self.assertEqual(body["near_matches"][0]["username"], "close")
        self.assertEqual(body["near_matches"][0]["missing"], ["ozone"])

    def test_verified_racks_sort_above_unverified(self):
        member("claimed", plugins=["serum"])
        member("scanned", plugins=["serum"], scanned=["Serum"])
        r = self.client.get(reverse("vstz-search"), {"plugins": "serum"})
        self.assertEqual(r.json()["matches"][0]["username"], "scanned")

    def test_search_with_no_plugins_is_refused(self):
        r = self.client.get(reverse("vstz-search"), {"plugins": ""})
        self.assertEqual(r.status_code, 400)

    def test_you_are_not_your_own_search_result(self):
        rack = rack_for(self.me)
        rack.set_plugins(["serum"])
        rack.save()
        r = self.client.get(reverse("vstz-search"), {"plugins": "serum"})
        self.assertEqual(r.json()["matches"], [])

    def test_a_scan_needs_a_list(self):
        r = self.client.post(reverse("vstz-scan"), {"found": "serum"}, format="json")
        self.assertEqual(r.status_code, 400)
