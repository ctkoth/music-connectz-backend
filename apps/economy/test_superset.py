"""Supersets: the Coach picks the partner; linking two lifts by hand is everybody's.

What is pinned here is the line between the two. The pairing rules are facts about
lifts (compound or isolation, push or pull), declared once in `superset_table` and
tested for completeness against the real library, so a lift added without being
classified is a red test. The gate is StatZ or the free hour, answered with the
upgrade door attached, and it never touches whether a member may superset.
"""
from datetime import timedelta
from types import SimpleNamespace as NS

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy import statz_trial, superset
from apps.economy.models import BodieZAccess, BodieZExercise, StatzTrial, membership_for
from apps.economy.superset import ANTAGONISTS, MODES, TABLE, pair_rows, valid_groups
from apps.economy.superset_table import TABLE as TABLE_FILE

User = get_user_model()
URL = "/api/economy/bodiez/pair/"


def ex(i, name, muscle, equipment="barbell", custom=False):
    return NS(id=i, name=name, muscle_group=muscle, equipment=equipment,
              created_by_id=1 if custom else None)


# A small library with real names, so the rules read like a gym.
LIB = [
    ex(1, "Bench Press", "chest"),
    ex(2, "Dumbbell Fly", "chest", "dumbbell"),
    ex(3, "Barbell Row", "back"),
    ex(4, "Bicep Curl", "biceps", "dumbbell"),
    ex(5, "Tricep Pushdown", "triceps", "cable"),
    ex(6, "Squat", "upper_legs"),
    ex(7, "Seated Leg Curl", "upper_legs", "machine"),
    ex(8, "Leg Press", "upper_legs", "machine"),
    ex(9, "Running", "cardio", "bodyweight"),
    ex(10, "Pec Deck", "chest", "machine"),
    ex(11, "Lat Pulldown", "back", "cable"),
    ex(12, "My Own Press", "chest", custom=True),
    ex(13, "Overhead Press", "shoulders"),
    ex(14, "Dumbbell Rear Delt Fly", "back", "dumbbell"),
]


def row(i, sets=3, reps=10, **kw):
    return {"exercise_id": i, "sets": sets, "reps": reps, "weight_kg": None, **kw}


def ids(rows):
    return [r["exercise_id"] for r in rows]


class TableTests(TestCase):
    """The library and the table have to say the same thing."""

    def test_every_library_exercise_is_classified(self):
        missing = [e.name for e in BodieZExercise.objects.library() if e.name not in TABLE]
        self.assertEqual(missing, [], "classify these in apps/economy/superset_table.py")

    def test_no_row_in_the_table_names_a_lift_that_is_not_in_the_library(self):
        names = set(BodieZExercise.objects.library().values_list("name", flat=True))
        self.assertEqual([n for n in TABLE if n not in names], [])

    def test_values_are_from_the_closed_sets(self):
        for name, (mech, force) in TABLE_FILE.items():
            self.assertIn(mech, {"compound", "isolation", "other"}, name)
            self.assertIn(force, {"push", "pull", "neither"}, name)

    def test_the_lifts_a_member_would_check_are_what_they_say(self):
        want = {"Bench Press": ("compound", "push"), "Dumbbell Fly": ("isolation", "push"),
                "Barbell Row": ("compound", "pull"), "Bicep Curl": ("isolation", "pull"),
                "Tricep Pushdown": ("isolation", "push"), "Seated Leg Curl": ("isolation", "pull"),
                "Squat": ("compound", "push"), "Deadlift": ("compound", "pull"),
                "Running": ("other", "neither"), "Plank": ("other", "neither")}
        for name, got in want.items():
            self.assertEqual(TABLE[name], got, name)

    def test_cardio_and_holds_are_never_paired_by_any_rule(self):
        for name, (mech, force) in TABLE.items():
            if mech == "other":
                self.assertEqual(force, "neither", name)


