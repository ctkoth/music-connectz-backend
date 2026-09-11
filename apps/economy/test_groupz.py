"""GroupZ — that the five tabs answer, and that three of them stay derived.

The load-bearing assertions here are the ones about NOT storing: friends and
fans have to keep agreeing with `follow_counts`, and a block has to keep
landing in `Block` where the DM rule reads it. Both would still "work" on
screen if somebody moved them into a GroupZ-owned table, and both would be
quietly wrong — which is exactly the kind of change a test has to refuse.
"""
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from .models import (Block, Follow, MemberGroup, MemberGroupMember,
                     blocked_user_ids, follow_counts)
from .groupz import CUSTOM_GROUP_LIMITS

User = get_user_model()


class GroupZTests(APITestCase):
    def setUp(self):
        self.me = User.objects.create_user("me", password="x")
        self.mutual = User.objects.create_user("mutual", password="x")
        self.fan = User.objects.create_user("fan", password="x")
        self.stranger = User.objects.create_user("stranger", password="x")
        # mutual <-> me  (a friend), fan -> me (a fan, not followed back)
        Follow.objects.create(follower=self.me, following=self.mutual)
        Follow.objects.create(follower=self.mutual, following=self.me)
        Follow.objects.create(follower=self.fan, following=self.me)
        self.client.force_authenticate(self.me)

    def _get(self):
        r = self.client.get(reverse("groupz"))
        self.assertEqual(r.status_code, 200)
        # The five used to BE the response. They are under "groups" now, beside
        # the "tier_limit" the custom-group ladder needs — so every read here
        # goes through this one helper rather than each test learning the
        # envelope separately.
        groups = r.data["groups"]
        return {g["kind"] if g["id"] in ("friends", "fans", "blocked") else g["id"]: g
                for g in groups}, groups

    def test_all_five_kinds_present_even_when_empty(self):
        _, rows = self._get()
        kinds = {g["kind"] for g in rows}
        # Partners and custom are absent until made; the derived three are
        # always there, because an absent row makes the client offer a
        # "Create" button for something that cannot be created.
        self.assertEqual({"friends", "fans", "blocked"}, kinds)

    def test_friends_and_fans_are_the_follow_graph(self):
        by, _ = self._get()
        self.assertEqual(["mutual"], by["friends"]["members"])
        self.assertEqual(["fan"], by["fans"]["members"])

    def test_derived_counts_agree_with_follow_counts(self):
        """The whole reason these aren't stored. If somebody gives GroupZ its
        own friends table, this is what refuses it."""
        by, _ = self._get()
        counts = follow_counts(self.me)
        self.assertEqual(counts["friends"], len(by["friends"]["members"]))
        self.assertEqual(counts["fans"], len(by["fans"]["members"]))

    def test_derived_groups_are_not_editable_and_say_why(self):
        by, _ = self._get()
        for kind in ("friends", "fans"):
            self.assertFalse(by[kind]["can_add"], kind)
            self.assertTrue(by[kind]["note"], f"{kind} must say what changes it")
        # Blocked is the one derived-looking tab you DO edit directly.
        self.assertTrue(by["blocked"]["can_add"])

    def test_adding_to_a_derived_group_is_refused_with_a_reason(self):
        r = self.client.post(reverse("groupz-member", args=["fans", "add"]),
                             {"username": "stranger"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("FanZ", r.data["detail"])

    def test_block_writes_to_Block_so_dms_see_it(self):
        """GroupZ's header promises a blocked member can never DM you. That is
        only true while the block lands in the table the DM rule reads."""
        r = self.client.post(reverse("groupz-member", args=["blocked", "add"]),
                             {"username": "stranger"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(Block.objects.filter(blocker=self.me, blocked=self.stranger).exists())
        self.assertIn(self.stranger.id, blocked_user_ids(self.me))

    def test_blocking_a_friend_drops_the_follow_both_ways(self):
        """Otherwise they stay listed under FriendZ on the same screen that
        says they're blocked."""
        self.client.post(reverse("groupz-member", args=["blocked", "add"]),
                         {"username": "mutual"}, format="json")
        self.assertFalse(Follow.objects.filter(follower=self.me, following=self.mutual).exists())
        self.assertFalse(Follow.objects.filter(follower=self.mutual, following=self.me).exists())
        by, _ = self._get()
        self.assertEqual([], by["friends"]["members"])
        self.assertEqual(["mutual"], by["blocked"]["members"])

    def test_unblock(self):
        self.client.post(reverse("groupz-member", args=["blocked", "add"]),
                         {"username": "stranger"}, format="json")
        self.client.post(reverse("groupz-member", args=["blocked", "remove"]),
                         {"username": "stranger"}, format="json")
        self.assertFalse(Block.objects.filter(blocker=self.me).exists())

    def test_custom_group_create_add_remove(self):
        r = self.client.post(reverse("groupz"), {"kind": "custom", "title": "Horn section"},
                             format="json")
        self.assertEqual(r.status_code, 201)
        gid = r.data["id"]

        self.client.post(reverse("groupz-member", args=[gid, "add"]),
                         {"username": "@stranger"}, format="json")   # leading @ tolerated
        by, _ = self._get()
        self.assertEqual(["stranger"], by[gid]["members"])
        self.assertTrue(by[gid]["can_add"])

        self.client.post(reverse("groupz-member", args=[gid, "remove"]),
                         {"username": "stranger"}, format="json")
        by, _ = self._get()
        self.assertEqual([], by[gid]["members"])

    def test_custom_needs_a_name_and_wont_duplicate(self):
        self.assertEqual(400, self.client.post(
            reverse("groupz"), {"kind": "custom", "title": "  "}, format="json").status_code)
        self.client.post(reverse("groupz"), {"kind": "custom", "title": "Crew"}, format="json")
        again = self.client.post(reverse("groupz"), {"kind": "custom", "title": "crew"},
                                 format="json")
        self.assertEqual(400, again.status_code)

    def test_partners_is_one_group_not_many(self):
        self.client.post(reverse("groupz"), {"kind": "partners"}, format="json")
        self.client.post(reverse("groupz"), {"kind": "partners"}, format="json")
        self.assertEqual(1, MemberGroup.objects.filter(owner=self.me, kind="partners").count())

    def test_creating_a_derived_kind_is_refused(self):
        for kind in ("friends", "fans", "blocked"):
            r = self.client.post(reverse("groupz"), {"kind": kind}, format="json")
            self.assertEqual(400, r.status_code, kind)

    def test_cannot_touch_somebody_elses_group(self):
        theirs = MemberGroup.objects.create(owner=self.stranger, kind="custom", title="Theirs")
        r = self.client.post(reverse("groupz-member", args=[theirs.id, "add"]),
                             {"username": "fan"}, format="json")
        self.assertEqual(404, r.status_code)
        self.assertFalse(MemberGroupMember.objects.filter(group=theirs).exists())

    def test_cannot_add_yourself(self):
        r = self.client.post(reverse("groupz"), {"kind": "custom", "title": "Solo"},
                             format="json")
        r2 = self.client.post(reverse("groupz-member", args=[r.data["id"], "add"]),
                              {"username": "me"}, format="json")
        self.assertEqual(400, r2.status_code)

    def test_unknown_member_is_named(self):
        r = self.client.post(reverse("groupz"), {"kind": "custom", "title": "X"}, format="json")
        r2 = self.client.post(reverse("groupz-member", args=[r.data["id"], "add"]),
                              {"username": "nobody"}, format="json")
        self.assertEqual(400, r2.status_code)
        self.assertIn("nobody", r2.data["detail"])

    def test_requires_auth(self):
        self.client.force_authenticate(None)
        self.assertEqual(401, self.client.get(reverse("groupz")).status_code)

    def test_a_member_with_no_membership_row_still_gets_the_tab(self):
        """The dullest test here, and the one that would have caught it.

        The tier ladder for custom groups is read on every GET. Reading it as
        `user.membership.tier` raises for anybody whose Membership row has
        never been made — which is every account that has not yet touched a
        tiered surface — so the whole tab answered 500 for exactly the newest
        members. `membership_for()` makes the row instead.

        `self.me` deliberately has no Membership; asserting 200 and a free
        ladder is what pins the accessor.
        """
        from .models import Membership, TIER_FREE
        self.assertFalse(Membership.objects.filter(user=self.me).exists())

        r = self.client.get(reverse("groupz"))
        self.assertEqual(200, r.status_code)
        self.assertEqual(CUSTOM_GROUP_LIMITS[TIER_FREE], r.data["tier_limit"]["limit"])
        self.assertEqual(0, r.data["tier_limit"]["current"])

    def test_the_five_stay_under_groups_so_a_client_keeps_working(self):
        """`groups` and `tier_limit` are both required keys.

        The response used to BE the list. It grew an envelope so the ladder
        could travel with it, and an endpoint may grow keys but never lose
        one — the screen reading this deploys separately, so a renamed key
        blanks a live tab for as long as the frontend takes to follow.
        """
        r = self.client.get(reverse("groupz"))
        self.assertIn("groups", r.data)
        self.assertIn("tier_limit", r.data)
        self.assertEqual({"kind", "limit", "current"}, set(r.data["tier_limit"]))
