"""BodieZ tests — the catalog, the training loop, the coach, and the tier gates."""
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.bodiez import catalog as cat
from apps.bodiez import coach
from apps.bodiez.models import (BUCKETS, BodieZItem, BodyMetric, Exercise,
                                GymLocation, Routine, RoutineExercise,
                                WorkoutSession, WorkoutSet)
from apps.economy.models import (TIER_FREE, TIER_PREMIUM, TIER_STATZ,
                                 membership_for)

User = get_user_model()

# The muscle groups the blueprint names, in its order.
SPEC_MUSCLES = ["neck", "shoulder", "chest", "bicep", "tricep", "forearm", "wrist",
                "back", "trapz", "abz", "upper-leg", "lower-leg"]
# The equipment the blueprint names.
SPEC_EQUIPMENT = ["barbell", "dumbbell", "kettlebell", "ez-bar", "weight-plates",
                  "flat-bench", "decline-bench", "cable", "machine"]


def seed():
    from django.core.management import call_command
    from io import StringIO
    call_command("seed_bodiez", stdout=StringIO())


class CatalogTests(TestCase):
    def test_every_muscle_group_the_spec_names_exists_in_order(self):
        self.assertEqual(cat.MUSCLE_KEYS[:len(SPEC_MUSCLES)], SPEC_MUSCLES)

    def test_glutes_and_full_body_are_added_not_substituted(self):
        """Leaving the largest muscle in the body inside 'upper leg' makes a
        posterior-chain routine impossible to filter for."""
        self.assertIn("glutes", cat.MUSCLE_KEYS)
        self.assertIn("full-body", cat.MUSCLE_KEYS)

    def test_every_equipment_type_the_spec_names_exists(self):
        for key in SPEC_EQUIPMENT:
            self.assertIn(key, cat.EQUIPMENT_KEYS, key)
        # and the ones the spec implied
        for key in ("incline-bench", "smith-machine", "squat-rack", "pull-up-bar",
                    "bands", "bodyweight"):
            self.assertIn(key, cat.EQUIPMENT_KEYS, key)

    def test_the_equipment_vocabulary_matches_the_weightlifter_persona(self):
        """One list, so 'what I can lift' and 'what this gym has' can't drift."""
        from apps.economy.personaz import PERSONAZ

        persona = PERSONAZ["weightlifter"]["categories"]["Equipment"]
        names = {n.lower() for n in persona if not n.startswith("Any")}
        catalog_names = {n.lower() for _k, n, _e in cat.EQUIPMENT}
        self.assertEqual(names, catalog_names)

    def test_the_muscle_vocabulary_matches_the_weightlifter_persona(self):
        from apps.economy.personaz import PERSONAZ

        persona = PERSONAZ["weightlifter"]["categories"]["Muscle Groups"]
        names = {n.lower() for n in persona if not n.startswith("Any")}
        catalog_names = {n.lower() for _k, n, _e, _r in cat.MUSCLE_GROUPS}
        self.assertEqual(names, catalog_names)

    def test_every_exercise_is_well_formed(self):
        keys = set()
        for key, name, muscle, secondary, equipment, pattern, difficulty in cat.EXERCISES:
            self.assertNotIn(key, keys, f"duplicate exercise key {key}")
            keys.add(key)
            self.assertTrue(name.strip(), key)
            self.assertIn(muscle, cat.MUSCLE_KEYS, key)
            self.assertIn(pattern, cat.PATTERN_KEYS, key)
            self.assertIn(difficulty, cat.DIFFICULTY_KEYS, key)
            for m in secondary:
                self.assertIn(m, cat.MUSCLE_KEYS, f"{key}: bad secondary {m}")
            self.assertTrue(equipment, f"{key}: no equipment (use 'bodyweight')")
            # A requirement is a string (needed) or a tuple (any one will do).
            for group in cat.requirement_groups(equipment):
                self.assertTrue(group, f"{key}: empty requirement group")
                for q in group:
                    self.assertIn(q, cat.EQUIPMENT_KEYS, f"{key}: bad equipment {q}")

    def test_every_muscle_group_has_at_least_one_exercise(self):
        """A muscle you can filter to but never train is a dead end in the UI."""
        covered = set()
        for _k, _n, muscle, secondary, _e, _p, _d in cat.EXERCISES:
            covered.add(muscle)
            covered.update(secondary)
        for m in cat.MUSCLE_KEYS:
            self.assertIn(m, covered, m)

    def test_bodyweight_alone_still_gives_a_real_routine(self):
        """The hotel-room case. If this returns nothing, the filter is useless."""
        rows = cat.exercises_for(equipment=["bodyweight"])
        self.assertGreaterEqual(len(rows), 8)
        muscles = {r["muscle"] for r in rows}
        self.assertIn("chest", muscles)
        self.assertIn("abz", muscles)

    def test_the_filter_requires_every_piece_not_just_one(self):
        """A bench press with no bench is not a bench press."""
        with_bar_only = {r["key"] for r in cat.exercises_for(equipment=["barbell", "weight-plates"])}
        self.assertNotIn("bench-press", with_bar_only)
        with_bench = {r["key"] for r in cat.exercises_for(
            equipment=["barbell", "weight-plates", "flat-bench"])}
        self.assertIn("bench-press", with_bench)

    def test_filtering_by_muscle_includes_secondary_work(self):
        rows = {r["key"] for r in cat.exercises_for(muscles=["tricep"])}
        self.assertIn("tricep-pushdown", rows)      # primary
        self.assertIn("bench-press", rows)          # secondary

    def test_the_catalog_endpoint_is_public_and_complete(self):
        data = APIClient().get("/api/bodiez/catalog/").data
        self.assertEqual(len(data["equipment"]), len(cat.EQUIPMENT))
        self.assertEqual(len(data["muscle_groups"]), len(cat.MUSCLE_GROUPS))
        self.assertEqual([b["key"] for b in data["buckets"]], BUCKETS)
        self.assertIn("AI Coach (costs a daily prompt)", data["tiers"]["free"])

    def test_seeding_is_idempotent(self):
        seed()
        self.assertEqual(Exercise.objects.filter(owner__isnull=True).count(),
                         len(cat.EXERCISES))
        seed()
        self.assertEqual(Exercise.objects.filter(owner__isnull=True).count(),
                         len(cat.EXERCISES))


