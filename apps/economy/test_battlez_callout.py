from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.catalog import (BATTLE_CALLOUT_ENERGY, COMMENT_ENERGY,
                                  COMMENT_FREE_PER_DAY)
from apps.economy.models import Post, Wallet, wallet_for

User = get_user_model()


class CalloutAndCommentCostTests(TestCase):
    def setUp(self):
        self.c = APIClient()
        self.me = User.objects.create_user("me", "me@x.com", "pw12345678")
        self.foe = User.objects.create_user("foe", "foe@x.com", "pw12345678")
        self.c.force_authenticate(self.me)
        Wallet.objects.update_or_create(user=self.me, defaults={"energy": 10})

    def energy(self, u=None):
        return wallet_for(u or self.me).energy

    def test_callout_is_charged_and_refunded_on_decline(self):
        r = self.c.post("/api/economy/battlez/challenge/", {"opponent": "foe"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.energy(), 10 - BATTLE_CALLOUT_ENERGY)
        f = APIClient(); f.force_authenticate(self.foe)
        f.post(f"/api/economy/battlez/{r.data['id']}/respond/", {"accept": False}, format="json")
        self.assertEqual(self.energy(), 10)

    def test_callout_with_no_energy_is_refused_and_free(self):
        Wallet.objects.filter(user=self.me).update(energy=0)
        r = self.c.post("/api/economy/battlez/challenge/", {"opponent": "foe"}, format="json")
        self.assertEqual(r.status_code, 402)

    def test_comments_are_free_then_cost_and_own_post_is_free(self):
        post = Post.objects.create(author=self.foe, title="t")
        Post.objects.filter(pk=post.pk).update(created_at=timezone.now() - timedelta(hours=1))
        item = f"post:{post.id}"
        q = self.c.get("/api/economy/social/", {"item": item}).data
        self.assertEqual(q["comment_cost_energy"], 0)
        for _ in range(COMMENT_FREE_PER_DAY):
            self.c.post("/api/economy/social/comment/", {"item": item, "body": "hi"}, format="json")
        self.assertEqual(self.energy(), 10)
        self.assertEqual(self.c.get("/api/economy/social/", {"item": item}).data["comment_cost_energy"], COMMENT_ENERGY)
        self.c.post("/api/economy/social/comment/", {"item": item, "body": "more"}, format="json")
        self.assertEqual(self.energy(), 10 - COMMENT_ENERGY)
        mine = Post.objects.create(author=self.me, title="m")
        self.assertEqual(self.c.get("/api/economy/social/", {"item": f"post:{mine.id}"}).data["comment_cost_energy"], 0)


class SuggestSkillsTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("solo", "solo@x.com", "pw12345678")

    def post(self, skills):
        Post.objects.create(author=self.u, title="t", skills_used=skills)

    def test_a_solo_producer_gets_the_whole_stack_once_it_is_a_habit(self):
        from apps.economy.postz import suggest_skills
        for _ in range(5):
            self.post(["Producer", "Mix Engineer", "Rapper"])
        self.post(["Rapper"])                      # the last post alone would say Rapper
        skills, why = suggest_skills(self.u)
        self.assertEqual((set(skills), why), ({"Producer", "Mix Engineer", "Rapper"}, "habit"))

    def test_below_the_bar_the_last_post_wins(self):
        from apps.economy.postz import suggest_skills
        self.post(["Producer", "Mix Engineer"]); self.post(["Rapper"])
        self.assertEqual(suggest_skills(self.u), (["Rapper"], "last"))

    def test_no_history_falls_back_to_declared(self):
        from apps.economy.postz import suggest_skills
        self.assertEqual(suggest_skills(self.u)[1], "declared")


class FollowAndHostCostTests(TestCase):
    def setUp(self):
        from apps.economy.catalog import FOLLOW_FREE_PER_DAY
        self.free = FOLLOW_FREE_PER_DAY
        self.c = APIClient()
        self.me = User.objects.create_user("me", "me@x.com", "pw12345678")
        self.c.force_authenticate(self.me)
        Wallet.objects.update_or_create(user=self.me, defaults={"energy": 5})
        self.others = [User.objects.create_user(f"u{i}", f"u{i}@x.com", "pw12345678") for i in range(self.free + 3)]

    def test_follows_are_free_then_cost_and_follow_back_is_free(self):
        for u in self.others[:self.free]:
            self.assertEqual(self.c.post("/api/economy/follow/", {"username": u.username}, format="json").status_code, 200)
        self.assertEqual(wallet_for(self.me).energy, 5)
        nxt = self.others[self.free]
        self.assertEqual(self.c.get("/api/economy/follow/", {"username": nxt.username}).data["follow_cost_energy"], 1)
        self.c.post("/api/economy/follow/", {"username": nxt.username}, format="json")
        self.assertEqual(wallet_for(self.me).energy, 4)
        from apps.economy.models import Follow
        fan = self.others[self.free + 1]
        Follow.objects.create(follower=fan, following=self.me)
        self.c.post("/api/economy/follow/", {"username": fan.username}, format="json")
        self.assertEqual(wallet_for(self.me).energy, 4)

    def test_hosting_costs_and_refuses_when_broke(self):
        r = self.c.post("/api/economy/battlez/", {"title": "open"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(wallet_for(self.me).energy, 4)
        Wallet.objects.filter(user=self.me).update(energy=0)
        self.assertEqual(self.c.post("/api/economy/battlez/", {"title": "x"}, format="json").status_code, 402)
