"""LogicZ — an address per tab, and a tab that says what it is.

A screen with no address is a screen you can only tell somebody how to find.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.logicz import LOGICZ_TABS, slug_for
from apps.economy.models import membership_for

User = get_user_model()
LOGICZ = "/api/economy/logicz/"


class SlugTests(TestCase):
    def test_the_trailing_z_is_dropped_as_the_spec_asks(self):
        # musicconnectz.net/battle, /sing, /game — Corey's own examples.
        self.assertEqual(slug_for("battlez"), "battle")
        self.assertEqual(slug_for("singz"), "sing")
        self.assertEqual(slug_for("postz"), "post")
        self.assertEqual(slug_for("collabz"), "collab")

    def test_a_name_without_a_trailing_z_is_left_alone(self):
        self.assertEqual(slug_for("occ"), "occ")
        self.assertEqual(slug_for("social"), "social")

    def test_a_two_letter_key_is_not_stripped_to_nothing(self):
        self.assertEqual(slug_for("az"), "az")

    def test_slugs_are_unique_so_two_tabs_never_share_an_address(self):
        slugs = [slug_for(t["key"]) for t in LOGICZ_TABS]
        self.assertEqual(len(slugs), len(set(slugs)))


class RegistryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="m", password="hunter2hunter2")
        membership_for(self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_every_tab_carries_its_address(self):
        for t in self.client.get(LOGICZ).data["tabs"]:
            self.assertEqual(t["url"], f"/{t['slug']}")

    def test_every_tab_says_what_it_is(self):
        # The tab list gave a name and an emoji and nothing else.
        for t in self.client.get(LOGICZ).data["tabs"]:
            self.assertTrue(t["desc"], t["key"])
            self.assertTrue(t["emoji"] and t["icon"], t["key"])

    def test_an_app_inside_a_tab_says_whether_it_is_built(self):
        # A modal promising five apps and delivering one is worse than one
        # promising one.
        for t in self.client.get(LOGICZ).data["tabs"]:
            for a in t["apps"]:
                self.assertIn("built", a)
                self.assertTrue(a["name"] and a["desc"], a)

    def test_the_counts_match_the_rows(self):
        for t in self.client.get(LOGICZ).data["tabs"]:
            self.assertEqual(t["total_apps"], len(t["apps"]))
            self.assertEqual(t["built_apps"], sum(1 for a in t["apps"] if a["built"]))

    def test_the_slug_map_is_served_so_the_client_never_derives_it_twice(self):
        d = self.client.get(LOGICZ).data
        self.assertEqual(d["slugs"]["battlez"], "battle")
        self.assertEqual(len(d["slugs"]), len(d["tabs"]))
