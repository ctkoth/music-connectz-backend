from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.models import (BATTLE_MIN_RATINGS, Battle, BattleEntry, ItemRating,
                                 LISTEN_REQUIRED_SEC, ListenProgress, post_interaction_block)
from apps.economy import weeklybattle


def client(u):
    c = APIClient(); c.force_authenticate(u); return c


class WeeklyBattleTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner", password="pw12345!x", is_superuser=True, is_staff=True)
        self.a = User.objects.create_user("aa", password="pw12345!x")
        self.b = User.objects.create_user("bb", password="pw12345!x")
        self.judges = [User.objects.create_user(f"j{i}", password="pw12345!x") for i in range(4)]
        from unittest import mock
        p = mock.patch("apps.economy.views.platform_owner", return_value=self.owner)
        p.start(); self.addCleanup(p.stop)

    def week(self, who):
        return client(who).get("/api/economy/battlez/weekly/").json()

    def test_one_battle_per_week_made_on_first_read(self):
        w1 = self.week(self.a)["week"]; w2 = self.week(self.b)["week"]
        self.assertEqual(w1["id"], w2["id"])
        self.assertEqual(Battle.objects.filter(kind="weekly").count(), 1)

    def test_owner_may_enter_and_board_ranks_by_qualified_median(self):
        bid = self.week(self.a)["week"]["id"]
        for u in (self.owner, self.a, self.b):
            r = client(u).post(f"/api/economy/battlez/{bid}/enter/", {"title": u.username}, format="json")
            self.assertEqual(r.status_code, 201, r.content)
        ea = BattleEntry.objects.get(user=self.a); eb = BattleEntry.objects.get(user=self.b)
        for j in self.judges[:BATTLE_MIN_RATINGS]:
            ItemRating.objects.create(user=j, item_id=ea.item_key, score=9)
            ItemRating.objects.create(user=j, item_id=eb.item_key, score=6)
        board = self.week(self.a)["week"]["board"]
        self.assertEqual([(r["username"], r["rank"]) for r in board[:2]], [("aa", 1), ("bb", 2)])
        self.assertIsNone(board[2]["rank"])                       # owner: unrated, below the line
        self.assertEqual(board[2]["needs"], BATTLE_MIN_RATINGS)

    def test_settles_when_the_week_ends(self):
        bid = self.week(self.a)["week"]["id"]
        client(self.a).post(f"/api/economy/battlez/{bid}/enter/", {"title": "x"}, format="json")
        e = BattleEntry.objects.get(user=self.a)
        for j in self.judges[:BATTLE_MIN_RATINGS]:
            ItemRating.objects.create(user=j, item_id=e.item_key, score=8)
        Battle.objects.filter(pk=bid).update(ends_at=timezone.now() - timedelta(minutes=1))
        d = self.week(self.b)
        self.assertEqual(d["last_week"]["winner"], "aa")
        self.assertNotEqual(d["week"]["id"], bid)


class BattleRatingRuleTests(TestCase):
    def setUp(self):
        self.h = User.objects.create_user("h", password="pw12345!x")
        self.o = User.objects.create_user("o", password="pw12345!x")
        self.x = User.objects.create_user("x", password="pw12345!x")

    def test_no_rating_your_own_take_or_your_own_1v1(self):
        b = Battle.objects.create(host=self.h, opponent=self.o, mode=Battle.MODE_1V1, title="t")
        e = BattleEntry.objects.create(battle=b, user=self.h)
        self.assertIsNotNone(post_interaction_block(e.item_key, self.h, "rate"))
        self.assertIsNotNone(post_interaction_block(e.item_key, self.o, "rate"))
        self.assertIsNone(post_interaction_block(e.item_key, self.x, "rate"))

    def test_a_playable_take_must_be_heard(self):
        b = Battle.objects.create(host=self.h, title="t")
        e = BattleEntry.objects.create(battle=b, user=self.o, media_type="audio", media_url="/m.mp3")
        self.assertIn("listen", post_interaction_block(e.item_key, self.x, "rate")["detail"])
        ListenProgress.objects.create(user=self.x, item_id=e.item_key, seconds=LISTEN_REQUIRED_SEC)
        self.assertIsNone(post_interaction_block(e.item_key, self.x, "rate"))
