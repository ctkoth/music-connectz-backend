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
from .models import (AttractivenessRating, OverallRating, membership_for,
                     profile_for)

User = get_user_model()


def member(name, *, birthday="", price=0, lat=None, lng=None, share=False,
           attractive_public=True):
    u = User.objects.create_user(username=name, password="filters-pass-1")
    p = profile_for(u)
    p.birthday = birthday
    p.skill_price_cents = price
    p.lat, p.lng = lat, lng
    p.share_location = share
    p.save()
    # The attractiveness opt-in is on Membership, not Profile. Setting it on the
    # profile here is what let a resolver that read the wrong model look correct.
    m = membership_for(u)
    m.attractiveness_public = attractive_public
    m.save(update_fields=["attractiveness_public"])
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

    def test_a_published_attractiveness_score_is_readable(self):
        """The other half of the opt-out test. Without this, a resolver that
        returned None for *everybody* still passed — which it did."""
        u = member("published")
        rate(u, [7, 9], kind="attractiveness")
        self.assertEqual(sf.attractiveness_of(u), 8)

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


class StoredRequirementsTests(TestCase):
    """A search gate lives for one request. A gate set when somebody POSTED has
    to still be there when a stranger tries to join, hours later."""

    def test_a_round_trip_keeps_the_bounds(self):
        stored = sf.store({"age": "18-30"})
        self.assertEqual(stored["age"], {"min": 18.0, "max": 30.0})
        loaded = sf.load(stored)
        self.assertTrue(loaded["age"].contains(25))
        self.assertFalse(loaded["age"].contains(40))

    def test_junk_in_the_stored_dict_is_ignored_not_fatal(self):
        """Hand-edited or older rows must not 500 the join button."""
        self.assertEqual(sf.load({"nonsense": {"min": 1}, "age": "oops"}), {})
        self.assertEqual(sf.load(None), {})

    def test_it_describes_each_gate_in_words(self):
        text = sf.describe(sf.load(sf.store({"age": "18-30",
                                             "skill_rating_min": "7"})))
        self.assertIn("🎂 Age 18–30 years", text)
        self.assertIn("⭐ Skill rating 7+ score", text)

    def test_no_gates_lets_anybody_in(self):
        self.assertIsNone(sf.entry_error(member("open_door"), {}))

    def test_being_out_of_range_says_the_range_and_their_value(self):
        kid = member("too_young", birthday="2015-01-01")
        why = sf.entry_error(kid, sf.store({"age": "18-30"}))
        self.assertIn("18–30", why)
        self.assertIn(str(sf.age_of(kid)), why)

    def test_having_no_value_says_so_instead_of_guessing(self):
        """"You're the wrong age" is a lie when we never asked for a birthday."""
        why = sf.entry_error(member("no_birthday"), sf.store({"age": "18-30"}))
        self.assertIn("isn't set yet", why)