class RoutineTests(TestCase):
    def setUp(self):
        seed()
        self.client = APIClient()
        self.user = User.objects.create_user("lifter", "l@e.com", "pw12345678")
        self.client.force_authenticate(self.user)

    def _routine(self, **kw):
        body = {"name": "Push Day", "goal": "hypertrophy", "split": "push-pull-legs",
                "equipment": ["barbell", "flat-bench", "weight-plates"]}
        body.update(kw)
        return self.client.post("/api/bodiez/routines/", body, format="json")

    def test_build_a_routine_with_targets_and_supersets(self):
        rid = self._routine().data["routine"]["id"]
        bench = Exercise.objects.get(key="bench-press", owner=None)
        fly = Exercise.objects.get(key="db-fly", owner=None)

        resp = self.client.post(f"/api/bodiez/routines/{rid}/exercises/",
                                {"exercise_id": bench.id, "sets": 4, "reps": 8,
                                 "rest_seconds": 180, "target_weight": 185,
                                 "superset_group": "A"}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["routine_exercise"]["target_weight"], 185.0)
        # sets x reps x weight — the number overload moves
        self.assertEqual(resp.data["routine_exercise"]["target_volume"], 4 * 8 * 185.0)

        self.client.post(f"/api/bodiez/routines/{rid}/exercises/",
                         {"exercise_id": fly.id, "sets": 3, "reps": 12,
                          "rest_seconds": 60, "superset_group": "A"}, format="json")
        routine = self.client.get(f"/api/bodiez/routines/{rid}/").data["routine"]
        self.assertEqual(len(routine["exercises"]), 2)
        self.assertEqual({e["superset_group"] for e in routine["exercises"]}, {"A"})
        self.assertIn("chest", routine["muscles"])
        self.assertGreater(routine["estimated_minutes"], 0)

    def test_estimated_duration_counts_rest_because_rest_dominates(self):
        rid = self._routine().data["routine"]["id"]
        bench = Exercise.objects.get(key="bench-press", owner=None)
        self.client.post(f"/api/bodiez/routines/{rid}/exercises/",
                         {"exercise_id": bench.id, "sets": 5, "rest_seconds": 180},
                         format="json")
        r = Routine.objects.get(pk=rid)
        # 5 sets x (45s work + 180s rest) = 1125s ~ 19 min
        self.assertEqual(r.estimated_minutes, 19)

    def test_routines_live_in_buckets_and_default_to_anytime(self):
        rid = self._routine().data["routine"]["id"]
        self.assertEqual(Routine.objects.get(pk=rid).bucket, "anytime")
        self.client.patch(f"/api/bodiez/routines/{rid}/", {"bucket": "today"},
                          format="json")
        self.assertEqual(Routine.objects.get(pk=rid).bucket, "today")
        listed = self.client.get("/api/bodiez/routines/?bucket=today").data["routines"]
        self.assertEqual(len(listed), 1)

    def test_delete_trashes_first_and_only_deletes_from_trash(self):
        rid = self._routine().data["routine"]["id"]
        resp = self.client.delete(f"/api/bodiez/routines/{rid}/")
        self.assertIn("trashed", resp.data)
        self.assertTrue(Routine.objects.filter(pk=rid).exists())
        resp = self.client.delete(f"/api/bodiez/routines/{rid}/")
        self.assertIn("deleted", resp.data)
        self.assertFalse(Routine.objects.filter(pk=rid).exists())

    def test_trashed_routines_are_out_of_the_default_list(self):
        rid = self._routine().data["routine"]["id"]
        self.client.delete(f"/api/bodiez/routines/{rid}/")
        self.assertEqual(self.client.get("/api/bodiez/routines/").data["routines"], [])

    def test_a_custom_exercise_can_be_added_and_used(self):
        resp = self.client.post("/api/bodiez/exercises/",
                                {"name": "Reverse Hyper", "muscle": "glutes",
                                 "equipment": ["machine"], "pattern": "hinge"},
                                format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.data["exercise"]["custom"])
        rid = self._routine().data["routine"]["id"]
        add = self.client.post(f"/api/bodiez/routines/{rid}/exercises/",
                               {"exercise_id": resp.data["exercise"]["id"]}, format="json")
        self.assertEqual(add.status_code, 201)

    def test_another_members_custom_exercise_is_not_usable(self):
        other = User.objects.create_user("other", "o@e.com", "pw12345678")
        theirs = Exercise.objects.create(key="theirs", name="Theirs", owner=other,
                                         muscle="chest")
        rid = self._routine().data["routine"]["id"]
        resp = self.client.post(f"/api/bodiez/routines/{rid}/exercises/",
                                {"exercise_id": theirs.id}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_the_exercise_filter_respects_equipment(self):
        data = self.client.get("/api/bodiez/exercises/?equipment=bodyweight").data
        keys = {e["key"] for e in data["exercises"]}
        self.assertIn("push-up", keys)
        self.assertNotIn("bench-press", keys)


class SessionTests(TestCase):
    def setUp(self):
        seed()
        self.client = APIClient()
        self.user = User.objects.create_user("lifter", "l@e.com", "pw12345678")
        self.client.force_authenticate(self.user)
        self.bench = Exercise.objects.get(key="bench-press", owner=None)

    def _session(self):
        return self.client.post("/api/bodiez/sessions/", {}, format="json").data["session"]["id"]

    def test_log_sets_and_finish(self):
        sid = self._session()
        for n, (w, reps) in enumerate([(135, 10), (155, 8), (175, 6)], start=1):
            resp = self.client.post(f"/api/bodiez/sessions/{sid}/sets/",
                                    {"exercise_id": self.bench.id, "set_number": n,
                                     "weight": w, "reps": reps, "rpe": 8.5,
                                     "rest_seconds": 180}, format="json")
            self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["session_volume"], 135 * 10 + 155 * 8 + 175 * 6)

        done = self.client.post(f"/api/bodiez/sessions/{sid}/finish/",
                                {"perceived_effort": 8}, format="json")
        self.assertEqual(done.data["session"]["status"], "done")
        self.assertIsNotNone(done.data["session"]["ended_at"])

    def test_a_finished_session_lands_in_the_logbook(self):
        sid = self._session()
        self.client.post(f"/api/bodiez/sessions/{sid}/sets/",
                         {"exercise_id": self.bench.id, "weight": 135, "reps": 10},
                         format="json")
        self.client.post(f"/api/bodiez/sessions/{sid}/finish/", {}, format="json")
        self.assertTrue(BodieZItem.objects.filter(user=self.user, bucket="logbook").exists())

    def test_only_one_session_can_be_live_at_a_time(self):
        """Two open sessions means sets landing in the wrong one."""
        self._session()
        resp = self.client.post("/api/bodiez/sessions/", {}, format="json")
        self.assertEqual(resp.status_code, 409)

    def test_set_numbers_auto_increment_per_exercise(self):
        sid = self._session()
        for _ in range(3):
            self.client.post(f"/api/bodiez/sessions/{sid}/sets/",
                             {"exercise_id": self.bench.id, "weight": 100, "reps": 5},
                             format="json")
        numbers = list(WorkoutSet.objects.filter(session_id=sid).values_list(
            "set_number", flat=True))
        self.assertEqual(sorted(numbers), [1, 2, 3])

    def test_warmups_do_not_count_toward_volume(self):
        sid = self._session()
        self.client.post(f"/api/bodiez/sessions/{sid}/sets/",
                         {"exercise_id": self.bench.id, "weight": 45, "reps": 20,
                          "is_warmup": True}, format="json")
        resp = self.client.post(f"/api/bodiez/sessions/{sid}/sets/",
                                {"exercise_id": self.bench.id, "weight": 135, "reps": 10},
                                format="json")
        self.assertEqual(resp.data["session_volume"], 1350)

    def test_estimated_1rm_refuses_to_flatter_you_past_12_reps(self):
        s = WorkoutSession.objects.create(user=self.user)
        low = WorkoutSet.objects.create(session=s, exercise=self.bench, weight=200, reps=5)
        high = WorkoutSet.objects.create(session=s, exercise=self.bench, weight=95, reps=30)
        self.assertAlmostEqual(low.estimated_1rm, 233.3, places=1)
        self.assertIsNone(high.estimated_1rm)

    def test_a_finished_session_refuses_more_sets(self):
        sid = self._session()
        self.client.post(f"/api/bodiez/sessions/{sid}/finish/", {}, format="json")
        resp = self.client.post(f"/api/bodiez/sessions/{sid}/sets/",
                                {"exercise_id": self.bench.id, "weight": 100, "reps": 5},
                                format="json")
        self.assertEqual(resp.status_code, 400)

    def test_another_members_session_is_a_404(self):
        other = User.objects.create_user("other", "o@e.com", "pw12345678")
        theirs = WorkoutSession.objects.create(user=other)
        self.assertEqual(self.client.post(f"/api/bodiez/sessions/{theirs.id}/sets/",
                                          {"exercise_id": self.bench.id}, format="json"
                                          ).status_code, 404)


