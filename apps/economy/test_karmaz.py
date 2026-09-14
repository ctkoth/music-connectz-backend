"""What rating, voting, commenting and answering a stranger pay — and every
place each one could become a faucet.

Nothing here tests that a reward lands; that is one line and it either works
or the wallet is visibly wrong. What is tested is the structure the whole
design rests on: **in every case the thing that triggers a payout is done by
somebody other than the person being paid.** Break that and each of these is
a mint, so each is pinned from the direction somebody trying to farm it would
come at it.

The six that matter:

  1. An upvote and a downvote pay the SAME. Pay more for up and the app buys
     its own praise; pay only for up and the down half of the signal is unused.
  2. Flipping a vote pays once. The `ref` is the comment, and the constraint
     is at the database rather than in a code path.
  3. A comment earns from OTHER PEOPLE'S votes, an hour later, once, and never
     on your own post.
  4. Nothing pays for SENDING a message. Two accounts messaging each other is
     the purest faucet available here.
  5. A cold reply pays both sides once per pair, for life.
  6. DupeZ vetoes all of it. It already decides what one person is.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import OAuthIdentity
from . import karmaz as K
from .models import (EngagementPayout, Message, Post, Reaction, SocialComment,
                     wallet_for)

User = get_user_model()


def member(name):
    return User.objects.create_user(name, f"{name}@mcz.test", "pw12345!")


def link_accounts(a, b, email="shared@mcz.test"):
    """The reachable STRONG DupeZ signal — the account email is unique at the
    database, so a shared linked sign-in is the only cross-email duplicate that
    can exist, and it is the case CLAUDE.md says Corey has."""
    for n, u in enumerate((a, b)):
        OAuthIdentity.objects.create(user=u, provider="google",
                                     provider_uid=f"uid-{u.pk}-{n}", email=email)


def comment(user, item="post:1", *, hours_ago=0):
    c = SocialComment.objects.create(user=user, item_id=item, body="a thought")
    if hours_ago:
        SocialComment.objects.filter(pk=c.pk).update(
            created_at=timezone.now() - timedelta(hours=hours_ago))
        c.refresh_from_db()
    return c


def upvotes(c, n, start=0):
    for i in range(n):
        Reaction.objects.create(user=member(f"voter{start}{i}"),
                                item_id=K.comment_key(c.pk), value=1)


class VoteTests(TestCase):
    def setUp(self):
        self.author = member("author")
        self.voter = member("voter")
        self.c = comment(self.author)

    def test_a_vote_pays_the_voter(self):
        out = K.vote_on_comment(self.voter, self.c, 1)
        self.assertEqual(out["energy"], K.VOTE_ENERGY)
        self.assertEqual(wallet_for(self.voter).energy, K.VOTE_ENERGY)

    def test_up_and_down_pay_exactly_the_same(self):
        """Load-bearing. Pay more for up and the platform is buying its own
        praise; pay only for up and the down half of the signal is unused."""
        up = K.vote_on_comment(self.voter, self.c, 1)["energy"]
        other = member("downer")
        down = K.vote_on_comment(other, comment(self.author, "post:2"), -1)["energy"]
        self.assertEqual(up, down)
        self.assertTrue(up)

    def test_flipping_a_vote_pays_once(self):
        """The ref is the COMMENT, so up-down-up collects exactly one ⚡ — and
        the guard is a unique constraint, not an if."""
        for v in (1, -1, 1, 0, -1):
            K.vote_on_comment(self.voter, self.c, v)
        self.assertEqual(wallet_for(self.voter).energy, K.VOTE_ENERGY)

    def test_clearing_a_vote_does_not_claw_it_back(self):
        K.vote_on_comment(self.voter, self.c, 1)
        K.vote_on_comment(self.voter, self.c, 0)
        self.assertEqual(wallet_for(self.voter).energy, K.VOTE_ENERGY)

    def test_voting_on_your_own_comment_pays_nothing(self):
        self.assertEqual(K.vote_on_comment(self.author, self.c, 1)["energy"], 0)
        self.assertEqual(wallet_for(self.author).energy, 0)

    def test_a_strongly_linked_account_is_paid_nothing(self):
        link_accounts(self.voter, self.author)
        self.assertEqual(K.vote_on_comment(self.voter, self.c, 1)["energy"], 0)

    def test_the_daily_cap_bites_and_says_so(self):
        for i in range(K.VOTE_DAILY_CAP):
            K.vote_on_comment(self.voter, comment(self.author, f"post:{i}"), 1)
        out = K.vote_on_comment(self.voter, comment(self.author, "post:99"), 1)
        self.assertTrue(out["capped"])
        self.assertEqual(out["energy"], 0)
        self.assertEqual(wallet_for(self.voter).energy, K.VOTE_DAILY_CAP * K.VOTE_ENERGY)

    def test_the_vote_still_registers_when_the_coin_is_capped(self):
        """The cap rations the reward, never the signal — a capped member's
        opinion still has to count or the karma stops meaning anything."""
        for i in range(K.VOTE_DAILY_CAP):
            K.vote_on_comment(self.voter, comment(self.author, f"post:{i}"), 1)
        c = comment(self.author, "post:99")
        K.vote_on_comment(self.voter, c, 1)
        self.assertEqual(K.karma_for(c.pk)[2], 1)


class CommentKarmaTests(TestCase):
    def setUp(self):
        self.author = member("writer")
        self.poster = member("poster")

    def test_it_does_not_settle_before_the_window(self):
        c = comment(self.author)
        upvotes(c, 5)
        self.assertIsNone(K.settle_comment(c))
        self.assertEqual(wallet_for(self.author).energy, 0)

    def test_after_the_window_it_pays_the_net_upvotes(self):
        c = comment(self.author, hours_ago=K.KARMA_SETTLE_HOURS + 1)
        upvotes(c, 4)
        out = K.settle_comment(c, post_author_id=self.poster.pk)
        self.assertEqual(out["energy"], 4 * K.KARMA_ENERGY_PER_NET)
        self.assertEqual(wallet_for(self.author).energy, 4)

    def test_it_is_capped(self):
        c = comment(self.author, hours_ago=K.KARMA_SETTLE_HOURS + 1)
        upvotes(c, K.KARMA_ENERGY_MAX + 20)
        out = K.settle_comment(c, post_author_id=self.poster.pk)
        self.assertEqual(out["energy"], K.KARMA_ENERGY_MAX)

    def test_one_friendly_upvote_is_not_a_judgement(self):
        c = comment(self.author, hours_ago=K.KARMA_SETTLE_HOURS + 1)
        upvotes(c, 1)
        out = K.settle_comment(c, post_author_id=self.poster.pk)
        self.assertEqual(out["energy"], 0)
        self.assertIn("net upvotes", out["why"])

    def test_a_downvoted_comment_earns_zero_never_negative(self):
        """Taking ⚡ off somebody for an unpopular opinion turns a quality
        signal into a punishment and teaches people to say nothing."""
        c = comment(self.author, hours_ago=K.KARMA_SETTLE_HOURS + 1)
        for i in range(4):
            Reaction.objects.create(user=member(f"d{i}"), item_id=K.comment_key(c.pk), value=-1)
        before = wallet_for(self.author).energy
        K.settle_comment(c, post_author_id=self.poster.pk)
        self.assertEqual(wallet_for(self.author).energy, before)

    def test_a_comment_on_your_own_post_earns_nothing(self):
        """The blueprint says "on another user's post" and means it."""
        c = comment(self.author, hours_ago=K.KARMA_SETTLE_HOURS + 1)
        upvotes(c, 6)
        out = K.settle_comment(c, post_author_id=self.author.pk)
        self.assertEqual(out["energy"], 0)
        self.assertEqual(out["why"], "your own post")

    def test_it_settles_once(self):
        c = comment(self.author, hours_ago=K.KARMA_SETTLE_HOURS + 1)
        upvotes(c, 4)
        K.settle_comment(c, post_author_id=self.poster.pk)
        upvotes(c, 6, start=9)
        self.assertIsNone(K.settle_comment(c, post_author_id=self.poster.pk))
        self.assertEqual(wallet_for(self.author).energy, 4)

    def test_settling_at_zero_is_still_settled(self):
        """Otherwise every read re-counts the votes on every old comment in
        the feed, for ever."""
        c = comment(self.author, hours_ago=K.KARMA_SETTLE_HOURS + 1)
        K.settle_comment(c, post_author_id=self.poster.pk)
        c.refresh_from_db()
        self.assertIsNotNone(c.karma_settled_at)
        self.assertFalse(K.due(c))

    def test_settle_visible_never_takes_a_feed_down(self):
        self.assertEqual(K.settle_visible([None, None]), 0)


class ColdMessageTests(TestCase):
    def setUp(self):
        self.a = member("cold")      # sends first
        self.b = member("warm")      # replies

    def _a_messages_b(self):
        Message.objects.create(sender=self.a, recipient=self.b, body="hi")

    def test_sending_pays_nothing(self):
        """The purest faucet available here: two accounts, forever."""
        self._a_messages_b()
        self.assertEqual(wallet_for(self.a).energy, 0)
        self.assertFalse(EngagementPayout.objects.exists())

    def test_replying_to_a_stranger_pays_both_sides(self):
        self._a_messages_b()
        out = K.cold_reply(self.b, self.a)
        self.assertEqual(out["reply"], K.COLD_REPLY_ENERGY)
        self.assertEqual(out["sent"], K.COLD_SENT_ENERGY)
        self.assertEqual(wallet_for(self.b).energy, K.COLD_REPLY_ENERGY)
        self.assertEqual(wallet_for(self.a).energy, K.COLD_SENT_ENERGY)

    def test_answering_is_worth_more_than_sending(self):
        """Making the cold message the better-paid side would be paying for
        outbound volume, which is a word for spam."""
        self.assertGreater(K.COLD_REPLY_ENERGY, K.COLD_SENT_ENERGY)

    def test_it_pays_once_per_pair_for_life(self):
        self._a_messages_b()
        K.cold_reply(self.b, self.a)
        Message.objects.create(sender=self.b, recipient=self.a, body="again")
        self.assertIsNone(K.cold_reply(self.b, self.a))
        self.assertEqual(wallet_for(self.b).energy, K.COLD_REPLY_ENERGY)

    def test_a_first_message_that_is_not_a_reply_pays_nothing(self):
        """Nobody messaged them, so there is nothing being answered."""
        self.assertIsNone(K.cold_reply(self.a, self.b))

    def test_a_strongly_linked_pair_is_paid_nothing(self):
        link_accounts(self.a, self.b)
        self._a_messages_b()
        self.assertIsNone(K.cold_reply(self.b, self.a))

    def test_you_cannot_reply_to_yourself(self):
        self.assertIsNone(K.cold_reply(self.a, self.a))

    def test_the_daily_cap_bites(self):
        for i in range(K.COLD_DAILY_CAP):
            other = member(f"stranger{i}")
            Message.objects.create(sender=other, recipient=self.b, body="hi")
            K.cold_reply(self.b, other)
        last = member("stranger_late")
        Message.objects.create(sender=last, recipient=self.b, body="hi")
        out = K.cold_reply(self.b, last)
        self.assertTrue(out["capped"])
        self.assertEqual(wallet_for(self.b).energy,
                         K.COLD_DAILY_CAP * K.COLD_REPLY_ENERGY)

    def test_one_side_being_capped_does_not_starve_the_other(self):
        """One member's busy day must not be the reason somebody else goes
        unpaid for being answered."""
        for i in range(K.COLD_DAILY_CAP):
            other = member(f"s{i}")
            Message.objects.create(sender=other, recipient=self.b, body="hi")
            K.cold_reply(self.b, other)
        self._a_messages_b()
        out = K.cold_reply(self.b, self.a)
        self.assertTrue(out["capped"])
        self.assertEqual(out["sent"], K.COLD_SENT_ENERGY)
        self.assertEqual(wallet_for(self.a).energy, K.COLD_SENT_ENERGY)


class RewardsTableTests(TestCase):
    def test_every_payer_is_published(self):
        keys = {r["key"] for r in K.rewards()}
        self.assertEqual(keys, {"rate", "vote", "comment_karma", "cold_reply", "cold_sent"})

    def test_the_table_carries_the_numbers_the_code_pays(self):
        by = {r["key"]: r for r in K.rewards()}
        self.assertEqual(by["vote"]["energy"], K.VOTE_ENERGY)
        self.assertEqual(by["cold_reply"]["energy"], K.COLD_REPLY_ENERGY)
        self.assertEqual(by["cold_sent"]["energy"], K.COLD_SENT_ENERGY)

    def test_the_rating_row_reads_the_rating_module(self):
        """One place, so the table cannot state a price RateZ won't pay."""
        from .models import RATING_REWARD_ENERGY
        by = {r["key"]: r for r in K.rewards()}
        self.assertEqual(by["rate"]["energy"], RATING_REWARD_ENERGY)


