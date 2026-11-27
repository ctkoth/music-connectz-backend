"""RoutineZ on a yearly rhythm, the platform habits that became routines, and the conversion of old tasks."""
from datetime import date
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import lilith_starters as ST
from apps.economy import lilith_taskz as L
from apps.economy.models import LilithRoutine, LilithTask, wallet_for

User = get_user_model()
ROUTINES = "/api/economy/lilith/routines/"
MOVE = "/api/economy/lilith/move/"


def member(name):
    return User.objects.create_user(name, f"{name}@mcz.test", "pw12345!")


def routine(u, **kw):
    kw.setdefault("title", "r")
    return LilithRoutine.objects.create(user=u, **kw)


class YearlyPeriodTests(TestCase):
    def test_a_year_starts_on_the_first_of_january(self):
        self.assertEqual(L.period_start(date(2026, 7, 4), "yearly"), date(2026, 1, 1))
        self.assertEqual(L.previous_period_start(date(2026, 1, 1), "yearly"), date(2025, 1, 1))
        self.assertEqual((L.PERIOD_NOUN["yearly"], L.PERIOD_NOW["yearly"]), ("year", "this year"))

    def test_keeping_it_twice_in_a_year_is_one_keep(self):
        r = routine(member("y1"), cadence="yearly")
        L.keep_routine(r, on=date(2026, 3, 5))
        self.assertTrue(L.keep_routine(r, on=date(2026, 11, 20)).get("already"))

    def test_a_skipped_year_restarts_the_streak(self):
        r = routine(member("y2"), cadence="yearly")
        L.keep_routine(r, on=date(2026, 3, 5))
        self.assertEqual(L.keep_routine(r, on=date(2027, 2, 1))["streak"], 2)
        self.assertEqual(L.keep_routine(r, on=date(2029, 1, 10))["streak"], 1)     # 2028 was skipped

    def test_the_first_yearly_rung_is_three_years_not_a_day(self):
        # A keep on 31 December and one on 1 January are consecutive years a day apart: no rung there.
        self.assertEqual(min(L.CADENCE_MILESTONES["yearly"]), 3)
        u = member("y3")
        r = routine(u, cadence="yearly")
        L.keep_routine(r, on=date(2026, 12, 31))
        self.assertIsNone(L.keep_routine(r, on=date(2027, 1, 1))["milestone"])     # two years, not a rung yet
        out = L.keep_routine(r, on=date(2028, 1, 1))
        self.assertEqual(out["milestone"]["spinaz"], L.CADENCE_MILESTONES["yearly"][3])
        self.assertEqual(wallet_for(u).spinaz, L.CADENCE_MILESTONES["yearly"][3])

    def test_the_yearly_rungs_are_published_before_anything_is_pressed(self):
        keys = {row["key"] for row in L.rewards_table()}
        for d in L.CADENCE_MILESTONES["yearly"]:
            self.assertIn(f"routine_yearly_{d}", keys)


class YearlyApiTests(TestCase):
    def setUp(self):
        self.u = member("yapi")
        self.c = APIClient(); self.c.force_authenticate(self.u)

    def test_a_routine_can_be_added_yearly_and_the_board_says_so(self):
        r = self.c.post(ROUTINES, {"title": "Write the year down", "cadence": "yearly"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual((r.json()["cadence"], r.json()["unit"], r.json()["period_now"]),
                         ("yearly", "year", "this year"))
        self.assertEqual(LilithRoutine.objects.get(pk=r.json()["id"]).source, "self")

    def test_moving_a_routine_to_yearly_restarts_its_run_and_says_so(self):
        r = routine(self.u, cadence="daily", streak=9)
        out = self.c.post(MOVE, {"kind": "routine", "id": r.pk, "to": "yearly"}, format="json").json()
        self.assertEqual(out["routine"]["cadence"], "yearly")
        self.assertTrue(out["streak_reset"])
        self.assertEqual(out["lost_streak"], 9)


class PlatformStartersAreRoutinesTests(TestCase):
    def test_a_verified_habit_is_never_a_task(self):
        for t in ST.TASKS:
            self.assertFalse(t.get("action"), t["key"])
        self.assertEqual(set(ST.TASK_KEYS), {"pick_persona", "finish_profile", "portfolio_links",
                                             "import_soundcloud", "verify_18", "answer_collab"})

    def test_every_retired_task_points_at_a_real_routine(self):
        for old, new in ST.RETIRED_TASKS.items():
            self.assertIsNotNone(ST.routine_by_key(new), (old, new))
        self.assertEqual(ST.routine_for_retired("take_singz"), "daily_singz")
        self.assertIsNone(ST.routine_for_retired("finish_profile"))

    def test_messaging_collabing_and_the_coach_are_routines(self):
        self.assertEqual(ST.routine_by_key("reach_out")["action"], "message_sent")
        self.assertEqual(ST.routine_by_key("start_collab")["action"], "collab_started")
        self.assertEqual(ST.routine_by_key("start_collab")["cadence"], "monthly")
        self.assertEqual(ST.routine_by_key("daily_singz")["action"], "take_singz")

    def test_yearly_habits_exist_for_the_longer_rhythms(self):
        yearly = {r["key"] for r in ST.ROUTINES if r["cadence"] == "yearly"}
        self.assertTrue({"invite_musician", "release_a_year", "year_in_review"} <= yearly)
        self.assertEqual(ST.routine_by_key("invite_musician")["action"], "invite_joined")


class ConvertPlatformTasksCommandTests(TestCase):
    def setUp(self):
        self.u = member("conv")
        self.habit = LilithTask.objects.create(user=self.u, title="Message someone", source="platform",
                                               template="message_member", bucket="anytime")
        self.setup_step = LilithTask.objects.create(user=self.u, title="Verify", source="platform",
                                                    template="verify_18", bucket="anytime")

    def test_a_dry_run_changes_nothing(self):
        out = StringIO()
        call_command("lilith_platform_routines", stdout=out)
        self.assertIn("Dry run", out.getvalue())
        self.assertTrue(LilithTask.objects.filter(pk=self.habit.pk).exists())
        self.assertFalse(LilithRoutine.objects.filter(user=self.u).exists())

    def test_write_turns_a_habit_task_into_its_routine_and_keeps_the_set_up_step(self):
        call_command("lilith_platform_routines", "--write", stdout=StringIO())
        self.assertFalse(LilithTask.objects.filter(pk=self.habit.pk).exists())
        r = LilithRoutine.objects.get(user=self.u)
        self.assertEqual((r.template, r.cadence, r.action, r.source, r.title),
                         ("reach_out", "weekly", "message_sent", "platform", "Message someone"))
        self.assertTrue(LilithTask.objects.filter(pk=self.setup_step.pk).exists())

    def test_a_member_already_keeping_that_routine_keeps_the_task(self):
        routine(self.u, template="reach_out", cadence="weekly", title="Reach Out")
        call_command("lilith_platform_routines", "--write", stdout=StringIO())
        self.assertTrue(LilithTask.objects.filter(pk=self.habit.pk).exists())
        self.assertEqual(LilithRoutine.objects.filter(user=self.u, template="reach_out").count(), 1)
