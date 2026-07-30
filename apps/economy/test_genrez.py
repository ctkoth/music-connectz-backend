"""GenreZ — the 2.2 genre list, which the first audit pass missed entirely.

It wasn't in `instrumentDatabase` with the skills; it was a bare array inside
`openGenreModal()`. Every check below either pins the 2.2 data or covers the
spelling variance members actually type.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.genrez import (ALSO_SKILLS, EXTRA_GENRES, GENRES, V22_GENRES,
                                 catalog_payload, genre_payload, is_v22,
                                 normalize_genre, normalize_genres)
from apps.economy.models import profile_for
from apps.economy.personaz import skills_for

User = get_user_model()

# Transcribed from the 2.2 build, in its exact order:
#   const genres = ['Trap', 'Drill', 'Cloud Rap', 'Boom Bap', 'House', 'Techno',
#                   'Pop', 'Hip Hop', 'R&B', 'Jazz', 'Soul', 'Indie',
#                   'Electronic', 'Ambient', 'Lo-Fi'];
SOURCE_2_2 = ["Trap", "Drill", "Cloud Rap", "Boom Bap", "House", "Techno", "Pop",
              "Hip Hop", "R&B", "Jazz", "Soul", "Indie", "Electronic", "Ambient",
              "Lo-Fi"]


class V22PreservedTests(TestCase):
    def test_all_fifteen_are_present_in_their_original_order(self):
        self.assertEqual(V22_GENRES, SOURCE_2_2)
        self.assertEqual(len(V22_GENRES), 15)

    def test_the_2_2_genres_come_first_in_the_full_list(self):
        """So a picker can render the familiar ones above the fold."""
        self.assertEqual(GENRES[:15], SOURCE_2_2)

    def test_names_are_plain_text_exactly_as_2_2_rendered_them(self):
        """Unlike every skill label, the genre buttons carried no emoji. The name
        is what a member saw; emoji is separate metadata."""
        for name in V22_GENRES:
            payload = genre_payload(name)
            self.assertEqual(payload["name"], name)
            self.assertTrue(payload["name"].isascii() or name == "R&B", name)
            self.assertNotIn(payload["emoji"], payload["name"])

    def test_each_genre_is_flagged_by_origin(self):
        for name in V22_GENRES:
            self.assertTrue(is_v22(name), name)
            self.assertEqual(genre_payload(name)["since"], "2.2")
        for name in EXTRA_GENRES:
            self.assertFalse(is_v22(name), name)
            self.assertEqual(genre_payload(name)["since"], "2.4")

    def test_the_four_that_are_also_rapping_skills_are_flagged(self):
        """A genre describes the work, a skill describes the person. 2.2 had both
        and that overlap is deliberate, so it's marked rather than resolved."""
        rapping = skills_for("artist")
        for name in ALSO_SKILLS:
            self.assertIn(name, V22_GENRES, name)
            self.assertIn(name, rapping, f"{name} should still be a Rapping skill")
            self.assertTrue(genre_payload(name)["also_a_skill"], name)
        self.assertEqual(ALSO_SKILLS, {"Trap", "Drill", "Cloud Rap", "Boom Bap"})

    def test_no_duplicates_anywhere(self):
        self.assertEqual(len(GENRES), len(set(GENRES)))

    def test_the_additions_cover_what_2_2_had_no_home_for(self):
        """2.2's fifteen skew hard to hip-hop and electronic."""
        for missing in ("Rock", "Metal", "Country", "Gospel", "Classical",
                        "Afrobeats", "Reggaeton", "Reggae", "K-Pop", "Blues"):
            self.assertIn(missing, GENRES, missing)


