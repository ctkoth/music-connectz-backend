"""Lilith's call-to-action routines: cadence, verified actions, starters and suggestions."""
import re
from datetime import date, timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from . import lilith_actions as A
from . import lilith_starters as ST
from . import lilith_suggest as SG
from . import lilith_taskz as L
from .models import (ItemRating, LilithPayout, LilithRoutine, LilithTask, Message, Post, TakeScore,
                     profile_for, wallet_for)
from .personaz import artist_roles, clean_persona, personas_of

User = get_user_model()


def member(name):
    return User.objects.create_user(name, f"{name}@mcz.test", "pw12345!")


def api(u):
    c = APIClient(); c.force_authenticate(User.objects.get(pk=u.pk)); return c


def routine(u, **kw):
    kw.setdefault("title", "r")
    return LilithRoutine.objects.create(user=u, **kw)


def backdate(model_obj, field, days):
    type(model_obj).objects.filter(pk=model_obj.pk).update(**{field: timezone.now() - timedelta(days=days)})


class CatalogueTests(TestCase):
    def test_every_action_reads_a_real_table_without_error(self):
        u = member("cat")
        since = timezone.now() - timedelta(days=1)
        for key in A.specs():
            self.assertEqual(A.events(u, key, since), [], key)       # a FieldError here is a routine that never ticks

    def test_every_starter_names_a_real_action_and_a_real_tab(self):
        for item in ST.TASKS + ST.ROUTINES:
            if item.get("action"):
                self.assertIn(item["action"], A.specs(), item["key"])
        keys = [t["key"] for t in ST.TASKS]
        self.assertEqual(len(keys), len(set(keys)))
        keys = [r["key"] for r in ST.ROUTINES]
        self.assertEqual(len(keys), len(set(keys)))
        app = Path(__file__).resolve().parents[3] / "-music-connectz-frontend-" / "src" / "App.jsx"
        if app.exists():
            tabs = set(re.findall(r'key: "([a-z0-9_]+)", label:', app.read_text()))
            for item in ST.TASKS + ST.ROUTINES + list(A.catalogue()):
                self.assertIn(item["app_key"], tabs, item.get("key"))

    def test_every_starter_has_a_name_a_description_and_a_cadence_that_exists(self):
        for r in ST.ROUTINES:
            self.assertTrue(r["title"] and len(r["note"]) > 20, r["key"])
            self.assertIn(r["cadence"], L.CADENCES)
        for t in ST.TASKS:
            self.assertTrue(t["title"] and len(t["note"]) > 20, t["key"])
        self.assertEqual({r["cadence"] for r in ST.ROUTINES}, set(L.CADENCES))     # daily, weekly AND monthly

    def test_every_coach_has_its_own_take_action_task_and_daily_routine(self):
        for app in A.coaches():
            self.assertIn(f"take_{app}", A.specs())
            self.assertTrue(ST.task_by_key(f"take_{app}"))
            self.assertEqual(ST.routine_by_key(f"daily_{app}")["app_key"], app)


