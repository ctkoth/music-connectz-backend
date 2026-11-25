"""ThuroZ, SeXi and Thorough: 6.9 or more, as one word."""
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from .classz import ABOVE, MIN_RATINGS, classes_for, in_class, state_for
from .gates import clean_gates, describe, failing_gate, member_metrics
from .models import (AttractivenessRating, OverallRating, membership_for, profile_for)

User = get_user_model()


class Base(TestCase):
    def setUp(self):
        self.me = User.objects.create_user("me", "me@x.com", "hunter2hunter2")
        self.raters = [User.objects.create_user(f"r{i}", f"r{i}@x.com", "hunter2hunter2") for i in range(5)]
        self.c = APIClient()
        self.c.force_authenticate(self.me)

    def rate(self, target, scores, model=OverallRating):
        for r, s in zip(self.raters, scores):
            model.objects.create(rater=r, target=target, score=s)

    def member(self, name):
        u = User.objects.create_user(name, f"{name}@x.com", "hunter2hunter2")
        profile_for(u)
        return u


class TheBarTests(Base):
    def test_above_six_point_nine_with_enough_members_behind_it(self):
        self.assertTrue(in_class(7, MIN_RATINGS))
        self.assertTrue(in_class(6.95, 3))
        self.assertTrue(in_class(ABOVE, 9), "6.9 is 6.9 or more")
        self.assertFalse(in_class(6.89, 9))
        self.assertFalse(in_class(6.5, 9))
        self.assertFalse(in_class(None, 9))

    def test_one_friends_ten_is_not_a_class(self):
        u = self.member("solo")
        self.rate(u, [10])
        self.assertEqual(classes_for([profile_for(u)]), {})
        self.rate(u, [10, 10], model=AttractivenessRating)
        self.assertEqual(classes_for([profile_for(u)]), {})

    def test_three_members_agreeing_make_it_and_the_median_decides(self):
        good, mixed = self.member("good"), self.member("mixed")
        self.rate(good, [8, 7, 9])
        self.rate(mixed, [10, 6, 6])          # one 10 cannot carry a median
        got = classes_for([profile_for(good), profile_for(mixed)])
        self.assertEqual(got, {good.id: ["thuro"]})

    def test_sexi_honours_the_members_own_switch_and_is_never_a_minors(self):
        from datetime import date
        shown, hidden, minor = self.member("shown"), self.member("hid"), self.member("kid")
        for u in (shown, hidden, minor):
            self.rate(u, [9, 8, 9], model=AttractivenessRating)
        m = membership_for(hidden)
        m.attractiveness_public = False
        m.save(update_fields=["attractiveness_public"])
        p = profile_for(minor)
        p.birthday = date(date.today().year - 15, 1, 1)
        p.save(update_fields=["birthday"])
        got = classes_for([profile_for(u) for u in (shown, hidden, minor)])
        self.assertEqual(got, {shown.id: ["sexi"]})
        self.assertNotIn("sexi", state_for(minor), "a minor is not offered the class at all")

    def test_my_own_standing_says_the_count_before_the_median(self):
        self.rate(self.me, [9, 9])
        row = state_for(self.me)["thuro"]
        self.assertFalse(row["is"])
        self.assertEqual(row["ratings_needed"], 1)
        self.assertIn("2 of 3", row["line"])


class TheCoachIsThreeVoicesTests(Base):
    """Corey: the AI coach counts toward ThuroZ as three voices, so it can replace or
    supplement member ratings."""

    def takes(self, user, scores, app="rapz"):
        from .models import TakeScore
        for s in scores:
            TakeScore.objects.create(user=user, app_key=app, overall=s, scores={})

    def test_the_coach_alone_is_enough_once_it_has_three_takes(self):
        u = self.member("alone")
        self.takes(u, [8, 9])
        self.assertEqual(classes_for([profile_for(u)]), {}, "two takes are not a voice yet")
        self.takes(u, [8])
        self.assertEqual(classes_for([profile_for(u)]), {u.id: ["thuro"]})

    def test_it_supplements_member_ratings(self):
        u = self.member("both")
        self.rate(u, [8])
        self.takes(u, [8, 9, 8])
        self.assertEqual(classes_for([profile_for(u)]), {u.id: ["thuro"]})

    def test_it_cuts_both_ways(self):
        u = self.member("mixed")
        self.rate(u, [9, 9, 9])
        self.assertEqual(classes_for([profile_for(u)]), {u.id: ["thuro"]})
        self.takes(u, [4, 4, 4])                 # 9,9,9,4,4,4 -> median 6.5
        self.assertEqual(classes_for([profile_for(u)]), {})

    def test_only_the_recent_takes_speak(self):
        from .royaltyfactor import COACH_WINDOW
        u = self.member("improved")
        self.takes(u, [2] * 5)                   # old
        self.takes(u, [9] * COACH_WINDOW)        # the window
        self.assertEqual(classes_for([profile_for(u)]), {u.id: ["thuro"]})

    def test_my_standing_says_the_coach_is_in_the_number(self):
        self.takes(self.me, [8, 8, 8])
        row = state_for(self.me)["thuro"]
        self.assertTrue(row["is"])
        self.assertEqual((row["members"], row["coach_votes"], row["count"]), (0, 3, 3))
        self.assertIn("AI coach", row["line"])

    def test_sexi_takes_no_coach_voice(self):
        u = self.member("face")
        self.rate(u, [9, 9], model=AttractivenessRating)
        self.takes(u, [10, 10, 10])
        self.assertEqual(classes_for([profile_for(u)]), {u.id: ["thuro"]}, "ThuroZ from the takes, never SeXi")

    def test_the_coach_is_worth_three_in_the_class_and_in_the_royalty_formula(self):
        from . import classz, royaltyfactor
        self.assertEqual((classz.COACH_VOTES, royaltyfactor.COACH_VOTES), (3, 3))
        self.assertIs(classz.COACH_VOTES, royaltyfactor.COACH_VOTES)


