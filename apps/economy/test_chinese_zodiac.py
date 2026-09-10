"""The other zodiac, and the boundary that makes it hard.

Almost every one of these is about the seven weeks at the start of a year. The
Chinese zodiac turns at LUNAR new year, anywhere from 21 Jan to 20 Feb, so
`year % 12` is wrong for about one member in nine — and always the same ones,
which is the kind of error noticed first by exactly the people it is about.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import CHINESE_ANIMALS, chinese_zodiac_for, profile_for

User = get_user_model()


class TheAnimal(TestCase):
    def test_a_date_well_inside_the_year(self):
        self.assertEqual(chinese_zodiac_for("1990-06-01")["animal"], "Horse")
        self.assertEqual(chinese_zodiac_for("2000-08-14")["animal"], "Dragon")
        self.assertEqual(chinese_zodiac_for("2024-07-04")["animal"], "Dragon")

    def test_the_cycle_is_twelve_years_long(self):
        for y in (1988, 2000, 2012, 2024):
            with self.subTest(year=y):
                self.assertEqual(chinese_zodiac_for(f"{y}-06-01")["animal"], "Dragon")

    def test_every_animal_carries_a_mark(self):
        """The live app renders signs as Unicode, not artwork — the western
        ones already do — so an animal without one would render as a gap."""
        self.assertEqual(len(CHINESE_ANIMALS), 12)
        for name, emoji in CHINESE_ANIMALS:
            self.assertTrue(name and emoji)


class TheBoundary(TestCase):
    """The whole reason this is not `year % 12`."""

    def test_the_day_the_year_turns(self):
        # CNY 2024 was 10 February. The day before is still the Rabbit year.
        self.assertEqual(chinese_zodiac_for("2024-02-10")["animal"], "Dragon")
        self.assertEqual(chinese_zodiac_for("2024-02-09")["animal"], "Rabbit")

    def test_january_belongs_to_the_year_before(self):
        # Born 15 Jan 2000 and every naive implementation says Dragon.
        self.assertEqual(chinese_zodiac_for("2000-01-15")["animal"], "Rabbit")
        self.assertEqual(chinese_zodiac_for("2000-02-05")["animal"], "Dragon")

    def test_a_late_new_year(self):
        # 1985 turned on 20 February — the latest it goes.
        self.assertEqual(chinese_zodiac_for("1985-02-19")["animal"], "Rat")
        self.assertEqual(chinese_zodiac_for("1985-02-20")["animal"], "Ox")

    def test_an_early_new_year(self):
        # 1966 turned on 21 January — the earliest it goes.
        self.assertEqual(chinese_zodiac_for("1966-01-20")["animal"], "Snake")
        self.assertEqual(chinese_zodiac_for("1966-01-21")["animal"], "Horse")

    def test_after_february_the_lookup_is_not_needed(self):
        """Only 21 Jan – 20 Feb is ambiguous, so nothing else is ever flagged."""
        for date in ("1901-03-01", "2099-12-31"):
            with self.subTest(date=date):
                self.assertFalse(chinese_zodiac_for(date)["approximate"])

    def test_a_year_outside_the_table_admits_it(self):
        """A sign somebody is TOLD is theirs, wrongly, is worse than one the
        app says it is unsure of."""
        out = chinese_zodiac_for("2099-01-05")
        self.assertTrue(out["approximate"])
        self.assertIn(out["animal"], [n for n, _ in CHINESE_ANIMALS])


class BadInput(TestCase):
    def test_nothing_to_read(self):
        for bad in ("", None, "not-a-date", "2000-13-40", "2000", "--"):
            with self.subTest(value=bad):
                self.assertIsNone(chinese_zodiac_for(bad))


class OnTheProfileCard(TestCase):
    """The card every member screen and search result is built from."""

    def _card(self, birthday):
        u = User.objects.create_user(username=f"z{birthday or 0}"[:20], password="pw")
        p = profile_for(u)
        p.birthday = birthday
        p.save()
        from .social import _profile_card
        return _profile_card(profile_for(u))

    def test_it_rides_along_with_the_western_sign(self):
        card = self._card("1990-06-01")
        self.assertEqual(card["sign_cn"]["animal"], "Horse")
        self.assertEqual(card["sign_cn"]["emoji"], "🐎")

    def test_no_birthday_means_no_sign_rather_than_a_wrong_one(self):
        self.assertIsNone(self._card("")["sign_cn"])

    def test_the_export_carries_it_too(self):
        """A member's own copy of their data should say what the app says."""
        u = User.objects.create_user(username="exporter", password="pw")
        p = profile_for(u)
        p.birthday = "2000-01-15"
        p.save()
        self.client.force_login(u)
        d = self.client.get("/api/economy/account/export/").json()
        self.assertEqual(d["profile"]["sign_cn"]["animal"], "Rabbit")


class OnTheMemberEndpoint(TestCase):
    """`/api/auth/me/` is what the member's own screen reads."""

    def test_both_zodiacs_ride_together(self):
        u = User.objects.create_user(username="mez", password="pw")
        p = profile_for(u)
        p.birthday = "2000-01-15"
        p.sign = "Capricorn"
        p.save()
        self.client.force_login(u)
        d = self.client.get("/api/auth/me/").json()
        self.assertEqual(d["zodiac"], "Capricorn")
        # Born before the lunar new year, so the year before's animal.
        self.assertEqual(d["zodiac_cn"]["animal"], "Rabbit")

    def test_no_birthday_leaves_it_null_rather_than_guessing(self):
        u = User.objects.create_user(username="mez2", password="pw")
        self.client.force_login(u)
        self.assertIsNone(self.client.get("/api/auth/me/").json()["zodiac_cn"])