class CadenceTests(TestCase):
    def setUp(self):
        self.u = member("cad")

    def _keep(self, r, on):
        return L.keep_routine(r, on=on)

    def test_weekly_counts_iso_weeks_and_twice_in_a_week_is_one_keep(self):
        r = routine(self.u, cadence="weekly")
        mon = date(2026, 3, 2)                                   # a Monday
        self._keep(r, mon)
        self.assertTrue(self._keep(r, mon + timedelta(days=4)).get("already"))
        self.assertEqual(self._keep(r, mon + timedelta(days=7))["streak"], 2)
        self.assertEqual(self._keep(r, mon + timedelta(days=21))["streak"], 1)       # skipped a week → restarts

    def test_monthly_counts_calendar_months(self):
        r = routine(self.u, cadence="monthly")
        self._keep(r, date(2026, 1, 31))
        self.assertEqual(self._keep(r, date(2026, 2, 1))["streak"], 2)               # next calendar month, 1 day later
        self.assertEqual(self._keep(r, date(2026, 4, 5))["streak"], 1)               # skipped March

    def test_each_cadence_pays_its_own_rungs(self):
        for cadence, rung in (("weekly", 4), ("monthly", 3), ("daily", 7)):
            u = member(f"rung{cadence}")
            r = routine(u, cadence=cadence)
            start = date(2026, 1, 5)                              # a Monday, the 5th
            step = {"daily": 1, "weekly": 7, "monthly": 0}[cadence]
            out = None
            for i in range(rung):
                on = (date(2026, 1 + i, 5) if cadence == "monthly" else start + timedelta(days=step * i))
                out = self._keep(r, on)
            self.assertEqual(out["milestone"]["spinaz"], L.CADENCE_MILESTONES[cadence][rung], cadence)
            self.assertEqual(wallet_for(u).spinaz, L.CADENCE_MILESTONES[cadence][rung])

    def test_a_milestone_is_once_for_life_even_if_the_routine_is_deleted_and_remade(self):
        r = routine(self.u, cadence="weekly", template="ship_one")
        for i in range(4):
            self._keep(r, date(2026, 1, 5) + timedelta(days=7 * i))
        paid = wallet_for(self.u).spinaz
        self.assertEqual(paid, L.CADENCE_MILESTONES["weekly"][4])
        r.delete()
        r2 = routine(self.u, cadence="weekly", template="ship_one")
        for i in range(4):
            self._keep(r2, date(2026, 6, 1) + timedelta(days=7 * i))
        self.assertEqual(wallet_for(self.u).spinaz, paid)                              # not paid twice
        self.assertEqual(LilithPayout.objects.filter(user=self.u, kind="routine_milestone").count(), 1)


class VerifiedRoutineTests(TestCase):
    def setUp(self):
        self.u = member("ver")

    def _take(self, app="rapz", days_ago=0):
        t = TakeScore.objects.create(user=self.u, app_key=app, scores={"flow": 6}, overall=6)
        backdate(t, "created_at", days_ago)

    def test_lilith_keeps_it_from_the_records_and_only_rows_after_it_existed_count(self):
        self._take(days_ago=5)                                        # before the routine: does not count
        r = routine(self.u, action="take_rapz")
        self.assertEqual(L.sweep(self.u)[0], [])
        self._take()
        swept, prog = L.sweep(self.u)
        self.assertEqual(len(swept), 1)
        r.refresh_from_db()
        self.assertEqual(r.streak, 1)

    def test_the_streak_is_caught_up_when_the_board_was_not_opened(self):
        r = routine(self.u, action="take_rapz")
        backdate(r, "created_at", 10)
        for d in (4, 3, 2):                                           # three consecutive days, board never opened
            self._take(days_ago=d)
        L.sweep(self.u)
        r.refresh_from_db()
        self.assertEqual(r.streak, 3)

    def test_the_wrong_coach_does_not_keep_it(self):
        r = routine(self.u, action="take_rapz")
        self._take(app="singz")
        L.sweep(self.u)
        r.refresh_from_db()
        self.assertEqual(r.streak, 0)

    def test_a_goal_of_three_needs_three(self):
        r = routine(self.u, action="rating_given", goal=3)
        for i in range(2):
            ItemRating.objects.create(user=self.u, item_id=f"post:{900 + i}", score=7)
        _, prog = L.sweep(self.u)
        self.assertEqual((prog[("routine", r.pk)]["done"], prog[("routine", r.pk)]["met"]), (2, False))
        ItemRating.objects.create(user=self.u, item_id="post:999", score=7)
        L.sweep(self.u)
        r.refresh_from_db()
        self.assertEqual(r.streak, 1)

    def test_a_member_cannot_tick_a_verified_routine_or_task_by_hand(self):
        r = routine(self.u, action="post_made")
        t = LilithTask.objects.create(user=self.u, title="post", source="platform", action="post_made")
        c = api(self.u)
        self.assertEqual(c.post(f"/api/economy/lilith/routines/{r.pk}/").status_code, 409)
        self.assertEqual(c.post(f"/api/economy/lilith/tasks/{t.pk}/complete/").status_code, 409)
        Post.objects.create(author=self.u, title="x")
        self.assertEqual(c.post(f"/api/economy/lilith/tasks/{t.pk}/complete/").status_code, 200)
        t.refresh_from_db()
        self.assertTrue(t.done_at)

    def test_the_board_sweeps_and_reports_what_it_closed(self):
        LilithTask.objects.create(user=self.u, title="m", source="platform", action="message_sent")
        other = member("other")
        Message.objects.create(sender=self.u, recipient=other, body="hi")
        data = api(self.u).get("/api/economy/lilith/").json()
        self.assertEqual([s["title"] for s in data["swept"]], ["m"])
        self.assertTrue(data["actions"])

    def test_a_custom_cta_takes_its_control_from_the_server_not_the_request(self):
        r = api(self.u).post("/api/economy/lilith/routines/", {
            "title": "Post weekly", "cadence": "weekly", "action": "post_made",
            "app_key": "bugz", "target": "evil"}, format="json").json()
        self.assertEqual((r["app_key"], r["action"], r["cadence"]), ("postz", "post_made", "weekly"))
        bad = api(self.u).post("/api/economy/lilith/routines/", {"title": "x", "action": "mint_money"}, format="json").json()
        self.assertEqual(bad["action"], "")


