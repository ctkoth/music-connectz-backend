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
        self.assertEqual(clean_visibility({"bio": MEMBER}), {"bio": [MEMBER]})

    def test_an_unset_field_follows_the_default(self):
        p = profile_for(member("unset"))
        self.assertEqual(level_for(p, "bio"), [DEFAULTS["bio"]])


class TheScreenSeesEveryFieldTests(TestCase):
    def test_settings_list_includes_the_untouched_ones(self):
        """A member can only check what they're exposing by seeing the whole
        list — the same reason ZodiacZ publishes all twenty-four bonuses."""
        rows = settings_for(profile_for(member("allfields")))
        self.assertEqual({r["field"] for r in rows}, set(DEFAULTS))
        for r in rows:
            self.assertTrue(set(r["level"]) <= {PRIVATE, MEMBER, PUBLIC})
            self.assertEqual(r["default"], [DEFAULTS[r["field"]]])


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
        self.assertEqual(level_for(p, "bio"), [PRIVATE])
        self.assertEqual(level_for(p, "gender"), [PUBLIC])


class ManyAudiencesTests(TestCase):
    """A field carries as many audiences as its owner wants, and ANY of them
    letting the viewer in is enough.

    One is still the normal case — every default is a single audience — and
    the list is the shape rather than a requirement to use more than one."""

    def setUp(self):
        from .audience import FANS, FRIENDS, PARTNERZ
        from .models import Follow
        self.FRIENDS, self.FANS, self.PARTNERZ = FRIENDS, FANS, PARTNERZ
        self.owner = member("aud_owner")
        self.p = profile_for(self.owner)
        self.friend = member("aud_friend")
        self.fan = member("aud_fan")
        self.stranger = member("aud_stranger")
        # friend follows both ways; fan follows one way.
        Follow.objects.create(follower=self.owner, following=self.friend)
        Follow.objects.create(follower=self.friend, following=self.owner)
        Follow.objects.create(follower=self.fan, following=self.owner)

    def set_bio(self, *tokens):
        self.p.visibility = {"bio": list(tokens)}
        self.p.save()

    def test_one_audience_is_a_complete_answer(self):
        self.set_bio(self.FRIENDS)
        self.assertEqual(level_for(self.p, "bio"), [self.FRIENDS])
        self.assertTrue(can_see(self.p, "bio", self.friend))
        self.assertFalse(can_see(self.p, "bio", self.stranger))

    def test_two_audiences_and_either_is_enough(self):
        """"My PartnerZ and my friends" is the obvious real request, and
        forcing one choice makes people pick the looser option."""
        from .groupz import note_work
        note_work([self.owner.pk, self.stranger.pk], collabs=3)
        self.set_bio(self.FRIENDS, self.PARTNERZ)
        self.assertTrue(can_see(self.p, "bio", self.friend))
        self.assertTrue(can_see(self.p, "bio", self.stranger))
        self.assertFalse(can_see(self.p, "bio", self.fan))

    def test_a_fan_is_not_a_friend(self):
        self.set_bio(self.FANS)
        self.assertTrue(can_see(self.p, "bio", self.fan))
        self.assertFalse(can_see(self.p, "bio", self.friend))

    def test_the_owner_always_sees_their_own(self):
        self.set_bio(self.FRIENDS)
        self.assertTrue(can_see(self.p, "bio", self.owner))

    def test_anonymous_is_in_no_relationship_audience(self):
        self.set_bio(self.FRIENDS, self.FANS, self.PARTNERZ)
        self.assertFalse(can_see(self.p, "bio", None))

    def test_a_custom_group_is_an_audience(self):
        from .models import Group, GroupMember
        g = Group.objects.create(owner=self.owner, kind=Group.KIND_CUSTOM, title="crew")
        GroupMember.objects.create(group=g, member=self.stranger)
        self.set_bio(f"group:{g.pk}")
        self.assertTrue(can_see(self.p, "bio", self.stranger))
        self.assertFalse(can_see(self.p, "bio", self.friend))

    def test_somebody_elses_group_grants_nothing(self):
        """A group is local to its owner, so an id only means anything against
        the member whose field is being read."""
        from .models import Group, GroupMember
        theirs = Group.objects.create(owner=self.friend, kind=Group.KIND_CUSTOM, title="not mine")
        GroupMember.objects.create(group=theirs, member=self.stranger)
        self.set_bio(f"group:{theirs.pk}")
        self.assertFalse(can_see(self.p, "bio", self.stranger))

    def test_public_swallows_anything_narrower(self):
        """"Public and my friends" is just public. Storing both would be a row
        that reads as a restriction it does not apply."""
        self.assertEqual(clean_visibility({"bio": [PUBLIC, self.FRIENDS]}), {})
        self.assertEqual(clean_visibility({"gender": [PUBLIC, self.FRIENDS]}), {"gender": [PUBLIC]})

    def test_private_beside_an_audience_loses(self):
        """"Only me, and also my friends" is a contradiction. The audience is
        the specific thing they chose."""
        self.assertEqual(clean_visibility({"bio": [PRIVATE, self.FRIENDS]}), {"bio": [self.FRIENDS]})

    def test_a_stored_string_still_reads(self):
        """Rows written before a field could carry several. A string meant one
        audience and reads as exactly that — no migration, because rewriting
        every row to say the same thing is a migration whose only effect is
        risk."""
        self.p.visibility = {"bio": PRIVATE}
        self.p.save()
        self.assertEqual(level_for(self.p, "bio"), [PRIVATE])
        self.assertFalse(can_see(self.p, "bio", self.friend))

    def test_junk_in_the_list_is_dropped_not_refused(self):
        self.assertEqual(clean_visibility({"bio": [self.FRIENDS, "wizards"]}),
                         {"bio": [self.FRIENDS]})


