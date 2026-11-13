"""A skill can be dated by its YEAR alone, because members know the year they started, not the day.

Stored as that year's 1 January plus `precision: "year"` on the stint, so every existing date parser
keeps working; the flag is what says the month and day are a convention and not a claim.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import membership_for, profile_for
from apps.economy.personaz import clean_persona, needs_repair, personas_of
from apps.economy.social import _skill_years

User = get_user_model()
PW = "hunter2hunter2"


def persona(*stints, name="rapping"):
    return {"key": "indieartist", "name": "Artist", "skills": [{"name": name, "periods": list(stints)}]}


class CleaningTests(TestCase):
    def test_a_year_only_start_keeps_its_flag(self):
        c = clean_persona(persona({"start": "2010-01-01", "precision": "year"}))
        self.assertEqual(c["skills"][0]["periods"], [{"start": "2010-01-01", "precision": "year"}])

    def test_the_flag_is_dropped_on_any_other_date(self):
        # Year-only is always a 1 January; a request cannot make a real date "approximate".
        c = clean_persona(persona({"start": "2010-06-15", "precision": "year"}))
        self.assertEqual(c["skills"][0]["periods"], [{"start": "2010-06-15"}])

    def test_junk_precision_is_dropped(self):
        c = clean_persona(persona({"start": "2010-01-01", "precision": "decade"}))
        self.assertEqual(c["skills"][0]["periods"], [{"start": "2010-01-01"}])

    def test_it_survives_an_end_date(self):
        c = clean_persona(persona({"start": "2000-01-01", "end": "2010-03-04", "precision": "year"}))
        self.assertEqual(c["skills"][0]["periods"], [{"start": "2000-01-01", "end": "2010-03-04", "precision": "year"}])

    def test_cleaning_is_stable_so_a_repair_sweep_leaves_it_alone(self):
        stored = [clean_persona(persona({"start": "2010-01-01", "precision": "year"}))]
        self.assertFalse(needs_repair(stored))

    def test_the_experience_arithmetic_is_unchanged(self):
        # 1 January of the year: calendar years since is exactly the whole years served.
        import datetime
        year = datetime.date.today().year - 7
        c = clean_persona(persona({"start": f"{year}-01-01", "precision": "year"}))
        self.assertEqual(_skill_years(c["skills"][0]), 7)


class PickerEndpointTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("maker", password=PW)
        membership_for(self.u)
        self.client = APIClient()
        self.client.force_authenticate(self.u)

    def skill(self, *stints):
        p = profile_for(self.u)
        p.personas = [persona(*stints)]
        p.save()
        r = self.client.get("/api/economy/ratez/skills/")
        return r.data["personas"][0]["skills"][0]

    def test_a_year_only_start_is_served_as_such(self):
        s = self.skill({"start": "2010-01-01", "precision": "year"})
        self.assertEqual(s["learned"], "2010-01-01")
        self.assertEqual(s["learned_precision"], "year")

    def test_a_full_date_is_served_as_a_day(self):
        s = self.skill({"start": "2010-06-15"})
        self.assertEqual(s["learned_precision"], "day")

    def test_undated_has_no_precision(self):
        s = self.skill()
        self.assertIsNone(s["learned_precision"])

    def test_the_earliest_stint_decides(self):
        s = self.skill({"start": "2015-03-01"}, {"start": "2005-01-01", "precision": "year"})
        self.assertEqual(s["learned"], "2005-01-01")
        self.assertEqual(s["learned_precision"], "year")

    def test_it_round_trips_through_the_profile_writer(self):
        # PATCH /auth/me/ is the writer PersonaZ uses; the flag must survive it.
        self.client.patch("/api/auth/me/", {"personas": [persona({"start": "2010-01-01", "precision": "year"})]},
                          format="json")
        kept = personas_of(profile_for(self.u))[0]["skills"][0]["periods"]
        self.assertEqual(kept, [{"start": "2010-01-01", "precision": "year"}])


class YearOnlyEndTests(TestCase):
    """The END can be a year too. Stored as that year's 1 July, flagged `end_precision: "year"`."""

    def test_a_year_only_end_keeps_its_flag(self):
        c = clean_persona(persona({"start": "2000-01-01", "precision": "year",
                                   "end": "2010-07-01", "end_precision": "year"}))
        self.assertEqual(c["skills"][0]["periods"],
                         [{"start": "2000-01-01", "end": "2010-07-01", "precision": "year", "end_precision": "year"}])

    def test_the_flag_is_dropped_on_any_other_end_date(self):
        c = clean_persona(persona({"start": "2000-01-01", "end": "2010-03-04", "end_precision": "year"}))
        self.assertEqual(c["skills"][0]["periods"], [{"start": "2000-01-01", "end": "2010-03-04"}])

    def test_an_end_flag_with_no_end_is_nothing(self):
        c = clean_persona(persona({"start": "2000-01-01", "end_precision": "year"}))
        self.assertEqual(c["skills"][0]["periods"], [{"start": "2000-01-01"}])

    def test_cleaning_is_stable(self):
        stored = [clean_persona(persona({"start": "2000-01-01", "precision": "year",
                                         "end": "2010-07-01", "end_precision": "year"}))]
        self.assertFalse(needs_repair(stored))

    def test_start_and_stop_in_one_year_is_still_counted(self):
        # 1 January to 1 July: half a year served, never dropped to "no start date".
        import datetime
        y = datetime.date.today().year - 3
        c = clean_persona(persona({"start": f"{y}-01-01", "precision": "year",
                                   "end": f"{y}-07-01", "end_precision": "year"}))
        self.assertEqual(_skill_years(c["skills"][0]), 0)         # whole years: under one
        from apps.economy.social import _periods_of
        self.assertEqual(len(_periods_of(c["skills"][0])), 1)


class YearOnlyEndEndpointTests(PickerEndpointTests):
    def test_served_with_the_precision_of_the_last_stop(self):
        s = self.skill({"start": "2000-01-01", "precision": "year", "end": "2010-07-01", "end_precision": "year"})
        self.assertEqual(s["last_played"], "2010-07-01")
        self.assertEqual(s["last_played_precision"], "year")
        self.assertTrue(s["approximate"])
        self.assertEqual(s["years"], 10)                          # 1 Jan 2000 to 1 Jul 2010

    def test_a_full_end_date_is_a_day(self):
        s = self.skill({"start": "2000-03-04", "end": "2010-05-06"})
        self.assertEqual(s["last_played_precision"], "day")
        self.assertFalse(s["approximate"])

    def test_a_year_only_start_alone_is_approximate(self):
        s = self.skill({"start": "2000-01-01", "precision": "year"})
        self.assertTrue(s["approximate"])
        self.assertIsNone(s["last_played_precision"])

    def test_the_end_flag_round_trips_through_the_profile_writer(self):
        self.client.patch("/api/auth/me/", {"personas": [persona(
            {"start": "2000-01-01", "precision": "year", "end": "2010-07-01", "end_precision": "year"})]}, format="json")
        kept = personas_of(profile_for(self.u))[0]["skills"][0]["periods"]
        self.assertEqual(kept[0]["end_precision"], "year")
