"""Range gates — five ranges, one spec, every surface.

The blueprint asks for five exclusive ranges (skill rating, skill price,
attractiveness, age, distance) on member search AND on anything a member posts
that others join. Two of them did not exist at all: nothing stored a skill
price, and nothing ever read an overall rating in search.
"""
import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.gates import (
    GATE_KEYS,
    clean_gates,
    describe,
    failing_gate,
    member_metrics,
)
from apps.economy.models import (
    AttractivenessRating,
    CollabDeal,
    OverallRating,
    Profile,
    Venue,
    profile_for,
)
from apps.economy.social import profile_skill_rate

User = get_user_model()
PW = "hunter2hunter2"


def birthday_for_age(years):
    today = datetime.date.today()
    return f"{today.year - years:04d}-{today.month:02d}-{today.day:02d}"


def make_member(name, *, rating=None, attract=None, age=None, rates=(),
                lat=None, lng=None):
    """A member carrying exactly the metrics a test needs, and none of the
    others — an absent metric is the case the gates are supposed to exclude."""
    user = User.objects.create_user(name, f"{name}@e.com", PW)
    p = profile_for(user)
    if age is not None:
        p.birthday = birthday_for_age(age)
    if rates:
        p.personas = [{"key": "musician", "name": "Musician", "skills": [
            {"name": f"skill{i}", "rate_cents": c} for i, c in enumerate(rates)
        ]}]
    if lat is not None:
        p.lat, p.lng, p.share_location = lat, lng, True
    p.save()
    if rating is not None:
        rater = User.objects.create_user(f"{name}-r", f"{name}-r@e.com", PW)
        OverallRating.objects.create(rater=rater, target=user, score=rating)
    if attract is not None:
        rater = User.objects.create_user(f"{name}-a", f"{name}-a@e.com", PW)
        AttractivenessRating.objects.create(rater=rater, target=user, score=attract)
    return user


class CleanGatesTests(TestCase):
    def test_a_pair_survives_and_is_numeric(self):
        self.assertEqual(clean_gates({"rating": ["4", 8]}), {"rating": [4.0, 8.0]})

    def test_one_sided_ranges_are_kept(self):
        self.assertEqual(clean_gates({"age": [21, None]}), {"age": [21.0, None]})
        self.assertEqual(clean_gates({"age": [None, 30]}), {"age": [None, 30.0]})

    def test_an_empty_pair_is_not_a_gate(self):
        self.assertEqual(clean_gates({"age": [None, None]}), {})
        self.assertEqual(clean_gates({"age": ["", ""]}), {})

    def test_distance_is_a_maximum_only(self):
        # "within N km" has no floor worth expressing, so a bare number reads
        # as the ceiling rather than the floor.
        self.assertEqual(clean_gates({"km": 25}), {"km": [None, 25.0]})
        self.assertEqual(clean_gates({"km": [None, 25]}), {"km": [None, 25.0]})

    def test_negative_distance_is_clamped_not_inverted(self):
        self.assertEqual(clean_gates({"km": -5}), {"km": [None, 0.0]})

    def test_unknown_keys_and_junk_are_dropped(self):
        self.assertEqual(clean_gates({"height": [1, 2], "rating": "nonsense"}), {})
        self.assertEqual(clean_gates(None), {})
        self.assertEqual(clean_gates([1, 2]), {})

    def test_every_declared_key_round_trips(self):
        raw = {"rating": [1, 10], "price": [0, 5000], "attract": [5, 10],
               "age": [18, 99], "km": [None, 50]}
        self.assertEqual(set(clean_gates(raw)), set(GATE_KEYS))


class FailingGateTests(TestCase):
    GATES = {"rating": [4.0, 8.0], "age": [21.0, None], "km": [None, 50.0]}

    def test_inside_every_range_passes(self):
        m = {"rating": 6, "age": 30, "km": 10}
        self.assertIsNone(failing_gate(m, self.GATES))

    def test_below_the_floor_names_the_gate(self):
        self.assertEqual(failing_gate({"rating": 2, "age": 30, "km": 1}, self.GATES), "rating")

    def test_above_the_ceiling_names_the_gate(self):
        self.assertEqual(failing_gate({"rating": 6, "age": 30, "km": 90}, self.GATES), "km")

    def test_no_value_for_a_gated_metric_is_excluded(self):
        # This is the whole point of "gates exclusive". A rating gate that lets
        # unrated members through is not a gate, it's a suggestion.
        self.assertEqual(failing_gate({"rating": None, "age": 30, "km": 1}, self.GATES), "rating")

    def test_a_metric_with_no_gate_may_be_missing(self):
        self.assertIsNone(failing_gate({"rating": 6, "age": 30, "km": 1, "price": None}, self.GATES))

    def test_no_gates_admits_everyone(self):
        self.assertIsNone(failing_gate({}, {}))
        self.assertIsNone(failing_gate({}, None))

    def test_the_boundaries_are_inclusive(self):
        self.assertIsNone(failing_gate({"rating": 4, "age": 21, "km": 50}, self.GATES))

    def test_describe_reads_as_the_host_wrote_it(self):
        self.assertEqual(describe("km", self.GATES), "within 50 km")
        self.assertEqual(describe("rating", self.GATES), "skill rating 4–8")
        self.assertEqual(describe("age", self.GATES), "age at least 21")