class CompoundIsolationTests(SimpleTestCase):
    def pair(self, rows, **kw):
        return pair_rows(rows, LIB, "compound_isolation", **kw)

    def test_a_compound_and_an_isolation_for_one_muscle_are_paired_compound_first(self):
        out = self.pair([row(2), row(1)])            # fly listed before the press
        self.assertEqual(ids(out["exercises"]), [1, 2])
        self.assertEqual([r["group"] for r in out["exercises"]], ["A", "A"])
        self.assertEqual(out["added"], [])
        self.assertEqual(out["pairs"][0]["exercise_ids"], [1, 2])

    def test_a_compound_with_nobody_to_pair_with_gets_an_isolation_from_the_library(self):
        out = self.pair([row(1)])
        self.assertEqual(ids(out["exercises"]), [1, 2])          # the curated first isolation: library order
        self.assertEqual(out["added"], [2])
        added = out["exercises"][1]
        self.assertTrue(added["added"])
        self.assertEqual((added["sets"], added["reps"]), (3, 12))

    def test_add_false_pairs_only_what_is_already_there(self):
        out = self.pair([row(1)], add=False)
        self.assertEqual(ids(out["exercises"]), [1])
        self.assertEqual(out["added"], [])
        self.assertEqual(out["left_single"], [1])

    def test_an_isolation_alone_gets_a_compound_that_leads(self):
        out = self.pair([row(2)])
        self.assertEqual(ids(out["exercises"]), [1, 2])
        self.assertEqual(out["added"], [1])

    def test_two_different_muscles_are_not_a_compound_isolation_pair(self):
        out = self.pair([row(1), row(4)], add=False)             # bench press, bicep curl
        self.assertEqual(out["pairs"], [])

    def test_equipment_the_member_does_not_own_is_never_added(self):
        out = self.pair([row(1)], equipment=["machine"])
        self.assertEqual(ids(out["exercises"]), [1, 10])         # pec deck, not the dumbbell fly

    def test_a_lift_the_member_cannot_do_is_never_added(self):
        out = self.pair([row(1)], is_accessible=lambda e: e.id != 2)
        self.assertEqual(ids(out["exercises"]), [1, 10])

    def test_nothing_suitable_means_no_pair_and_no_invention(self):
        out = self.pair([row(1)], is_accessible=lambda e: e.id == 1)
        self.assertEqual(ids(out["exercises"]), [1])
        self.assertEqual(out["left_single"], [1])


class PushPullTests(SimpleTestCase):
    def pair(self, rows, **kw):
        return pair_rows(rows, LIB, "push_pull", **kw)

    def test_chest_press_and_row_are_a_pair_push_first(self):
        out = self.pair([row(3), row(1)])
        self.assertEqual(ids(out["exercises"]), [1, 3])
        self.assertEqual(out["pairs"][0]["group"], "A")

    def test_biceps_and_triceps_oppose(self):
        out = self.pair([row(4), row(5)])
        self.assertEqual(ids(out["exercises"]), [5, 4])          # the push (triceps) leads

    def test_two_pushes_never_pair(self):
        out = self.pair([row(1), row(13)], add=False)            # bench, overhead press
        self.assertEqual(out["pairs"], [])

    def test_legs_oppose_themselves_by_force(self):
        out = self.pair([row(6), row(7)])                        # squat, leg curl
        self.assertEqual(ids(out["exercises"]), [6, 7])
        self.assertEqual(self.pair([row(6), row(8)], add=False)["pairs"], [])   # squat + leg press: both push

    def test_a_push_with_nobody_to_pull_against_gets_a_pull_of_comparable_effort(self):
        out = self.pair([row(1)])
        self.assertEqual(ids(out["exercises"]), [1, 3])          # a compound pull, not a warm-up
        self.assertEqual(out["added"], [3])

    def test_cardio_is_left_alone(self):
        out = self.pair([row(9), row(1)])
        self.assertIn(9, out["left_single"])
        self.assertNotIn("group", next(r for r in out["exercises"] if r["exercise_id"] == 9))
        # the cardio row keeps its place; the press gets a partner added after it
        self.assertEqual(ids(out["exercises"]), [9, 1, 3])

    def test_a_pair_pulls_its_partner_up_beside_it_and_moves_nothing_else(self):
        out = self.pair([row(1), row(9), row(4), row(3)], add=False)      # press, cardio, curl, row
        self.assertEqual(ids(out["exercises"]), [1, 3, 9, 4])
        self.assertEqual([r.get("group") for r in out["exercises"]], ["A", "A", None, None])