class CoachTests(TestCase):
    """Progressive overload. Conservative on purpose."""

    def setUp(self):
        seed()
        self.user = User.objects.create_user("lifter", "l@e.com", "pw12345678")
        self.bench = Exercise.objects.get(key="bench-press", owner=None)
        self.routine = Routine.objects.create(owner=self.user, name="Push")
        self.re = RoutineExercise.objects.create(
            routine=self.routine, exercise=self.bench, sets=3, reps=8, target_weight=185)

    def _log(self, reps_per_set, weight=185, days_ago=0):
        s = WorkoutSession.objects.create(user=self.user, status="done")
        WorkoutSession.objects.filter(pk=s.pk).update(
            started_at=timezone.now() - timedelta(days=days_ago))
        for n, reps in enumerate(reps_per_set, start=1):
            WorkoutSet.objects.create(session=s, exercise=self.bench, set_number=n,
                                      weight=weight, reps=reps, completed=True)
        return s

    def test_no_data_says_so_instead_of_guessing(self):
        v = coach.overload_verdict(self.user, self.re)
        self.assertEqual(v["verdict"], coach.VERDICT_UNKNOWN)

    def test_two_clean_sessions_earn_a_weight_increase(self):
        self._log([8, 8, 8], days_ago=7)
        self._log([8, 8, 8], days_ago=3)
        v = coach.overload_verdict(self.user, self.re)
        self.assertEqual(v["verdict"], coach.VERDICT_INCREASE)
        self.assertGreater(v["suggested_weight"], 185)

    def test_one_good_session_is_not_enough(self):
        """One good day is noise. This is the rule that stops people getting hurt."""
        self._log([6, 6, 5], days_ago=7)
        self._log([8, 8, 8], days_ago=3)
        v = coach.overload_verdict(self.user, self.re)
        self.assertNotEqual(v["verdict"], coach.VERDICT_INCREASE)

    def test_just_missing_the_target_says_repeat(self):
        self._log([8, 8, 7], days_ago=3)
        v = coach.overload_verdict(self.user, self.re)
        self.assertEqual(v["verdict"], coach.VERDICT_REPEAT)
        self.assertEqual(v["suggested_weight"], 185)

    def test_missing_badly_says_reduce(self):
        self._log([5, 4, 3], days_ago=3)
        v = coach.overload_verdict(self.user, self.re)
        self.assertEqual(v["verdict"], coach.VERDICT_REDUCE)
        self.assertLess(v["suggested_weight"], 185)

    def test_three_sessions_of_falling_volume_says_deload(self):
        self._log([8, 8, 8], weight=185, days_ago=21)
        self._log([7, 7, 7], weight=185, days_ago=14)
        self._log([5, 5, 5], weight=185, days_ago=7)
        v = coach.overload_verdict(self.user, self.re)
        self.assertEqual(v["verdict"], coach.VERDICT_DELOAD)
        self.assertLess(v["suggested_weight"], 185 * 0.7)

    def test_bodymap_marks_untrained_muscles_undertrained(self):
        self._log([8, 8, 8], days_ago=1)
        m = coach.body_map(self.user)
        by_muscle = {r["muscle"]: r for r in m["muscles"]}
        self.assertEqual(by_muscle["chest"]["state"], "light")     # 3 sets is light
        self.assertEqual(by_muscle["upper-leg"]["state"], "undertrained")
        self.assertIn("upper-leg", m["weakest"])

    def test_bodymap_gives_secondary_muscles_half_credit(self):
        """A bench press trains triceps, but not the way a pushdown does."""
        self._log([8, 8, 8, 8], days_ago=1)
        by_muscle = {r["muscle"]: r for r in coach.body_map(self.user)["muscles"]}
        self.assertEqual(by_muscle["chest"]["sets"], 4)
        self.assertEqual(by_muscle["tricep"]["sets"], 2.0)

    def test_bodymap_flags_overwork(self):
        for day in range(1, 5):
            self._log([8] * 8, days_ago=day)
        by_muscle = {r["muscle"]: r for r in coach.body_map(self.user)["muscles"]}
        self.assertEqual(by_muscle["chest"]["state"], "overworked")

    def test_readiness_is_honest_about_what_it_is_not(self):
        r = coach.readiness(self.user)
        self.assertIn("no sleep or HRV", r["basis"])
        self.assertEqual(r["state"], "fresh")

    def test_readiness_calls_a_hard_week_fatigued(self):
        for day in range(1, 7):
            s = self._log([8, 8, 8], days_ago=day)
            s.perceived_effort = 9
            s.save(update_fields=["perceived_effort"])
        self.assertEqual(coach.readiness(self.user)["state"], "fatigued")


