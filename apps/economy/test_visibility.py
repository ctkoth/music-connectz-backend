"""Per-field visibility: private / member / public, chosen per field.

The load-bearing claim is that NOBODY'S EXPOSURE MOVED when this shipped — the
defaults are what each field already did — so most of these tests are about the
defaults matching the two card builders rather than about the control itself.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .models import profile_for, public_name
from .visibility import (DEFAULTS, MEMBER, PRIVATE, PUBLIC, can_see,
                         clean_visibility, level_for, redact, settings_for)

User = get_user_model()


def member(name):
    return User.objects.create_user(name, f"{name}@example.com", "hunter2hunter2")


class DefaultsAreTodaysBehaviourTests(TestCase):
    """If a default disagrees with the card that field is on, the feature
    changed somebody's exposure on deploy day without asking."""

    def setUp(self):
        self.p = profile_for(member("defaults"))

    def test_what_is_on_the_logged_out_card_stays_public(self):
        for field in ("display_name", "bio", "personas", "links", "badge_title"):
            self.assertEqual(DEFAULTS[field], PUBLIC, field)
            self.assertTrue(can_see(self.p, field, None), field)

    def test_what_is_member_only_stays_member_only(self):
        for field in ("gender", "sign", "regions", "nationalities", "sober",
                      "personality", "attracted_to", "age", "avatar"):
            self.assertEqual(DEFAULTS[field], MEMBER, field)
            self.assertFalse(can_see(self.p, field, None), field)
            self.assertTrue(can_see(self.p, field, member(f"v_{field}")), field)

    def test_what_was_served_to_nobody_stays_private(self):
        for field in ("birthday", "location", "substances", "first_name", "last_name"):
            self.assertEqual(DEFAULTS[field], PRIVATE, field)
            self.assertFalse(can_see(self.p, field, None), field)
            self.assertFalse(can_see(self.p, field, member(f"w_{field}")), field)

    def test_age_and_birthday_are_separate_questions(self):
        """"Roughly how old I am" and "the day I was born" are different
        answers, and the second one is a security question."""
        self.assertNotEqual(DEFAULTS["age"], DEFAULTS["birthday"])


class TheOwnerAlwaysSeesTheirOwnTests(TestCase):
    def test_even_when_everything_is_private(self):
        me = member("owner")
        p = profile_for(me)
        p.visibility = {f: PRIVATE for f in DEFAULTS}
        p.save()
        for field in DEFAULTS:
            self.assertTrue(can_see(p, field, me), field)


class MixedLevelsTests(TestCase):
    """The actual ask: public on one field, member on another, private on a
    third, all at once."""

    def setUp(self):
        self.me = member("mixed")
        self.me.first_name, self.me.last_name = "Corey", "Knap"
        self.me.save()
        self.p = profile_for(self.me)
        self.p.visibility = {"first_name": PUBLIC, "last_name": MEMBER,
                             "birthday": PRIVATE, "bio": MEMBER}
        self.p.save()

    def test_a_stranger_sees_only_the_public_half(self):
        self.assertEqual(public_name(self.p, None), "Corey")

    def test_a_signed_in_member_sees_both_halves(self):
        self.assertEqual(public_name(self.p, member("looker")), "Corey Knap")

    def test_a_field_moved_to_member_leaves_the_logged_out_page(self):
        self.assertTrue(can_see(self.p, "bio", member("looker2")))
        self.assertFalse(can_see(self.p, "bio", None))


class RedactionTests(TestCase):
    def setUp(self):
        self.p = profile_for(member("redact"))
        self.p.visibility = {"gender": PRIVATE, "regions": PRIVATE,
                             "sober": PRIVATE, "age": PRIVATE, "sign": PRIVATE}
        self.p.save()

    def test_blanks_to_the_same_type_so_a_client_does_not_break(self):
        card = redact({"gender": "male", "regions": ["uk"], "age": 30},
                      self.p, None)
        self.assertEqual(card["gender"], "")
        self.assertEqual(card["regions"], [])
        self.assertIsNone(card["age"])

    def test_a_hidden_bool_is_none_not_false(self):
        """`sober: False` is a claim. Answering a question nobody may ask with
        a lie is worse than not answering."""
        self.assertIsNone(redact({"sober": True}, self.p, None)["sober"])

    def test_a_derived_key_follows_its_source(self):
        """Hiding `sign` and serving `sign_cn` would be the setting doing
        nothing, which is the failure mode of a control that looks like it
        worked."""
        card = redact({"sign": "Leo", "sign_cn": "Rat"}, self.p, None)
        self.assertEqual(card["sign_cn"], "")

    def test_it_leaves_keys_it_does_not_govern_alone(self):
        card = redact({"username": "corey", "tier": "free"}, self.p, None)
        self.assertEqual(card["username"], "corey")
        self.assertEqual(card["tier"], "free")


class CleanVisibilityTests(TestCase):
    def test_junk_is_dropped_never_refused(self):
        """A profile write must not 400 over one bad key — the rule
        `clean_code` already follows for a personality letter."""
        self.assertEqual(clean_visibility({"nope": "public"}), {})
        self.assertEqual(clean_visibility({"bio": "sideways"}), {})
        self.assertEqual(clean_visibility("not a dict"), {})

    def test_a_value_equal_to_the_default_is_not_stored(self):
        """The row records CHOICES, so a default can be corrected later without
        rewriting every profile that only ever agreed with it."""
        self.assertEqual(clean_visibility({"bio": PUBLIC}), {})
        self.assertEqual(clean_visibility({"bio": MEMBER}), {"bio": MEMBER})

    def test_an_unset_field_follows_the_default(self):
        p = profile_for(member("unset"))
        self.assertEqual(level_for(p, "bio"), DEFAULTS["bio"])


class TheScreenSeesEveryFieldTests(TestCase):
    def test_settings_list_includes_the_untouched_ones(self):
        """A member can only check what they're exposing by seeing the whole
        list — the same reason ZodiacZ publishes all twenty-four bonuses."""
        rows = settings_for(profile_for(member("allfields")))
        self.assertEqual({r["field"] for r in rows}, set(DEFAULTS))
        for r in rows:
            self.assertIn(r["level"], (PRIVATE, MEMBER, PUBLIC))
            self.assertEqual(r["default"], DEFAULTS[r["field"]])


class TheWriteMergesTests(TestCase):
    def test_sending_one_field_does_not_reset_the_others(self):
        """The client sends what it changed. A whole-map write would reset
        every control the client doesn't know about — which is what happens
        while the two repos deploy independently."""
        me = member("merge")
        c = APIClient()
        c.force_authenticate(me)
        c.patch("/api/auth/me/", {"visibility": {"bio": PRIVATE}}, format="json")
        c.patch("/api/auth/me/", {"visibility": {"gender": PUBLIC}}, format="json")
        p = profile_for(me)
        self.assertEqual(level_for(p, "bio"), PRIVATE)
        self.assertEqual(level_for(p, "gender"), PUBLIC)
