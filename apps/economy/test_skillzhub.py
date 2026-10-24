"""SkillZ hub: the seven coaches, what a take costs BEFORE any is opened, and
what the member has done in each.

The hub quotes no number of its own — the price is the coach's own GET — so
these tests pin that the two agree, that the hub never grows a query per coach,
and that the coaches it lists are exactly the ones that have a mounted route.
"""
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy import skillzhub
from apps.economy.catalog import ai_cost
from apps.economy.instruments import INSTRUMENTS, scores_for
from apps.economy.models import TakeScore, daily_prompt_state, wallet_for
from apps.skillz.models import TrainingProfile

User = get_user_model()
URL = "/api/economy/skillz/"
PW = "pw12345!"
ORDER = ["singz", "rapz", "guitarz", "bassz", "keyz", "violinz", "flutez", "saxz", "clarinetz", "trumpetz", "drumz"]


class HubBase(TestCase):
    def setUp(self):
        self.me = User.objects.create_user("coached", "c@e.com", PW)
        self.c = APIClient()
        self.c.force_authenticate(self.me)

    def get(self):
        r = self.c.get(URL)
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def app(self, key):
        return next(a for a in self.get()["apps"] if a["key"] == key)


class ShapeTests(HubBase):
    def test_it_needs_a_sign_in(self):
        self.assertIn(APIClient().get(URL).status_code, (401, 403))

    def test_the_coaches_come_in_the_stated_order(self):
        self.assertEqual([a["key"] for a in self.get()["apps"]], ORDER)

    def test_every_coach_is_one_that_has_a_scored_profile_and_a_route(self):
        from music_connectz.urls import INSTRUMENT_APP_KEYS
        self.assertEqual(set(ORDER), set(INSTRUMENTS))
        self.assertEqual(set(ORDER), set(INSTRUMENT_APP_KEYS))
        for key, _, _ in skillzhub.COACHES:
            self.assertIn(key, INSTRUMENTS)

    def test_every_coach_is_built_open_and_in_the_standalone(self):
        for a in self.get()["apps"]:
            self.assertTrue(a["built"], a["key"])
            self.assertEqual(a["tab"], a["key"])
            self.assertTrue(a["in_app"] and a["standalone"], a["key"])
            for k in ("label", "emoji", "icon", "desc", "price", "count", "scores"):
                self.assertTrue(a[k] is not None and a[k] != "", (a["key"], k))

    def test_labels_are_the_profiles_own(self):
        for a in self.get()["apps"]:
            self.assertEqual(a["label"], INSTRUMENTS[a["key"]]["label"])

    def test_scores_are_what_the_coach_scores_and_nothing_else(self):
        for a in self.get()["apps"]:
            self.assertEqual(a["scores"], list(scores_for(a["key"]).values()))

    def test_a_description_names_the_dimensions_without_their_marks(self):
        d = self.app("drumz")["desc"]
        for word in ("timing", "groove", "dynamics", "consistency", "fills"):
            self.assertIn(word, d)
        self.assertNotIn("⏱", d)

    def test_what_is_not_built_is_names_only_and_never_a_tile(self):
        body = self.get()
        self.assertEqual(body["coming"], ["DJ", "Producer", "A&R", "Illustrator", "Videographer"])
        labels = {a["label"] for a in body["apps"]}
        self.assertFalse(labels & set(body["coming"]))
        self.assertTrue(all(isinstance(c, str) for c in body["coming"]))


class PriceTests(HubBase):
    def test_the_hub_quotes_what_the_coachs_own_get_quotes(self):
        for key in ORDER:
            coach = self.c.get(f"/api/{key}/coach/").json()
            hub = self.app(key)["price"]
            self.assertEqual(hub["cost_cents"], coach["cost_cents"], key)
            self.assertEqual(hub["free_today"], coach["free_today"], key)
            self.assertEqual(hub["daily_remaining"], coach["daily_remaining"], key)

    def test_a_spent_allowance_is_no_longer_free_today(self):
        allowance, _, _ = daily_prompt_state(self.me)
        w = wallet_for(self.me)
        w.prompts_used_today = allowance
        w.save()
        price = self.app("singz")["price"]
        self.assertFalse(price["free_today"])
        self.assertEqual(price["daily_remaining"], 0)
        self.assertEqual(price["cost_cents"], ai_cost("standard"))

    def test_daily_is_the_prompt_state(self):
        allowance, used, remaining = daily_prompt_state(self.me)
        self.assertEqual(self.get()["daily"], {"allowance": allowance, "used": used, "remaining": remaining})

    def test_the_hub_charges_nothing(self):
        before = (wallet_for(self.me).promptz, wallet_for(self.me).prompts_used_today)
        self.get()
        w = wallet_for(self.me)
        self.assertEqual(before, (w.promptz, w.prompts_used_today))


