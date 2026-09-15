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
        """Many, up to the tier's ceiling — which is 1 on Free, so this takes
        a tier that keeps more. The cap is `custom_groups` in catalog.py."""
        from .models import TIER_PREMIUM, membership_for
        m = membership_for(self.me)
        m.tier = TIER_PREMIUM
        m.save(update_fields=["tier", "updated_at"])

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
    HOPED. A settled work is a thing neither side can fake alone: the other
    person had to agree, and something outside the two of them had to settle —
    escrow paying out, or a room deciding a battle. That is the substance rule
    applied to a friendship.
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

    def _release(self, payer, payee, n=1, cents=1000):
        """n deals that actually settled — through `release_deal`, not by
        typing the status on, because the tally is written by the release."""
        from .collab import release_deal
        from .models import CollabDeal
        for i in range(n):
            d = CollabDeal.objects.create(
                initiator=payer, status=CollabDeal.STATUS_FUNDED,
                title=f"deal {i}", held_cents=cents,
                participants=[
                    {"username": payer.username, "pays_cents": cents, "funded": True},
                    {"username": payee.username, "receives_cents": cents},
                ])
            release_deal(d)

    def _empty_release(self, other, n=1):
        """Deals nobody funded, released by the auto path. Free to make."""
        from .collab import release_deal
        from .models import CollabDeal
        for i in range(n):
            d = CollabDeal.objects.create(
                initiator=self.me, status=CollabDeal.STATUS_FUNDED, title=f"free {i}",
                participants=[{"username": self.me.username},
                              {"username": other.username}])
            release_deal(d)

    def partners(self):
        return next(g for g in self.c.get("/api/groupz/").data if g["kind"] == "partners")["members"]

    def test_a_friend_becomes_a_partner_at_the_threshold(self):
        self._friends(self.mate)
        self._release(self.me, self.mate, self.G.PARTNER_WORKS - 1)
        self.assertEqual(self.partners(), [])
        self._release(self.me, self.mate, 1)
        self.assertEqual(self.partners(), ["mate"])

    def test_collabs_without_friendship_are_not_a_partnership(self):
        """Corey's rule: partners come from FriendZ. It also means the two of
        you follow each other, so a partnership is never a surprise to one
        side."""
        self._release(self.me, self.mate, self.G.PARTNER_WORKS + 2)
        self.assertEqual(self.partners(), [])

    def test_a_deal_that_held_nothing_does_not_count(self):
        """The hole this rule exists for.

        `payers()` is empty when nobody pays, so `all_funded()` is `all([])`
        — one Fund call flips an empty deal to FUNDED and `maybe_auto_release`
        releases it on its own. Three of those cost nothing and took no work,
        so PartnerZ would be free and the benefit hanging off it would be free
        with it.
        """
        self._friends(self.mate)
        self._empty_release(self.mate, self.G.PARTNER_WORKS + 5)
        self.assertEqual(self.partners(), [])

    def test_only_released_deals_count(self):
        """A draft nobody funded is an intention; a funded one that never paid
        out is an argument."""
        from .models import CollabDeal
        self._friends(self.mate)
        for st in (CollabDeal.STATUS_DRAFT, CollabDeal.STATUS_FUNDED, CollabDeal.STATUS_REFUNDED):
            for _ in range(self.G.PARTNER_WORKS):
                CollabDeal.objects.create(
                    initiator=self.me, status=st, title="x", held_cents=1000,
                    participants=[{"username": self.me.username, "pays_cents": 1000},
                                  {"username": self.mate.username, "receives_cents": 1000}])
        self.assertEqual(self.partners(), [])

    def test_somebody_elses_deals_do_not_count(self):
        """Two other people finishing three collabs must not make either of
        them YOUR partner."""
        a, b = member("aaa"), member("bbb")
        self._friends(a)
        self._release(a, b, self.G.PARTNER_WORKS)
        self.assertEqual(self.partners(), [])

    def test_it_counts_deals_you_did_not_start(self):
        """Being brought onto somebody else's deal is still finishing work
        together."""
        self._friends(self.mate)
        self._release(self.mate, self.me, self.G.PARTNER_WORKS)
        self.assertEqual(self.partners(), ["mate"])

    def test_you_cannot_add_a_partner_and_it_says_how_far_off_you_are(self):
        """A refusal that also answers "then how?" — the number is the point."""
        self._friends(self.mate)
        self._release(self.me, self.mate, 1)
        r = self.c.post("/api/groupz/partners/add/", {"username": "mate"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("earned, not added", r.data["detail"])
        self.assertIn("finished 1 work", r.data["detail"])
        self.assertIn(str(self.G.PARTNER_WORKS), r.data["detail"])

    def test_the_note_states_the_rule_and_what_it_is_worth(self):
        note = next(g for g in self.c.get("/api/groupz/").data
                    if g["kind"] == "partners")["note"]
        self.assertIn(str(self.G.PARTNER_WORKS), note)
        self.assertIn("Earned, not added", note)
        # The gain half of the cost/gain rule: a benefit nobody is told about
        # changes nobody's behaviour.
        self.assertIn(str(self.G.PARTNER_ESCROW_DAYS_OFF), note)

    def test_the_board_does_not_grow_a_query_per_collab(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from .models import Partnership

        def count_for(n):
            Partnership.objects.all().delete()
            self.G.note_work([self.me.pk, self.mate.pk], collabs=n)
            for i in range(n):
                other = member(f"extra{n}_{i}")
                self.G.note_work([self.me.pk, other.pk], collabs=1)
            with CaptureQueriesContext(connection) as ctx:
                self.c.get("/api/groupz/")
            return len(ctx.captured_queries)

        self._friends(self.mate)
        few, many = count_for(3), count_for(30)
        self.assertEqual(few, many, f"{few} queries for 3 partnerships but {many} for 30")


class PartnerZCountsBattlesTests(TestCase):
    """A battle the room decided is work two people finished together.

    Corey asked for battles alongside collabs, and the reason it is safe is
    the same reason a funded collab is: a WINNER means at least one side
    cleared BATTLE_MIN_RATINGS judges, so somebody who is not one of the two
    of them had to turn up. A draw means nobody rated it, and a battle nobody
    watched is not a working relationship.
    """

    def setUp(self):
        from . import groupz
        self.G = groupz
        self.me = member("mc")
        self.mate = member("rival")
        Follow.objects.create(follower=self.me, following=self.mate)
        Follow.objects.create(follower=self.mate, following=self.me)
        self.c = APIClient()
        self.c.force_authenticate(self.me)

    def _battle(self, *, decided):
        from .battlez import settle_battle
        from .models import Battle, BattleEntry, ItemRating
        b = Battle.objects.create(host=self.me, opponent=self.mate, title="round",
                                  mode=Battle.MODE_1V1, status=Battle.STATUS_OPEN)
        for u in (self.me, self.mate):
            BattleEntry.objects.create(battle=b, user=u, title=u.username)
        if decided:
            from .battlez import BATTLE_MIN_RATINGS
            entry = b.entries.filter(user=self.me).first()
            for i in range(BATTLE_MIN_RATINGS):
                ItemRating.objects.create(item_id=entry.item_key,
                                          user=member(f"judge{b.pk}_{i}"), score=9)
        return settle_battle(b)

    def partners(self):
        return next(g for g in self.c.get("/api/groupz/").data if g["kind"] == "partners")["members"]

    def test_decided_battles_make_partners(self):
        for _ in range(self.G.PARTNER_WORKS):
            b = self._battle(decided=True)
            self.assertIsNotNone(b.winner_id)
        self.assertEqual(self.partners(), ["rival"])

    def test_a_draw_nobody_judged_counts_for_nothing(self):
        for _ in range(self.G.PARTNER_WORKS + 3):
            b = self._battle(decided=False)
            self.assertIsNone(b.winner_id)
        self.assertEqual(self.partners(), [])

    def test_battles_and_collabs_add_up_to_the_same_threshold(self):
        """Three works, not three of each. A battle and two collabs is a
        working relationship by any reading."""
        from .collab import release_deal
        from .models import CollabDeal
        self._battle(decided=True)
        for i in range(self.G.PARTNER_WORKS - 1):
            release_deal(CollabDeal.objects.create(
                initiator=self.me, status=CollabDeal.STATUS_FUNDED,
                title=f"d{i}", held_cents=500,
                participants=[{"username": "mc", "pays_cents": 500, "funded": True},
                              {"username": "rival", "receives_cents": 500}]))
        self.assertEqual(self.partners(), ["rival"])
        row = self.G.works_with(self.me)["rival"]
        self.assertEqual((row["collabs"], row["battles"]), (self.G.PARTNER_WORKS - 1, 1))


class PartnerZEscrowBenefitTests(TestCase):
    """The one thing PartnerZ is worth, and why it is this and not a payout.

    A per-day 🍥 for HOLDING the status would pay a fixed past achievement
    forever — the substance rule inverted, and an annuity behind a gate you
    pass once. This benefit is worth nothing to somebody faking it: a faker
    owns both wallets, so their own money reaching their own other account
    sooner is worth exactly zero. It only pays when two genuinely separate
    people work together AGAIN.
    """

    def setUp(self):
        from django.conf import settings
        from . import groupz
        from .collab import deal_dict, escrow_release_days
        self.G = groupz
        self.days = escrow_release_days
        self.deal_dict = deal_dict
        self.base = settings.ESCROW_AUTO_RELEASE_DAYS
        self.floor = settings.ESCROW_MIN_RELEASE_DAYS
        self.payer = member("payer")
        self.payee = member("payee")

    def _deal(self, payer=None, payee=None, cents=1000):
        from .models import CollabDeal
        payer, payee = payer or self.payer, payee or self.payee
        return CollabDeal.objects.create(
            initiator=payer, status=CollabDeal.STATUS_FUNDED, title="x", held_cents=cents,
            participants=[{"username": payer.username, "pays_cents": cents, "funded": True},
                          {"username": payee.username, "receives_cents": cents}])

    def _partner(self, a, b):
        self.G.note_work([a.pk, b.pk], collabs=self.G.PARTNER_WORKS)

    def test_strangers_get_the_full_window(self):
        self.assertEqual(self.days(self._deal()), self.base)

    def test_partners_release_sooner(self):
        self._partner(self.payer, self.payee)
        self.assertEqual(self.days(self._deal()),
                         max(self.floor, self.base - self.G.PARTNER_ESCROW_DAYS_OFF))

    def test_it_never_goes_under_the_floor(self):
        self._partner(self.payer, self.payee)
        self.assertGreaterEqual(self.days(self._deal()), self.floor)

    def test_one_payer_who_is_not_a_partner_holds_the_window(self):
        """The same narrowness the Patron badge has: the window is each
        PAYER'S own protection, so a payer who has not earned the shortening
        does not have it spent on their behalf."""
        from .models import CollabDeal
        other = member("copayer")
        self._partner(self.payer, self.payee)
        d = CollabDeal.objects.create(
            initiator=self.payer, status=CollabDeal.STATUS_FUNDED, title="x", held_cents=2000,
            participants=[{"username": "payer", "pays_cents": 1000, "funded": True},
                          {"username": "copayer", "pays_cents": 1000, "funded": True},
                          {"username": "payee", "receives_cents": 2000}])
        self.assertEqual(self.days(d), self.base)

    def test_a_payee_who_is_not_a_partner_holds_the_window(self):
        from .models import CollabDeal
        member("stranger")
        self._partner(self.payer, self.payee)
        d = CollabDeal.objects.create(
            initiator=self.payer, status=CollabDeal.STATUS_FUNDED, title="x", held_cents=2000,
            participants=[{"username": "payer", "pays_cents": 2000, "funded": True},
                          {"username": "payee", "receives_cents": 1000},
                          {"username": "stranger", "receives_cents": 1000}])
        self.assertEqual(self.days(d), self.base)

    def test_the_card_says_why_it_is_shorter(self):
        """A shortened window with no reason on it reads as a bug, and a
        benefit nobody can see arrive changes nobody's behaviour."""
        self.assertFalse(self.deal_dict(self._deal(), self.payer)["auto_release_partnerz"])
        self._partner(self.payer, self.payee)
        row = self.deal_dict(self._deal(), self.payer)
        self.assertTrue(row["auto_release_partnerz"])
        self.assertLess(row["auto_release_days"], row["auto_release_default_days"])

    def test_a_list_of_deals_does_not_re_ask_per_card(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        self._partner(self.payer, self.payee)
        deals = [self._deal() for _ in range(6)]
        cache = {}
        with CaptureQueriesContext(connection) as ctx:
            rows = [self.deal_dict(d, self.payer, cache) for d in deals]
        self.assertTrue(all(r["auto_release_partnerz"] for r in rows))
        self.assertLessEqual(len(ctx.captured_queries), 4,
                             f"{len(ctx.captured_queries)} queries for 6 deals — per-card read")


class RebuildPartnershipsTests(TestCase):
    """The tally is written by the settlement, so it can be wrong in two ways
    — a row that predates it, and an increment swallowed by an exception. The
    sweep is what makes both temporary."""

    def setUp(self):
        from . import groupz
        self.G = groupz
        self.a, self.b = member("aa"), member("bb")

    def test_dry_by_default(self):
        from django.core.management import call_command
        from .models import Partnership
        self.G.note_work([self.a.pk, self.b.pk], collabs=9)   # a tally with no events
        call_command("rebuild_partnerships")
        self.assertEqual(Partnership.objects.get().collabs, 9)

    def test_write_replaces_the_tally_with_the_events(self):
        from django.core.management import call_command
        from .models import Partnership
        self.G.note_work([self.a.pk, self.b.pk], collabs=9)
        call_command("rebuild_partnerships", "--write")
        # No released deal exists, so the honest answer is no partnership.
        self.assertFalse(Partnership.objects.exists())

    def test_it_recovers_a_tally_that_never_got_written(self):
        from django.core.management import call_command
        from .models import CollabDeal, Partnership
        for i in range(2):
            CollabDeal.objects.create(
                initiator=self.a, status=CollabDeal.STATUS_RELEASED, title=f"d{i}",
                participants=[{"username": "aa", "pays_cents": 100, "funded": True},
                              {"username": "bb", "receives_cents": 100}])
        self.assertFalse(Partnership.objects.exists())
        call_command("rebuild_partnerships", "--write")
        self.assertEqual(Partnership.objects.get().collabs, 2)


class AlmostPartnersTests(TestCase):
    """The `works` counter has been on Partnership since the tally replaced the
    scan, and every reader filtered `works__gte=PARTNER_WORKS` — so somebody one
    deal from a real benefit looked identical to somebody who had never worked
    with anyone. The number existed and nothing served it."""

    def setUp(self):
        from . import groupz as G
        self.G = G
        self.me = member("almost_me")
        self.c = APIClient()
        self.c.force_authenticate(self.me)

    def test_two_of_three_is_reported_with_what_is_left(self):
        mate = member("almost_mate")
        self.G.note_work([self.me.pk, mate.pk], collabs=2)
        rows = self.G.almost_partners(self.me)
        self.assertEqual(rows, [{"username": "almost_mate", "works": 2, "needs": 1}])

    def test_someone_already_partnered_is_not_in_it(self):
        """They have the benefit — the list is who hasn't got it yet."""
        mate = member("done_mate")
        self.G.note_work([self.me.pk, mate.pk], collabs=self.G.PARTNER_WORKS)
        self.assertEqual(self.G.almost_partners(self.me), [])

    def test_a_stranger_is_not_in_it(self):
        """Zero works is not progress — it would list everybody on the platform
        as almost a partner, which says nothing about anybody."""
        member("stranger")
        self.assertEqual(self.G.almost_partners(self.me), [])

    def test_closest_first(self):
        near, far = member("near_one"), member("far_one")
        self.G.note_work([self.me.pk, near.pk], collabs=2)
        self.G.note_work([self.me.pk, far.pk], collabs=1)
        self.assertEqual([r["username"] for r in self.G.almost_partners(self.me)],
                         ["near_one", "far_one"])

    def test_battles_count_toward_it_the_same_as_collabs(self):
        mate = member("battle_mate")
        self.G.note_work([self.me.pk, mate.pk], battles=2)
        self.assertEqual(self.G.almost_partners(self.me)[0]["needs"], 1)

    def test_it_rides_on_the_partners_row_beside_members(self):
        """Added beside `members`, never folded into it — the client is in the
        other repo and an endpoint may grow a key but never lose one."""
        mate = member("tab_mate")
        self.G.note_work([self.me.pk, mate.pk], collabs=2)
        row = next(r for r in self.c.get("/api/groupz/").data
                   if r["id"] == "partners")
        self.assertIn("members", row)
        self.assertEqual(row["almost"], [{"username": "tab_mate", "works": 2, "needs": 1}])

    def test_it_does_not_grow_a_query_per_person(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from .models import Partnership

        def count_for(n):
            Partnership.objects.all().delete()
            for i in range(n):
                self.G.note_work([self.me.pk, member(f"near{n}_{i}").pk], collabs=2)
            with CaptureQueriesContext(connection) as ctx:
                self.c.get("/api/groupz/")
            return len(ctx.captured_queries)

        self.assertLessEqual(count_for(20), count_for(2) + 2)


class CustomGroupLadderTests(TestCase):
    """How many custom groups a tier keeps, and who may put an icon on one.

    FriendZ, FanZ and PartnerZ are untouched by both: they are derived from
    Follow and from finished work, so capping them would be capping a fact
    rather than a feature."""

    def setUp(self):
        from . import groupz as G
        self.G = G
        self.me = member("cg")
        self.c = APIClient()
        self.c.force_authenticate(self.me)

    def _tier(self, t):
        from .models import membership_for
        m = membership_for(self.me)
        m.tier = t
        m.save(update_fields=["tier", "updated_at"])

    def _make(self, title, emoji=None):
        body = {"kind": "custom", "title": title}
        if emoji is not None:
            body["emoji"] = emoji
        return self.c.post("/api/groupz/", body, format="json")

    def test_free_gets_one_which_is_a_ladder_not_a_wall(self):
        from .catalog import limits_for
        from .models import TIER_FREE
        self.assertEqual(limits_for(TIER_FREE)["custom_groups"], 1)
        self.assertEqual(self._make("mine").status_code, 201)

    def test_the_ceiling_names_itself_and_says_what_lifts_it(self):
        self._make("one")
        r = self._make("two")
        self.assertEqual(r.status_code, 403, r.content)
        self.assertEqual(r.data["custom_groups"], 1)
        self.assertIn("tier up", r.data["detail"])
        # and it says the derived lists are not eating the allowance
        self.assertIn("PartnerZ", r.data["detail"])

    def test_it_ladders(self):
        from .catalog import limits_for
        from .models import TIER_FREE, TIER_PREMIUM, TIER_STATZ
        self.assertEqual(
            [limits_for(t)["custom_groups"] for t in (TIER_FREE, TIER_PREMIUM, TIER_STATZ)],
            [1, 5, 20])

    def test_premium_may_set_an_icon(self):
        from .models import TIER_PREMIUM, Group
        self._tier(TIER_PREMIUM)
        self.assertEqual(self._make("iconed", "🎧").status_code, 201)
        self.assertEqual(Group.objects.get(owner=self.me, title="iconed").emoji, "🎧")

    def test_free_still_gets_the_group_just_without_the_icon(self):
        """Decoration is dropped, never a refusal — failing the whole create
        over an icon would fail the thing they actually asked for."""
        from .models import Group
        self.assertEqual(self._make("plain", "🎧").status_code, 201)
        self.assertEqual(Group.objects.get(owner=self.me, title="plain").emoji, "")

    def test_the_derived_lists_do_not_count_toward_the_ceiling(self):
        self._make("one")                      # free ceiling now reached
        for kind in ("friends", "fans", "partners", "blocked"):
            r = self.c.post("/api/groupz/", {"kind": kind}, format="json")
            self.assertEqual(r.status_code, 200, f"{kind}: {r.content}")

    def test_the_board_carries_the_icon(self):
        from .models import TIER_PREMIUM
        self._tier(TIER_PREMIUM)
        self._make("shown", "🔥")
        row = next(g for g in self.c.get("/api/groupz/").data if g["title"] == "shown")
        self.assertEqual(row["emoji"], "🔥")

    def test_limits_publishes_the_ceiling_before_the_button(self):
        r = self.c.get("/api/economy/limits/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["custom_groups"], 1)
        self.assertEqual(r.data["custom_groups_used"], 0)
        self.assertFalse(r.data["can_set_emoji"])