class SkillPriceTests(TestCase):
    """The price range had no metric behind it — a skill carried a name and a
    start date and nothing else, so `rate_cents` had to exist first."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("priced", "p@e.com", PW)
        self.client.force_authenticate(self.user)

    def test_rate_survives_a_profile_save(self):
        resp = self.client.patch("/api/auth/me/", {"personas": [
            {"key": "musician", "name": "Musician",
             "skills": [{"name": "Violin", "start": "2000-01-01", "rate_cents": 4500}]}
        ]}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        skill = profile_for(self.user).personas[0]["skills"][0]
        self.assertEqual(skill["rate_cents"], 4500)
        self.assertEqual(skill["start"], "2000-01-01")   # and the stint is intact

    def test_a_junk_rate_is_dropped_not_stored(self):
        self.client.patch("/api/auth/me/", {"personas": [
            {"key": "m", "name": "M", "skills": [{"name": "Violin", "rate_cents": "free"}]}
        ]}, format="json")
        self.assertNotIn("rate_cents", profile_for(self.user).personas[0]["skills"][0])

    def test_the_price_metric_is_the_cheapest_skill(self):
        # A price gate asks "can I afford this person" — the honest answer is
        # their cheapest skill, not their dearest.
        p = profile_for(make_member("multi", rates=(9000, 2500, 6000)))
        self.assertEqual(profile_skill_rate(p), 2500)

    def test_a_member_with_no_rate_has_no_price(self):
        p = profile_for(make_member("unpriced"))
        self.assertIsNone(profile_skill_rate(p))


class MetricsAreLazyTests(TestCase):
    """Search walks up to 500 profiles. If every metric were computed for every
    member, a search with no gates set would cost a thousand pointless queries."""

    def test_untouched_metrics_cost_nothing(self):
        make_member("lazy", rating=7)
        # select_related the way MembersView does, so the user row is not a
        # query of its own.
        profile = Profile.objects.select_related("user").get(user__username="lazy")
        metrics = member_metrics(profile)
        with self.assertNumQueries(0):
            metrics.get("age")          # pure profile field
        with self.assertNumQueries(1):
            self.assertEqual(metrics.get("rating"), 7)
        with self.assertNumQueries(0):
            self.assertEqual(metrics.get("rating"), 7)   # cached


class MemberSearchGateTests(TestCase):
    """The five ranges as the searcher sees them."""

    def setUp(self):
        self.client = APIClient()
        self.me = User.objects.create_user("me", "me@e.com", PW)
        self.client.force_authenticate(self.me)

    def names(self, **params):
        resp = self.client.get("/api/economy/members/", params)
        self.assertEqual(resp.status_code, 200, resp.content)
        return {m["username"] for m in resp.data["members"]}

    def test_skill_rating_range(self):
        make_member("low", rating=2)
        make_member("mid", rating=6)
        make_member("high", rating=10)
        self.assertEqual(self.names(rating_min=5, rating_max=8), {"mid"})

    def test_an_unrated_member_is_excluded_by_a_rating_gate(self):
        make_member("mid", rating=6)
        make_member("unrated")
        self.assertEqual(self.names(rating_min=1, rating_max=10), {"mid"})
        # …and is perfectly visible when nobody asked for a rating.
        self.assertIn("unrated", self.names())

    def test_skill_price_range(self):
        make_member("cheap", rates=(1500,))
        make_member("dear", rates=(20000,))
        make_member("free")
        self.assertEqual(self.names(price_min=0, price_max=5000), {"cheap"})

    def test_price_uses_the_cheapest_skill_so_a_dear_extra_is_not_a_bar(self):
        make_member("mixed", rates=(1500, 30000))
        self.assertEqual(self.names(price_max=5000), {"mixed"})

    def test_attractiveness_range(self):
        make_member("plain", attract=3)
        make_member("striking", attract=9)
        self.assertEqual(self.names(attr_min=8), {"striking"})

    def test_age_range(self):
        make_member("young", age=19)
        make_member("older", age=44)
        self.assertEqual(self.names(age_min=25, age_max=60), {"older"})

    def test_distance_range(self):
        p = profile_for(self.me)
        p.lat, p.lng, p.share_location = 40.0, -74.0, True
        p.save()
        make_member("near", lat=40.05, lng=-74.0)
        make_member("far", lat=45.0, lng=-74.0)
        make_member("hidden")           # shares no location at all
        self.assertEqual(self.names(max_km=50), {"near"})

    def test_all_five_at_once_is_an_and(self):
        make_member("perfect", rating=7, attract=7, age=30, rates=(2000,))
        make_member("cheap-but-unrated", attract=7, age=30, rates=(2000,))
        self.assertEqual(
            self.names(rating_min=5, attr_min=5, age_min=18, age_max=99, price_max=5000),
            {"perfect"},
        )

    def test_the_distance_number_still_reaches_the_card(self):
        p = profile_for(self.me)
        p.lat, p.lng, p.share_location = 40.0, -74.0, True
        p.save()
        make_member("near", lat=40.05, lng=-74.0)
        resp = self.client.get("/api/economy/members/", {"max_km": 50})
        self.assertIsNotNone(resp.data["members"][0]["distance_km"])


class VenueGateTests(TestCase):
    """A venue advertises its gates and the door enforces the same ones."""

    def setUp(self):
        self.client = APIClient()
        self.host = User.objects.create_user("host", "h@e.com", PW)

    def venue(self, **kw):
        return Venue.objects.create(host=self.host, title="Session", host_price_cents=0, **kw)

    def test_a_host_can_post_gates_and_read_them_back(self):
        self.client.force_authenticate(self.host)
        resp = self.client.post("/api/economy/venues/", {
            "title": "Studio night", "gates": {"rating": [6, 10], "km": 25},
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["venue"]["gates"], {"rating": [6.0, 10.0], "km": [None, 25.0]})

    def test_a_member_outside_the_range_is_refused_and_told_which_one(self):
        v = self.venue(gates={"rating": [6, 10]})
        self.client.force_authenticate(make_member("weak", rating=2))
        resp = self.client.post(f"/api/economy/venues/{v.pk}/join/")
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertEqual(resp.data["gate"], "rating")
        self.assertIn("skill rating", resp.data["detail"])

    def test_an_unrated_member_is_refused_too(self):
        v = self.venue(gates={"rating": [1, 10]})
        self.client.force_authenticate(make_member("unrated"))
        self.assertEqual(self.client.post(f"/api/economy/venues/{v.pk}/join/").status_code, 403)

    def test_a_member_inside_every_range_gets_in(self):
        v = self.venue(gates={"rating": [6, 10], "age": [18, None]})
        self.client.force_authenticate(make_member("solid", rating=8, age=30))
        resp = self.client.post(f"/api/economy/venues/{v.pk}/join/")
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_an_ungated_venue_asks_nobody_for_anything(self):
        v = self.venue()
        self.client.force_authenticate(make_member("anyone"))
        self.assertEqual(self.client.post(f"/api/economy/venues/{v.pk}/join/").status_code, 200)

    def test_the_legacy_min_attract_venues_still_work(self):
        # Venues created before gates existed carry min_attract and nothing else.
        v = self.venue(min_attract=8)
        self.client.force_authenticate(make_member("plain", attract=3))
        resp = self.client.post(f"/api/economy/venues/{v.pk}/join/")
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertIn("attractiveness 8+", resp.data["detail"])


class CollabGateTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        # Both priced, because a deal's gates are now ENFORCED on the people
        # named on it — storing them and checking nothing made "CollabZ carries
        # the range gates" a label. See test_collab_split for the refusals.
        self.me = make_member("initiator", rates=(2500,))
        self.mate = make_member("mate", rates=(2500,))
        self.client.force_authenticate(self.me)

    def test_a_deal_carries_its_gates(self):
        resp = self.client.post("/api/economy/collab/", {
            "title": "EP", "currency": "spinaz",
            "participants": [{"username": "initiator", "worth_cents": 100},
                             {"username": "mate", "worth_cents": 100}],
            "gates": {"price": [None, 5000]},
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["gates"], {"price": [None, 5000.0]})
        self.assertEqual(CollabDeal.objects.get().gates, {"price": [None, 5000.0]})

    def test_an_ungated_deal_reports_an_empty_dict_not_null(self):
        resp = self.client.post("/api/economy/collab/", {
            "title": "EP", "currency": "spinaz",
            "participants": [{"username": "initiator", "worth_cents": 100},
                             {"username": "mate", "worth_cents": 100}],
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["gates"], {})
