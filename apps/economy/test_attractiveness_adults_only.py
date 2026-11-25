"""Attractiveness is an ADULT metric in both directions, on the READ side too.

The rating endpoints already refuse a minor as rater or target. These pin the other half: a rating row that already exists
for somebody who is (now) a minor — written before the wall, or before a birthday was set — is never shown, never filterable
and never used to class them; and a searcher who is a minor has the attractiveness range ignored.
"""
import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import (AttractivenessRating, attractiveness_shown_medians, attractiveness_stats,
                                 membership_for, profile_for)

User = get_user_model()


def born(age):
    t = datetime.date.today()
    return f"{t.year - age - 1}-01-01"


class AdultsOnlyReadTests(TestCase):
    def setUp(self):
        self.adult = User.objects.create_user("adultx", "a@e.com", "pw-Long-enough-1")
        self.teen = User.objects.create_user("teenx", "t@e.com", "pw-Long-enough-1")
        self.unknown = User.objects.create_user("unkx", "u@e.com", "pw-Long-enough-1")
        for u, b in ((self.adult, born(30)), (self.teen, born(15)), (self.unknown, "")):
            membership_for(u)
            p = profile_for(u); p.birthday = b; p.save()
        self.raters = [User.objects.create_user(f"r{i}", f"r{i}@e.com", "pw-Long-enough-1") for i in range(3)]
        # Ratings that already exist for all three (written directly: the endpoint would refuse the teen).
        for t in (self.adult, self.teen, self.unknown):
            for r in self.raters:
                AttractivenessRating.objects.create(rater=r, target=t, score=8)

    def test_a_minors_number_is_never_served(self):
        shown = attractiveness_shown_medians([self.adult.id, self.teen.id, self.unknown.id])
        self.assertIn(self.adult.id, shown)
        self.assertNotIn(self.teen.id, shown)
        self.assertIn(self.unknown.id, shown)          # unknown age counts as adult, as everywhere else

    def test_a_minor_is_not_in_the_stats_that_class_and_gate(self):
        stats = attractiveness_stats([self.adult.id, self.teen.id])
        self.assertIn(self.adult.id, stats)
        self.assertNotIn(self.teen.id, stats)

    def test_a_verified_adult_with_a_teen_birthday_typed_is_still_an_adult(self):
        p = profile_for(self.teen); p.verified_18plus = True; p.save()
        self.assertIn(self.teen.id, attractiveness_shown_medians([self.teen.id]))

    def test_a_minor_searcher_has_the_attractiveness_range_ignored(self):
        # A teen only sees their own age group, so there has to be another teen to find.
        peer = User.objects.create_user("teenpeer", "tp@e.com", "pw-Long-enough-1")
        membership_for(peer); pp = profile_for(peer); pp.birthday = born(15); pp.save()
        c = APIClient(); c.force_authenticate(self.teen)
        # An exclusive range that nobody meets: for an adult it would empty the list.
        r = c.get("/api/economy/members/?attr_min=11")
        self.assertEqual(r.status_code, 200)
        names = {m["username"] for m in (r.json().get("members") or r.json().get("results") or [])}
        self.assertIn("teenpeer", names, "a minor's range must be ignored, not applied")
        a = APIClient(); a.force_authenticate(self.adult)
        r2 = a.get("/api/economy/members/?attr_min=11")
        names2 = {m["username"] for m in (r2.json().get("members") or r2.json().get("results") or [])}
        self.assertFalse(names2, "the same range still gates an adult")
