"""Thorough 💯: the ladder, who wears it, and where it shows.

The rating itself is `bodiez.thoroughness`, tested in test_bodiez. What is
pinned here is the layer above it: the rungs (Corey's numbers), one rung held
at a time, privacy, the batch reads on posts/collabs/venues, and the group.
"""
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from . import thoroughz
from .models import (BADGES, Badge, BodieZExercise, BodieZSession, BodieZSet,
                     CollabDeal, Notification, Post, VenueEvent, grant_badge,
                     recheck_badges)

User = get_user_model()


def _train(user, lifts, sessions=8, sets=3, rising=True):
    """Finished sessions three days apart, inside the 28-day window."""
    now = timezone.now()
    for i in range(sessions):
        s = BodieZSession.objects.create(user=user)
        when = now - timedelta(days=3 * (sessions - 1 - i), hours=1)
        BodieZSession.objects.filter(pk=s.pk).update(started_at=when, ended_at=when + timedelta(hours=1))
        for ex in lifts:
            for n in range(sets):
                BodieZSet.objects.create(session=s, exercise=ex, set_number=n + 1, reps=8,
                                         weight_kg=40 + (5 * i if rising else 0))


def _lifts(n):
    return [BodieZExercise.objects.create(name=f"Thorough Lift {i}", muscle_group="chest",
                                          equipment="barbell") for i in range(n)]


class TheRungs(TestCase):
    def test_corey_numbers(self):
        self.assertEqual([thoroughz.tier_for(r) for r in (None, 1, 5, 6, 7, 8, 9, 10)],
                         [None, None, None, "thorough", "decent", "legendary", "supreme", "perfect"])

    def test_the_placeholder_emoji(self):
        self.assertEqual({k: BADGES[k]["emoji"] for k in thoroughz.KEYS},
                         {"perfect": "💎", "supreme": "🌟", "legendary": "🥇",
                          "decent": "🥈", "thorough": "💯"})
        self.assertEqual(thoroughz.GROUP_NAME, "Thorough 💯")

    def test_nothing_pays(self):
        # A rating that paid would be worth faking.
        for k in thoroughz.KEYS:
            self.assertEqual(BADGES[k]["effects"], {"achievement": True}, k)
            self.assertTrue(BADGES[k]["temporary"], k)


