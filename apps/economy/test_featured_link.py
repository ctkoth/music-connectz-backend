"""Featured track — one Profile.links entry pinned to the top of a profile.

A POINTER (featured_url) at an existing link, not a second copy of it, so a
removed link can't leave a dangling "now playing" banner behind — the read
side (featured_link_for) resolves it fresh every time and shows nothing if
it no longer matches.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import profile_for
from apps.economy.social import featured_link_for

User = get_user_model()
PW = "hunter2hunter2"
PROFILE = "/api/economy/profile/"
SPOTIFY = "https://open.spotify.com/track/abc"


class FeaturedLinkTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("koth", "k@example.com", PW)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        p = profile_for(self.user)
        p.links = [{"label": "Spotify", "url": SPOTIFY, "service": "spotify"}]
        p.save(update_fields=["links"])

    def test_featuring_an_existing_link_saves_it(self):
        r = self.client.post(PROFILE, {"featured_url": SPOTIFY}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["featured_url"], SPOTIFY)
        self.assertEqual(r.data["featured_link"]["label"], "Spotify")

    def test_featuring_a_url_not_in_links_is_refused(self):
        r = self.client.post(PROFILE, {"featured_url": "https://soundcloud.com/nope"}, format="json")
        self.assertEqual(r.status_code, 400, r.data)
        self.assertEqual(profile_for(self.user).featured_url, "")

    def test_unfeaturing_clears_it(self):
        self.client.post(PROFILE, {"featured_url": SPOTIFY}, format="json")
        r = self.client.post(PROFILE, {"featured_url": ""}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["featured_url"], "")
        self.assertIsNone(r.data["featured_link"])

    def test_removing_the_featured_link_leaves_no_dangling_reference(self):
        # The member features it, then removes it from their links entirely
        # (via SocialVerifyView's "remove", the real path) without ever
        # explicitly unfeaturing — featured_link_for must not show a ghost.
        self.client.post(PROFILE, {"featured_url": SPOTIFY}, format="json")
        p = profile_for(self.user)
        p.links = []
        p.save(update_fields=["links"])
        self.assertIsNone(featured_link_for(p))

    def test_a_strangers_profile_shows_the_featured_link_too(self):
        stranger = User.objects.create_user("stranger", "s@example.com", PW)
        self.client.post(PROFILE, {"featured_url": SPOTIFY}, format="json")
        self.client.force_authenticate(stranger)
        r = self.client.get(f"/api/economy/members/{self.user.username}/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["featured_link"]["url"], SPOTIFY)

    def test_public_profile_page_shows_it_with_no_login(self):
        self.client.post(PROFILE, {"featured_url": SPOTIFY}, format="json")
        anon = APIClient()
        r = anon.get(f"/api/economy/public/members/{self.user.username}/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["featured_link"]["url"], SPOTIFY)
