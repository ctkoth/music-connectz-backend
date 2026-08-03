import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import profile_for
from apps.economy.social import _skill_years, profile_max_experience, skill_activity

User = get_user_model()
TODAY = datetime.date.today()


def yrs_ago(n):
    """Exactly n calendar years back. timedelta(days=n*365.2425) lands a day
    short once leap days accumulate, which is a property of the helper and not
    of the code under test."""
    try:
        return TODAY.replace(year=TODAY.year - n).isoformat()
    except ValueError:          # 29 Feb
        return TODAY.replace(year=TODAY.year - n, day=28).isoformat()


class SkillYearsTests(TestCase):
    """Experience is time SERVED, not time elapsed since you started.

    The old rule was `today - start`, so someone who played 1999-2013 and
    stopped was credited 26 years instead of 14 — a number nobody could have
    earned, printed next to their name.
    """

    def test_a_closed_stint_counts_only_the_years_played(self):
        skill = {"name": "Violin", "periods": [{"start": yrs_ago(26), "end": yrs_ago(12)}]}
        self.assertEqual(_skill_years(skill), 14)

    def test_an_open_stint_runs_to_today(self):
        self.assertEqual(_skill_years({"name": "Violin", "periods": [{"start": yrs_ago(9)}]}), 9)

    def test_stints_are_summed_across_a_gap(self):
        # 14 years, quit, came back 2 years ago → 16, not 26.
        skill = {"name": "Violin", "periods": [
            {"start": yrs_ago(26), "end": yrs_ago(12)},
            {"start": yrs_ago(2)},
        ]}
        self.assertEqual(_skill_years(skill), 16)

    def test_the_gap_itself_is_never_credited(self):
        gap_only = {"name": "X", "periods": [{"start": yrs_ago(20), "end": yrs_ago(20)}]}
        self.assertIsNone(_skill_years(gap_only))

    def test_the_legacy_start_only_shape_still_works(self):
        # Nobody's saved data changes meaning until they add an end date.
        self.assertEqual(_skill_years({"name": "Violin", "start": yrs_ago(7)}), 7)

    def test_an_undated_skill_has_no_experience(self):
        self.assertIsNone(_skill_years({"name": "Violin"}))
        self.assertIsNone(_skill_years("Violin"))

    def test_a_future_end_date_cannot_inflate_the_number(self):
        skill = {"name": "X", "periods": [
            {"start": yrs_ago(3), "end": (TODAY + datetime.timedelta(days=4000)).isoformat()},
        ]}
        self.assertEqual(_skill_years(skill), 3)

    def test_garbage_dates_are_ignored_not_fatal(self):
        self.assertIsNone(_skill_years({"name": "X", "periods": [{"start": "not-a-date"}]}))


class SkillActivityTests(TestCase):
    """14 years still going is not 14 years that stopped in 2013, and a
    collaborator is choosing between those two."""

    def test_an_open_stint_reads_active(self):
        active, last = skill_activity({"name": "X", "periods": [{"start": yrs_ago(5)}]})
        self.assertTrue(active)
        self.assertIsNone(last)

    def test_a_closed_skill_reports_when_it_stopped(self):
        end = yrs_ago(12)
        active, last = skill_activity({"name": "X", "periods": [{"start": yrs_ago(26), "end": end}]})
        self.assertFalse(active)
        self.assertEqual(last, end)

    def test_the_latest_end_wins_across_several_closed_stints(self):
        recent = yrs_ago(2)
        active, last = skill_activity({"name": "X", "periods": [
            {"start": yrs_ago(20), "end": yrs_ago(15)},
            {"start": yrs_ago(6), "end": recent},
        ]})
        self.assertFalse(active)
        self.assertEqual(last, recent)

    def test_legacy_start_only_is_treated_as_still_going(self):
        active, _ = skill_activity({"name": "X", "start": yrs_ago(4)})
        self.assertTrue(active)


class ProfileExperienceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("k", "k@e.com", "pw12345678")
        self.p = profile_for(self.user)

    def test_it_takes_the_best_skill_and_sums_that_skill_s_stints(self):
        self.p.personas = [{"key": "indieartist", "name": "Indie Artist", "skills": [
            {"name": "Violin", "periods": [{"start": yrs_ago(26), "end": yrs_ago(12)}]},   # 14
            {"name": "Piano", "periods": [{"start": yrs_ago(9)}]},                          # 9
        ]}]
        self.p.save()
        self.assertEqual(profile_max_experience(self.p), 14)

    def test_a_bare_string_persona_does_not_500(self):
        # This was a live crash on every member card.
        self.p.personas = ["producer", {"key": "x", "skills": [{"name": "A", "start": yrs_ago(3)}]}]
        self.p.save()
        self.assertEqual(profile_max_experience(self.p), 3)

    def test_nothing_dated_means_no_number(self):
        self.p.personas = [{"key": "x", "name": "X", "skills": [{"name": "Violin"}]}]
        self.p.save()
        self.assertIsNone(profile_max_experience(self.p))


class PeriodsSurviveTheRoundTripTests(TestCase):
    """_clean_persona sits on the write path; dropping `periods` there would
    silently zero somebody's experience the next time they saved."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("k", "k@e.com", "pw12345678")
        self.client.force_authenticate(self.user)

    def test_periods_are_kept_through_a_save(self):
        periods = [{"start": yrs_ago(26), "end": yrs_ago(12)}, {"start": yrs_ago(2)}]
        resp = self.client.patch("/api/auth/me/", {"personas": [
            {"key": "indieartist", "name": "Indie Artist",
             "skills": [{"name": "Violin", "periods": periods}]},
        ]}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        saved = profile_for(self.user).personas[0]["skills"][0]
        self.assertEqual(saved["periods"], periods)
        self.assertEqual(profile_max_experience(profile_for(self.user)), 16)

    def test_a_legacy_start_survives_untouched(self):
        self.client.patch("/api/auth/me/", {"personas": [
            {"key": "x", "name": "X", "skills": [{"name": "Violin", "start": yrs_ago(7)}]},
        ]}, format="json")
        saved = profile_for(self.user).personas[0]["skills"][0]
        self.assertEqual(saved["start"], yrs_ago(7))
        self.assertEqual(profile_max_experience(profile_for(self.user)), 7)

    def test_a_period_with_no_start_is_dropped_rather_than_stored_broken(self):
        self.client.patch("/api/auth/me/", {"personas": [
            {"key": "x", "name": "X", "skills": [{"name": "V", "periods": [{"end": yrs_ago(1)}]}]},
        ]}, format="json")
        self.assertEqual(profile_for(self.user).personas[0]["skills"][0], {"name": "V"})