class NormalizeTests(TestCase):
    def test_exact_names_pass_through(self):
        for name in GENRES:
            self.assertEqual(normalize_genre(name), name)

    def test_the_spellings_members_actually_type(self):
        for typed, expected in (
            ("rnb", "R&B"), ("R and B", "R&B"), ("r&b", "R&B"), ("RnB", "R&B"),
            ("hiphop", "Hip Hop"), ("HIP HOP", "Hip Hop"), ("rap", "Hip Hop"),
            ("lofi", "Lo-Fi"), ("lo fi", "Lo-Fi"), ("Lo-Fi", "Lo-Fi"),
            ("dnb", "Drum & Bass"), ("drum and bass", "Drum & Bass"),
            ("edm", "Electronic"), ("kpop", "K-Pop"), ("  trap  ", "Trap"),
        ):
            self.assertEqual(normalize_genre(typed), expected, typed)

    def test_genuine_nonsense_is_refused(self):
        for bad in ("", None, "   ", "not a genre", "vaporwave-core-2000"):
            self.assertIsNone(normalize_genre(bad), bad)

    def test_a_list_is_cleaned_deduplicated_and_order_preserved(self):
        out = normalize_genres(["trap", "RnB", "Trap", "nonsense", "lofi"])
        self.assertEqual(out, ["Trap", "R&B", "Lo-Fi"])

    def test_a_bare_string_is_accepted_as_a_one_item_list(self):
        self.assertEqual(normalize_genres("drill"), ["Drill"])

    def test_unknown_genres_are_dropped_not_kept(self):
        """Unlike persona skills. A genre is a closed vocabulary that drives
        discovery — a free-text one is a genre nobody can search for."""
        self.assertEqual(normalize_genres(["Trap", "MyOwnGenre"]), ["Trap"])

    def test_the_list_is_capped(self):
        self.assertEqual(len(normalize_genres(GENRES)), 12)
        self.assertEqual(len(normalize_genres(GENRES, limit=3)), 3)

    def test_junk_input_does_not_raise(self):
        for bad in (None, 7, {"a": 1}):
            self.assertEqual(normalize_genres(bad), [])


class EndpointTests(TestCase):
    def test_the_catalog_is_public_and_flags_the_2_2_set(self):
        resp = APIClient().get("/api/economy/genrez/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["v22"], SOURCE_2_2)
        self.assertEqual(resp.data["count"], len(GENRES))
        names = [g["name"] for g in resp.data["genres"]]
        self.assertEqual(names[:15], SOURCE_2_2)

    def test_the_rules_2_2_only_expressed_in_behaviour_are_stated(self):
        rules = APIClient().get("/api/economy/genrez/").data["rules"]
        self.assertEqual(rules["select"], "one")          # selectedGenre was a string
        self.assertTrue(rules["required_on_work"])        # "Genre/Style *"
        self.assertEqual(rules["max_on_profile"], 12)


class ProfileGenreTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("k", "k@e.com", "pw12345678")
        self.client.force_authenticate(self.user)

    def test_genres_save_through_the_profile_patch(self):
        resp = self.client.patch("/api/auth/me/",
                                 {"genres": ["trap", "lofi", "RnB"]}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(profile_for(self.user).genres, ["Trap", "Lo-Fi", "R&B"])
        self.assertEqual(resp.data["genres"], ["Trap", "Lo-Fi", "R&B"])

    def test_unknown_genres_do_not_land_on_the_profile(self):
        self.client.patch("/api/auth/me/",
                          {"genres": ["Drill", "SomethingMadeUp"]}, format="json")
        self.assertEqual(profile_for(self.user).genres, ["Drill"])

    def test_genres_appear_on_the_public_profile(self):
        self.client.patch("/api/auth/me/", {"genres": ["House"]}, format="json")
        other = User.objects.create_user("o", "o@e.com", "pw12345678")
        self.client.force_authenticate(other)
        resp = self.client.get("/api/economy/members/k/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["genres"], ["House"])

    def test_clearing_genres_works(self):
        self.client.patch("/api/auth/me/", {"genres": ["House"]}, format="json")
        self.client.patch("/api/auth/me/", {"genres": []}, format="json")
        self.assertEqual(profile_for(self.user).genres, [])

    def test_personas_are_untouched_by_a_genre_patch(self):
        self.client.patch("/api/auth/me/",
                          {"personas": [{"key": "artist", "skills": []}]}, format="json")
        self.client.patch("/api/auth/me/", {"genres": ["Jazz"]}, format="json")
        p = profile_for(self.user)
        self.assertEqual(p.genres, ["Jazz"])
        self.assertEqual(p.personas[0]["key"], "artist")
