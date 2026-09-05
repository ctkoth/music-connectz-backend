"""The member directory: the viewer sets the order, and the count is honest.

Two things were true before this: `/api/economy/members/` had no consumer in
the mounted app at all (Social ConnectZ rendered six invented creators), and
the endpoint answered in ONE fixed order with a `members` array capped at 100
and no way to tell that from "the whole platform".

So this pins three properties:

* every order in `orders` actually reorders, and puts "no value" LAST — a
  member with no rating is not a member rated zero;
* `matched` counts everyone the filters kept, not the page;
* the page is built in a bounded number of queries. That last one is the
  reason the rest is affordable: the card carries follower counts and two
  medians, which were several queries EACH before the bulk helpers landed.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.models import (Follow, OverallRating, membership_for,
                                 profile_for)
from apps.economy.social import MEMBER_ORDERS

User = get_user_model()


def mk(name, **profile):
    u = User.objects.create_user(name, f"{name}@e.com", "pw12345678")
    p = profile_for(u)
    for k, v in profile.items():
        setattr(p, k, v)
    p.save()
    return u


class MemberOrderTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.me = User.objects.create_user("me", "me@e.com", "pw12345678")
        self.client.force_authenticate(self.me)
        # Three members, deliberately created in an order that matches none of
        # the sorts, so a passing test cannot be creation order in disguise.
        self.b = mk("bravo")
        self.a = mk("alpha")
        self.c = mk("charlie")

    def names(self, **params):
        resp = self.client.get("/api/economy/members/", params)
        self.assertEqual(resp.status_code, 200, resp.content)
        return resp, [m["username"] for m in resp.data["members"]]

    def test_orders_are_published_with_the_results(self):
        resp, _ = self.names()
        keys = [o["key"] for o in resp.data["orders"]]
        # Every order the server can do is offered, minus the one that needs a
        # location this member has not shared.
        self.assertIn("name", keys)
        self.assertIn("rated", keys)
        self.assertNotIn("nearest", keys)
        for o in resp.data["orders"]:
            self.assertTrue(o["label"] and o["note"], o)

    def test_nearest_is_only_offered_when_the_viewer_shares_a_location(self):
        p = profile_for(self.me)
        p.share_location, p.lat, p.lng = True, 40.0, -74.0
        p.save()
        resp, _ = self.names()
        self.assertIn("nearest", [o["key"] for o in resp.data["orders"]])

    def test_name_order_is_alphabetical(self):
        _, names = self.names(sort="name")
        self.assertEqual(names, ["alpha", "bravo", "charlie"])

    def test_rated_puts_the_highest_first_and_the_unrated_last(self):
        for score, target in ((9, self.c), (4, self.b)):
            OverallRating.objects.create(rater=self.me, target=target, score=score)
        _, names = self.names(sort="rated")
        self.assertEqual(names, ["charlie", "bravo", "alpha"])

    def test_followers_order_counts_music_connectz_followers(self):
        Follow.objects.create(follower=self.me, following=self.b)
        Follow.objects.create(follower=self.a, following=self.b)
        Follow.objects.create(follower=self.me, following=self.c)
        _, names = self.names(sort="followers")
        self.assertEqual(names[:2], ["bravo", "charlie"])

    def test_newest_is_most_recently_joined_first(self):
        for user, days in ((self.a, 30), (self.b, 10), (self.c, 1)):
            user.date_joined = timezone.now() - timedelta(days=days)
            user.save(update_fields=["date_joined"])
        _, names = self.names(sort="newest")
        self.assertEqual(names, ["charlie", "bravo", "alpha"])

    def test_active_is_most_recently_seen_first_and_never_seen_last(self):
        m = membership_for(self.b)
        m.last_seen = timezone.now() - timedelta(hours=1)
        m.save(update_fields=["last_seen"])
        m = membership_for(self.a)
        m.last_seen = timezone.now() - timedelta(days=9)
        m.save(update_fields=["last_seen"])
        membership_for(self.c).__class__.objects.filter(user=self.c).update(last_seen=None)
        _, names = self.names(sort="active")
        self.assertEqual(names, ["bravo", "alpha", "charlie"])

    def test_an_unknown_sort_falls_back_rather_than_erroring(self):
        resp, names = self.names(sort="whatever-they-typed")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(sorted(names), ["alpha", "bravo", "charlie"])
        self.assertEqual(resp.data["sort"], "")

    def test_matched_counts_everyone_not_the_page(self):
        resp, names = self.names()
        self.assertEqual(resp.data["matched"], 3)
        self.assertEqual(len(names), 3)

    def test_the_viewer_is_never_in_their_own_directory(self):
        _, names = self.names()
        self.assertNotIn("me", names)

    def test_a_page_of_members_is_a_bounded_number_of_queries(self):
        # Twenty more members, so a per-card query would show up as a hundred
        # extra. This is the property that lets the header pill open a real
        # directory instead of a six-row invention.
        for i in range(20):
            mk(f"member{i:02d}")
        with self.assertNumQueries(FuzzyMax(28)):
            self.client.get("/api/economy/members/", {"sort": "name"})


class FuzzyMax(int):
    """assertNumQueries wants an exact number; what matters here is a CEILING.

    Pinning the exact count turns every unrelated query change into a failing
    test that teaches nobody anything. Pinning a ceiling catches the thing
    this test exists for: a query that runs once PER MEMBER."""

    def __eq__(self, other):
        return other <= int(self)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return int.__hash__(self)


class MemberOrderCoverageTests(TestCase):
    def test_every_published_order_is_implemented(self):
        """A key in MEMBER_ORDERS that `_sort_members` doesn't handle would be
        an option in the picker that quietly does nothing."""
        from apps.economy.social import _sort_members
        cards = [
            {"username": "b", "overall": 5, "followers": 2, "experience_years": 3,
             "distance_km": 10, "last_seen": "2026-01-02T00:00:00", "joined": "2020-01-01T00:00:00"},
            {"username": "a", "overall": None, "followers": 9, "experience_years": None,
             "distance_km": None, "last_seen": None, "joined": "2024-01-01T00:00:00"},
        ]
        for o in MEMBER_ORDERS:
            out = _sort_members(list(cards), o["key"], True, set())
            self.assertEqual(len(out), 2, o["key"])
            if o["key"] in ("rated", "experience", "nearest", "active"):
                # Whatever the key, the member with no value for it is last.
                self.assertEqual(out[-1]["username"], "a", o["key"])
