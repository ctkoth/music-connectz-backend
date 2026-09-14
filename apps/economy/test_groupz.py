"""GroupZ, and the three kinds it deliberately does NOT store.

`GroupZ.jsx` had been calling `/api/groupz/` since it was written and getting a
404, so the tab sat on a spinner for its whole life. The obvious fix is five
tables, and it would have been wrong: three of the five kinds are things this
platform already answers, and a second store would drift from the first.

The dangerous one is Blocked. A member reads "Blocked" on this tab and expects
the block to be real — if GroupZ kept its own list, the person they blocked
would keep DMing them, because MessageZ reads `Block` and would never have
heard about it. Most of the tests below are that: writing here writes THERE,
and the other surfaces see it.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Block, Follow, Group, GroupMember, blocked_user_ids

User = get_user_model()


def member(name):
    return User.objects.create_user(name, f"{name}@mcz.test", "pw12345!")


class BoardTests(TestCase):
    def setUp(self):
        self.me = member("me")
        self.c = APIClient()
        self.c.force_authenticate(self.me)

    def kinds(self):
        return [g["kind"] for g in self.c.get("/api/groupz/").data]

    def group(self, kind):
        return next(g for g in self.c.get("/api/groupz/").data if g["kind"] == kind)

    def test_the_derived_four_always_exist(self):
        """There is nothing to create — the thing they read from is always
        there, so a brand-new member opens the tab to a working board."""
        for k in ("friends", "fans", "partners", "blocked"):
            self.assertIn(k, self.kinds())

    def test_friends_are_mutual_follows(self):
        """`Follow`'s own docstring, served rather than restated."""
        mutual, oneway = member("mutual"), member("oneway")
        Follow.objects.create(follower=self.me, following=mutual)
        Follow.objects.create(follower=mutual, following=self.me)
        Follow.objects.create(follower=oneway, following=self.me)
        self.assertEqual(self.group("friends")["members"], ["mutual"])

    def test_fans_follow_you_and_you_do_not_follow_back(self):
        fan, friend = member("fan"), member("friend")
        Follow.objects.create(follower=fan, following=self.me)
        Follow.objects.create(follower=friend, following=self.me)
        Follow.objects.create(follower=self.me, following=friend)
        self.assertEqual(self.group("fans")["members"], ["fan"])

    def test_blocked_shows_who_YOU_blocked_not_who_blocked_you(self):
        """`blocked_user_ids` returns both directions, which is right for
        hiding content and wrong for a list somebody is meant to edit — you
        cannot unblock somebody who blocked you."""
        mine, theirs = member("mine"), member("theirs")
        Block.objects.create(blocker=self.me, blocked=mine)
        Block.objects.create(blocker=theirs, blocked=self.me)
        self.assertEqual(self.group("blocked")["members"], ["mine"])

    def test_a_group_is_local_to_its_owner(self):
        """The blueprint's word. Being in somebody's Partners list is a note
        they made about you, not a fact about you."""
        other = member("other")
        self.c.post("/api/groupz/", {"kind": "partners"}, format="json")
        gid = self.group("partners")["id"]
        self.c.post(f"/api/groupz/{gid}/add/", {"username": "other"}, format="json")

        theirs = APIClient()
        theirs.force_authenticate(other)
        self.assertEqual([g for g in theirs.get("/api/groupz/").data if not g["derived"]], [])