class ConfiguredTests(HubBase):
    def test_every_coach_follows_the_gemini_key(self):
        with mock.patch.object(skillzhub, "_key", return_value="k"):
            self.assertTrue(all(a["configured"] for a in self.get()["apps"]))
        with mock.patch.object(skillzhub, "_key", return_value=""):
            self.assertFalse(any(a["configured"] for a in self.get()["apps"]))

    def test_it_agrees_with_the_coachs_own_configured_flag(self):
        with mock.patch.object(skillzhub, "_key", return_value=""):
            self.assertEqual(self.c.get("/api/singz/coach/").json()["configured"],
                             self.app("singz")["configured"])


class CountTests(HubBase):
    def test_counts_and_levels_are_the_members_own_rows(self):
        for key, n in (("singz", 3), ("drumz", 1)):
            for _ in range(n):
                TakeScore.objects.create(user=self.me, app_key=key, overall=7)
        other = User.objects.create_user("other", "o@e.com", PW)
        TakeScore.objects.create(user=other, app_key="singz", overall=9)
        TrainingProfile.objects.create(user=self.me, app_key="rapz", xp=1200)
        self.assertEqual(self.app("singz")["count"], 3)
        self.assertEqual(self.app("drumz")["count"], 1)
        self.assertEqual(self.app("keyz")["count"], 0)
        rapz = self.app("rapz")
        self.assertEqual((rapz["xp"], rapz["level"]), (1200, 3))
        self.assertEqual((self.app("keyz")["xp"], self.app("keyz")["level"]), (0, 1))


class RecentTests(HubBase):
    def test_the_shelf_is_newest_first_labelled_and_lands_on_the_coach(self):
        now = timezone.now()
        a = TakeScore.objects.create(user=self.me, app_key="singz", overall=6, genre="Soul")
        b = TakeScore.objects.create(user=self.me, app_key="drumz", overall=None)
        TakeScore.objects.filter(pk=a.pk).update(created_at=now - timedelta(hours=2))
        TakeScore.objects.filter(pk=b.pk).update(created_at=now - timedelta(hours=1))
        rows = self.get()["recent"]
        self.assertEqual([r["app"] for r in rows], ["drumz", "singz"])
        self.assertEqual(rows[0]["label"], "DrumZ · not scored")
        self.assertEqual(rows[1]["label"], "SingZ · 6/10 · Soul")
        for r in rows:
            self.assertEqual(r["tab"], r["app"])
            self.assertEqual(r["target"], f"{r['app']}-progress")
        listed = {a["key"] for a in self.get()["apps"]}
        self.assertTrue({r["tab"] for r in rows} <= listed)

    def test_it_is_only_your_own_and_capped(self):
        other = User.objects.create_user("other2", "o2@e.com", PW)
        TakeScore.objects.create(user=other, app_key="singz", overall=9)
        for _ in range(skillzhub.RECENT_MAX + 4):
            TakeScore.objects.create(user=self.me, app_key="rapz", overall=5)
        rows = self.get()["recent"]
        self.assertEqual(len(rows), skillzhub.RECENT_MAX)
        self.assertTrue(all(r["app"] == "rapz" for r in rows))

    def test_a_take_from_an_app_that_is_not_a_coach_is_not_on_the_shelf(self):
        TakeScore.objects.create(user=self.me, app_key="mimez", overall=5)
        self.assertEqual(self.get()["recent"], [])


class QueryCountTests(HubBase):
    def _queries(self):
        # The first read of a brand-new account creates its wallet and membership
        # rows; that is setup, not the hub's cost.
        self.get()
        with CaptureQueriesContext(connection) as q:
            self.get()
        return len(q)

    def test_the_cost_does_not_grow_with_what_the_member_has_done(self):
        base = self._queries()
        for key in ORDER:
            for _ in range(5):
                TakeScore.objects.create(user=self.me, app_key=key, overall=6)
            TrainingProfile.objects.create(user=self.me, app_key=key, xp=100)
        self.assertEqual(self._queries(), base)

    def test_and_it_is_a_handful(self):
        self.assertLessEqual(self._queries(), 8)
