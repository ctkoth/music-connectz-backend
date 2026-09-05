"""JournalZ's calendar, insights and prompts — the parts a diary app has.

JournalZ already had the hard half. What it lacked was a way to look at the
whole thing: a month you can see, a year you can count, and a reason to open it
today. These tests pin the three rules those surfaces have to keep.

  EVERY CELL IS A DOOR. A grid of thirty days that do nothing is wallpaper, not
  navigation — a kept day opens what you wrote, a missed one opens writing it.

  NOTHING IN A DIARY IS SCORED. Counts only, every one of them a thing that
  happened. A "depth" number on somebody's diary is the exact failure
  directz_ai_rating is remembered for.

  A PROMPT NEVER INVENTS A DAY. A member who did nothing gets the plain
  opener. A prompt about something that did not happen is worse than a blank
  page, because now the app is wrong as well as empty.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.journal_diarium import TOP_N, _longest_streak, _month_bounds
from apps.economy.models import JournalEntry, award_energy, award_spinaz

User = get_user_model()
PW = "pw12345678"

CAL = "/api/economy/journalz/calendar/"
INS = "/api/economy/journalz/insights/"
PRO = "/api/economy/journalz/prompts/"


class Base(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("diarist", "d@e.com", PW)
        self.client.force_authenticate(self.user)
        self.today = timezone.localdate()

    def write(self, days_ago=0, **kw):
        return JournalEntry.objects.create(
            author=self.user, day=self.today - timedelta(days=days_ago), **kw)


class MonthBoundsTests(TestCase):
    def test_it_finds_the_ends_of_the_month(self):
        first, last = _month_bounds("2026-02")
        self.assertEqual((first.day, last.day), (1, 28))

    def test_a_leap_february_has_its_extra_day(self):
        self.assertEqual(_month_bounds("2028-02")[1].day, 29)

    def test_a_typo_is_this_month_not_a_400(self):
        """A calendar that errors on a bad month is one you can't page with a
        keyboard."""
        today = timezone.localdate()
        for junk in ("", None, "not-a-month", "2026-13", "0000-01"):
            self.assertEqual(_month_bounds(junk)[0].month, today.month, junk)


class CalendarTests(Base):
    def test_every_day_of_the_month_comes_back_including_the_empty_ones(self):
        r = self.client.get(CAL)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(len(r.data["days"]), r.data["days_in_month"])

    def test_a_kept_day_opens_what_you_wrote(self):
        e = self.write(title="Studio")
        cell = next(d for d in self.client.get(CAL).data["days"]
                    if d["day"] == self.today.isoformat())
        self.assertTrue(cell["kept"])
        self.assertEqual(cell["entry_id"], e.id)
        self.assertEqual(cell["action"], "read")
        self.assertEqual(cell["title"], "Studio")

    def test_a_missed_day_opens_writing_it(self):
        cell = next(d for d in self.client.get(CAL).data["days"]
                    if d["day"] == (self.today - timedelta(days=1)).isoformat())
        self.assertFalse(cell["kept"])
        self.assertEqual(cell["action"], "write")

    def test_a_future_day_offers_nothing_because_a_diary_is_not_a_plan(self):
        days = self.client.get(CAL).data["days"]
        future = [d for d in days if d["future"]]
        self.assertTrue(all(d["action"] == "none" for d in future))

    def test_every_cell_carries_a_destination(self):
        for d in self.client.get(CAL).data["days"]:
            self.assertEqual(d["open_in"], "journalz")

    def test_two_entries_on_one_day_are_counted_not_hidden(self):
        self.write(title="Morning")
        self.write(title="Night")
        cell = next(d for d in self.client.get(CAL).data["days"]
                    if d["day"] == self.today.isoformat())
        self.assertEqual(cell["count"], 2)

    def test_the_arrows_know_which_month_comes_next(self):
        r = self.client.get(CAL, {"month": "2026-01"})
        self.assertEqual(r.data["prev_month"], "2025-12")
        self.assertEqual(r.data["next_month"], "2026-02")

    def test_it_is_free_at_every_tier(self):
        # Navigating your own diary is not a capability we rent to you — the
        # same argument that took the gate off LogZ.
        self.assertEqual(self.client.get(CAL).status_code, 200)

    def test_it_never_shows_somebody_elses_days(self):
        other = User.objects.create_user("other", "o@e.com", PW)
        JournalEntry.objects.create(author=other, day=self.today, title="Not yours")
        kept = [d for d in self.client.get(CAL).data["days"] if d["kept"]]
        self.assertEqual(kept, [])


class LongestStreakTests(TestCase):
    def test_no_days_is_zero_not_one(self):
        self.assertEqual(_longest_streak(set()), 0)

    def test_it_finds_the_longest_run_not_the_latest(self):
        d = timezone.localdate()
        days = {d - timedelta(days=n) for n in (0, 1)}            # a run of 2
        days |= {d - timedelta(days=n) for n in (10, 11, 12, 13)}  # a run of 4
        self.assertEqual(_longest_streak(days), 4)

    def test_a_gap_breaks_the_run(self):
        d = timezone.localdate()
        self.assertEqual(_longest_streak({d, d - timedelta(days=2)}), 1)


class InsightsTests(Base):
    def test_it_counts_what_happened_and_scores_nothing(self):
        self.write(title="a", mood="good", tags=["studio"], people=["novabeatz"])
        r = self.client.get(INS)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["entries"], 1)
        self.assertEqual(r.data["days_kept"], 1)
        # The property, stated: no score, no rating, no grade, anywhere.
        for banned in ("score", "rating", "grade", "depth", "quality"):
            self.assertNotIn(banned, r.data, f"a diary must never be {banned}d")

    def test_mood_is_a_distribution_never_an_average(self):
        """"Your average mood is 3.2" is a number nobody can act on and a
        claim nobody made."""
        self.write(days_ago=0, mood="great")
        self.write(days_ago=1, mood="low")
        r = self.client.get(INS)
        self.assertNotIn("average_mood", r.data)
        self.assertEqual({m["key"] for m in r.data["moods"]}, {"great", "low"})
        self.assertTrue(all(m["label"] for m in r.data["moods"]))

    def test_a_person_in_your_diary_opens_their_profile(self):
        self.write(people=["novabeatz"])
        row = self.client.get(INS).data["people"][0]
        self.assertEqual(row["username"], "novabeatz")
        self.assertEqual(row["open_in"], "social")

    def test_a_tag_opens_that_search(self):
        self.write(tags=["bristol"])
        row = self.client.get(INS).data["tags"][0]
        self.assertEqual(row["filter"], {"tag": "bristol"})
        self.assertEqual(row["open_in"], "journalz")

    def test_the_top_lists_are_capped_so_they_stay_top_lists(self):
        self.write(tags=[f"tag{i}" for i in range(TOP_N + 20)])
        self.assertLessEqual(len(self.client.get(INS).data["tags"]), TOP_N)

    def test_shared_and_private_are_both_counted(self):
        self.write(days_ago=0, visibility=JournalEntry.VIS_PRIVATE)
        self.write(days_ago=1, visibility=JournalEntry.VIS_PUBLIC)
        r = self.client.get(INS)
        self.assertEqual((r.data["private"], r.data["shared"]), (1, 1))

    def test_it_says_out_loud_that_nothing_is_scored(self):
        self.assertIn("scored", self.client.get(INS).data["note"])


class PromptTests(Base):
    def test_a_day_that_happened_becomes_a_reason_to_write(self):
        award_spinaz(self.user, 300, "referral (referrer)", open_in="earnz")
        r = self.client.get(PRO)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.data["prompts"])
        p = r.data["prompts"][0]
        self.assertIn("referral", p["opener"])
        # Nothing is a dead end, including a prompt.
        self.assertEqual(p["open_in"], "earnz")

    def test_the_opener_is_a_first_line_not_a_written_entry(self):
        """The app hands over an opener and the door. Writing the entry FOR
        somebody is the app keeping the diary, which is a different product."""
        award_energy(self.user, 5, "rated a post", open_in="postz")
        opener = self.client.get(PRO).data["prompts"][0]["opener"]
        self.assertLess(len(opener), 120)

    def test_a_quiet_day_gets_the_plain_opener_not_an_invented_highlight(self):
        r = self.client.get(PRO)
        self.assertEqual(r.data["prompts"], [])
        self.assertIn("quiet day", r.data["fallback"])

    def test_the_same_thing_twice_is_one_prompt(self):
        for _ in range(4):
            award_energy(self.user, 1, "rated a post", open_in="postz")
        self.assertEqual(len(self.client.get(PRO).data["prompts"]), 1)

    def test_it_is_capped_so_it_is_a_nudge_and_not_a_wall(self):
        for i in range(20):
            award_spinaz(self.user, 1, f"thing number {i}", open_in="postz")
        self.assertLessEqual(len(self.client.get(PRO).data["prompts"]), 5)

    def test_it_knows_whether_today_is_already_written(self):
        self.assertFalse(self.client.get(PRO).data["already_written"])
        self.write(title="done")
        r = self.client.get(PRO)
        self.assertTrue(r.data["already_written"])
        self.assertIn("Add to", r.data["fallback"])

    def test_yesterdays_ledger_is_not_offered_as_today(self):
        award_spinaz(self.user, 5, "yesterday's thing", open_in="postz")
        from apps.economy.models import Transaction
        Transaction.objects.filter(user=self.user).update(
            created_at=timezone.now() - timedelta(days=1))
        self.assertEqual(self.client.get(PRO).data["prompts"], [])

    def test_a_row_with_no_recorded_origin_still_prompts_without_a_dead_link(self):
        award_spinaz(self.user, 5, "something untagged")
        p = self.client.get(PRO).data["prompts"][0]
        self.assertEqual(p["open_in"], "")