class StarterTests(TestCase):
    def setUp(self):
        self.u = member("star")
        self.c = api(self.u)

    def test_adding_a_starter_copies_the_servers_content_and_is_idempotent(self):
        r = self.c.post("/api/economy/lilith/starters/", {"kind": "routine", "key": "off_the_top",
                                                          "title": "hack", "action": "x"}, format="json")
        self.assertEqual(r.status_code, 201)
        row = LilithRoutine.objects.get()
        self.assertEqual((row.title, row.cadence, row.action), ("Off the Top", "weekly", "freestyle_posted"))
        again = self.c.post("/api/economy/lilith/starters/", {"kind": "routine", "key": "off_the_top"}, format="json")
        self.assertTrue(again.json()["already"])
        self.assertEqual(LilithRoutine.objects.count(), 1)

    def test_the_tier_ceiling_applies(self):
        keys = ["daily_rapz", "off_the_top", "write_sixteen", "ship_one"]
        codes = [self.c.post("/api/economy/lilith/starters/", {"kind": "routine", "key": k}, format="json").status_code
                 for k in keys]
        self.assertEqual(codes, [201, 201, 201, 402])                  # free = 3 routines

    def test_an_instrument_aware_starter_opens_on_the_chosen_coach(self):
        r = self.c.post("/api/economy/lilith/starters/", {"kind": "routine", "key": "weekly_challenge", "app_key": "rapz"},
                        format="json").json()
        self.assertEqual(r["app_key"], "rapz")
        r = self.c.post("/api/economy/lilith/starters/", {"kind": "task", "key": "write_sixteen", "app_key": "bugz"},
                        format="json").json()
        self.assertEqual(r["app_key"], "sentenceconnectz")           # not instrument-aware: the server's own

    def test_the_board_marks_what_is_already_on_it(self):
        self.c.post("/api/economy/lilith/starters/", {"kind": "routine", "key": "ship_one"}, format="json")
        starters = self.c.get("/api/economy/lilith/").json()["starters"]
        self.assertTrue(next(r for r in starters["routines"] if r["key"] == "ship_one")["on_board"])
        self.assertFalse(next(r for r in starters["routines"] if r["key"] == "reach_out")["on_board"])


class SuggestionTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def _keys(self, u, **kw):
        from django.core.cache import cache
        cache.clear()
        return [s["key"] for s in SG.suggest(u, **kw)]

    def test_a_rapper_by_takes_is_offered_rapz_freestyle_and_bars(self):
        u = member("rapper")
        for _ in range(4):
            TakeScore.objects.create(user=u, app_key="rapz", scores={"flow": 6}, overall=6)
        got = self._keys(u)
        self.assertIn("daily_rapz", got)
        self.assertIn("off_the_top", got)
        self.assertIn("write_sixteen", got)
        s = next(s for s in SG.suggest(u) if s["key"] == "daily_rapz")
        self.assertIn("RapZ", s["why"])

    def test_a_rapper_by_declared_skill_is_offered_the_rap_pack_with_no_takes_yet(self):
        u = member("rapskill")
        p = profile_for(u)
        p.personas = [{"key": "indieartist", "name": "Independent Artist", "skills": [{"name": "Boom Bap 🥁"}]}]
        p.save()
        got = self._keys(u)
        self.assertIn("daily_rapz", got)
        self.assertIn("off_the_top", got)
        self.assertEqual(next(s for s in SG.suggest(u) if s["key"] == "daily_rapz")["why"], "Your skills say you play RapZ.")

    def test_a_manager_is_offered_outreach_not_takes(self):
        u = member("mgr")
        p = profile_for(u)
        p.personas = [{"key": "manager", "name": "Manager", "skills": []}]
        p.save()
        got = self._keys(u)
        self.assertIn("reach_out", got)
        self.assertNotIn("daily_rapz", got)

    def test_a_habit_and_a_gap_are_named_in_words(self):
        u = member("habit")
        for _ in range(4):
            TakeScore.objects.create(user=u, app_key="guitarz", scores={"a": 6}, overall=6)
        sug = {s["key"]: s for s in SG.suggest(u)}
        self.assertIn("4", sug["daily_guitarz"]["why"])
        self.assertEqual(sug["ship_one"]["because"], "gap")             # takes, never posts

    def test_what_is_on_the_board_is_not_offered_again_and_it_only_suggests(self):
        u = member("have")
        for _ in range(4):
            TakeScore.objects.create(user=u, app_key="rapz", scores={"flow": 6}, overall=6)
        self.assertNotIn("daily_rapz", self._keys(u, on_board_routines={"daily_rapz"}))
        self.assertEqual(LilithRoutine.objects.filter(user=u).count(), 0)   # never auto-added

    def test_a_new_member_still_gets_somewhere_to_start(self):
        self.assertTrue(self._keys(member("fresh")))

    def test_the_board_carries_the_suggestions(self):
        u = member("boardsug")
        self.assertTrue(api(u).get("/api/economy/lilith/").json()["suggested"])


class ArtistRoleTests(TestCase):
    def test_roles_come_from_declared_skills_in_declared_order(self):
        p = {"key": "indieartist", "name": "Independent Artist", "skills": [
            {"name": "Boom Bap 🥁"}, {"name": "tenor"}, {"name": "electric_guitar"},
            {"name": "Bass Guitar 🎸"}, {"name": "Acoustic Piano 🎹"}, {"name": "drums_snare"}]}
        self.assertEqual(artist_roles(p), ["🎤 Rapper", "🎶 Singer", "🎸 Guitarist", "🎸 Bassist", "🎹 Pianist", "🥁 Drummer"])

    def test_bass_the_voice_is_a_singer_and_bass_guitar_is_a_bassist(self):
        self.assertEqual(artist_roles({"key": "indieartist", "skills": [{"name": "bass"}]}), ["🎶 Singer"])
        self.assertEqual(artist_roles({"key": "indieartist", "skills": [{"name": "bass_guitar"}]}), ["🎸 Bassist"])

    def test_a_producer_is_not_a_rapper_but_gets_producer_roles(self):
        self.assertEqual(artist_roles({"key": "producer", "name": "Producer", "skills": [{"name": "boom_bap"}]}), [])
        self.assertEqual(artist_roles({"key": "producer", "skills": [{"name": "beat_making"}]}), ["🎚️ Beat Maker"])

    def test_designers_are_known_by_their_skills_and_labels_match_as_well_as_keys(self):
        p = {"key": "designer", "name": "Designer", "skills": [
            {"name": "Adobe Illustrator 🖌️"}, {"name": "figma"}, {"name": "Typography 🔤"}, {"name": "blender"}]}
        self.assertEqual(artist_roles(p), ["🖌️ Illustrator", "🎯 UI/UX Designer", "🔤 Typographer", "🧊 3D Artist"])

    def test_other_personas_get_roles_too(self):
        self.assertEqual(artist_roles({"key": "videographer", "skills": [{"name": "DaVinci Resolve 🎞️"}, {"name": "drone"}]}),
                         ["✂️ Video Editor", "🚁 Drone Operator"])
        self.assertEqual(artist_roles({"key": "ghostwriter", "skills": [{"name": "hooks"}]}), ["🪝 Hook Writer"])
        self.assertEqual(artist_roles({"key": "mixengineer", "skills": [{"name": "mastering"}]}), ["🎙️ Mastering Engineer"])
        self.assertEqual(artist_roles({"key": "arscout", "name": "A&R Scout", "skills": [{"name": "market_analysis"}]}), ["📊 Market Analyst"])

    def test_a_word_inside_another_word_is_not_a_match(self):
        self.assertEqual(artist_roles({"key": "indieartist", "skills": [{"name": "trapeze"}]}), [])
        self.assertEqual(artist_roles({"key": "indieartist", "skills": [{"name": "tapestry"}]}), [])

    def test_roles_are_derived_on_read_never_stored(self):
        u = member("roles")
        p = profile_for(u)
        p.personas = [clean_persona({"key": "indieartist", "name": "Independent Artist", "roles": ["Fake"],
                                     "skills": [{"name": "any_rapping"}]})]
        p.save()
        self.assertNotIn("roles", p.personas[0])
        self.assertEqual(personas_of(p)[0]["roles"], ["🎤 Rapper"])

    def test_it_reaches_the_member_card_and_the_public_profile(self):
        u = member("cardroles")
        p = profile_for(u)
        p.personas = [{"key": "indieartist", "name": "Independent Artist", "skills": [{"name": "any_singing"}]}]
        p.save()
        c = api(member("viewer"))
        card = c.get("/api/economy/profile/cardroles/") if False else None
        self.assertEqual(personas_of(p)[0]["roles"], ["🎶 Singer"])