class ProgressTests(TestCase):
    def setUp(self):
        seed()
        self.client = APIClient()
        self.user = User.objects.create_user("lifter", "l@e.com", "pw12345678")
        self.client.force_authenticate(self.user)
        self.bench = Exercise.objects.get(key="bench-press", owner=None)

    def _session(self, days_ago, weight=185):
        s = WorkoutSession.objects.create(user=self.user, status="done",
                                          ended_at=timezone.now())
        WorkoutSession.objects.filter(pk=s.pk).update(
            started_at=timezone.now() - timedelta(days=days_ago))
        WorkoutSet.objects.create(session=s, exercise=self.bench, weight=weight, reps=8)
        return s

    def test_progress_reports_volume_prs_and_streak(self):
        self._session(0, 185)
        self._session(1, 175)
        self._session(2, 165)
        data = self.client.get("/api/bodiez/progress/").data
        self.assertEqual(data["sessions"], 3)
        self.assertEqual(data["streak_days"], 3)
        self.assertEqual(data["personal_records"][0]["best_weight"], 185.0)
        self.assertGreater(data["total_volume"], 0)

    def test_a_streak_survives_training_yesterday(self):
        """A streak that dies at midnight punishes people for training at 9pm
        and not opening the app after."""
        self._session(1)
        self._session(2)
        self.assertEqual(self.client.get("/api/bodiez/progress/").data["streak_days"], 2)

    def test_a_gap_breaks_the_streak(self):
        self._session(0)
        self._session(5)
        self.assertEqual(self.client.get("/api/bodiez/progress/").data["streak_days"], 1)

    def test_bodyweight_change_comes_from_the_check_ins(self):
        BodyMetric.objects.create(user=self.user, date=date.today() - timedelta(days=30),
                                  weight=200)
        BodyMetric.objects.create(user=self.user, date=date.today(), weight=190)
        bw = self.client.get("/api/bodiez/progress/").data["bodyweight"]
        self.assertEqual(bw["change"], -10.0)

    def test_a_check_in_twice_in_a_day_updates_rather_than_duplicates(self):
        self.client.post("/api/bodiez/metrics/", {"weight": 200}, format="json")
        resp = self.client.post("/api/bodiez/metrics/", {"weight": 199}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(BodyMetric.objects.filter(user=self.user).count(), 1)
        self.assertEqual(float(BodyMetric.objects.get().weight), 199.0)


class BucketTests(TestCase):
    """The Lilith layer — what makes this a system rather than a logger."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("lifter", "l@e.com", "pw12345678")
        self.client.force_authenticate(self.user)

    def test_capture_lands_in_the_inbox_by_default(self):
        resp = self.client.post("/api/bodiez/items/",
                                {"title": "try that hamstring curl variation"},
                                format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["item"]["bucket"], "inbox")

    def test_items_move_between_buckets(self):
        iid = self.client.post("/api/bodiez/items/", {"title": "deload week"},
                               format="json").data["item"]["id"]
        for bucket in ("someday", "upcoming", "today", "anytime"):
            resp = self.client.patch(f"/api/bodiez/items/{iid}/", {"bucket": bucket},
                                     format="json")
            self.assertEqual(resp.data["item"]["bucket"], bucket)

    def test_the_bucket_list_carries_labels_with_their_emoji(self):
        """The emoji is part of the tab name in this paradigm, not decoration."""
        data = self.client.get("/api/bodiez/items/").data
        labels = {b["key"]: b["label"] for b in data["buckets"]}
        self.assertEqual(labels["inbox"], "Inbox 📥")
        self.assertEqual(labels["today"], "Today 💪")
        self.assertEqual(labels["logbook"], "Logbook 🧾")

    def test_delete_trashes_first(self):
        iid = self.client.post("/api/bodiez/items/", {"title": "x"},
                               format="json").data["item"]["id"]
        self.assertIn("trashed", self.client.delete(f"/api/bodiez/items/{iid}/").data)
        self.assertIn("deleted", self.client.delete(f"/api/bodiez/items/{iid}/").data)

    def test_another_members_item_is_a_404(self):
        other = User.objects.create_user("other", "o@e.com", "pw12345678")
        theirs = BodieZItem.objects.create(user=other, title="theirs")
        self.assertEqual(self.client.patch(f"/api/bodiez/items/{theirs.id}/",
                                           {"bucket": "today"}, format="json"
                                           ).status_code, 404)


class TierGateTests(TestCase):
    """Free trains. Premium gets locations. StatZ gets the coach and the shared
    routines. Nothing about tracking your own training is paywalled."""

    def setUp(self):
        seed()
        self.client = APIClient()
        self.user = User.objects.create_user("lifter", "l@e.com", "pw12345678")
        self.client.force_authenticate(self.user)

    def _tier(self, tier):
        m = membership_for(self.user)
        m.tier = tier
        m.save(update_fields=["tier", "updated_at"])

    def test_free_can_do_the_whole_training_loop(self):
        self._tier(TIER_FREE)
        rid = self.client.post("/api/bodiez/routines/", {"name": "Push"},
                               format="json").data["routine"]["id"]
        sid = self.client.post("/api/bodiez/sessions/", {"routine_id": rid},
                               format="json").data["session"]["id"]
        bench = Exercise.objects.get(key="bench-press", owner=None)
        self.assertEqual(self.client.post(f"/api/bodiez/sessions/{sid}/sets/",
                                          {"exercise_id": bench.id, "weight": 135,
                                           "reps": 10}, format="json").status_code, 201)
        for url in ("/api/bodiez/progress/", "/api/bodiez/bodymap/", "/api/bodiez/coach/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_locations_are_premium(self):
        self._tier(TIER_FREE)
        resp = self.client.get("/api/bodiez/locations/")
        self.assertEqual(resp.status_code, 402)
        self.assertEqual(resp.data["required_tier"], "premium")

        self._tier(TIER_PREMIUM)
        self.assertEqual(self.client.get("/api/bodiez/locations/").status_code, 200)

    def test_a_location_reports_what_it_cannot_train(self):
        """The metric worth having: not 'has 12 machines' but 'you cannot train
        biceps here'. A treadmill room plus your own body covers a surprising
        amount — and leaves four real holes."""
        self._tier(TIER_PREMIUM)
        resp = self.client.post("/api/bodiez/locations/",
                                {"name": "Treadmill closet",
                                 "equipment": ["cardio-machine"]}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        coverage = resp.data["location"]["muscle_coverage"]
        gaps = resp.data["location"]["gaps"]
        self.assertIn("chest", coverage)          # push-ups
        self.assertIn("abz", coverage)            # planks
        # Bodyweight covers a lot; what's left needs something to hold.
        self.assertEqual(set(gaps), {"forearm", "wrist"})

    def test_one_pair_of_dumbbells_closes_every_gap(self):
        """Worth knowing, and the kind of thing a coverage metric is for."""
        self._tier(TIER_PREMIUM)
        resp = self.client.post("/api/bodiez/locations/",
                                {"name": "Garage", "equipment": ["dumbbell"]},
                                format="json")
        self.assertEqual(resp.data["location"]["gaps"], [])

    def test_the_ai_coach_is_open_to_every_tier(self):
        """Locking it away entirely means a free member never finds out it's
        good. They spend a daily prompt instead."""
        self._tier(TIER_FREE)
        plan = ('{"name": "Home", "exercises": [{"key": "push-up", "sets": 3, '
                '"reps": 12, "rest_seconds": 60}]}')

        class _B:
            type, text = "text", plan

        class _R:
            content = [_B()]

        with patch("apps.economy.occ._create_with_fallback", return_value=_R()), \
                patch("anthropic.Anthropic"):
            resp = self.client.post("/api/bodiez/routines/ai/",
                                    {"equipment": ["bodyweight"]}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        # a free daily prompt covered it, so nothing was charged in cash
        self.assertEqual(resp.data["daily_prompts"]["allowance"], 3)
        self.assertEqual(resp.data["daily_prompts"]["used"], 1)

    def test_shared_routines_are_statz(self):
        self._tier(TIER_PREMIUM)
        resp = self.client.get("/api/bodiez/routines/?shared=1")
        self.assertEqual(resp.status_code, 402)

        self._tier(TIER_STATZ)
        other = User.objects.create_user("pro", "p@e.com", "pw12345678")
        Routine.objects.create(owner=other, name="Their PPL", is_public=True)
        Routine.objects.create(owner=other, name="Their draft", is_public=False)
        rows = self.client.get("/api/bodiez/routines/?shared=1").data["routines"]
        self.assertEqual([r["name"] for r in rows], ["Their PPL"])

    def test_a_private_routine_stays_private_even_from_statz(self):
        self._tier(TIER_STATZ)
        other = User.objects.create_user("pro", "p@e.com", "pw12345678")
        theirs = Routine.objects.create(owner=other, name="Draft", is_public=False)
        self.assertEqual(self.client.get(f"/api/bodiez/routines/{theirs.id}/").status_code,
                         404)


class AICoachTests(TestCase):
    def setUp(self):
        seed()
        self.client = APIClient()
        self.user = User.objects.create_user("pro", "p@e.com", "pw12345678")
        m = membership_for(self.user)
        m.tier = TIER_STATZ
        m.save(update_fields=["tier", "updated_at"])
        self.client.force_authenticate(self.user)

    def _reply(self, payload):
        class _B:
            type = "text"
            text = payload

        class _R:
            content = [_B()]
        return _R()

    def test_statz_runs_the_coach_without_spending_a_prompt(self):
        plan = ('{"name": "Home", "exercises": [{"key": "push-up", "sets": 3, '
                '"reps": 12, "rest_seconds": 60}]}')
        with patch("apps.economy.occ._create_with_fallback",
                   return_value=self._reply(plan)), patch("anthropic.Anthropic"):
            resp = self.client.post("/api/bodiez/routines/ai/",
                                    {"equipment": ["bodyweight"]}, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["cost_cents"], 0)
        self.assertEqual(resp.data["daily_prompts"]["used"], 0)

    def test_a_failed_run_costs_nothing(self):
        """A coach that didn't produce a plan is not a prompt you spent."""
        from apps.economy.models import daily_prompt_state
        with patch("apps.economy.occ._create_with_fallback",
                   return_value=self._reply("nope")), patch("anthropic.Anthropic"):
            self.client.post("/api/bodiez/routines/ai/",
                             {"equipment": ["bodyweight"]}, format="json")
        self.assertEqual(daily_prompt_state(self.user)[1], 0)

    def test_the_coach_writes_a_routine_from_the_catalog(self):
        plan = ('{"name": "Home Push", "goal": "hypertrophy", "split": "push-pull-legs",'
                ' "days_per_week": 3, "exercises": ['
                '{"key": "push-up", "sets": 4, "reps": 15, "rest_seconds": 60},'
                '{"key": "diamond-push-up", "sets": 3, "reps": 12, "rest_seconds": 60}]}')
        with patch("apps.economy.occ._create_with_fallback", return_value=self._reply(plan)), \
                patch("anthropic.Anthropic"):
            resp = self.client.post("/api/bodiez/routines/ai/",
                                    {"goal": "hypertrophy", "equipment": ["bodyweight"]},
                                    format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["routine"]["name"], "Home Push")
        self.assertEqual(len(resp.data["routine"]["exercises"]), 2)

    def test_exercises_the_member_cannot_perform_are_dropped(self):
        """A model that hallucinates one lift shouldn't produce a routine that
        half-works."""
        plan = ('{"name": "Bad", "exercises": ['
                '{"key": "push-up", "sets": 3, "reps": 10},'
                '{"key": "bench-press", "sets": 3, "reps": 10},'
                '{"key": "not-a-real-lift", "sets": 3, "reps": 10}]}')
        with patch("apps.economy.occ._create_with_fallback", return_value=self._reply(plan)), \
                patch("anthropic.Anthropic"):
            resp = self.client.post("/api/bodiez/routines/ai/",
                                    {"equipment": ["bodyweight"]}, format="json")
        self.assertEqual(resp.status_code, 201)
        keys = [e["exercise"]["key"] for e in resp.data["routine"]["exercises"]]
        self.assertEqual(keys, ["push-up"])

    def test_an_unusable_reply_is_a_503_not_an_empty_routine(self):
        with patch("apps.economy.occ._create_with_fallback",
                   return_value=self._reply("sure thing boss")), \
                patch("anthropic.Anthropic"):
            resp = self.client.post("/api/bodiez/routines/ai/",
                                    {"equipment": ["bodyweight"]}, format="json")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(Routine.objects.count(), 0)

    def test_no_matching_equipment_is_refused_with_advice(self):
        # Jump rope plus your own body trains plenty — but not wrists.
        plan, err = coach.ai_plan(self.user, "strength", equipment=["jump-rope"],
                                  focus=["wrist"])
        self.assertIsNone(plan)
        self.assertIn("bodyweight alone", err)
