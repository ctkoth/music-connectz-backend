"""Anyone can look. Nobody can touch, and some things nobody can see.

Most of this file is about what public access must NOT serve. That's the part
worth testing: a missing feature gets reported, a leak doesn't — the member
whose location went out to the open web never finds out.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from .models import (AttractivenessRating, Post, membership_for, profile_for,
                     wallet_for)

User = get_user_model()


def member(name, **profile_bits):
    u = User.objects.create_user(username=name, email=f"{name}@example.com",
                                 password="public-pass-1")
    p = profile_for(u)
    for key, value in profile_bits.items():
        setattr(p, key, value)
    p.save()
    return u


def post(author, title, visibility="public"):
    return Post.objects.create(author=author, title=title,
                               visibility=visibility)


class AnonymousCanLookTests(TestCase):
    def setUp(self):
        self.client = APIClient()          # deliberately NOT authenticated
        self.author = member("open_artist", bio="I make beats")
        post(self.author, "Public track")

    def test_the_overview_answers_what_you_can_do_without_an_account(self):
        r = self.client.get(reverse("public-overview"))
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("feed", body["public"]["readable"])
        self.assertIn("posting", body["public"]["requires_account"])

    def test_the_feed_is_readable(self):
        r = self.client.get(reverse("public-feed"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual([p["title"] for p in r.json()["posts"]],
                         ["Public track"])

    def test_a_member_page_is_readable(self):
        r = self.client.get(reverse("public-member", args=["open_artist"]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["member"]["bio"], "I make beats")
        self.assertEqual(len(r.json()["posts"]), 1)

    def test_the_member_list_is_readable(self):
        r = self.client.get(reverse("public-members"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("open_artist",
                      [m["username"] for m in r.json()["members"]])

    def test_an_unknown_member_is_a_clean_404(self):
        r = self.client.get(reverse("public-member", args=["nobody"]))
        self.assertEqual(r.status_code, 404)

    def test_username_lookup_is_case_insensitive(self):
        r = self.client.get(reverse("public-member", args=["OPEN_ARTIST"]))
        self.assertEqual(r.status_code, 200)


class VisibilityIsRespectedTests(TestCase):
    """A member who narrowed a post to members-only did not consent to the
    open web. "restricted" and "private" are choices, not decoration."""

    def setUp(self):
        self.client = APIClient()
        self.author = member("careful")
        post(self.author, "Everyone", visibility="public")
        post(self.author, "Members only", visibility="restricted")
        post(self.author, "Just me", visibility="private")

    def test_only_public_posts_reach_the_feed(self):
        titles = [p["title"] for p in
                  self.client.get(reverse("public-feed")).json()["posts"]]
        self.assertEqual(titles, ["Everyone"])

    def test_only_public_posts_reach_a_member_page(self):
        body = self.client.get(reverse("public-member",
                                       args=["careful"])).json()
        self.assertEqual([p["title"] for p in body["posts"]], ["Everyone"])


class NothingPrivateLeaksTests(TestCase):
    """The fields that describe a person rather than their work."""

    def setUp(self):
        self.client = APIClient()
        self.u = member("private_person", birthday="2000-05-05",
                        lat=51.5, lng=-0.12, share_location=True,
                        location="London", skill_price_cents=5000)
        m = membership_for(self.u)
        m.attractiveness_public = True
        m.save(update_fields=["attractiveness_public"])
        for i in range(2):
            AttractivenessRating.objects.create(
                rater=member(f"rater{i}"), target=self.u, score=9)
        w = wallet_for(self.u)
        w.money_cents = 12_345
        w.save(update_fields=["money_cents"])

    def payload(self):
        return self.client.get(
            reverse("public-member", args=["private_person"])).json()["member"]

    def test_no_location_even_when_the_member_shares_it_with_members(self):
        """share_location is consent to be found by other members, not consent
        to be on the open internet."""
        body = self.payload()
        for leak in ("lat", "lng", "location", "distance_km", "share_location"):
            self.assertNotIn(leak, body)

    def test_no_age_and_no_birthday(self):
        body = self.payload()
        for leak in ("birthday", "age", "verified_18plus"):
            self.assertNotIn(leak, body)

    def test_no_attractiveness_even_when_public_to_members(self):
        """Opt-in among members is not opt-in to being ranked by strangers."""
        self.assertNotIn("attractiveness", self.payload())

    def test_no_wallet_and_no_email(self):
        body = self.payload()
        for leak in ("wallet", "money_cents", "email", "spinaz", "tier"):
            self.assertNotIn(leak, body)

    def test_the_member_list_withholds_the_same_things(self):
        """The leak that matters is the one on the LIST endpoint — one request
        for everybody, rather than one profile at a time."""
        rows = self.client.get(reverse("public-members")).json()["members"]
        row = next(m for m in rows if m["username"] == "private_person")
        for leak in ("lat", "lng", "location", "birthday", "age",
                     "attractiveness", "email"):
            self.assertNotIn(leak, row)

    def test_work_ratings_are_public_because_they_describe_the_work(self):
        self.assertIn("skill_rating", self.payload())


class NoFiltersWithoutAnAccountTests(TestCase):
    """A stranger being able to search "18-22 within 5km" is a different
    product from members finding collaborators."""

    def setUp(self):
        self.client = APIClient()
        member("filtered", birthday="2008-01-01", lat=51.5, lng=-0.12,
               share_location=True)

    def test_range_parameters_are_ignored_rather_than_honoured(self):
        body = self.client.get(reverse("public-members"),
                               {"age": "13-17", "distance_max": "5"}).json()
        self.assertIsNone(body["filters"])
        self.assertEqual(len(body["members"]), 1,
                         "a filter was applied for somebody with no account")


class ReadOnlyTests(TestCase):
    """One-directional. Look, don't touch."""

    def setUp(self):
        self.client = APIClient()
        self.author = member("target")
        post(self.author, "A track")

    def test_you_cannot_post_to_the_public_routes(self):
        for name, args in (("public-feed", []), ("public-members", []),
                           ("public-member", ["target"]),
                           ("public-overview", [])):
            with self.subTest(route=name):
                r = self.client.post(reverse(name, args=args), {},
                                     format="json")
                self.assertEqual(r.status_code, 405)

    def test_the_members_only_endpoints_still_need_an_account(self):
        for name, args in (("economy-members", []),
                           ("economy-member", ["target"]),
                           ("economy-venues", []),
                           ("economy-searchfilters", [])):
            with self.subTest(route=name):
                r = self.client.get(reverse(name, args=args))
                expected = 200 if name == "economy-searchfilters" else 401
                self.assertEqual(
                    r.status_code, expected,
                    "opening the public read path must not open the app")


class ScrapingIsBoundedTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        author = member("prolific")
        for i in range(70):
            post(author, f"Track {i}")

    def test_a_page_is_capped(self):
        body = self.client.get(reverse("public-feed"), {"limit": "500"}).json()
        self.assertLessEqual(len(body["posts"]), 60)

    def test_junk_limits_fall_back_to_the_default(self):
        body = self.client.get(reverse("public-feed"), {"limit": "abc"}).json()
        self.assertEqual(body["limit"], 24)

    def test_a_negative_limit_does_not_invert_the_slice(self):
        body = self.client.get(reverse("public-feed"), {"limit": "-5"}).json()
        self.assertGreaterEqual(len(body["posts"]), 1)
