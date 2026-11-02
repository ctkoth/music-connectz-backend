"""Moods: how a thing made you feel, beside the up/down karma vote.

They are reactions, never measurements — so nothing here pays, and no other
module may read one (a mood that fed a rating would be a number a member could
buy by asking friends to press a heart)."""
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import moods
from apps.economy.models import MoodReaction, Notification, Post, ScoreShare, wallet_for

User = get_user_model()
PW = "pw-Long-enough-1"


class MoodTests(TestCase):
    def setUp(self):
        self.maker = User.objects.create_user("maker", "m@e.com", PW)
        self.fan = User.objects.create_user("fan", "f@e.com", PW)
        self.other = User.objects.create_user("other", "o@e.com", PW)
        ScoreShare.objects.create(token="tk1", app_key="singz", score=7, user=self.maker)
        self.post = Post.objects.create(author=self.maker, title="t", genre="x")
        self.c = APIClient(); self.c.force_authenticate(self.fan)
        self.o = APIClient(); self.o.force_authenticate(self.other)

    def react(self, item, mood, client=None):
        return (client or self.c).post("/api/economy/social/mood/", {"item": item, "mood": mood}, format="json")

    def test_the_list_is_the_servers_and_carries_the_asked_for_emotions(self):
        d = self.c.get("/api/economy/social/", {"item": "score:tk1"}).json()["moods"]
        by = {m["key"]: m["emoji"] for m in d["list"]}
        for k in ("love", "hate", "curious", "shocked"):
            self.assertIn(k, by)
        self.assertEqual(by["love"], "❤️")
        self.assertEqual(d["mine"], "")
        self.assertEqual(set(d["counts"]), set(moods.KEYS))

    def test_set_change_and_clear_keep_one_mood_per_member(self):
        self.assertEqual(self.react("score:tk1", "love").json()["moods"]["mine"], "love")
        d = self.react("score:tk1", "shocked").json()["moods"]
        self.assertEqual((d["mine"], d["counts"]["love"], d["counts"]["shocked"]), ("shocked", 0, 1))
        self.assertEqual(MoodReaction.objects.filter(user=self.fan).count(), 1)
        d = self.react("score:tk1", "").json()["moods"]
        self.assertEqual((d["mine"], d["counts"]["shocked"]), ("", 0))

    def test_counts_are_everybodys_and_mine_is_mine(self):
        self.react("post:%d" % self.post.id, "curious")
        self.react("post:%d" % self.post.id, "curious", self.o)
        d = self.o.get("/api/economy/social/", {"item": f"post:{self.post.id}"}).json()["moods"]
        self.assertEqual(d["counts"]["curious"], 2)
        self.assertEqual(d["mine"], "curious")

    def test_an_unknown_mood_is_refused_not_guessed(self):
        self.assertEqual(self.react("score:tk1", "meh").status_code, 400)
        self.assertEqual(MoodReaction.objects.count(), 0)

    def test_nobody_reacts_to_their_own_work(self):
        m = APIClient(); m.force_authenticate(self.maker)
        r = self.react("score:tk1", "love", m)
        self.assertEqual(r.status_code, 403)
        self.assertIn("your own take", r.json()["detail"])

    def test_things_that_are_not_there_or_not_reactable_are_refused(self):
        self.assertEqual(self.react("score:nope", "love").status_code, 404)
        self.assertEqual(self.react("post:999999", "love").status_code, 404)
        self.assertEqual(self.react("widget:1", "love").status_code, 400)

    def test_a_private_post_is_not_there_for_somebody_else(self):
        p = Post.objects.create(author=self.maker, title="p", genre="x", visibility="private")
        self.assertEqual(self.react(f"post:{p.id}", "love").status_code, 404)

    def test_it_pays_nothing_to_anyone(self):
        before = (wallet_for(self.fan).energy, wallet_for(self.maker).energy,
                  wallet_for(self.fan).spinaz, wallet_for(self.maker).spinaz)
        self.react("score:tk1", "love")
        self.react("score:tk1", "hate")
        after = (wallet_for(self.fan).energy, wallet_for(self.maker).energy,
                 wallet_for(self.fan).spinaz, wallet_for(self.maker).spinaz)
        self.assertEqual(before, after)

    def test_the_maker_is_told_once_not_on_every_change(self):
        self.react("score:tk1", "love")
        self.react("score:tk1", "shocked")
        self.assertEqual(Notification.objects.filter(user=self.maker).count(), 1)

    def test_it_needs_a_login(self):
        r = APIClient().post("/api/economy/social/mood/", {"item": "score:tk1", "mood": "love"}, format="json")
        self.assertIn(r.status_code, (401, 403))

    def test_the_mood_cost_is_one_query_pair_however_many_reactions(self):
        for i in range(8):
            u = User.objects.create_user(f"x{i}", f"x{i}@e.com", PW)
            MoodReaction.objects.create(user=u, item_id="score:tk1", mood="love")
        with self.assertNumQueries(2):
            moods.summary("score:tk1", self.fan)


class NothingMeasuresAMoodTests(TestCase):
    """Substance rule: a reaction is never a measurement."""

    def test_no_other_module_reads_a_mood(self):
        allowed = {"moods.py", "models.py", "social.py"}
        root = Path(__file__).parent
        bad = []
        for f in root.glob("*.py"):
            if f.name.startswith("test_") or f.name in allowed:
                continue
            if re.search(r"MoodReaction|\bmoods\b\.", f.read_text(encoding="utf-8", errors="ignore")):
                bad.append(f.name)
        self.assertEqual(bad, [], f"a mood must never feed a measurement: {bad}")