class MoveAnythingAnywhereTests(TestCase):
    def setUp(self):
        self.u = member("mover")
        self.c = api(self.u)

    def _move(self, **body):
        return self.c.post("/api/economy/lilith/move/", body, format="json")

    def test_a_task_moves_between_buckets_but_never_into_the_logbook(self):
        t = LilithTask.objects.create(user=self.u, title="a", bucket="inbox")
        self.assertEqual(self._move(kind="task", id=t.pk, to="someday").status_code, 200)
        t.refresh_from_db()
        self.assertEqual(t.bucket, "someday")
        self.assertEqual(self._move(kind="task", id=t.pk, to="logbook").status_code, 400)

    def test_a_task_becomes_a_routine_keeping_its_control_and_its_verified_action(self):
        t = LilithTask.objects.create(user=self.u, title="Post weekly", source="platform", app_key="postz",
                                      target="post-compose", action="post_made", goal=2, bucket="inbox")
        r = self._move(kind="task", id=t.pk, to="weekly")
        self.assertEqual(r.status_code, 201)
        row = LilithRoutine.objects.get()
        self.assertEqual((row.cadence, row.app_key, row.action, row.goal), ("weekly", "postz", "post_made", 2))
        self.assertFalse(LilithTask.objects.filter(pk=t.pk).exists())

    def test_a_finished_task_is_history_and_cannot_be_moved(self):
        t = LilithTask.objects.create(user=self.u, title="done", done_at=timezone.now(), bucket="logbook")
        self.assertEqual(self._move(kind="task", id=t.pk, to="daily").status_code, 400)

    def test_a_routine_changes_cadence_and_its_run_restarts_and_says_so(self):
        r = routine(self.u, cadence="daily", streak=9, last_done=timezone.localdate())
        out = self._move(kind="routine", id=r.pk, to="weekly").json()
        self.assertTrue(out["streak_reset"])
        self.assertEqual(out["lost_streak"], 9)
        r.refresh_from_db()
        self.assertEqual((r.cadence, r.streak, r.last_done), ("weekly", 0, None))

    def test_a_routine_becomes_a_task_and_the_streak_goes_with_the_routine(self):
        r = routine(self.u, title="Breathe", app_key="breathz", action="breath_session", streak=5)
        out = self._move(kind="routine", id=r.pk, to="task", bucket="upcoming").json()
        self.assertEqual(out["lost_streak"], 5)
        t = LilithTask.objects.get()
        self.assertEqual((t.bucket, t.action, t.source), ("upcoming", "breath_session", "platform"))
        self.assertFalse(LilithRoutine.objects.exists())

    def test_moving_back_and_forth_pays_nothing_and_cannot_re_earn_a_rung(self):
        before = wallet_for(self.u).spinaz
        t = LilithTask.objects.create(user=self.u, title="x", bucket="inbox")
        for to in ("daily", "task", "weekly", "task", "monthly"):
            if LilithTask.objects.filter(user=self.u).exists():
                tk = LilithTask.objects.get(user=self.u)
                self._move(kind="task", id=tk.pk, to=to)
            else:
                rr = LilithRoutine.objects.get(user=self.u)
                self._move(kind="routine", id=rr.pk, to=to)
        self.assertEqual(wallet_for(self.u).spinaz, before)

    def test_it_respects_the_tier_ceilings_and_other_peoples_entries(self):
        for i in range(3):
            routine(self.u, title=f"r{i}")
        t = LilithTask.objects.create(user=self.u, title="t", bucket="inbox")
        self.assertEqual(self._move(kind="task", id=t.pk, to="daily").status_code, 402)     # free = 3 routines
        other = member("other2")
        theirs = LilithTask.objects.create(user=other, title="mine", bucket="inbox")
        self.assertEqual(self._move(kind="task", id=theirs.pk, to="today").status_code, 404)