class VenueGateTests(TestCase):
    def setUp(self):
        self.host = member("venue_host", birthday="1990-01-01")
        self.client = APIClient()
        self.client.force_authenticate(self.host)

    def make(self, **extra):
        r = self.client.post(reverse("economy-venues"),
                             dict({"title": "Open mic"}, **extra), format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["venue"]

    def join_as(self, user, venue_id):
        c = APIClient()
        c.force_authenticate(user)
        return c.post(reverse("economy-venue-join", args=[venue_id]), {},
                      format="json")

    def test_the_venue_shows_what_it_gates_on(self):
        v = self.make(age_min=21)
        self.assertIn("🎂 Age 21+ years", v["requirements_text"])

    def test_somebody_outside_the_range_is_turned_away_with_a_reason(self):
        v = self.make(age="21-40")
        r = self.join_as(member("underage", birthday="2012-01-01"), v["id"])
        self.assertEqual(r.status_code, 403)
        self.assertIn("21–40", r.json()["detail"])

    def test_somebody_inside_the_range_gets_in(self):
        v = self.make(age="21-40")
        r = self.join_as(member("of_age", birthday="1995-01-01"), v["id"])
        self.assertEqual(r.status_code, 200, r.content)

    def test_the_old_min_attract_field_still_gates(self):
        """A shipped client that only knows min_attract must keep working."""
        v = self.make(min_attract=7)
        self.assertEqual(v["requirements"]["attractiveness"]["min"], 7.0)
        low = member("plain")
        rate(low, [3, 3], kind="attractiveness")
        self.assertEqual(self.join_as(low, v["id"]).status_code, 403)


class BattleGateTests(TestCase):
    def setUp(self):
        self.creator = member("ring_master", birthday="1990-01-01")
        self.client = APIClient()
        self.client.force_authenticate(self.creator)

    def make(self, **extra):
        r = self.client.post(reverse("battlez-battles"),
                             dict({"title": "Bars", "format": "cypher"}, **extra),
                             format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["battle"]

    def enter_as(self, user, battle_id, side="a"):
        c = APIClient()
        c.force_authenticate(user)
        return c.post(reverse("battlez-entries", args=[battle_id]),
                      {"side": side}, format="json")

    def test_a_battle_carries_its_gates(self):
        b = self.make(skill_rating_min=8)
        self.assertIn("⭐ Skill rating 8+ score", b["requirements_text"])

    def test_an_under_rated_challenger_is_refused(self):
        b = self.make(skill_rating_min=8)
        weak = member("weak")
        rate(weak, [4, 4, 5])
        r = self.enter_as(weak, b["id"])
        self.assertEqual(r.status_code, 403)
        self.assertIn("8+", r.json()["detail"])

    def test_a_qualifying_challenger_gets_in(self):
        b = self.make(skill_rating_min=8)
        strong = member("strong")
        rate(strong, [9, 9, 10])
        self.assertEqual(self.enter_as(strong, b["id"]).status_code, 201)

    def test_gates_do_not_touch_betting_or_voting(self):
        """Who may compete is not who may watch."""
        b = self.make(skill_rating_min=8)
        watcher = member("spectator")
        c = APIClient()
        c.force_authenticate(watcher)
        r = c.post(reverse("battlez-votes", args=[b["id"]]), {"side": "a"},
                   format="json")
        self.assertNotEqual(r.status_code, 403)


class CollabGateTests(TestCase):
    def setUp(self):
        self.owner = member("collab_owner", birthday="1990-01-01")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def make(self, **extra):
        r = self.client.post(reverse("collabz-projects"),
                             dict({"title": "Track", "kind": "original",
                                   "skills": ["Mixing"]}, **extra), format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["project"]

    def join_as(self, user, pid):
        c = APIClient()
        c.force_authenticate(user)
        return c.post(reverse("collabz-members", args=[pid]), {}, format="json")

    def test_a_price_gate_turns_away_somebody_too_expensive(self):
        p = self.make(skill_price_max=5000)
        r = self.join_as(member("pricey", price=20_000), p["id"])
        self.assertEqual(r.status_code, 403)
        self.assertIn("Skill price", " ".join(p["requirements_text"]))

    def test_somebody_within_budget_joins(self):
        p = self.make(skill_price_max=5000)
        self.assertEqual(self.join_as(member("affordable", price=2500),
                                      p["id"]).status_code, 201)

    def test_an_owners_invite_overrides_the_gate(self):
        """The owner picked that person on purpose. A filter that overrules a
        deliberate choice is the filter being wrong."""
        p = self.make(skill_price_max=5000)
        member("chosen", price=99_000)
        r = self.client.post(reverse("collabz-members", args=[p["id"]]),
                             {"username": "chosen"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)


class SocialSearchTests(TestCase):
    def setUp(self):
        self.me = member("searcher", birthday="1990-01-01")
        self.client = APIClient()
        self.client.force_authenticate(self.me)

    def search(self, **params):
        return self.client.get(reverse("economy-members"), params).json()

    def test_it_gates_on_skill_price_which_it_never_used_to(self):
        member("cheap", price=1000)
        member("dear", price=50_000)
        names = [m["username"] for m in
                 self.search(skill_price_max=5000)["members"]]
        self.assertEqual(names, ["cheap"])

    def test_it_gates_on_skill_rating_which_it_never_used_to(self):
        good = member("good_mixer")
        rate(good, [9, 9])
        member("unrated_mixer")
        names = [m["username"] for m in
                 self.search(skill_rating_min=8)["members"]]
        self.assertEqual(names, ["good_mixer"])

    def test_a_private_attractiveness_score_is_not_searchable(self):
        """The old inline gate read the median regardless of the opt-out, so a
        score somebody hid could still be filtered on — which reveals it."""
        hidden = member("kept_private", attractive_public=False)
        rate(hidden, [9, 9], kind="attractiveness")
        names = [m["username"] for m in
                 self.search(attractiveness_min=8)["members"]]
        self.assertNotIn("kept_private", names)

    def test_the_old_parameter_names_still_work(self):
        member("young_one", birthday="2015-01-01")
        old = member("grown", birthday="1995-01-01")
        rate(old, [9, 9], kind="attractiveness")
        names = [m["username"] for m in self.search(attr_min=8)["members"]]
        self.assertEqual(names, ["grown"])

    def test_members_with_nothing_set_are_counted_not_just_dropped(self):
        member("blank_slate")
        body = self.search(age_min=18)
        self.assertEqual(body["unknown_count"], 1)


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

    def test_the_picker_can_serve_exactly_the_2_2_vocabulary(self):
        """"I need 2.2" — five personas, 131 skills, nothing added since."""
        body = APIClient().get(reverse("collabz-catalog"), {"since": "2.2"}).json()
        self.assertEqual(body["since"], "2.2")
        self.assertEqual(len(body["personas"]), 5)
        self.assertEqual(body["skill_count"], 131)
        self.assertTrue(all(s["v22"] for p in body["personas"]
                            for c in p["categories"] for s in c["skills"]))

    def test_the_full_catalog_is_a_superset_of_2_2(self):
        """Neither list may drift from the other — they're one source filtered."""
        def flat(params):
            body = APIClient().get(reverse("collabz-catalog"), params).json()
            return {(p["key"], c["name"], s["key"]) for p in body["personas"]
                    for c in p["categories"] for s in c["skills"]}

        self.assertTrue(flat({"since": "2.2"}) <= flat({}))
