"""1v1 BattleZ with SpinaZ wagers.

You call somebody out, they accept, you both put a take up, the room judges
each of you, and spectators back a side. The pool is HELD the moment it's
staked — a promise to pay later is not a wager, and a pool that only exists on
paper can't be paid out.

Real-money battles stay a vote rather than a switch. Wagering cash is regulated
gambling in most places; counting who wants it is honest, shipping it on a show
of hands would not be.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.models import (
    BATTLE_MIN_RATINGS,
    BATTLE_WINDOW_HOURS,
    Battle,
    BattleEntry,
    BattleWager,
    ItemRating,
    MoneyBattleVote,
    Notification,
    OverallRating,
    award_spinaz,
    wallet_for,
)

User = get_user_model()
PW = "hunter2hunter2"


def judge(entry, *scores):
    for i, s in enumerate(scores):
        ItemRating.objects.create(
            user=User.objects.create_user(f"j{entry.id}x{i}", f"j{entry.id}x{i}@e.com", PW),
            item_id=entry.item_key, score=s)


class ChallengeTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.me = User.objects.create_user("me", "me@e.com", PW)
        self.them = User.objects.create_user("them", "t@e.com", PW)
        self.client.force_authenticate(self.me)

    def challenge(self, **over):
        return self.client.post("/api/economy/battlez/challenge/",
                                {"opponent": "them", "title": "16 bars", **over}, format="json")

    def test_a_challenge_starts_pending_not_live(self):
        # A battle somebody was entered into without agreeing is not a battle.
        resp = self.challenge()
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["status"], "pending")
        self.assertEqual(resp.data["opponent"], "them")
        self.assertIsNone(resp.data["ends_at"])

    def test_the_opponent_is_told(self):
        self.challenge()
        note = Notification.objects.filter(user=self.them).first()
        self.assertIsNotNone(note)
        self.assertIn("challenged you", note.text)

    def test_it_names_itself_when_you_do_not(self):
        self.assertEqual(self.challenge(title="").data["title"], "@me vs @them")

    def test_you_cannot_battle_yourself(self):
        self.assertEqual(self.challenge(opponent="me").status_code, 400)

    def test_an_unknown_opponent_is_refused_by_name(self):
        resp = self.challenge(opponent="ghost")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("ghost", resp.data["detail"])

    def test_the_ranges_decide_who_you_may_call_out(self):
        j = User.objects.create_user("j", "j@e.com", PW)
        OverallRating.objects.create(rater=j, target=self.them, score=2)
        resp = self.challenge(gates={"rating": [6, 10]})
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertEqual(resp.data["gate"], "rating")
        self.assertFalse(Battle.objects.exists())

    def test_the_kinds_are_kept(self):
        self.assertEqual(self.challenge(kind="freestyle").data["kind"], "freestyle")
        self.assertEqual(self.challenge(kind="nonsense").data["kind"], "1v1")


class RespondTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.me = User.objects.create_user("me", "me@e.com", PW)
        self.them = User.objects.create_user("them", "t@e.com", PW)
        self.b = Battle.objects.create(host=self.me, opponent=self.them, title="16 bars",
                                       mode=Battle.MODE_1V1, status=Battle.STATUS_PENDING)
        self.client.force_authenticate(self.them)

    def respond(self, accept=True):
        return self.client.post(f"/api/economy/battlez/{self.b.pk}/respond/",
                                {"accept": accept}, format="json")

    def test_accepting_starts_the_clock(self):
        resp = self.respond()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["status"], "open")
        self.assertIsNotNone(resp.data["ends_at"])
        self.b.refresh_from_db()
        window = (self.b.ends_at - self.b.accepted_at).total_seconds() / 3600
        self.assertAlmostEqual(window, BATTLE_WINDOW_HOURS, places=1)

    def test_declining_ends_it(self):
        self.assertEqual(self.respond(accept=False).data["status"], "declined")

    def test_only_the_person_challenged_can_answer(self):
        self.client.force_authenticate(self.me)
        self.assertEqual(self.respond().status_code, 403)

    def test_you_cannot_answer_twice(self):
        self.respond()
        self.assertEqual(self.respond().status_code, 409)


class SubmitTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.me = User.objects.create_user("me", "me@e.com", PW)
        self.them = User.objects.create_user("them", "t@e.com", PW)
        self.b = Battle.objects.create(host=self.me, opponent=self.them, title="16 bars",
                                       mode=Battle.MODE_1V1, status=Battle.STATUS_OPEN,
                                       ends_at=timezone.now() + timedelta(hours=2))
        self.client.force_authenticate(self.me)

    def submit(self):
        return self.client.post(f"/api/economy/battlez/{self.b.pk}/enter/",
                                {"title": "My 16", "media_type": "audio",
                                 "media_url": "https://x.test/me.mp3"}, format="json")

    def test_the_challenger_can_put_a_take_up_on_their_own_battle(self):
        # The open-challenge rule would have locked them out of the battle they
        # started, which is absurd for a 1v1.
        self.assertEqual(self.submit().status_code, 201)

    def test_so_can_the_opponent(self):
        self.client.force_authenticate(self.them)
        self.assertEqual(self.submit().status_code, 201)

    def test_nobody_else_can(self):
        self.client.force_authenticate(User.objects.create_user("x", "x@e.com", PW))
        resp = self.submit()
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertIn("only the two contestants", resp.data["detail"].lower())


class WagerTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.me = User.objects.create_user("me", "me@e.com", PW)
        self.them = User.objects.create_user("them", "t@e.com", PW)
        self.fan = User.objects.create_user("fan", "f@e.com", PW)
        award_spinaz(self.fan, 500, "seed")
        self.b = Battle.objects.create(host=self.me, opponent=self.them, title="16 bars",
                                       mode=Battle.MODE_1V1, status=Battle.STATUS_OPEN,
                                       ends_at=timezone.now() + timedelta(hours=2))
        self.client.force_authenticate(self.fan)

    def wager(self, side="host", amount=100):
        return self.client.post(f"/api/economy/battlez/{self.b.pk}/wager/",
                                {"side": side, "amount": amount}, format="json")

    def test_a_stake_leaves_the_wallet_and_is_held_by_the_battle(self):
        resp = self.wager()
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(wallet_for(self.fan).spinaz, 400)
        self.b.refresh_from_db()
        self.assertEqual(self.b.held_wager_spinaz, 100)
        self.assertEqual(resp.data["pools"]["host"], 100)

    def test_a_contestant_cannot_wager_on_their_own_battle(self):
        # Betting on yourself isn't spectating; betting against yourself is a
        # reason to lose on purpose.
        for who in (self.me, self.them):
            self.client.force_authenticate(who)
            self.assertEqual(self.wager().status_code, 403)

    def test_one_wager_each_so_nobody_stacks_both_sides(self):
        self.wager()
        self.assertEqual(self.wager(side="opponent").status_code, 409)

    def test_you_cannot_stake_what_you_do_not_have(self):
        resp = self.wager(amount=9999)
        self.assertEqual(resp.status_code, 402, resp.content)
        self.assertEqual(resp.data["spinaz"], 500)
        self.assertEqual(wallet_for(self.fan).spinaz, 500)

    def test_a_side_is_required(self):
        self.assertEqual(self.wager(side="maybe").status_code, 400)
        self.assertEqual(self.wager(amount=0).status_code, 400)

    def test_a_pending_battle_takes_no_wagers(self):
        self.b.status = Battle.STATUS_PENDING
        self.b.save(update_fields=["status"])
        self.assertEqual(self.wager().status_code, 409)


class SettleTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.me = User.objects.create_user("me", "me@e.com", PW)
        self.them = User.objects.create_user("them", "t@e.com", PW)
        self.b = Battle.objects.create(host=self.me, opponent=self.them, title="16 bars",
                                       mode=Battle.MODE_1V1, status=Battle.STATUS_OPEN,
                                       ends_at=timezone.now() + timedelta(hours=2))
        self.host_entry = BattleEntry.objects.create(battle=self.b, user=self.me, title="mine")
        self.opp_entry = BattleEntry.objects.create(battle=self.b, user=self.them, title="theirs")

    def backer(self, name, side, amount):
        u = User.objects.create_user(name, f"{name}@e.com", PW)
        award_spinaz(u, amount, "seed")
        award_spinaz(u, -amount, "stake")
        BattleWager.objects.create(battle=self.b, user=u, side=side, amount=amount)
        Battle.objects.filter(pk=self.b.pk).update(
            held_wager_spinaz=self.b.held_wager_spinaz + amount)
        self.b.refresh_from_db()
        return u

    def lapse(self):
        Battle.objects.filter(pk=self.b.pk).update(ends_at=timezone.now() - timedelta(minutes=1))
        self.b.refresh_from_db()

    def settle(self):
        from apps.economy.battlez import settle_battle
        return settle_battle(self.b)

    def test_the_higher_median_wins(self):
        judge(self.host_entry, 9, 9, 8)
        judge(self.opp_entry, 4, 5, 3)
        self.assertEqual(self.settle().winner, self.me)

    def test_winners_split_the_whole_pool_in_proportion_to_their_stake(self):
        judge(self.host_entry, 9, 9, 9)
        judge(self.opp_entry, 2, 2, 2)
        a = self.backer("a", "host", 300)
        b = self.backer("b", "host", 100)
        self.backer("c", "opponent", 200)          # loses it
        self.settle()
        # Pot 600, backers of the winner staked 400 → 3:1.
        self.assertEqual(wallet_for(a).spinaz + wallet_for(b).spinaz, 600)
        self.assertEqual(wallet_for(a).spinaz, 450)
        self.assertEqual(wallet_for(b).spinaz, 150)

    def test_the_pot_comes_out_exact_to_the_spinaz(self):
        judge(self.host_entry, 9, 9, 9)
        judge(self.opp_entry, 1, 1, 1)
        winners = [self.backer(n, "host", amt) for n, amt in (("a", 33), ("b", 33), ("c", 34))]
        self.backer("d", "opponent", 1)
        self.settle()
        self.assertEqual(sum(wallet_for(u).spinaz for u in winners), 101)

    def test_a_draw_gives_every_stake_back(self):
        judge(self.host_entry, 7, 7, 7)
        judge(self.opp_entry, 7, 7, 7)
        a = self.backer("a", "host", 100)
        c = self.backer("c", "opponent", 250)
        self.assertIsNone(self.settle().winner)
        self.assertEqual(wallet_for(a).spinaz, 100)
        self.assertEqual(wallet_for(c).spinaz, 250)

    def test_too_few_judges_means_nobody_qualifies_and_everyone_is_refunded(self):
        # One friend rating you a 10 is not a win.
        judge(self.host_entry, *([10] * (BATTLE_MIN_RATINGS - 1)))
        a = self.backer("a", "host", 100)
        self.assertIsNone(self.settle().winner)
        self.assertEqual(wallet_for(a).spinaz, 100)

    def test_one_judged_side_takes_it(self):
        judge(self.host_entry, 6, 6, 6)
        self.assertEqual(self.settle().winner, self.me)

    def test_nobody_backed_the_winner_so_the_losers_get_their_stakes_back(self):
        # We didn't earn them.
        judge(self.host_entry, 9, 9, 9)
        judge(self.opp_entry, 2, 2, 2)
        c = self.backer("c", "opponent", 400)
        self.settle()
        self.assertEqual(wallet_for(c).spinaz, 400)

    def test_the_held_pool_is_zero_afterwards(self):
        judge(self.host_entry, 9, 9, 9)
        judge(self.opp_entry, 2, 2, 2)
        self.backer("a", "host", 100)
        self.assertEqual(self.settle().held_wager_spinaz, 0)

    def test_settling_twice_does_not_pay_twice(self):
        judge(self.host_entry, 9, 9, 9)
        judge(self.opp_entry, 2, 2, 2)
        a = self.backer("a", "host", 100)
        self.settle()
        first = wallet_for(a).spinaz
        self.settle()
        self.assertEqual(wallet_for(a).spinaz, first)

    def test_a_contestant_cannot_settle_early(self):
        judge(self.host_entry, 9, 9, 9)
        self.client.force_authenticate(self.me)
        resp = self.client.post(f"/api/economy/battlez/{self.b.pk}/settle/", {}, format="json")
        self.assertEqual(resp.status_code, 409, resp.content)
        self.assertIn("minutes_left", resp.data)

    def test_but_can_once_the_window_has_passed(self):
        judge(self.host_entry, 9, 9, 9)
        judge(self.opp_entry, 3, 3, 3)
        self.lapse()
        self.client.force_authenticate(self.me)
        resp = self.client.post(f"/api/economy/battlez/{self.b.pk}/settle/", {}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["winner"], "me")

    def test_a_spectator_cannot_settle(self):
        self.lapse()
        self.client.force_authenticate(User.objects.create_user("x", "x@e.com", PW))
        self.assertEqual(self.client.post(f"/api/economy/battlez/{self.b.pk}/settle/",
                                          {}, format="json").status_code, 403)

    def test_it_settles_itself_on_read_when_the_window_lapses(self):
        # Otherwise a finished battle's pool sits held forever because nobody
        # happened to press a button.
        judge(self.host_entry, 8, 8, 8)
        judge(self.opp_entry, 2, 2, 2)
        a = self.backer("a", "host", 100)
        self.lapse()
        self.client.force_authenticate(a)
        resp = self.client.get(f"/api/economy/battlez/{self.b.pk}/")
        self.assertEqual(resp.data["status"], "settled")
        self.assertEqual(resp.data["winner"], "me")
        self.assertEqual(wallet_for(a).spinaz, 100)

    def test_the_scoreboard_says_who_qualified(self):
        judge(self.host_entry, 9, 9, 9)
        judge(self.opp_entry, 4)
        self.client.force_authenticate(self.me)
        board = self.client.get(f"/api/economy/battlez/{self.b.pk}/").data["scoreboard"]
        self.assertTrue(board["host"]["qualified"])
        self.assertFalse(board["opponent"]["qualified"])
        self.assertEqual(board["host"]["count"], 3)


class MoneyVoteTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(User.objects.create_user("k", "k@e.com", PW))

    def test_the_tally_starts_empty_and_says_what_it_is(self):
        resp = self.client.get("/api/economy/battlez/moneyvote/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["votes"], 0)
        self.assertFalse(resp.data["my_vote"])
        self.assertIn("legal clearance", resp.data["note"])

    def test_voting_toggles(self):
        self.assertTrue(self.client.post("/api/economy/battlez/moneyvote/", {}, format="json").data["my_vote"])
        self.assertEqual(MoneyBattleVote.objects.count(), 1)
        self.assertFalse(self.client.post("/api/economy/battlez/moneyvote/", {}, format="json").data["my_vote"])
        self.assertEqual(MoneyBattleVote.objects.count(), 0)
