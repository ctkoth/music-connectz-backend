"""The five search ranges are exclusive gates.

Outside the range means excluded, not ranked lower. A gate that quietly lets
people through isn't a gate — a member who set "18–30" and got a 45-year-old
would stop trusting the filter, and then the whole search.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from . import searchfilters as sf
from .models import (AttractivenessRating, OverallRating, profile_for)

User = get_user_model()


def member(name, *, birthday="", price=0, lat=None, lng=None, share=False,
           attractive_public=True):
    u = User.objects.create_user(username=name, password="filters-pass-1")
    p = profile_for(u)
    p.birthday = birthday
    p.skill_price_cents = price
    p.lat, p.lng = lat, lng
    p.share_location = share
    p.attractiveness_public = attractive_public
    p.save()
    return u


def rate(target, scores, kind="overall"):
    model = OverallRating if kind == "overall" else AttractivenessRating
    for i, s in enumerate(scores):
        model.objects.create(rater=member(f"{kind}-rater-{target.username}-{i}"),
                             target=target, score=s)


class RangeTests(TestCase):
    def test_an_inactive_range_is_not_a_gate(self):
        self.assertFalse(sf.Range("age").active)

    def test_it_gates_both_ends(self):
        r = sf.Range("age", 18, 30)
        self.assertTrue(r.contains(18))
        self.assertTrue(r.contains(30))
        self.assertFalse(r.contains(17))
        self.assertFalse(r.contains(31))

    def test_an_open_end_stays_open(self):
        self.assertTrue(sf.Range("age", 18, None).contains(99))
        self.assertTrue(sf.Range("age", None, 30).contains(1))

    def test_unknown_never_satisfies_a_gate(self):
        """If we can't prove they're inside, they aren't."""
        self.assertFalse(sf.Range("age", 18, 30).contains(None))

    def test_a_reversed_range_is_swapped_not_emptied(self):
        """A typo should not silently return nobody."""
        r = sf.Range("age", 30, 18)
        self.assertEqual((r.low, r.high), (18.0, 30.0))

    def test_it_clamps_to_the_hard_limits(self):
        r = sf.Range("attractiveness", -5, 99)
        self.assertEqual((r.low, r.high), (1.0, 10.0))


class ParseTests(TestCase):
    def test_it_reads_the_hyphen_form(self):
        got = sf.parse({"age": "18-30"})
        self.assertEqual((got["age"].low, got["age"].high), (18.0, 30.0))

    def test_it_reads_the_min_max_form(self):
        got = sf.parse({"age_min": "18", "age_max": "30"})
        self.assertEqual((got["age"].low, got["age"].high), (18.0, 30.0))

    def test_only_a_minimum_is_a_valid_gate(self):
        got = sf.parse({"skill_rating_min": "7"})
        self.assertEqual(got["skill_rating"].low, 7.0)
        self.assertIsNone(got["skill_rating"].high)

    def test_nothing_asked_for_means_no_gates(self):
        self.assertEqual(sf.parse({}), {})
        self.assertEqual(sf.parse({"age": ""}), {})

    def test_junk_is_ignored_rather_than_crashing(self):
        self.assertEqual(sf.parse({"age": "abc"}), {})

    def test_all_five_ranges_exist(self):
        self.assertEqual(sorted(sf.RANGES), ["age", "attractiveness", "distance",
                                             "skill_price", "skill_rating"])


