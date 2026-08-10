"""The 18+ wall — a boundary rather than a badge.

The InstrumentZ screens carry a "Teen-safe" label, and the same app rates
people on looks and collects sexual orientation. Under Play's Families policy
that is not a disclosure problem, it is a build problem: minors must not reach
those surfaces, and saying so on a form does not make it true.

`Profile.verified_18plus` already existed and was already set properly by
Stripe Identity from a government ID. Its own comment said it "gates money
betting + adult content" — and it gated nothing. Thirteen references, every one
setting it or displaying it, none consulting it. These tests are where it
starts being read.

Corey's call on the unknown case: no birthday and no verification means ADULT.
Most of the current user base has neither, and locking them out of what they
use today to satisfy a form would punish real people for a gap in our own data.
What gets walled is what we actually know.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.models import (
    AttractivenessRating,
    adult_only_reason,
    is_minor,
    membership_for,
    profile_for,
)

User = get_user_model()
PW = "hunter2hunter2"
RATE = "/api/economy/attractiveness/rate/"
ME = "/api/economy/profile/"


def born_years_ago(years):
    # January 1st, so the age is exactly `years` on every day of the year.
    # Counting backwards in days was off by the leap days and made an
    # eighteen-year-old seventeen.
    return f"{timezone.now().year - years}-01-01"


def member(name, age=None, verified=False):
    u = User.objects.create_user(name, f"{name}@e.com", PW)
    membership_for(u)
    p = profile_for(u)
    if age is not None:
        p.birthday = born_years_ago(age)
    p.verified_18plus = verified
    p.save()
    return u


class WhoCountsAsAMinorTests(TestCase):
    def test_a_stated_teen_age_is_a_minor(self):
        for age in (13, 15, 17):
            with self.subTest(age=age):
                self.assertTrue(is_minor(member(f"t{age}", age=age)))

    def test_a_stated_adult_age_is_not(self):
        self.assertFalse(is_minor(member("grown", age=18)))
        self.assertFalse(is_minor(member("older", age=40)))

    def test_an_unknown_age_is_not_a_minor(self):
        # Corey's call, and the reason: absence of information is not evidence
        # of youth, and this is most of the existing user base.
        self.assertFalse(is_minor(member("unknown")))

    def test_id_verification_outranks_a_typed_birthday(self):
        # Only in the permissive direction — the ID is the stronger evidence,
        # and somebody who verified as an adult does not stop being one because
        # a profile field says otherwise.
        self.assertFalse(is_minor(member("verified", age=15, verified=True)))

    def test_the_refusal_says_what_stays_open(self):
        reason = adult_only_reason(member("teen", age=15))
        self.assertIn("18+", reason)
        self.assertIn("collabs", reason)
        self.assertEqual(adult_only_reason(member("adult", age=30)), "")


class NobodyRatesAMinorOnLooksTests(TestCase):
    def setUp(self):
        self.adult = member("adult", age=30)
        self.teen = member("teen", age=15)
        self.other = member("other", age=25)
        self.client = APIClient()

    def rate(self, rater, target, score=8, url=RATE):
        self.client.force_authenticate(rater)
        return self.client.post(url, {"target_username": target.username, "score": score},
                                format="json")

    def test_an_adult_may_rate_an_adult(self):
        self.assertEqual(self.rate(self.adult, self.other).status_code, 200)

    def test_a_teen_cannot_rate(self):
        resp = self.rate(self.teen, self.adult)
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(resp.data["adult_only"])
        self.assertFalse(AttractivenessRating.objects.exists())

    def test_a_teen_cannot_BE_rated(self):
        # The half a rater-only check would have missed, and the half that
        # actually matters: adults scoring a fifteen-year-old on looks.
        resp = self.rate(self.adult, self.teen)
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(AttractivenessRating.objects.exists())

    def test_the_other_door_is_locked_too(self):
        # The dimension endpoint reaches the same table. Locking one view and
        # not the other is a front door with the back one open.
        url = "/api/economy/profile/rate/"
        self.client.force_authenticate(self.adult)
        resp = self.client.post(url, {"target_username": self.teen.username, "score": 9,
                                      "dimension": "attractiveness"}, format="json")
        self.assertEqual(resp.status_code, 403, resp.data)
        self.assertFalse(AttractivenessRating.objects.exists())

    def test_overall_rating_is_untouched_by_the_wall(self):
        # Rating somebody's WORK is not an adult surface. Walling it would take
        # a teen out of the economy over a policy about looks.
        self.client.force_authenticate(self.adult)
        resp = self.client.post("/api/economy/profile/rate/",
                                {"target_username": self.teen.username, "score": 9,
                                 "dimension": "overall"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_an_unknown_age_still_works_both_ways(self):
        nobody = member("nobody")
        self.assertEqual(self.rate(self.adult, nobody).status_code, 200)
        self.assertEqual(self.rate(nobody, self.adult).status_code, 200)


class OrientationIsAdultOnlyTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def save(self, user, **fields):
        self.client.force_authenticate(user)
        return self.client.post(ME, fields, format="json")

    def test_an_adult_may_set_it(self):
        u = member("adult", age=30)
        resp = self.save(u, attracted_to=["women"], asexual=False)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(profile_for(u).attracted_to, ["women"])

    def test_a_teen_may_not(self):
        u = member("teen", age=15)
        resp = self.save(u, attracted_to=["women"])
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(profile_for(u).attracted_to, [])

    def test_the_rest_of_the_save_still_lands(self):
        # Refusing the whole profile save would lose everything else they just
        # typed over two fields they cannot set.
        u = member("teen", age=15)
        resp = self.save(u, attracted_to=["women"], display_name="K-Oth Jr")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(profile_for(u).display_name, "K-Oth Jr")

    def test_it_says_what_it_did_not_save(self):
        # Silently dropping a field is worse than refusing it — the member
        # believes it stored and has no reason to look again.
        resp = self.save(member("teen", age=15), attracted_to=["women"])
        self.assertIn("attracted_to", resp.data["not_saved"])
        self.assertIn("18+", resp.data["not_saved_reason"])

    def test_anything_set_before_the_wall_is_cleared(self):
        # Otherwise the Play disclosure stays true for accounts we now say it
        # isn't, and the data sits there having never been re-consented.
        u = member("teen", age=15)
        p = profile_for(u); p.attracted_to = ["men"]; p.asexual = True; p.save()
        self.save(u, display_name="whatever")
        p.refresh_from_db()
        self.assertEqual(p.attracted_to, [])
        self.assertFalse(p.asexual)

    def test_an_unknown_age_may_still_set_it(self):
        u = member("unknown")
        resp = self.save(u, attracted_to=["women"])
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(profile_for(u).attracted_to, ["women"])
        self.assertNotIn("not_saved", resp.data)

    def test_setting_a_teen_birthday_closes_the_door_on_the_next_save(self):
        # The wall follows the data. A member who fills in a teen birthday
        # loses the adult fields from that point, without an admin touching it.
        u = member("later")
        self.save(u, attracted_to=["women"])
        self.assertEqual(profile_for(u).attracted_to, ["women"])
        self.save(u, birthday=born_years_ago(15))
        self.assertEqual(profile_for(u).attracted_to, [])
