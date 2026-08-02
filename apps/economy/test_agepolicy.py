"""Collaborate across ages. Don't date across them.

Music ConnectZ is all-ages and creative. A 15-year-old working with a
30-year-old producer is the ordinary case, and gating it removes the reason a
young member is here at all. The line goes around the surfaces that are about
somebody's BODY, not around the ones about their WORK.

Before agepolicy.py that was backwards: MangaZ fenced adults out of
collaborating, while any adult could score a 14-year-old 1-10 and that minor
would come back from an "attractiveness 8+" search.
"""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from . import agepolicy, searchfilters as sf
from .models import AttractivenessRating, Face, membership_for, profile_for

User = get_user_model()


def member(name, *, age=None, verified=False):
    u = User.objects.create_user(username=name, password="agepolicy-pass-1")
    p = profile_for(u)
    if age is not None:
        t = date.today()
        p.birthday = f"{t.year - age}-{t.month:02d}-{t.day:02d}"
    p.verified_18plus = verified
    p.save()
    m = membership_for(u)
    m.attractiveness_public = True
    m.save(update_fields=["attractiveness_public"])
    return u


class CollaborationIsOpenTests(TestCase):
    """The half that must NOT be restricted."""

    def test_a_teen_and_an_adult_may_collaborate(self):
        self.assertTrue(agepolicy.can_collaborate(member("teen", age=15),
                                                  member("adult", age=40)))

    def test_an_unknown_age_is_not_treated_as_a_minor_for_collaboration(self):
        """Locking incomplete profiles teaches people to lie about their
        birthday, which makes the data worse for the checks that matter."""
        self.assertFalse(agepolicy.is_minor(member("mystery")))

    def test_a_birthday_is_not_verification(self):
        self.assertFalse(agepolicy.is_verified_adult(member("claims", age=30)))
        self.assertTrue(agepolicy.is_verified_adult(
            member("proved", age=30, verified=True)))


class BodyRatingIsAdultsOnlyTests(TestCase):
    def test_an_adult_may_not_rate_a_minor(self):
        why = agepolicy.adults_only_error(member("grown", age=30),
                                          member("kid", age=14))
        self.assertIn("18+", why)

    def test_a_minor_may_not_rate_an_adult(self):
        """The same feature pointed the other way."""
        why = agepolicy.adults_only_error(member("kid2", age=14),
                                          member("grown2", age=30))
        self.assertIn("18+", why)

    def test_two_adults_are_fine(self):
        self.assertIsNone(agepolicy.adults_only_error(member("a1", age=30),
                                                      member("a2", age=25)))

    def test_an_unknown_age_is_refused_here(self):
        """Opposite default to collaboration, on purpose: "we don't know" is
        not "we checked", and this is the side where being wrong matters."""
        why = agepolicy.adults_only_error(member("nobirthday"),
                                          member("a3", age=30))
        self.assertIn("birthday", why)

    def test_the_message_says_what_you_CAN_do(self):
        why = agepolicy.adults_only_error(member("k3", age=14),
                                          member("a4", age=30))
        self.assertIn("Collaborating", why)


class RateEndpointTests(TestCase):
    def setUp(self):
        self.adult = member("rater_adult", age=30)
        self.client = APIClient()
        self.client.force_authenticate(self.adult)

    def rate(self, username, score=9):
        return self.client.post(reverse("economy-attractiveness-rate"),
                                {"target_username": username, "score": score},
                                format="json")

    def test_an_adult_cannot_score_a_minor(self):
        member("minor_target", age=14)
        r = self.rate("minor_target")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(AttractivenessRating.objects.count(), 0)

    def test_an_adult_can_score_another_adult(self):
        member("adult_target", age=22)
        self.assertEqual(self.rate("adult_target").status_code, 200)

    def test_a_minor_cannot_score_anyone(self):
        member("adult_target2", age=22)
        c = APIClient()
        c.force_authenticate(member("minor_rater", age=15))
        r = c.post(reverse("economy-attractiveness-rate"),
                   {"target_username": "adult_target2", "score": 9},
                   format="json")
        self.assertEqual(r.status_code, 403)

    def test_a_minors_face_cannot_be_scored(self):
        owner = member("minor_face_owner", age=13)
        face = Face.objects.create(owner=owner, name="pic")
        r = self.client.post(reverse("economy-face-rate", args=[face.id]),
                             {"score": 8}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_a_face_tagging_a_minor_cannot_be_scored_either(self):
        """The owner being an adult doesn't make the person in the photo one."""
        face = Face.objects.create(owner=member("adult_owner", age=30),
                                   name="pic",
                                   tagged=member("tagged_minor", age=15))
        r = self.client.post(reverse("economy-face-rate", args=[face.id]),
                             {"score": 8}, format="json")
        self.assertEqual(r.status_code, 403)


class MinorsAreNotSearchableByLooksTests(TestCase):
    def test_a_minor_never_resolves_an_attractiveness_score(self):
        """Checked at READ time too — ratings collected before a birthday was
        filled in must stop counting once we learn whose they are."""
        minor = member("late_birthday", age=16)
        for i in range(2):
            AttractivenessRating.objects.create(
                rater=member(f"r{i}", age=30), target=minor, score=9)
        self.assertIsNone(sf.attractiveness_of(minor))

    def test_an_adult_still_resolves(self):
        grown = member("visible", age=30)
        for i in range(2):
            AttractivenessRating.objects.create(
                rater=member(f"s{i}", age=30), target=grown, score=8)
        self.assertEqual(sf.attractiveness_of(grown), 8)

    def test_a_minor_is_excluded_from_an_attractiveness_gate(self):
        minor = member("gated_minor", age=15)
        for i in range(2):
            AttractivenessRating.objects.create(
                rater=member(f"t{i}", age=30), target=minor, score=10)
        split = sf.apply([minor], sf.parse({"attractiveness_min": "8"}))
        self.assertEqual(split["matches"], [])

    def test_an_unknown_age_is_excluded_too(self):
        self.assertIsNone(sf.attractiveness_of(member("ageless")))
