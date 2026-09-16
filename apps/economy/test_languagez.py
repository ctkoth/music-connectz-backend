"""LanguageZ — declared languages spoken AND how well, grouped by region,
one filter, every search.

Same rule as `test_religionz.py`: a DECLARATION, never a measurement, so
"could a member get a good one without getting good?" has no good one to
ask about. The real difference from religion is the shape — `{lang_key:
level}`, the same shape SubstanceZ already uses for "what, and how often" —
and the tests below cover what that shape adds on top of the shared pattern:
a level that must be one of three named ones, and a search that matches on
presence, not on how well.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import profile_for
from apps.economy import languagez as lz
from apps.economy.visibility import DEFAULTS, MEMBER, can_see

User = get_user_model()
PW = "hunter2hunter2"
LIST_URL = "/api/economy/languagez/"
MEMBERS = "/api/economy/members/"


class ListTests(TestCase):
    def test_it_is_exactly_the_top_fifty(self):
        self.assertEqual(len(lz.LANGUAGES), 50)

    def test_no_leaf_key_repeats(self):
        keys = [k for k, _ in lz.LANGUAGES]
        self.assertEqual(len(set(keys)), len(keys))

    def test_no_group_key_repeats(self):
        keys = [g for g, _, _ in lz.LANGUAGE_GROUPS]
        self.assertEqual(len(set(keys)), len(keys))

    def test_the_flat_list_is_every_group_leaf_and_nothing_else(self):
        leaves = tuple(leaf for _, _, leaves in lz.LANGUAGE_GROUPS for leaf in leaves)
        self.assertEqual(lz.LANGUAGES, leaves)

    def test_every_leaf_has_a_key_and_a_label_and_nothing_else(self):
        # No weight, no speaker count, no rank — the change that would look
        # harmless and turn a declaration into a measurement.
        for row in lz.LANGUAGES:
            self.assertEqual(len(row), 2)

    def test_there_are_exactly_three_levels_and_no_native(self):
        # Fluency is what decides whether two people can talk; a
        # native/fluent split is a distinction this app cannot verify and
        # has no reason to ask anyone to prove.
        self.assertEqual(lz.LEVELS, ("beginner", "intermediate", "fluent"))


class CleanTests(TestCase):
    def test_a_known_key_and_level_read_straight(self):
        self.assertEqual(lz.clean_languages({"en": "fluent", "ES": "Beginner"}),
                         {"en": "fluent", "es": "beginner"})

    def test_an_unrecognised_language_key_drops_just_that_entry(self):
        out = lz.clean_languages({"en": "fluent", "not-a-language": "fluent"})
        self.assertEqual(out, {"en": "fluent"})

    def test_an_unrecognised_level_drops_just_that_entry_never_guesses_one(self):
        # No default level — inventing one risks overstating somebody's
        # fluency, which is exactly the substance rule's failure case.
        out = lz.clean_languages({"en": "fluent", "es": "expert"})
        self.assertEqual(out, {"en": "fluent"})

    def test_not_a_dict_becomes_nothing_said(self):
        self.assertEqual(lz.clean_languages(["en", "es"]), {})
        self.assertEqual(lz.clean_languages(None), {})
        self.assertEqual(lz.clean_languages("en"), {})

    def test_it_is_capped_at_the_stated_max(self):
        many = {k: "fluent" for k, _ in lz.LANGUAGES[: lz.MAX_LANGUAGES + 5]}
        out = lz.clean_languages(many)
        self.assertLessEqual(len(out), lz.MAX_LANGUAGES)

    def test_every_listed_key_survives_the_cleaner_at_every_level(self):
        for key, _ in lz.LANGUAGES:
            for level in lz.LEVELS:
                self.assertEqual(lz.clean_languages({key: level}), {key: level})


class EndpointTests(TestCase):
    def test_it_opens_logged_out(self):
        r = APIClient().get(LIST_URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["groups"]), len(lz.LANGUAGE_GROUPS))

    def test_it_says_never_a_score(self):
        note = APIClient().get(LIST_URL).data["note"].lower()
        self.assertIn("never a score", note)

    def test_it_serves_the_cap(self):
        self.assertEqual(APIClient().get(LIST_URL).data["max"], lz.MAX_LANGUAGES)

    def test_it_serves_the_three_levels(self):
        self.assertEqual(APIClient().get(LIST_URL).data["levels"], list(lz.LEVELS))

    def test_groups_carry_key_label_and_options(self):
        for row in APIClient().get(LIST_URL).data["groups"]:
            self.assertEqual(set(row), {"key", "label", "options"})

    def test_the_options_flatten_back_to_exactly_fifty(self):
        groups = APIClient().get(LIST_URL).data["groups"]
        total = sum(len(g["options"]) for g in groups)
        self.assertEqual(total, 50)


class SearchFilterTests(TestCase):
    """One filter, in the one member search every screen uses."""

    def setUp(self):
        self.me = User.objects.create_user("searcher", "s@e.com", PW)
        profile_for(self.me)
        self.client = APIClient()
        self.client.force_authenticate(self.me)

    def member(self, name, languages):
        u = User.objects.create_user(name, f"{name}@e.com", PW)
        p = profile_for(u)
        p.languages = languages
        p.save()
        return u

    def usernames(self, query):
        return {m["username"] for m in self.client.get(f"{MEMBERS}?{query}").data["members"]}

    def test_one_language_filters_regardless_of_level(self):
        self.member("beginner_en", {"en": "beginner"})
        self.member("es_speaker", {"es": "fluent"})
        self.assertEqual(self.usernames("languages=en"), {"beginner_en"})

    def test_a_member_with_any_selected_language_matches(self):
        # OR within the metric, same rule `regions` already follows — a
        # bilingual member should not have to match every language searched.
        self.member("bilingual", {"en": "fluent", "fr": "beginner"})
        self.member("spanish_only", {"es": "fluent"})
        self.assertEqual(self.usernames("languages=fr,es"), {"bilingual", "spanish_only"})

    def test_no_filter_returns_everyone_including_the_undeclared(self):
        self.member("said", {"en": "fluent"})
        self.member("quiet", {})
        self.assertEqual(self.usernames(""), {"said", "quiet"})

    def test_the_undeclared_never_match_a_language_filter(self):
        self.member("said", {"en": "fluent"})
        self.member("quiet", {})
        self.assertEqual(self.usernames("languages=en"), {"said"})


class ProfileWriterTests(TestCase):
    """A field with two endpoints gets one cleaner, not two."""

    def setUp(self):
        self.user = User.objects.create_user("writer", "w@e.com", PW)
        profile_for(self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_the_economy_profile_writer_cleans_it(self):
        self.client.post("/api/economy/profile/",
                          {"languages": {"EN": "Fluent", "es": "beginner"}}, format="json")
        self.assertEqual(profile_for(self.user).languages, {"en": "fluent", "es": "beginner"})

    def test_the_auth_writer_cleans_it_the_same_way(self):
        self.client.patch("/api/auth/me/", {"languages": {"fr": "intermediate"}}, format="json")
        self.assertEqual(profile_for(self.user).languages, {"fr": "intermediate"})

    def test_junk_from_either_writer_drops_the_entry_not_a_500(self):
        for path, method in (("/api/economy/profile/", self.client.post),
                             ("/api/auth/me/", self.client.patch)):
            r = method(path, {"languages": {"en": "fluent", "xx": "fluent"}}, format="json")
            self.assertLess(r.status_code, 400, path)
            self.assertEqual(profile_for(self.user).languages, {"en": "fluent"})

    def test_the_profile_serves_the_declared_levels(self):
        self.client.patch("/api/auth/me/", {"languages": {"hi": "fluent", "ta": "beginner"}},
                          format="json")
        d = self.client.get("/api/economy/profile/").data
        self.assertEqual(d["languages"], {"hi": "fluent", "ta": "beginner"})


class VisibilityTests(TestCase):
    def test_default_is_member_not_public_or_private(self):
        self.assertEqual(DEFAULTS["languages"], MEMBER)

    def test_a_stranger_cannot_see_it_a_signed_in_member_can(self):
        owner = User.objects.create_user("owner", "o@e.com", PW)
        p = profile_for(owner)
        p.languages = {"en": "fluent"}
        p.save()
        viewer = User.objects.create_user("viewer", "v@e.com", PW)
        self.assertFalse(can_see(p, "languages", None))
        self.assertTrue(can_see(p, "languages", viewer))


class NeverAMeasurementTests(TestCase):
    def test_the_cap_keeps_a_row_from_growing_without_bound(self):
        # languages is a JSONField, so there is no column width to overflow —
        # what stands in for it is the MAX_LANGUAGES cap, the same role
        # `personas`/`links` being capped at 50 plays for those lists.
        many = {k: "fluent" for k, _ in lz.LANGUAGES}
        self.assertLessEqual(len(lz.clean_languages(many)), lz.MAX_LANGUAGES)