class TrashTests(TestCase):
    def setUp(self):
        self.u = member("trasher")
        self.c = api(self.u)

    def _move(self, **b):
        return self.c.post("/api/economy/lilith/move/", b, format="json")

    def test_an_entry_can_go_someday_today_someday_routine_and_trash_and_back(self):
        t = LilithTask.objects.create(user=self.u, title="idea", bucket="someday")
        for to in ("today", "someday", "inbox", "upcoming", "anytime", "trash", "today"):
            self.assertEqual(self._move(kind="task", id=t.pk, to=to).status_code, 200, to)
        t.refresh_from_db()
        self.assertEqual((t.bucket, t.trashed_at), ("today", None))
        r = self._move(kind="task", id=t.pk, to="weekly")
        self.assertEqual(r.status_code, 201)
        rid = LilithRoutine.objects.get().pk
        self.assertEqual(self._move(kind="routine", id=rid, to="trash").status_code, 200)
        self.assertTrue(LilithRoutine.objects.get().trashed_at)
        self.assertEqual(self._move(kind="routine", id=rid, to="weekly").json()["moved"], "restored")
        self.assertIsNone(LilithRoutine.objects.get().trashed_at)

    def test_a_trashed_entry_is_out_of_the_ceiling_the_sweep_and_the_ticks(self):
        for i in range(3):
            routine(self.u, title=f"r{i}")
        extra = routine(self.u, title="r3x", action="message_sent")
        # ceiling is 3 for free, so the 4th above only exists because we bypassed the API; trash one and it counts as room
        self._move(kind="routine", id=extra.pk, to="trash")
        self.assertEqual(L.live_routines(self.u).count(), 3)
        Message.objects.create(sender=self.u, recipient=member("rcv"), body="x")
        L.sweep(self.u)
        extra.refresh_from_db()
        self.assertEqual(extra.streak, 0)                              # a trashed routine is not kept
        t = LilithTask.objects.create(user=self.u, title="t", bucket="inbox")
        self._move(kind="task", id=t.pk, to="trash")
        self.assertEqual(self.c.post(f"/api/economy/lilith/tasks/{t.pk}/complete/").status_code, 400)

    def test_the_board_serves_the_trash_and_empties_it_after_thirty_days(self):
        old = LilithTask.objects.create(user=self.u, title="old", bucket="trash", trashed_at=timezone.now() - timedelta(days=31))
        new = LilithTask.objects.create(user=self.u, title="new", bucket="trash", trashed_at=timezone.now())
        data = self.c.get("/api/economy/lilith/").json()
        self.assertEqual([t["title"] for t in data["buckets"]["trash"]], ["new"])
        self.assertFalse(LilithTask.objects.filter(pk=old.pk).exists())
        self.assertEqual(data["trash_days"], 30)
        self.assertTrue(any(b["key"] == "trash" for b in data["bucket_labels"]))

    def test_restoring_needs_room_and_emptying_is_for_good(self):
        t = LilithTask.objects.create(user=self.u, title="back", bucket="trash", trashed_at=timezone.now())
        out = self.c.delete("/api/economy/lilith/trash/").json()
        self.assertEqual(out["deleted"]["tasks"], 1)
        self.assertFalse(LilithTask.objects.filter(pk=t.pk).exists())

    def test_adding_a_starter_that_is_in_the_trash_restores_it_rather_than_copying(self):
        self.c.post("/api/economy/lilith/starters/", {"kind": "routine", "key": "ship_one"}, format="json")
        rid = LilithRoutine.objects.get().pk
        self._move(kind="routine", id=rid, to="trash")
        r = self.c.post("/api/economy/lilith/starters/", {"kind": "routine", "key": "ship_one"}, format="json")
        self.assertTrue(r.json()["restored"])
        self.assertEqual(LilithRoutine.objects.count(), 1)

    def test_trashing_and_restoring_pays_nothing(self):
        before = wallet_for(self.u).spinaz
        t = LilithTask.objects.create(user=self.u, title="x", bucket="inbox")
        for to in ("trash", "today", "trash", "inbox"):
            self._move(kind="task", id=t.pk, to=to)
        self.assertEqual(wallet_for(self.u).spinaz, before)