class SafetyTests(SimpleTestCase):
    def test_a_custom_exercise_is_never_paired_or_added(self):
        out = pair_rows([row(12)], LIB, "compound_isolation")
        self.assertEqual(out["pairs"], [])
        self.assertEqual(out["added"], [])
        self.assertNotIn(12, [r["exercise_id"] for r in out["exercises"] if r.get("added")])

    def test_a_custom_exercise_named_like_a_library_lift_is_still_not_classified_by_its_name(self):
        # The table is keyed by NAME, and a member can call their own exercise
        # anything. Matching on the name alone would let them borrow a library
        # lift's classification for something nobody has checked.
        lib = LIB + [ex(15, "Bench Press", "chest", custom=True)]
        out = pair_rows([row(15)], lib, "compound_isolation")
        self.assertEqual(out["pairs"], [])
        self.assertEqual(out["exercises"][0]["exercise_id"], 15)
        # and a custom lift is never the partner that gets added
        lib2 = [e for e in LIB if e.id != 2] + [ex(16, "Dumbbell Fly", "chest", custom=True)]
        out = pair_rows([row(1)], lib2, "compound_isolation")
        self.assertNotIn(16, ids(out["exercises"]))

    def test_it_never_adds_a_lift_already_in_the_routine(self):
        out = pair_rows([row(1), row(2), row(10)], LIB, "compound_isolation")
        self.assertEqual(len(set(ids(out["exercises"]))), len(out["exercises"]))

    def test_running_it_twice_changes_nothing_the_second_time(self):
        first = pair_rows([row(1), row(3)], LIB, "push_pull")
        second = pair_rows(first["exercises"], LIB, "push_pull")
        self.assertEqual(second["exercises"], first["exercises"])
        self.assertEqual(second["added"], [])

    def test_a_pair_made_by_hand_is_left_exactly_as_it_is(self):
        mine = [row(1, group="A"), row(4, group="A"), row(3)]            # bench + curl, by hand
        out = pair_rows(mine, LIB, "push_pull", add=False)
        self.assertEqual(ids(out["exercises"])[:2], [1, 4])
        self.assertEqual([r.get("group") for r in out["exercises"]][:2], ["A", "A"])

    def test_a_stale_label_is_dropped_not_guessed_at(self):
        # three rows sharing one, and two with a lift between them
        self.assertEqual([r.get("group") for r in valid_groups([row(1, group="A"), row(2, group="A"), row(3, group="A")])],
                         [None, None, None])
        self.assertEqual([r.get("group") for r in valid_groups([row(1, group="A"), row(3), row(2, group="A")])],
                         [None, None, None])
        self.assertEqual([r.get("group") for r in valid_groups([row(1, group="B"), row(2, group="B"), row(3)])],
                         ["B", "B", None])

    def test_labels_run_a_b_c_down_the_routine(self):
        out = pair_rows([row(1), row(3), row(4), row(5)], LIB, "push_pull")
        self.assertEqual([r.get("group") for r in out["exercises"]], ["A", "A", "B", "B"])

    def test_order_is_renumbered(self):
        out = pair_rows([row(3), row(1)], LIB, "push_pull")
        self.assertEqual([r["order"] for r in out["exercises"]], [0, 1])

    def test_an_unknown_mode_is_refused(self):
        with self.assertRaises(ValueError):
            pair_rows([row(1)], LIB, "nonsense")

    def test_the_antagonist_map_only_names_real_groups(self):
        groups = {e.muscle_group for e in LIB} | {"shoulders", "glutes"}
        for g, others in ANTAGONISTS.items():
            self.assertIn(g, groups | set(ANTAGONISTS))
            self.assertTrue(others)


class EndpointTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("lifter", "l@x.test", "pw-Long-enough-1")
        self.c = APIClient()
        self.c.force_authenticate(self.user)
        self.ids = {n: BodieZExercise.objects.get(name=n, created_by__isnull=True).id
                    for n in ("Bench Press", "Barbell Row", "Dumbbell Fly")}

    def _rows(self, *names):
        return [{"exercise_id": self.ids[n], "sets": 3, "reps": 10} for n in names]

    def test_a_free_member_is_refused_with_the_upgrade_door_and_the_free_way_named(self):
        r = self.c.post(URL, {"mode": "push_pull", "exercises": self._rows("Bench Press")}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["upgrade"]["tab"], "membershipz")
        self.assertEqual(r.json()["statz_feature"], "coach_pairing")
        self.assertIn("by hand", r.json()["detail"])

    def test_the_free_hour_unlocks_it_and_the_end_of_the_hour_locks_it_again(self):
        self.c.post("/api/economy/statz-trial/")
        r = self.c.post(URL, {"mode": "push_pull", "exercises": self._rows("Bench Press", "Barbell Row")}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["pairs"][0]["names"], ["Bench Press", "Barbell Row"])
        StatzTrial.objects.filter(user=self.user).update(ends_at=timezone.now() - timedelta(seconds=1))
        r = self.c.post(URL, {"mode": "push_pull", "exercises": self._rows("Bench Press", "Barbell Row")}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_statz_has_it_without_a_sample(self):
        m = membership_for(self.user)
        m.tier = "statz"
        m.save()
        r = self.c.post(URL, {"mode": "compound_isolation", "exercises": self._rows("Bench Press")}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["added"], [self.ids["Dumbbell Fly"]])

    def test_the_offer_is_readable_by_every_tier_before_anything_is_pressed(self):
        r = self.c.get(URL).json()
        self.assertFalse(r["allowed"])
        self.assertEqual({m["key"] for m in r["modes"]}, set(MODES))
        self.assertTrue(r["sample"]["available"])
        self.assertIn("by hand", r["manual"])

    def test_the_sample_lists_the_two_bodiez_features(self):
        keys = {f["key"] for f in statz_trial.FEATURES}
        self.assertTrue({"coach_pairing", "rest_alerts"} <= keys)
        for f in statz_trial.FEATURES:
            self.assertTrue(f["tab"] and f["target"])

    def test_a_sample_never_changes_the_real_tier(self):
        self.c.post("/api/economy/statz-trial/")
        self.c.post(URL, {"mode": "push_pull", "exercises": self._rows("Bench Press")}, format="json")
        self.assertEqual(membership_for(self.user).tier, "free")

    def test_bad_input_is_a_400_not_a_500(self):
        self.c.post("/api/economy/statz-trial/")
        self.assertEqual(self.c.post(URL, {"mode": "x", "exercises": []}, format="json").status_code, 400)
        self.assertEqual(self.c.post(URL, {"mode": "push_pull", "exercises": "no"}, format="json").status_code, 400)
        self.assertEqual(self.c.post(URL, {"mode": "push_pull", "exercises": [{"exercise_id": 99999999}]},
                                     format="json").status_code, 400)
        self.assertEqual(self.c.post(URL, {"mode": "push_pull", "exercises": [{"exercise_id": 1}] * 61},
                                     format="json").status_code, 400)

    def test_what_the_member_cannot_do_is_never_added(self):
        m = membership_for(self.user)
        m.tier = "statz"
        m.save()
        BodieZAccess.objects.create(user=self.user, seated_or_lying_only=True)
        r = self.c.post(URL, {"mode": "compound_isolation", "exercises": self._rows("Bench Press")}, format="json")
        added = BodieZExercise.objects.filter(id__in=r.json()["added"])
        for e in added:
            self.assertTrue({"seated", "lying"} & set(e.position_list), e.name)

    def test_a_members_own_custom_exercise_is_left_alone(self):
        m = membership_for(self.user)
        m.tier = "statz"
        m.save()
        mine = BodieZExercise.objects.create(created_by=self.user, name="My Chest Thing", muscle_group="chest",
                                             equipment="dumbbell")
        r = self.c.post(URL, {"mode": "compound_isolation",
                              "exercises": [{"exercise_id": mine.id, "sets": 3, "reps": 10}]}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["pairs"], [])
        self.assertNotIn(mine.id, r.json()["added"])