class ApiTests(TestCase):
    def setUp(self):
        self.me = member("apiuser")
        self.them = member("them")
        self.post = Post.objects.create(author=self.them, title="t", description="b")
        self.item = f"post:{self.post.pk}"
        self.c = SocialComment.objects.create(user=self.them, item_id=self.item, body="hi")
        self.client = APIClient()
        self.client.force_authenticate(self.me)

    def test_the_rewards_endpoint_states_the_caps(self):
        r = self.client.get("/api/economy/karmaz/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["today"]["vote_cap"], K.VOTE_DAILY_CAP)
        self.assertTrue(r.data["rewards"])

    def test_voting_a_comment_through_the_api_pays_and_returns_the_karma(self):
        r = self.client.post("/api/economy/social/react/",
                             {"item": self.item, "comment_id": self.c.pk, "value": 1},
                             format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["voted"]["energy"], K.VOTE_ENERGY)
        self.assertEqual(r.data["voted"]["net"], 1)

    def test_a_comment_carries_its_karma_and_my_vote(self):
        self.client.post("/api/economy/social/react/",
                         {"item": self.item, "comment_id": self.c.pk, "value": 1},
                         format="json")
        row = self.client.get(f"/api/economy/social/?item={self.item}").data["comments"][0]
        self.assertEqual(row["up"], 1)
        self.assertEqual(row["my_vote"], 1)
        # Not settled yet, so null rather than 0 — they mean different things.
        self.assertIsNone(row["karma_energy"])

    def test_reading_the_comments_settles_what_is_due(self):
        """The lazy settle, through the real endpoint. The commenter is a THIRD
        member on purpose: `self.c` is by the post's own author, and a comment
        on your own post earns nothing — a version of this test using it passed
        the endpoint and asserted a payout the rule correctly refuses."""
        guest = member("guest")
        c = SocialComment.objects.create(user=guest, item_id=self.item, body="good one")
        SocialComment.objects.filter(pk=c.pk).update(
            created_at=timezone.now() - timedelta(hours=K.KARMA_SETTLE_HOURS + 1))
        upvotes(c, 3)
        self.client.get(f"/api/economy/social/?item={self.item}")
        self.assertEqual(wallet_for(guest).energy, 3)

    def test_reading_does_not_pay_a_comment_on_the_readers_own_post(self):
        SocialComment.objects.filter(pk=self.c.pk).update(
            created_at=timezone.now() - timedelta(hours=K.KARMA_SETTLE_HOURS + 1))
        upvotes(self.c, 5)
        self.client.get(f"/api/economy/social/?item={self.item}")
        self.assertEqual(wallet_for(self.them).energy, 0)

    def test_a_vote_on_a_comment_that_is_not_on_this_item_is_refused(self):
        other = SocialComment.objects.create(user=self.them, item_id="post:999", body="x")
        r = self.client.post("/api/economy/social/react/",
                             {"item": self.item, "comment_id": other.pk, "value": 1},
                             format="json")
        self.assertEqual(r.status_code, 404)

    def test_settling_a_dormant_thread_is_not_one_query_per_comment(self):
        """The case the count test below misses: those comments are new, so
        nothing settles and the settle path never runs. A thread that has been
        sitting unsettled is where a per-row read would actually bite."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        def count_for(n):
            SocialComment.objects.filter(item_id=self.item).exclude(pk=self.c.pk).delete()
            guest = member(f"g{n}")
            for i in range(n):
                c = SocialComment.objects.create(user=guest, item_id=self.item, body=f"c{i}")
                SocialComment.objects.filter(pk=c.pk).update(
                    created_at=timezone.now() - timedelta(hours=K.KARMA_SETTLE_HOURS + 1))
            with CaptureQueriesContext(connection) as ctx:
                self.client.get(f"/api/economy/social/?item={self.item}")
            return len(ctx.captured_queries)

        few, many = count_for(2), count_for(20)
        self.assertEqual(few, many,
                         f"{few} queries settling 2 comments but {many} for 20 — "
                         "the settle path is reading per row.")

    def test_the_comment_list_query_count_does_not_grow_with_comments(self):
        def count_for(n):
            SocialComment.objects.filter(item_id=self.item).exclude(pk=self.c.pk).delete()
            for i in range(n):
                SocialComment.objects.create(user=self.them, item_id=self.item, body=f"c{i}")
            from django.test.utils import CaptureQueriesContext
            from django.db import connection
            with CaptureQueriesContext(connection) as ctx:
                self.client.get(f"/api/economy/social/?item={self.item}")
            return len(ctx.captured_queries)
        few, many = count_for(2), count_for(30)
        self.assertEqual(few, many,
                         f"{few} queries for 2 comments but {many} for 30 — "
                         "something in the comment list is per-row.")

    def test_replying_reports_what_it_paid(self):
        Message.objects.create(sender=self.them, recipient=self.me, body="hi")
        r = self.client.post("/api/economy/messages/",
                             {"to": self.them.username, "body": "hello back"},
                             format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["earned"]["reply"], K.COLD_REPLY_ENERGY)
