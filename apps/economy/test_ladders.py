"""Every tier gate is on the one list, read from the constant that gates it."""
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import catalog, features, statz_trial
from apps.economy.ladders import ladders

U = get_user_model()


class LadderListTests(TestCase):
    def test_no_tier_limit_is_left_off(self):
        named = {r["source"].split(":", 1)[1] for r in ladders() if r["source"].startswith("tier_limits:")}
        missing = set(catalog.TIER_LIMITS["free"]) - named
        self.assertFalse(missing, f"TIER_LIMITS keys with no row in ladders.py: {sorted(missing)}")

    def test_every_plan_feature_and_statz_feature_is_listed(self):
        keys = {r["key"] for r in ladders()}
        for k in features.FEATURES:
            self.assertIn(f"feature:{k}", keys)
        for f in statz_trial.FEATURES:
            self.assertIn(f"statz:{f['key']}", keys)

    def test_coreys_numbers_read_as_he_said_them(self):
        rows = {r["key"]: r["values"] for r in ladders()}
        for k in ("daw_tracks", "mix_tracks", "tone_presets", "anime_shots", "imagez_layers", "releases"):
            self.assertEqual(rows[k], {"free": "3", "premium": "6", "statz": "Unlimited"}, k)
        self.assertEqual(rows["wav_bits"], {"free": "MP3 only", "premium": "16-bit WAV", "statz": "24-bit WAV"})
        self.assertEqual(rows["char_limit"]["statz"], "Unlimited")         # Corey's fixed number

    def test_statz_features_say_the_sample_covers_them(self):
        r = [x for x in ladders() if x["key"] == "statz:daw_automation"][0]
        self.assertEqual(r["values"], {"free": "Daily sample", "premium": "Daily sample", "statz": "✓"})

    def test_every_row_points_at_a_real_tab(self):
        app = Path(__file__).resolve().parents[3] / "-music-connectz-frontend-" / "src" / "App.jsx"
        if not app.exists():
            self.skipTest("frontend checkout not beside this one")
        tabs = set(re.findall(r'key: "([a-z0-9_]+)", label:', app.read_text()))
        for r in ladders():
            if r["tab"]:
                self.assertIn(r["tab"], tabs, r["key"])

    def test_served_logged_out_and_says_which_column_is_yours(self):
        d = APIClient().get("/api/economy/ladders/").data
        self.assertEqual(d["tiers"], ["free", "premium", "statz"])
        self.assertEqual(d["mine"], "")
        c = APIClient(); c.force_authenticate(U.objects.create_user("m", password="pw12345!x"))
        self.assertEqual(c.get("/api/economy/ladders/").data["mine"], "free")


class CoreysNumbersReachedTests(TestCase):
    def test_lilith_routines_and_sonday_boards_are_3_6_unlimited(self):
        from apps.economy.ladders import ladders
        rows = {r["key"]: r for r in ladders()}
        for key in ("lilith_routines", "sonday_boards"):
            self.assertTrue(rows[key]["coreys_numbers"], (key, rows[key]["values"]))


class EqBandsRowTests(TestCase):
    def test_eq_bands_are_on_the_ladder_at_coreys_numbers(self):
        from apps.economy.ladders import ladders
        row = next(r for r in ladders() if r["key"] == "eq_bands")
        self.assertTrue(row["coreys_numbers"], row["values"])


class AlbumRowTests(TestCase):
    def test_album_songs_are_on_the_ladder_at_coreys_numbers(self):
        from apps.economy.ladders import ladders
        row = next(r for r in ladders() if r["key"] == "album_songs")
        self.assertEqual(row["values"], {"free": "8", "premium": "11", "statz": "Unlimited"}, "Corey: the tier numbers plus five")
        self.assertEqual(row["target"], "mixz-album")


class GlowColorsRowTests(TestCase):
    def test_glow_colors_are_coreys_numbers_and_on_the_ladder(self):
        from apps.economy.catalog import limits_for
        from apps.economy.ladders import ladders
        self.assertEqual([limits_for(t)["glow_colors"] for t in ("free", "premium", "statz")], [3, 6, None])
        row = next(r for r in ladders() if r["key"] == "glow_colors")
        self.assertTrue(row["coreys_numbers"], row["values"])


class SplitOpensRowTests(TestCase):
    def test_split_opens_are_coreys_numbers_and_on_the_ladder(self):
        from apps.economy.catalog import limits_for
        from apps.economy.ladders import ladders
        self.assertEqual([limits_for(t)["split_opens"] for t in ("free", "premium", "statz")], [3, 6, None])
        self.assertTrue(next(r for r in ladders() if r["key"] == "split_opens")["coreys_numbers"])