class ResolverTests(TestCase):
    def test_age_comes_from_the_birthday(self):
        u = member("aged", birthday="2000-01-01")
        self.assertGreaterEqual(sf.age_of(u), 25)

    def test_no_birthday_is_unknown_not_zero(self):
        self.assertIsNone(sf.age_of(member("ageless")))

    def test_price_of_zero_is_a_real_answer(self):
        """Plenty of people collaborate for free — that's not missing data."""
        self.assertEqual(sf.skill_price_of(member("free_worker", price=0)), 0)

    def test_skill_rating_is_the_overall_median(self):
        u = member("rated")
        rate(u, [8, 8, 10])
        self.assertEqual(sf.skill_rating_of(u), 8)

    def test_attractiveness_is_hidden_when_the_member_opted_out(self):
        """A gate must never expose a score kept off the profile."""
        u = member("private", attractive_public=False)
        rate(u, [9, 9], kind="attractiveness")
        self.assertIsNone(sf.attractiveness_of(u))

    def test_distance_needs_both_sides_sharing(self):
        viewer = member("here", lat=51.5, lng=-0.12, share=True)
        shared = member("there", lat=48.85, lng=2.35, share=True)
        hidden = member("hidden", lat=48.85, lng=2.35, share=False)
        self.assertGreater(sf.distance_of(shared, viewer=viewer), 300)
        self.assertIsNone(sf.distance_of(hidden, viewer=viewer),
                          "one-sided coordinates would leak where someone is")

    def test_distance_is_unknown_when_the_viewer_does_not_share(self):
        viewer = member("lurker", lat=51.5, lng=-0.12, share=False)
        other = member("shown", lat=48.85, lng=2.35, share=True)
        self.assertIsNone(sf.distance_of(other, viewer=viewer))


class ApplyTests(TestCase):
    def test_it_separates_out_of_range_from_unknown(self):
        young = member("young", birthday="2010-01-01")
        right = member("right", birthday="2000-01-01")
        blank = member("blank")
        split = sf.apply([young, right, blank], sf.parse({"age": "18-40"}))
        self.assertEqual([u.username for u in split["matches"]], ["right"])
        self.assertEqual([u.username for u in split["excluded"]], ["young"])
        self.assertEqual([u.username for u in split["unknown"]], ["blank"])

    def test_no_gates_matches_everyone(self):
        people = [member("a"), member("b")]
        self.assertEqual(len(sf.apply(people, {})["matches"]), 2)

    def test_gates_combine_as_and(self):
        u = member("both", birthday="2000-01-01", price=5000)
        ranges = sf.parse({"age": "18-40", "skill_price_max": "1000"})
        self.assertEqual(sf.apply([u], ranges)["matches"], [])

    def test_evaluate_says_which_gate_rejected_them(self):
        u = member("rejected", birthday="2010-01-01")
        ok, detail = sf.evaluate(u, sf.parse({"age": "18-40"}))
        self.assertFalse(ok)
        self.assertEqual(detail["age"]["reason"], "out_of_range")


class CatalogTests(TestCase):
    def test_it_states_that_gates_are_exclusive(self):
        rules = sf.catalog()["rules"]
        self.assertTrue(rules["exclusive"])
        self.assertTrue(rules["unknown_excluded"])

    def test_it_names_every_surface_that_uses_them(self):
        self.assertEqual(sorted(sf.catalog()["applies_to"]),
                         ["battlez", "collabz", "social", "venuez"])


class CollabSkillsRequiredTests(TestCase):
    """"Skill (optional)" was a free-text box nobody could filter on."""

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(member("poster"))

    def test_a_collab_with_no_skill_is_refused(self):
        r = self.client.post(reverse("collabz-projects"),
                             {"title": "Need help", "kind": "original"},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("at least one skill", r.json()["detail"])

    def test_a_collab_with_a_real_skill_is_accepted(self):
        r = self.client.post(reverse("collabz-projects"),
                             {"title": "Need a mixer", "kind": "original",
                              "skills": ["Mixing"]}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["project"]["skills"], ["Mixing"])

    def test_a_decorated_label_from_the_picker_resolves(self):
        r = self.client.post(reverse("collabz-projects"),
                             {"title": "Guitar", "kind": "original",
                              "skills": ["Acoustic Guitar 🎸"]}, format="json")
        self.assertEqual(r.json()["project"]["skills"], ["Acoustic Guitar"])

    def test_free_text_is_not_a_skill_and_says_so(self):
        r = self.client.post(reverse("collabz-projects"),
                             {"title": "Vibes", "kind": "original",
                              "skills": ["good vibes"]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("good vibes", r.json()["unrecognised_skills"])

    def test_the_catalog_serves_the_picker_vocabulary(self):
        body = APIClient().get(reverse("collabz-catalog")).json()
        self.assertTrue(body["skills_required"])
        artist = next(p for p in body["personas"] if p["key"] == "artist")
        names = [c["name"] for c in artist["categories"]]
        self.assertIn("String Instruments", names)
        self.assertIn("ranges", body)