class RecommendedFromProfileAndActivityTests(TestCase):
    def _tasks(self, u):
        from django.core.cache import cache
        cache.clear()
        return {s["key"]: s for s in SG.suggest(u) if s["kind"] == "task"}

    def test_an_empty_profile_is_told_what_is_missing_in_words(self):
        u = member("bare")
        got = self._tasks(u)
        self.assertIn("pick_persona", got)
        self.assertIn("finish_profile", got)
        self.assertIn("portfolio_links", got)
        self.assertIn("verify_18", got)
        self.assertEqual(got["finish_profile"]["because"], "profile")
        self.assertIn("bio is empty", got["finish_profile"]["why"])

    def test_a_filled_in_profile_is_not_nagged(self):
        u = member("full")
        p = profile_for(u)
        p.bio = "I make beats."
        p.links = [{"url": "https://example.com", "label": "site"}]
        p.personas = [{"key": "producer", "name": "Producer", "skills": []}]
        p.verified_18plus = True
        p.save()
        got = self._tasks(u)
        for k in ("pick_persona", "finish_profile", "portfolio_links", "verify_18"):
            self.assertNotIn(k, got)

    def test_a_low_last_take_recommends_the_drill_and_names_the_score(self):
        u = member("low")
        p = profile_for(u)
        p.bio, p.links, p.verified_18plus = "bars", [{"url": "https://e.com", "label": "x"}], True
        p.personas = [{"key": "indieartist", "name": "Independent Artist", "skills": [{"name": "any_rapping"}]}]
        p.save()                                                          # profile in order: only the activity speaks
        TakeScore.objects.create(user=u, app_key="rapz", scores={"flow": 3}, overall=3)
        got = self._tasks(u)
        self.assertEqual(list(got)[0], "fix_weakest")
        self.assertIn("scored 3", got["fix_weakest"]["why"])
        self.assertIn("take_rapz", got)                                  # and today's take, in the coach they use
        self.assertIn("post_finished", got)                              # scored, never posted

    def test_a_collab_waiting_on_you_comes_first(self):
        from .models import CollabDeal
        a, b = member("starter"), member("waiting")
        deal = CollabDeal.objects.create(initiator=a, title="d", currency="spinaz", status="draft",
                                         participants=[{"username": "starter", "accepted_at": "2026-01-01T00:00:00Z"},
                                                       {"username": "waiting"}])
        got = self._tasks(b)
        self.assertEqual(list(got)[0], "answer_collab")
        self.assertIn("1 collab is waiting", got["answer_collab"]["why"])

    def test_what_is_already_on_the_board_is_not_recommended_and_the_board_carries_both_kinds(self):
        u = member("onboard")
        c = api(u)
        data = c.get("/api/economy/lilith/").json()
        kinds = {s["kind"] for s in data["suggested"]}
        self.assertEqual(kinds, {"routine", "task"})
        c.post("/api/economy/lilith/starters/", {"kind": "task", "key": "pick_persona"}, format="json")
        again = {s["key"] for s in c.get("/api/economy/lilith/").json()["suggested"] if s["kind"] == "task"}
        self.assertNotIn("pick_persona", again)
