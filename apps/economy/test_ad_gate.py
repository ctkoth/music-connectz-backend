"""Whether a member may be shown a third-party ad frame.

`play/data-safety.md` answers "Committed to the Play Families Policy: Yes", and
that answer was earned by hard-walling the adult surfaces for teen accounts.
Teens are an intended audience — RapZ carries a "Teen-safe · SkillZ training"
badge — and the Families Policy requires ads shown to them to come from a
Play-certified SDK. An arbitrary third-party ad frame is not one and cannot
attest to being one.

So the rule is one function, answered by the server, and these tests hold it to
the same age logic the adult surfaces already use. A second copy of a policy
rule Google audits is the kind that drifts and is noticed when an app is pulled.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.models import (
    is_minor,
    membership_for,
    profile_for,
    third_party_ads_allowed,
)

User = get_user_model()
PW = "hunter2hunter2"
LIMITS = "/api/economy/limits/"


def born(years_ago):
    """A birthday that makes someone exactly `years_ago` years old this year.

    Anchored to January so leap days can't shift a 17-year-old into 18 — an
    earlier version of this helper did exactly that and quietly made a test
    about minors run against an adult.
    """
    return f"{timezone.now().year - years_ago}-01-01"


class Base(TestCase):
    def member(self, name, *, birthday=None, verified=False):
        user = User.objects.create_user(name, f"{name}@e.com", PW)
        membership_for(user)
        p = profile_for(user)
        if birthday:
            p.birthday = birthday
        p.verified_18plus = verified
        p.save()
        return user


class TheRuleFollowsTheAgeWall(Base):
    def test_a_teen_is_not_shown_third_party_ads(self):
        teen = self.member("teen", birthday=born(15))
        self.assertTrue(is_minor(teen))
        self.assertFalse(third_party_ads_allowed(teen))

    def test_an_adult_is(self):
        adult = self.member("adult", birthday=born(30))
        self.assertTrue(third_party_ads_allowed(adult))

    def test_an_unknown_age_counts_as_an_adult(self):
        # Matches is_minor and the decision recorded in play/data-safety.md:
        # most of the user base has no birthday, and treating unknown as
        # underage would take features from real people to satisfy a form.
        self.assertTrue(third_party_ads_allowed(self.member("nobirthday")))

    def test_id_verification_outranks_a_typed_birthday(self):
        # A verified adult is an adult whatever the birthday field says — the
        # ID outranks the typing, in the permissive direction only.
        verified = self.member("verified", birthday=born(15), verified=True)
        self.assertTrue(third_party_ads_allowed(verified))

    def test_the_boundaries_land_where_the_age_wall_puts_them(self):
        for years, allowed in ((12, True), (13, False), (17, False), (18, True)):
            with self.subTest(age=years):
                user = self.member(f"age{years}", birthday=born(years))
                # Under 13 isn't a "minor" by this app's definition — that
                # bracket is refused at signup, not ad-gated here. The rule
                # tracks is_minor exactly rather than inventing its own bands.
                self.assertEqual(third_party_ads_allowed(user), allowed)
                self.assertEqual(third_party_ads_allowed(user), not is_minor(user))

    def test_the_decision_never_disagrees_with_is_minor(self):
        for name, birthday in (("a", born(14)), ("b", born(40)), ("c", None)):
            with self.subTest(member=name):
                user = self.member(f"pair{name}", birthday=birthday)
                self.assertEqual(third_party_ads_allowed(user), not is_minor(user))


class TheClientIsToldTheAnswerNotTheAge(Base):
    def test_limits_carries_the_decision(self):
        adult = self.member("adult", birthday=born(30))
        client = APIClient()
        client.force_authenticate(adult)
        self.assertTrue(client.get(LIMITS).json()["third_party_ads"])

    def test_a_teen_is_told_no(self):
        teen = self.member("teen", birthday=born(15))
        client = APIClient()
        client.force_authenticate(teen)
        self.assertFalse(client.get(LIMITS).json()["third_party_ads"])

    def test_the_endpoint_does_not_ship_the_birthday_to_decide_it(self):
        # The client should not need an age to know whether to render an advert.
        # Sending one so the browser can work it out would be a member's
        # birthday travelling further than it needs to, not less.
        teen = self.member("teen", birthday=born(15))
        client = APIClient()
        client.force_authenticate(teen)
        payload = client.get(LIMITS).json()
        self.assertIn("third_party_ads", payload)
        self.assertNotIn("birthday", payload)
        self.assertNotIn("age", payload)

    def test_anonymous_callers_get_no_answer_at_all(self):
        # An unauthenticated caller has no age to reason about, so the safe
        # thing is that they can't reach the endpoint rather than defaulting.
        self.assertEqual(APIClient().get(LIMITS).status_code, 401)