class TheGateTests(Base):
    def test_a_class_is_a_gate_and_is_exclusive(self):
        good, unrated = self.member("good"), self.member("new")
        self.rate(good, [8, 8, 8])
        gates = clean_gates({"thuro": True, "sexi": False, "junk": True})
        self.assertEqual(gates, {"thuro": True})
        self.assertIsNone(failing_gate(member_metrics(profile_for(good)), gates))
        self.assertEqual(failing_gate(member_metrics(profile_for(unrated)), gates), "thuro")
        self.assertIn("ThuroZ only", describe("thuro", gates))
        self.assertIn("at least 3 voices", describe("thuro", gates))

    def test_a_class_sits_beside_a_range_and_both_must_pass(self):
        good = self.member("good")
        self.rate(good, [8, 8, 8])
        gates = clean_gates({"thuro": True, "age": [18, None]})
        self.assertEqual(failing_gate(member_metrics(profile_for(good)), gates), "age")

    def test_an_old_gates_dict_reads_exactly_as_before(self):
        self.assertEqual(clean_gates({"rating": [7, None]}), {"rating": [7.0, None]})


class TheSearchTests(Base):
    URL = "/api/economy/members/"

    def setUp(self):
        super().setUp()
        self.good, self.low, self.new = self.member("good"), self.member("low"), self.member("new")
        self.rate(self.good, [8, 9, 7])
        self.rate(self.low, [5, 6, 5])

    def names(self, q=""):
        return {m["username"] for m in self.c.get(self.URL + q).data["members"]}

    def test_thuro_narrows_the_search_and_says_who_it_left_out(self):
        self.assertTrue({"good", "low", "new"} <= self.names())
        r = self.c.get(self.URL + "?thuro=1").data
        self.assertEqual({m["username"] for m in r["members"]}, {"good"})
        self.assertIn("left out by the class filter", r["class_note"])
        self.assertEqual(self.c.get(self.URL).data["class_note"], "")

    def test_every_card_says_its_classes_and_the_filter_costs_nothing_per_member(self):
        cards = {m["username"]: m for m in self.c.get(self.URL).data["members"]}
        self.assertEqual(cards["good"]["classes"], ["thuro"])
        self.assertEqual(cards["low"]["classes"], [])

        def cost(q):
            with CaptureQueriesContext(connection) as ctx:
                self.c.get(self.URL + q)
            return len(ctx)
        base = cost("?thuro=1")
        for i in range(6):
            u = self.member(f"more{i}")
            self.rate(u, [9, 9, 9])
        self.assertEqual(cost("?thuro=1"), base)


class TheEndpointTests(Base):
    def test_it_publishes_the_rule_and_where_i_stand(self):
        self.rate(self.me, [8, 8, 8])
        d = self.c.get("/api/economy/classz/").data
        self.assertEqual((d["above"], d["min_ratings"]), (ABOVE, MIN_RATINGS))
        self.assertEqual({c["key"] for c in d["classes"]}, {"thuro", "sexi", "thorough"})
        self.assertTrue(d["mine"]["thuro"]["is"])
        self.assertIn("pays nothing", d["note"])

    def test_nothing_reads_a_class_as_money_or_rank(self):
        """It decides who is SEEN. No wallet, royalty, price or badge module may read it."""
        import re
        from pathlib import Path
        root = Path(__file__).parent
        allowed = {"classz.py", "gates.py", "social.py", "urls.py"}
        for f in root.glob("*.py"):
            if f.name.startswith("test_") or f.name in allowed:
                continue
            self.assertIsNone(re.search(r"from \.classz|import classz|classes_for\(", f.read_text(encoding="utf-8")), f.name)


class ThoroughClassTests(Base):
    """Thorough: the BodieZ badge (6.9+) as a one-tap "only" filter, read as it is worn."""

    def test_a_worn_thorough_badge_is_in_the_class_a_hidden_one_is_not(self):
        from .models import Badge
        worn, hidden, none = self.member("worn"), self.member("hid"), self.member("none")
        Badge.objects.create(user=worn, key="thorough", visible=True)
        Badge.objects.create(user=hidden, key="decent", visible=False)
        got = classes_for([profile_for(u) for u in (worn, hidden, none)])
        self.assertIn("thorough", got[worn.id])
        self.assertNotIn(hidden.id, got)
        self.assertNotIn(none.id, got)

    def test_it_is_an_exclusive_gate_and_says_so(self):
        from .models import Badge
        worn, none = self.member("worn"), self.member("none")
        Badge.objects.create(user=worn, key="legendary", visible=True)
        gates = clean_gates({"thorough": True})
        self.assertEqual(gates, {"thorough": True})
        self.assertIsNone(failing_gate(member_metrics(profile_for(worn)), gates))
        self.assertEqual(failing_gate(member_metrics(profile_for(none)), gates), "thorough")
        self.assertIn("Thorough only", describe("thorough", gates))

    def test_it_is_published_with_where_i_stand(self):
        r = self.c.get("/api/economy/classz/")
        self.assertIn("thorough", [c["key"] for c in r.data["classes"]])
        self.assertIn("lifts logged", r.data["mine"]["thorough"]["line"])