class EarningIt(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("lifter", password="pw")

    def test_thorough_training_on_three_lifts_is_perfect(self):
        _train(self.u, _lifts(3))
        self.assertEqual(thoroughz.member_rating(self.u)["rating"], 10)
        recheck_badges(self.u)
        self.assertEqual(set(Badge.objects.filter(user=self.u).values_list("key", flat=True))
                         & set(thoroughz.KEYS), {"perfect"})

    def test_two_lifts_are_not_enough_however_hard(self):
        _train(self.u, _lifts(2))
        self.assertEqual(thoroughz.member_rating(self.u), {"rating": None, "lifts": 2})
        recheck_badges(self.u)
        self.assertFalse(Badge.objects.filter(user=self.u, key__in=thoroughz.KEYS).exists())

    def test_finishing_a_session_moves_the_ladder(self):
        lifts = _lifts(3)
        _train(self.u, lifts, sessions=7)
        s = BodieZSession.objects.create(user=self.u)
        for ex in lifts:
            for n in range(3):
                BodieZSet.objects.create(session=s, exercise=ex, set_number=n + 1, reps=8, weight_kg=90)
        c = APIClient()
        c.force_authenticate(self.u)
        r = c.patch(f"/api/economy/bodiez/sessions/{s.id}/", {"finish": True}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(Badge.objects.filter(user=self.u, key__in=thoroughz.KEYS).exists())

    def test_one_rung_at_a_time_and_climbing_is_not_a_lapse(self):
        with mock.patch.object(thoroughz, "badge_key_for", return_value="decent"):
            recheck_badges(self.u)
        with mock.patch.object(thoroughz, "badge_key_for", return_value="legendary"):
            recheck_badges(self.u)
        keys = set(Badge.objects.filter(user=self.u).values_list("key", flat=True))
        self.assertIn("legendary", keys)
        self.assertNotIn("decent", keys)
        self.assertFalse(Notification.objects.filter(user=self.u, text__contains="lapsed").exists())

    def test_going_quiet_takes_it_back_and_says_so(self):
        with mock.patch.object(thoroughz, "badge_key_for", return_value="decent"):
            recheck_badges(self.u)
        with mock.patch.object(thoroughz, "badge_key_for", return_value=None):
            recheck_badges(self.u)
        self.assertFalse(Badge.objects.filter(user=self.u, key__in=thoroughz.KEYS).exists())
        self.assertTrue(Notification.objects.filter(user=self.u, text__contains="lapsed").exists())

    def test_the_sweep_takes_down_a_lapsed_mark(self):
        from django.core.management import call_command
        grant_badge(self.u, "supreme")
        call_command("refresh_thorough", stdout=open("/dev/null", "w"))
        self.assertFalse(Badge.objects.filter(user=self.u, key="supreme").exists())


class WhereItShows(TestCase):
    def setUp(self):
        self.a = User.objects.create_user("aa", password="pw")
        self.b = User.objects.create_user("bb", password="pw")
        self.c = APIClient()
        self.c.force_authenticate(self.b)
        grant_badge(self.a, "legendary")

    def test_a_hidden_badge_is_worn_nowhere(self):
        Badge.objects.filter(user=self.a).update(visible=False)
        self.assertEqual(thoroughz.marks_for([self.a.id]), {})

    def test_on_a_post_in_the_feed(self):
        Post.objects.create(author=self.a, title="Song", visibility="public")
        r = self.c.get("/api/economy/postz/")
        self.assertEqual(r.status_code, 200)
        row = next(p for p in r.data["posts"] if p["author"] == "aa")
        self.assertEqual(row["author_mark"]["emoji"], "🥇")
        self.assertEqual(row["author_mark"]["label"], "Legendary 🥇")

    def test_on_a_contributor_of_a_collab_post(self):
        Post.objects.create(author=self.b, title="Ours", visibility="public",
                            contributors=[{"username": "aa", "slot": "beat"}])
        r = self.c.get("/api/economy/postz/")
        row = next(p for p in r.data["posts"] if p["title"] == "Ours")
        self.assertIsNone(row["author_mark"])
        self.assertEqual(row["contributor_marks"]["aa"]["key"], "legendary")

    def test_the_feed_pays_the_same_queries_for_one_post_or_many(self):
        Post.objects.create(author=self.a, title="one", visibility="public")
        self.c.get("/api/economy/postz/")          # first-call caches, not per-card cost
        with CaptureQueriesContext(connection) as one:
            self.c.get("/api/economy/postz/")
        for i in range(6):
            who = User.objects.create_user(f"m{i}", password="pw")
            grant_badge(who, "decent")
            Post.objects.create(author=who, title=f"p{i}", visibility="public")
        with CaptureQueriesContext(connection) as many:
            self.c.get("/api/economy/postz/")
        self.assertEqual(len(one), len(many))

    def test_on_a_collab_deal(self):
        CollabDeal.objects.create(initiator=self.b, title="Deal",
                                  participants=[{"username": "bb"}, {"username": "aa"}])
        r = self.c.get("/api/economy/collab/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["deals"][0]["marks"]["aa"]["emoji"], "🥇")
        self.assertNotIn("bb", r.data["deals"][0]["marks"])

    def test_on_a_venue(self):
        VenueEvent.objects.create(host=self.a, kind=VenueEvent.KIND_FREE, title="Jam", area="Denver",
                                  starts_at=timezone.now() + timedelta(days=1), skills=[], hours=1)
        r = self.c.get("/api/economy/venuez/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["venues"][0]["host_mark"]["key"], "legendary")

    def test_on_the_member_card_as_a_worn_badge(self):
        r = self.c.get("/api/economy/members/aa/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("legendary", [b["key"] for b in r.data["badges"]])


class TheGroup(TestCase):
    def setUp(self):
        self.me = User.objects.create_user("me", password="pw")
        self.c = APIClient()
        self.c.force_authenticate(self.me)

    def test_grouped_by_rung_with_posts_on_top(self):
        top = User.objects.create_user("top", password="pw")
        mid = User.objects.create_user("mid", password="pw")
        hid = User.objects.create_user("hid", password="pw")
        grant_badge(top, "perfect")
        grant_badge(mid, "thorough")
        grant_badge(hid, "supreme")
        Badge.objects.filter(user=hid).update(visible=False)
        Post.objects.create(author=top, title="Top's track", visibility="public")
        Post.objects.create(author=hid, title="hidden", visibility="public")
        Post.objects.create(author=mid, title="secret", visibility="private")

        r = self.c.get("/api/economy/thoroughz/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["group"]["name"], "Thorough 💯")
        self.assertEqual(list(r.data)[:3], ["group", "caveat", "min_lifts"])
        tiers = {t["key"]: t for t in r.data["tiers"]}
        self.assertEqual([t["key"] for t in r.data["tiers"]], list(thoroughz.KEYS))
        self.assertEqual(tiers["perfect"]["members"], ["top"])
        self.assertEqual(tiers["thorough"]["members"], ["mid"])
        self.assertEqual(tiers["supreme"]["members"], [])
        self.assertEqual(r.data["members"], 2)
        self.assertEqual([p["title"] for p in r.data["posts"]], ["Top's track"])
        self.assertEqual(r.data["posts"][0]["mark"]["emoji"], "💎")

    def test_mine_says_what_the_next_rung_takes(self):
        r = self.c.get("/api/economy/thoroughz/")
        self.assertIsNone(r.data["mine"]["rating"])
        self.assertEqual(r.data["mine"]["next"], {"rating": 6, "label": "Thorough 💯"})
