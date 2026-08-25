"""QuestZ — the Energy on-ramp, and the properties that keep it honest.

Three things these are really about:

* **Progress is measured, never asserted.** Every quest counts real rows. A
  board that trusted the client would be a button that mints Energy.
* **The anti-spam property.** "Post 5 tracks" pays for garbage — posting costs
  nothing without priced skills. The weekly quest counts posts SOMEBODY ELSE
  rated, which is identical work honestly and impossible alone.
* **Minting is bounded and explained.** A daily ceiling, one claim per period
  enforced by the database, and every award through `award_energy` so LogZ
  carries the reason.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy import questz
from apps.economy.models import (CollabDeal, ItemRating, Post, QuestClaim,
                                 Referral, SocialComment, Transaction,
                                 membership_for, wallet_for)

User = get_user_model()
PW = "hunter2hunter2"
BOARD = "/api/economy/questz/"


def row(data, quest_id):
    return next(q for q in data["quests"] if q["id"] == quest_id)


class Base(TestCase):
    def setUp(self):
        self.me = User.objects.create_user(username="maker", password=PW)
        self.them = User.objects.create_user(username="rando", password=PW)
        for u in (self.me, self.them):
            membership_for(u); wallet_for(u)
        self.c = APIClient(); self.c.force_authenticate(self.me)

    def rate(self, n, by=None, item="post:999"):
        for i in range(n):
            ItemRating.objects.create(user=by or self.me, item_id=f"{item}-{i}", score=8)


class TheBoardStatesThePriceFirstTests(Base):

    def test_every_quest_says_what_it_pays_before_it_is_done(self):
        d = self.c.get(BOARD).data
        self.assertTrue(d["quests"])
        for q in d["quests"]:
            self.assertGreater(q["energy"], 0, f"{q['id']} pays nothing")
            self.assertTrue(q["what"] and q["why"], f"{q['id']} doesn't say why")
            self.assertEqual(q["done"], 0)
            self.assertFalse(q["claimable"])

    def test_every_quest_is_a_doorway_to_the_control_that_finishes_it(self):
        """Cross-pollination: a board that shows a task and no way to it is the
        read-only surface the rules call unfinished."""
        for q in self.c.get(BOARD).data["quests"]:
            self.assertTrue(q["app"], f"{q['id']} has nowhere to go")
            self.assertTrue(q["target_anchor"], f"{q['id']} lands at the top of a tab")

    def test_the_board_explains_why_quests_exist_at_all(self):
        self.assertIn("reach", self.c.get(BOARD).data["note"])


class ProgressIsMeasuredNotAssertedTests(Base):

    def test_rating_five_tracks_finishes_the_daily(self):
        self.rate(5)
        q = row(self.c.get(BOARD).data, "rate-5")
        self.assertEqual(q["done"], 5)
        self.assertTrue(q["claimable"])

    def test_progress_is_capped_at_the_target_so_the_bar_never_lies(self):
        self.rate(9)
        self.assertEqual(row(self.c.get(BOARD).data, "rate-5")["done"], 5)

    def test_your_own_comments_on_your_own_posts_do_not_count(self):
        """The quest is about giving somebody feedback, not bumping yourself."""
        mine = Post.objects.create(author=self.me, title="mine")
        theirs = Post.objects.create(author=self.them, title="theirs")
        SocialComment.objects.create(user=self.me, item_id=f"post:{mine.id}", body="🔥")
        SocialComment.objects.create(user=self.me, item_id=f"post:{mine.id}", body="🔥")
        self.assertEqual(row(self.c.get(BOARD).data, "comment-2")["done"], 0)
        SocialComment.objects.create(user=self.me, item_id=f"post:{theirs.id}", body="the second verse drags")
        self.assertEqual(row(self.c.get(BOARD).data, "comment-2")["done"], 1)

    def test_a_claim_rechecks_the_data_rather_than_trusting_the_board(self):
        r = self.c.post("/api/economy/questz/rate-5/claim/")
        self.assertEqual(r.status_code, 400)
        self.assertIn("0 of 5", r.data["detail"])


class TheAntiSpamPropertyTests(Base):
    """The one that made me change the brief.

    "Post 5 tracks" is free to do and free to fake. This counts posts somebody
    else rated — the same work for a real member, and unreachable for one
    account talking to itself.
    """

    def test_five_posts_alone_earn_nothing(self):
        for i in range(5):
            Post.objects.create(author=self.me, title=f"spam {i}")
        self.assertEqual(row(self.c.get(BOARD).data, "posts-rated-3")["done"], 0)

    def test_rating_your_own_posts_still_earns_nothing(self):
        for i in range(5):
            p = Post.objects.create(author=self.me, title=f"spam {i}")
            ItemRating.objects.create(user=self.me, item_id=f"post:{p.id}", score=10)
        self.assertEqual(row(self.c.get(BOARD).data, "posts-rated-3")["done"], 0)

    def test_three_posts_other_people_rated_finishes_it(self):
        for i in range(3):
            p = Post.objects.create(author=self.me, title=f"real {i}")
            ItemRating.objects.create(user=self.them, item_id=f"post:{p.id}", score=8)
        q = row(self.c.get(BOARD).data, "posts-rated-3")
        self.assertEqual(q["done"], 3)
        self.assertTrue(q["claimable"])

    def test_one_post_rated_by_five_people_is_still_one_post(self):
        p = Post.objects.create(author=self.me, title="one")
        for i in range(5):
            u = User.objects.create_user(username=f"fan{i}", password=PW)
            ItemRating.objects.create(user=u, item_id=f"post:{p.id}", score=9)
        self.assertEqual(row(self.c.get(BOARD).data, "posts-rated-3")["done"], 1)

    def test_a_referral_pays_only_once_they_post(self):
        Referral.objects.create(referrer=self.me, joinee=self.them)
        self.assertEqual(row(self.c.get(BOARD).data, "referral-active")["done"], 0)
        Post.objects.create(author=self.them, title="showed up")
        self.assertEqual(row(self.c.get(BOARD).data, "referral-active")["done"], 1)


class ClaimingPaysOnceTests(Base):

    def test_a_finished_quest_pays_the_stated_energy(self):
        self.rate(5)
        before = wallet_for(self.me).energy
        r = self.c.post("/api/economy/questz/rate-5/claim/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["energy"], 25)
        self.assertEqual(wallet_for(self.me).energy, before + 25)

    def test_the_same_quest_cannot_be_claimed_twice_in_a_period(self):
        self.rate(5)
        self.assertEqual(self.c.post("/api/economy/questz/rate-5/claim/").status_code, 200)
        again = self.c.post("/api/economy/questz/rate-5/claim/")
        self.assertEqual(again.status_code, 409)
        self.assertEqual(QuestClaim.objects.filter(user=self.me, quest_id="rate-5").count(), 1)

    def test_the_award_lands_in_logz_with_its_reason(self):
        """A balance that moves for an unexplained reason is what LogZ exists
        to prevent."""
        self.rate(5)
        self.c.post("/api/economy/questz/rate-5/claim/")
        note = Transaction.objects.filter(user=self.me).order_by("-id").first().note
        self.assertIn("QuestZ", note)
        self.assertIn("Rate 5 tracks", note)

    def test_a_claimed_quest_reads_as_claimed_on_the_board(self):
        self.rate(5)
        self.c.post("/api/economy/questz/rate-5/claim/")
        q = row(self.c.get(BOARD).data, "rate-5")
        self.assertTrue(q["claimed"])
        self.assertFalse(q["claimable"])

    def test_an_unknown_quest_is_a_404_not_a_payout(self):
        self.assertEqual(self.c.post("/api/economy/questz/free-money/claim/").status_code, 404)


class PeriodsResetThemselvesTests(Base):
    """The unique constraint IS the reset — nothing runs on a schedule."""

    def test_a_daily_key_changes_at_midnight_and_a_weekly_on_monday(self):
        mon = timezone.now().replace(hour=12) - timedelta(days=timezone.now().weekday())
        self.assertNotEqual(questz.period_key(questz.DAILY, mon),
                            questz.period_key(questz.DAILY, mon + timedelta(days=1)))
        self.assertEqual(questz.period_key(questz.WEEKLY, mon),
                         questz.period_key(questz.WEEKLY, mon + timedelta(days=3)))
        self.assertNotEqual(questz.period_key(questz.WEEKLY, mon),
                            questz.period_key(questz.WEEKLY, mon + timedelta(days=7)))

    def test_yesterdays_claim_does_not_block_todays(self):
        self.rate(5)
        QuestClaim.objects.create(
            user=self.me, quest_id="rate-5", energy=25,
            period=questz.period_key(questz.DAILY, timezone.now() - timedelta(days=1)))
        self.assertEqual(self.c.post("/api/economy/questz/rate-5/claim/").status_code, 200)

    def test_a_milestone_has_one_period_forever(self):
        self.assertEqual(questz.period_key(questz.ONCE), "once")
        Post.objects.create(author=self.me, title="first")
        self.assertEqual(self.c.post("/api/economy/questz/first-post/claim/").status_code, 200)
        self.assertEqual(self.c.post("/api/economy/questz/first-post/claim/").status_code, 409)


class MintingIsBoundedTests(Base):

    def test_the_daily_ceiling_defers_rather_than_refuses(self):
        self.rate(5)
        QuestClaim.objects.create(user=self.me, quest_id="filler",
                                  period=questz.period_key(questz.DAILY),
                                  energy=questz.DAILY_ENERGY_CAP)
        r = self.c.post("/api/economy/questz/rate-5/claim/")
        self.assertEqual(r.status_code, 429)
        # The wording matters: nothing is taken away, it just waits.
        self.assertIn("keeps until tomorrow", r.data["detail"])
        self.assertIn("nothing is lost", r.data["detail"].lower())

    def test_a_capped_quest_says_so_on_the_board_instead_of_offering_a_button(self):
        self.rate(5)
        QuestClaim.objects.create(user=self.me, quest_id="filler",
                                  period=questz.period_key(questz.DAILY),
                                  energy=questz.DAILY_ENERGY_CAP)
        q = row(self.c.get(BOARD).data, "rate-5")
        self.assertTrue(q["capped"])
        self.assertFalse(q["claimable"], "a button that can only refuse is the bug we keep fixing")

    def test_the_ceiling_sits_under_what_real_reach_pays(self):
        """Quests are a floor for people with no audience, never a better deal
        than being listened to."""
        self.assertLessEqual(questz.DAILY_ENERGY_CAP, 150)


class StreaksMultiplyDailiesOnlyTests(Base):

    def _claimed_on(self, days_ago):
        QuestClaim.objects.create(
            user=self.me, quest_id="rate-5", energy=25,
            period=questz.period_key(questz.DAILY,
                                     timezone.now() - timedelta(days=days_ago)))

    def test_a_week_of_dailies_is_worth_half_again(self):
        for d in range(1, 8):
            self._claimed_on(d)
        self.assertGreaterEqual(questz.streak_days(self.me), 7)
        self.assertEqual(questz.streak_multiplier(questz.streak_days(self.me)), 1.5)

    def test_a_gap_yesterday_ends_the_streak(self):
        for d in (2, 3, 4, 5, 6, 7, 8):
            self._claimed_on(d)
        self.assertEqual(questz.streak_days(self.me), 0)

    def test_today_being_empty_does_not_end_a_streak_yesterday_holds_up(self):
        for d in range(1, 8):
            self._claimed_on(d)
        self.assertEqual(questz.streak_days(self.me), 7)

    def test_a_streak_raises_a_daily_and_leaves_weeklies_and_milestones_alone(self):
        for d in range(1, 8):
            self._claimed_on(d)
        d = self.c.get(BOARD).data
        self.assertEqual(d["streak_multiplier"], 1.5)
        self.assertEqual(row(d, "comment-2")["energy"], 30)        # 20 x 1.5
        self.assertEqual(row(d, "posts-rated-3")["energy"], 150)   # weekly, untouched
        self.assertEqual(row(d, "first-collab")["energy"], 500)    # milestone, untouched


class TheOnRampTests(Base):
    """What this is FOR: a member with no reach earns 0 ⚡/hour, and Energy is
    what the tools cost."""

    def test_a_member_with_no_reach_earns_nothing_passively(self):
        from apps.economy.models import energy_rate_per_hour
        self.assertEqual(energy_rate_per_hour(self.me), 0)

    def test_the_milestones_alone_can_fund_a_real_start(self):
        once = [q for q in questz.QUESTS if q["scope"] == questz.ONCE]
        self.assertGreaterEqual(sum(q["energy"] for q in once), 900)

    def test_the_biggest_milestone_after_collab_is_the_one_that_ends_quests(self):
        """Verifying reach switches on hourly Energy — so it is deliberately
        worth more than any other one-off except a funded collab."""
        once = {q["id"]: q["energy"] for q in questz.QUESTS if q["scope"] == questz.ONCE}
        others = [v for k, v in once.items() if k not in ("reach-verified", "first-collab")]
        self.assertGreater(once["reach-verified"], max(others))
