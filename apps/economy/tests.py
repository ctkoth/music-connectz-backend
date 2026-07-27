from django.test import SimpleTestCase

from .models import zodiac_for


class ZodiacBoundaries(SimpleTestCase):
    """Every sign's first and last day, against the standard zodiac calendar."""

    CASES = {
        "1990-01-19": "Capricorn", "1990-01-20": "Aquarius",
        "1990-02-18": "Aquarius", "1990-02-19": "Pisces",
        "1990-03-20": "Pisces", "1990-03-21": "Aries",
        "1990-04-19": "Aries", "1990-04-20": "Taurus",
        "1990-05-20": "Taurus", "1990-05-21": "Gemini",
        "1990-06-20": "Gemini", "1990-06-21": "Cancer",
        "1990-07-22": "Cancer", "1990-07-23": "Leo",
        "1990-08-22": "Leo", "1990-08-23": "Virgo",
        "1990-09-22": "Virgo", "1990-09-23": "Libra",
        "1990-10-22": "Libra", "1990-10-23": "Scorpio",
        "1990-11-21": "Scorpio", "1990-11-22": "Sagittarius",
        "1990-12-21": "Sagittarius", "1990-12-22": "Capricorn",
        "1990-12-31": "Capricorn",
    }

    def test_cutoffs(self):
        for birthday, sign in self.CASES.items():
            with self.subTest(birthday=birthday):
                self.assertEqual(zodiac_for(birthday), sign)

    def test_unparseable_birthday_is_blank(self):
        for value in ("", None, "not-a-date", "1990-13"):
            self.assertEqual(zodiac_for(value), "")