class AudienceResolvesInBulkTests(TestCase):
    """Fifty cards must not be four questions fifty times."""

    def test_it_answers_without_further_queries(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from .audience import Audience
        from .models import Follow

        viewer = member("bulk_viewer")
        owners = [member(f"bulk_{i}") for i in range(12)]
        for o in owners[:6]:
            Follow.objects.create(follower=viewer, following=o)
            Follow.objects.create(follower=o, following=viewer)

        with CaptureQueriesContext(connection) as ctx:
            aud = Audience(viewer, [o.pk for o in owners])
        built = len(ctx.captured_queries)

        with CaptureQueriesContext(connection) as ctx2:
            for o in owners:
                aud.allows(o.pk, "friends")
                aud.allows(o.pk, "partnerz")
        self.assertEqual(len(ctx2.captured_queries), 0, "asking cost a query")
        self.assertLessEqual(built, 4, "building should be a fixed handful")

    def test_building_does_not_grow_with_the_number_of_members(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from .audience import Audience

        viewer = member("bulk_v2")
        def cost(n):
            owners = [member(f"b2_{n}_{i}") for i in range(n)]
            with CaptureQueriesContext(connection) as ctx:
                Audience(viewer, [o.pk for o in owners])
            return len(ctx.captured_queries)
        self.assertEqual(cost(2), cost(30))


class AudienceAddsNoPerMemberCostTests(TestCase):
    """The reason `Audience` is a context and not a function call.

    Asking "is this viewer a friend / fan / PartnerZ / group member of THIS
    member" per card would be four questions per row on a screen that renders
    up to five hundred. This pins that resolving audiences costs a FIXED
    handful however many members come back.

    It deliberately measures the audience resolution rather than the whole
    endpoint: `MembersView` already fans out about ten queries per member
    through `member_metrics`, which predates this and is its own problem. A
    test asserting a total would fail for that reason and hide this one.
    """

    def test_resolving_is_flat_in_the_number_of_members(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from .audience import Audience
        from .models import Follow

        me = member("flat_me")

        def cost(n, tag):
            others = [member(f"f_{tag}_{i}") for i in range(n)]
            for o in others:
                Follow.objects.create(follower=me, following=o)
                Follow.objects.create(follower=o, following=me)
            with CaptureQueriesContext(connection) as ctx:
                Audience(me, [o.pk for o in others])
            return len(ctx.captured_queries)

        self.assertEqual(cost(3, "few"), cost(40, "many"),
                         "audience resolution grew with the member count")

    def test_and_asking_afterwards_is_free(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from .audience import Audience

        me = member("free_me")
        others = [member(f"free_{i}") for i in range(10)]
        aud = Audience(me, [o.pk for o in others])
        with CaptureQueriesContext(connection) as ctx:
            for o in others:
                for token in ("friends", "fans", "partnerz", "group:1"):
                    aud.allows(o.pk, token)
        self.assertEqual(len(ctx.captured_queries), 0)