class WritingGoesToTheRealStoreTests(TestCase):
    """The whole design in five tests: this tab is a router, not a store."""

    def setUp(self):
        self.me = member("owner")
        self.them = member("them")
        self.c = APIClient()
        self.c.force_authenticate(self.me)

    def test_blocking_here_is_a_real_block_everywhere(self):
        r = self.c.post("/api/groupz/blocked/add/", {"username": "them"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(Block.objects.filter(blocker=self.me, blocked=self.them).exists())
        # The thing MessageZ, BattleZ and PlaylistZ all read.
        self.assertIn(self.them.pk, blocked_user_ids(self.me))

    def test_a_blocked_member_cannot_message_you(self):
        """The claim the tab makes, checked against the endpoint that honours
        it rather than against our own table."""
        self.c.post("/api/groupz/blocked/add/", {"username": "them"}, format="json")
        theirs = APIClient()
        theirs.force_authenticate(self.them)
        r = theirs.post("/api/economy/messages/", {"to": "owner", "body": "hi"}, format="json")
        self.assertEqual(r.status_code, 403, r.content[:200])

    def test_blocking_drops_the_follow_both_ways(self):
        """Leaving the follow in place is the tab saying one thing and the feed
        doing another."""
        Follow.objects.create(follower=self.me, following=self.them)
        Follow.objects.create(follower=self.them, following=self.me)
        self.c.post("/api/groupz/blocked/add/", {"username": "them"}, format="json")
        self.assertFalse(Follow.objects.filter(follower=self.me, following=self.them).exists())
        self.assertFalse(Follow.objects.filter(follower=self.them, following=self.me).exists())

    def test_unblocking_here_unblocks_everywhere(self):
        Block.objects.create(blocker=self.me, blocked=self.them)
        self.c.post("/api/groupz/blocked/remove/", {"username": "them"}, format="json")
        self.assertFalse(Block.objects.filter(blocker=self.me, blocked=self.them).exists())

    def test_adding_a_friend_follows_them(self):
        self.c.post("/api/groupz/friends/add/", {"username": "them"}, format="json")
        self.assertTrue(Follow.objects.filter(follower=self.me, following=self.them).exists())

    def test_it_does_not_claim_a_friendship_nobody_agreed_to(self):
        """Following somebody is all you can do on your own. Whether that makes
        you friends is up to them, and the response says which happened."""
        r = self.c.post("/api/groupz/friends/add/", {"username": "them"}, format="json")
        self.assertIn("follow back", r.data["detail"])
        self.assertNotIn("them", r.data["groups"][0]["members"])   # friends is first

        Follow.objects.create(follower=self.them, following=self.me)
        r = self.c.post("/api/groupz/friends/add/", {"username": "them"}, format="json")
        self.assertIn("friends", r.data["detail"])


class FanZIsNotYoursToEditTests(TestCase):
    def setUp(self):
        self.me = member("star")
        self.them = member("nobody")
        self.c = APIClient()
        self.c.force_authenticate(self.me)

    def test_you_cannot_add_your_own_fans(self):
        """A member who can type their own fan list has a follower count that
        means nothing — the substance rule with a social graph attached."""
        r = self.c.post("/api/groupz/fans/add/", {"username": "nobody"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("by following you", r.data["detail"])
        self.assertFalse(Follow.objects.filter(following=self.me).exists())

    def test_it_says_what_to_do_instead(self):
        """A refusal with nowhere to go is the dead end the cross-pollination
        rule exists to close."""
        r = self.c.post("/api/groupz/fans/add/", {"username": "nobody"}, format="json")
        self.assertIn("FriendZ", r.data["detail"])


class OwnedGroupTests(TestCase):
    def setUp(self):
        self.me = member("curator")
        self.them = member("mate")
        self.c = APIClient()
        self.c.force_authenticate(self.me)

    def test_partners_cannot_be_created_as_a_list(self):
        """It is derived from finished collabs now — a stored one would be the
        thing it replaced."""
        r = self.c.post("/api/groupz/", {"kind": "partners"}, format="json")
        self.assertEqual(r.status_code, 200)   # a derived kind already exists
        self.assertEqual(Group.objects.filter(owner=self.me, kind="partners").count(), 0)

    def test_custom_groups_need_a_name_and_there_can_be_many(self):
        self.assertEqual(self.c.post("/api/groupz/", {"kind": "custom"}, format="json").status_code, 400)
        for t in ("Tour band", "Mix notes"):
            self.c.post("/api/groupz/", {"kind": "custom", "title": t}, format="json")
        self.assertEqual(Group.objects.filter(owner=self.me, kind="custom").count(), 2)

    def test_members_add_and_remove(self):
        self.c.post("/api/groupz/", {"kind": "custom", "title": "crew"}, format="json")
        gid = next(g["id"] for g in self.c.get("/api/groupz/").data if g["kind"] == "custom")
        self.c.post(f"/api/groupz/{gid}/add/", {"username": "mate"}, format="json")
        self.assertEqual(GroupMember.objects.filter(group_id=int(gid)).count(), 1)
        self.c.post(f"/api/groupz/{gid}/remove/", {"username": "mate"}, format="json")
        self.assertEqual(GroupMember.objects.filter(group_id=int(gid)).count(), 0)

    def test_adding_twice_is_not_two_rows(self):
        self.c.post("/api/groupz/", {"kind": "custom", "title": "crew"}, format="json")
        gid = next(g["id"] for g in self.c.get("/api/groupz/").data if g["kind"] == "custom")
        for _ in range(3):
            self.c.post(f"/api/groupz/{gid}/add/", {"username": "mate"}, format="json")
        self.assertEqual(GroupMember.objects.filter(group_id=int(gid)).count(), 1)

    def test_a_blocked_member_cannot_be_added_to_a_group(self):
        Block.objects.create(blocker=self.me, blocked=self.them)
        self.c.post("/api/groupz/", {"kind": "custom", "title": "crew"}, format="json")
        gid = next(g["id"] for g in self.c.get("/api/groupz/").data if g["kind"] == "custom")
        r = self.c.post(f"/api/groupz/{gid}/add/", {"username": "mate"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertIn("Unblock", r.data["detail"])

    def test_you_cannot_edit_somebody_elses_group(self):
        theirs = Group.objects.create(owner=self.them, kind="custom", title="not yours")
        r = self.c.post(f"/api/groupz/{theirs.pk}/add/", {"username": "mate"}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_the_derived_four_cannot_be_deleted(self):
        """A 404 would be untrue of a list the member is looking at."""
        for k in ("friends", "fans", "partners", "blocked"):
            r = self.c.delete(f"/api/groupz/{k}/")
            self.assertEqual(r.status_code, 400, k)
            self.assertIn("aren't lists you can delete", r.data["detail"])

    def test_a_custom_group_can_be_deleted(self):
        self.c.post("/api/groupz/", {"kind": "custom", "title": "gone"}, format="json")
        gid = next(g["id"] for g in self.c.get("/api/groupz/").data if g["kind"] == "custom")
        self.assertEqual(self.c.delete(f"/api/groupz/{gid}/").status_code, 200)
        self.assertFalse(Group.objects.filter(owner=self.me, kind="custom").exists())


class EdgeTests(TestCase):
    def setUp(self):
        self.me = member("edge")
        self.c = APIClient()
        self.c.force_authenticate(self.me)

    def test_you_cannot_put_yourself_in_your_own_group(self):
        r = self.c.post("/api/groupz/friends/add/", {"username": "edge"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_an_unknown_member_says_so(self):
        r = self.c.post("/api/groupz/friends/add/", {"username": "ghost"}, format="json")
        self.assertEqual(r.status_code, 404)
        self.assertIn("ghost", r.data["detail"])

    def test_it_needs_an_account(self):
        self.assertEqual(APIClient().get("/api/groupz/").status_code, 401)

    def test_the_board_does_not_grow_a_query_per_member(self):
        """Five groups on one screen must not be five round trips per group."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        def count_for(n):
            Follow.objects.all().delete()
            for i in range(n):
                u = member(f"f{n}x{i}")
                Follow.objects.create(follower=self.me, following=u)
                Follow.objects.create(follower=u, following=self.me)
            with CaptureQueriesContext(connection) as ctx:
                self.c.get("/api/groupz/")
            return len(ctx.captured_queries)

        few, many = count_for(2), count_for(20)
        self.assertEqual(few, many,
                         f"{few} queries for 2 friends but {many} for 20 — per-member read")


class PartnerZIsEarnedTests(TestCase):
    """PartnerZ comes from finished work, not from a checkbox.

    "Intend to work with frequently" was typed, so the list said what somebody
    HOPED. Three released collabs is a thing neither side can fake alone: the
    other person agreed three times and escrow settled three times. That is the
    substance rule applied to a friendship.
    """

    def setUp(self):
        from . import groupz
        self.G = groupz
        self.me = member("worker")
        self.mate = member("mate")
        self.c = APIClient()
        self.c.force_authenticate(self.me)

    def _friends(self, other):
        Follow.objects.create(follower=self.me, following=other)
        Follow.objects.create(follower=other, following=self.me)

    def _collabs(self, other, n):
        from .models import CollabDeal
        for i in range(n):
            CollabDeal.objects.create(
                initiator=self.me, status=CollabDeal.STATUS_RELEASED,
                title=f"deal {i}",
                participants=[{"username": self.me.username}, {"username": other.username}])

    def partners(self):
        return next(g for g in self.c.get("/api/groupz/").data if g["kind"] == "partners")["members"]

    def test_a_friend_becomes_a_partner_at_the_threshold(self):
        self._friends(self.mate)
        self._collabs(self.mate, self.G.PARTNER_COLLABS - 1)
        self.assertEqual(self.partners(), [])
        self._collabs(self.mate, 1)
        self.assertEqual(self.partners(), ["mate"])

    def test_collabs_without_friendship_are_not_a_partnership(self):
        """Corey's rule: partners come from FriendZ. It also means the two of
        you follow each other, so a partnership is never a surprise to one
        side."""
        self._collabs(self.mate, self.G.PARTNER_COLLABS + 2)
        self.assertEqual(self.partners(), [])

    def test_only_released_deals_count(self):
        """A draft nobody funded is an intention; a funded one that never paid
        out is an argument."""
        from .models import CollabDeal
        self._friends(self.mate)
        for st in (CollabDeal.STATUS_DRAFT, CollabDeal.STATUS_FUNDED, CollabDeal.STATUS_REFUNDED):
            for _ in range(self.G.PARTNER_COLLABS):
                CollabDeal.objects.create(
                    initiator=self.me, status=st, title="x",
                    participants=[{"username": self.me.username},
                                  {"username": self.mate.username}])
        self.assertEqual(self.partners(), [])

    def test_somebody_elses_deals_do_not_count(self):
        """Two other people finishing three collabs must not make either of
        them YOUR partner."""
        from .models import CollabDeal
        a, b = member("aaa"), member("bbb")
        self._friends(a)
        for _ in range(self.G.PARTNER_COLLABS):
            CollabDeal.objects.create(initiator=a, status=CollabDeal.STATUS_RELEASED, title="x",
                                      participants=[{"username": "aaa"}, {"username": "bbb"}])
        self.assertEqual(self.partners(), [])

    def test_it_counts_deals_you_did_not_start(self):
        """Being brought onto somebody else's deal is still finishing work
        together."""
        from .models import CollabDeal
        self._friends(self.mate)
        for _ in range(self.G.PARTNER_COLLABS):
            CollabDeal.objects.create(
                initiator=self.mate, status=CollabDeal.STATUS_RELEASED, title="x",
                participants=[{"username": self.mate.username}, {"username": self.me.username}])
        self.assertEqual(self.partners(), ["mate"])

    def test_you_cannot_add_a_partner_and_it_says_how_far_off_you_are(self):
        """A refusal that also answers "then how?" — the number is the point."""
        self._friends(self.mate)
        self._collabs(self.mate, 1)
        r = self.c.post("/api/groupz/partners/add/", {"username": "mate"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("earned, not added", r.data["detail"])
        self.assertIn("finished 1 collab", r.data["detail"])
        self.assertIn(str(self.G.PARTNER_COLLABS), r.data["detail"])

    def test_the_note_states_the_rule(self):
        note = next(g for g in self.c.get("/api/groupz/").data
                    if g["kind"] == "partners")["note"]
        self.assertIn(str(self.G.PARTNER_COLLABS), note)
        self.assertIn("Earned, not added", note)

    def test_the_board_does_not_grow_a_query_per_collab(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from .models import CollabDeal

        def count_for(n):
            CollabDeal.objects.all().delete()
            for i in range(n):
                CollabDeal.objects.create(
                    initiator=self.me, status=CollabDeal.STATUS_RELEASED, title=f"d{i}",
                    participants=[{"username": self.me.username},
                                  {"username": self.mate.username}])
            with CaptureQueriesContext(connection) as ctx:
                self.c.get("/api/groupz/")
            return len(ctx.captured_queries)

        self._friends(self.mate)
        few, many = count_for(3), count_for(30)
        self.assertEqual(few, many, f"{few} queries for 3 deals but {many} for 30")
