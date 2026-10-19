"""ReligionZ — a declared religion, one filter, every search.

The rule that makes this allowed under the substance rule is that it is a
DECLARATION and not a measurement: fifty traditions and none of them ranked
above another, so "could a member get a good one without getting good?" has
no good one to ask about. These tests pin the lines that keep it that way —
the same shape `test_personalityz.py` already pins for the four-axis field.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import profile_for
from apps.economy import religionz as rz
from apps.economy.visibility import DEFAULTS, MEMBER, can_see

User = get_user_model()
PW = "hunter2hunter2"
LIST_URL = "/api/economy/religionz/"
MEMBERS = "/api/economy/members/"


class ListTests(TestCase):
    def test_it_is_exactly_the_top_fifty(self):
        self.assertEqual(len(rz.RELIGIONS), 50)

    def test_no_leaf_key_repeats(self):
        keys = [k for k, _ in rz.RELIGIONS]
        self.assertEqual(len(set(keys)), len(keys))

    def test_no_group_key_repeats(self):
        keys = [g for g, _, _ in rz.RELIGION_GROUPS]
        self.assertEqual(len(set(keys)), len(keys))

    def test_every_leaf_has_a_key_and_a_label_and_nothing_else(self):
        # No weight, no rank, no adherent count — the change that would look
        # harmless and turn a declaration into a measurement.
        for row in rz.RELIGIONS:
            self.assertEqual(len(row), 2)

    def test_the_flat_list_is_every_group_leaf_and_nothing_else(self):
        # RELIGIONS is derived from RELIGION_GROUPS, not typed a second
        # time — the exact trap the module exists to avoid.
        leaves = tuple(leaf for _, _, leaves in rz.RELIGION_GROUPS for leaf in leaves)
        self.assertEqual(rz.RELIGIONS, leaves)

    def test_every_group_has_at_least_one_branch(self):
        for key, label, leaves in rz.RELIGION_GROUPS:
            self.assertGreater(len(leaves), 0, key)

    def test_christianity_has_its_named_branches(self):
        # The user's own example — Christian with Catholic, Lutheran, etc.
        christianity = dict((g, leaves) for g, _, leaves in rz.RELIGION_GROUPS)["christianity"]
        keys = {k for k, _ in christianity}
        self.assertIn("catholic", keys)
        self.assertIn("lutheran", keys)

    def test_every_family_with_more_than_one_leaf_reads_as_a_family(self):
        # "same w all religions" — Islam and Buddhism get the same grouped
        # shape Christianity does, not a special case for one tradition.
        multi_branch = [g for g, _, leaves in rz.RELIGION_GROUPS if len(leaves) > 1]
        self.assertIn("islam", multi_branch)
        self.assertIn("buddhism", multi_branch)


class CleanTests(TestCase):
    def test_a_known_key_reads_straight(self):
        self.assertEqual(rz.clean_religion("catholic"), "catholic")
        self.assertEqual(rz.clean_religion(" Sunni "), "sunni")

    def test_junk_becomes_nothing_said_and_never_refuses_a_save(self):
        # A profile write must not 400 over an unrecognised value, and a
        # wrong value silently kept would be worse than a blank one.
        self.assertEqual(rz.clean_religion("not-a-real-religion"), "")
        self.assertEqual(rz.clean_religion(None), "")
        self.assertEqual(rz.clean_religion(""), "")

    def test_every_listed_key_survives_the_cleaner(self):
        for key, _ in rz.RELIGIONS:
            self.assertEqual(rz.clean_religion(key), key)


class EndpointTests(TestCase):
    def test_it_opens_logged_out(self):
        r = APIClient().get(LIST_URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["groups"]), len(rz.RELIGION_GROUPS))

    def test_it_says_never_a_score(self):
        note = APIClient().get(LIST_URL).data["note"].lower()
        self.assertIn("never a score", note)

    def test_groups_carry_key_label_and_options(self):
        for row in APIClient().get(LIST_URL).data["groups"]:
            self.assertEqual(set(row), {"key", "label", "options"})

    def test_options_carry_only_key_and_label(self):
        for row in APIClient().get(LIST_URL).data["groups"]:
            for opt in row["options"]:
                self.assertEqual(set(opt), {"key", "label"})

    def test_the_options_flatten_back_to_exactly_fifty(self):
        groups = APIClient().get(LIST_URL).data["groups"]
        total = sum(len(g["options"]) for g in groups)
        self.assertEqual(total, 50)

    def test_christianity_is_a_group_with_catholic_and_lutheran_in_it(self):
        groups = {g["key"]: g for g in APIClient().get(LIST_URL).data["groups"]}
        keys = {o["key"] for o in groups["christianity"]["options"]}
        self.assertIn("catholic", keys)
        self.assertIn("lutheran", keys)


class SearchFilterTests(TestCase):
    """One filter, in the one member search every screen uses — same claim
    `test_personalityz.py` makes for personality."""

    def setUp(self):
        self.me = User.objects.create_user("searcher", "s@e.com", PW)
        profile_for(self.me)
        self.client = APIClient()
        self.client.force_authenticate(self.me)

    def member(self, name, religion):
        u = User.objects.create_user(name, f"{name}@e.com", PW)
        p = profile_for(u)
        p.religion = religion
        p.save()
        return u

    def usernames(self, query):
        return {m["username"] for m in self.client.get(f"{MEMBERS}?{query}").data["members"]}

    def test_one_religion_filters(self):
        self.member("cat", "catholic")
        self.member("sun", "sunni")
        self.assertEqual(self.usernames("religions=catholic"), {"cat"})

    def test_multiple_religions_are_ORed(self):
        self.member("cat", "catholic")
        self.member("sun", "sunni")
        self.member("bud", "buddhism_theravada")
        self.assertEqual(self.usernames("religions=catholic,sunni"), {"cat", "sun"})

    def test_no_filter_returns_everyone_including_the_undeclared(self):
        self.member("said", "catholic")
        self.member("quiet", "")
        self.assertEqual(self.usernames(""), {"said", "quiet"})

    def test_the_undeclared_never_match_a_religion_filter(self):
        # A search for Catholics that returned everyone who said nothing
        # would be a filter that does not filter.
        self.member("said", "catholic")
        self.member("quiet", "")
        self.assertEqual(self.usernames("religions=catholic"), {"said"})

    def test_combines_with_another_filter_the_same_way_signs_does(self):
        u = self.member("both", "catholic")
        p = profile_for(u)
        p.sign = "leo"
        p.save()
        self.member("wrong_sign", "catholic")
        self.assertEqual(self.usernames("religions=catholic&signs=leo"), {"both"})


class ProfileWriterTests(TestCase):
    """A field with two endpoints gets one cleaner, not two — the exact
    two-writers trap CLAUDE.md documents for `personas` and `links`."""

    def setUp(self):
        self.user = User.objects.create_user("writer", "w@e.com", PW)
        profile_for(self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_the_economy_profile_writer_cleans_it(self):
        self.client.post("/api/economy/profile/", {"religion": " Catholic "}, format="json")
        self.assertEqual(profile_for(self.user).religion, "catholic")

    def test_the_auth_writer_cleans_it_the_same_way(self):
        self.client.patch("/api/auth/me/", {"religion": "Sunni"}, format="json")
        self.assertEqual(profile_for(self.user).religion, "sunni")

    def test_junk_from_either_writer_is_nothing_said_not_a_500(self):
        for path, method in (("/api/economy/profile/", self.client.post),
                             ("/api/auth/me/", self.client.patch)):
            r = method(path, {"religion": "not-a-real-one"}, format="json")
            self.assertLess(r.status_code, 400, path)
            self.assertEqual(profile_for(self.user).religion, "")

    def test_the_profile_serves_the_declared_value(self):
        self.client.patch("/api/auth/me/", {"religion": "hinduism"}, format="json")
        d = self.client.get("/api/economy/profile/").data
        self.assertEqual(d["religion"], "hinduism")


class VisibilityTests(TestCase):
    """Member-only by default, same reach as gender, sign and personality —
    a religion is not on the logged-out card any more than those are."""

    def test_default_is_member_not_public_or_private(self):
        self.assertEqual(DEFAULTS["religion"], MEMBER)

    def test_a_stranger_cannot_see_it_a_signed_in_member_can(self):
        owner = User.objects.create_user("owner", "o@e.com", PW)
        p = profile_for(owner)
        p.religion = "catholic"
        p.save()
        viewer = User.objects.create_user("viewer", "v@e.com", PW)
        self.assertFalse(can_see(p, "religion", None))
        self.assertTrue(can_see(p, "religion", viewer))


class NeverAMeasurementTests(TestCase):
    """The line that must not be crossed later for convenience — same claim
    `test_personalityz.py` makes."""

    def test_the_list_carries_no_weight_or_adherent_count_to_score_with(self):
        for key, label in rz.RELIGIONS:
            self.assertIsInstance(key, str)
            self.assertIsInstance(label, str)


class ColumnWidthTests(TestCase):
    def test_every_key_fits_the_column(self):
        from apps.economy.models import Profile
        width = Profile._meta.get_field("religion").max_length
        for key, _ in rz.RELIGIONS:
            self.assertLessEqual(len(key), width, key)
