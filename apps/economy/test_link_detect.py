"""LinkDetectView — recognizing which platform a pasted URL belongs to, so
the client can show the right logo without the member picking one off a
list. A known domain matches for free; an unknown one asks the model once.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import membership_for, profile_for

User = get_user_model()
PW = "hunter2hunter2"
URL = "/api/economy/social/detect/"
VERIFY = "/api/economy/social/verify/"


class LinkDetectBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="koth", password=PW, email="k@example.com")
        membership_for(self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)


class KnownDomainTests(LinkDetectBase):
    def test_spotify_is_recognized_instantly(self):
        r = self.client.post(URL, {"url": "https://open.spotify.com/artist/xyz"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["service"], "spotify")
        self.assertEqual(r.data["source"], "domain")

    def test_a_subdomain_of_a_known_service_still_matches(self):
        r = self.client.post(URL, {"url": "https://music.youtube.com/watch?v=1"}, format="json")
        self.assertEqual(r.data["service"], "youtube")

    def test_a_bare_www_domain_matches(self):
        r = self.client.post(URL, {"url": "https://www.instagram.com/koth"}, format="json")
        self.assertEqual(r.data["service"], "instagram")

    def test_a_domain_that_merely_contains_the_string_does_not_match(self):
        # notspotify.com must not be treated as spotify.com.
        with patch("apps.economy.social_verify._ai_detect_service", return_value=(None, None)):
            r = self.client.post(URL, {"url": "https://notspotify.com/x"}, format="json")
        self.assertEqual(r.data["service"], "website")

    def test_no_ai_call_is_made_for_a_known_domain(self):
        with patch("apps.economy.social_verify._ai_detect_service") as ai:
            self.client.post(URL, {"url": "https://soundcloud.com/koth"}, format="json")
        ai.assert_not_called()

    def test_url_requires_no_scheme(self):
        r = self.client.post(URL, {"url": "tiktok.com/@koth"}, format="json")
        self.assertEqual(r.data["service"], "tiktok")


class UnknownDomainTests(LinkDetectBase):
    def test_the_model_is_asked_for_an_unrecognized_domain(self):
        # hearnow.com isn't in KNOWN_SERVICES — a real niche music-link
        # platform, standing in for "anything the hand-rolled list misses".
        with patch("apps.economy.social_verify._ai_detect_service",
                  return_value=("hearnow", "HearNow")):
            r = self.client.post(URL, {"url": "https://koth.hearnow.com"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["service"], "hearnow")
        self.assertEqual(r.data["source"], "ai")

    def test_a_model_that_cannot_tell_falls_back_to_website_not_a_refusal(self):
        with patch("apps.economy.social_verify._ai_detect_service", return_value=(None, None)):
            r = self.client.post(URL, {"url": "https://my-press-kit.example.com"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["service"], "website")
        self.assertEqual(r.data["source"], "fallback")

    def test_url_is_required(self):
        r = self.client.post(URL, {}, format="json")
        self.assertEqual(r.status_code, 400)


class SocialVerifyLinkManagementTests(LinkDetectBase):
    """The save/remove/GET actions LinkDetectView's result feeds into."""

    def test_get_lists_every_link_with_its_state(self):
        p = profile_for(self.user)
        p.links = [{"label": "Spotify", "url": "https://open.spotify.com/x", "verified": True}]
        p.save(update_fields=["links"])
        r = self.client.get(VERIFY)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(len(r.data["links"]), 1)
        self.assertIn("reach_median", r.data)

    def test_save_stores_the_detected_service_for_the_icon_lookup(self):
        self.client.post(VERIFY, {"action": "save", "url": "https://open.spotify.com/x",
                                  "label": "Spotify", "service": "spotify"}, format="json")
        self.assertEqual(profile_for(self.user).links[0]["service"], "spotify")

    def test_save_adds_an_unverified_link_with_no_checks(self):
        r = self.client.post(VERIFY, {"action": "save", "url": "https://koth.bandcamp.com",
                                       "label": "Bandcamp"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        links = profile_for(self.user).links
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["label"], "Bandcamp")
        self.assertFalse(links[0]["verified"])

    def test_saving_an_existing_link_relabels_it_without_touching_verification(self):
        p = profile_for(self.user)
        p.links = [{"label": "Old Name", "url": "https://open.spotify.com/x", "verified": True,
                   "verified_count": 500}]
        p.save(update_fields=["links"])
        self.client.post(VERIFY, {"action": "save", "url": "https://open.spotify.com/x",
                                  "label": "New Name"}, format="json")
        link = profile_for(self.user).links[0]
        self.assertEqual(link["label"], "New Name")
        self.assertTrue(link["verified"])
        self.assertEqual(link["verified_count"], 500)

    def test_remove_drops_the_link(self):
        p = profile_for(self.user)
        p.links = [{"label": "Spotify", "url": "https://open.spotify.com/x"}]
        p.save(update_fields=["links"])
        r = self.client.post(VERIFY, {"action": "remove", "url": "https://open.spotify.com/x"},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(profile_for(self.user).links, [])

    def test_removing_something_never_saved_is_a_harmless_no_op(self):
        r = self.client.post(VERIFY, {"action": "remove", "url": "https://open.spotify.com/x"},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(profile_for(self.user).links, [])


class EnergyDeltaChipTests(LinkDetectBase):
    """Each link's ⚡/hour swing — the number the cost/gain chip is built
    from. Free tier here, so energy_rate_per_hour = reach_median // 10."""

    def test_a_link_with_no_real_number_behind_it_projects_nothing(self):
        p = profile_for(self.user)
        p.links = [{"label": "Spotify", "url": "https://open.spotify.com/x"}]
        p.save(update_fields=["links"])
        r = self.client.get(VERIFY)
        self.assertIsNone(r.data["links"][0]["energy_delta"])

    def test_a_verified_link_shows_what_removing_it_would_cost(self):
        p = profile_for(self.user)
        # Sources become [mcz=0, spotify=1000] -> median 500 -> Free ⚡/hr = 50.
        # Without spotify: [mcz=0] -> median 0 -> 0 ⚡/hr. Removing it costs 50.
        p.links = [{"label": "Spotify", "url": "https://open.spotify.com/x",
                   "verified": True, "verified_count": 1000}]
        p.save(update_fields=["links"])
        r = self.client.get(VERIFY)
        self.assertEqual(r.data["links"][0]["energy_delta"], -50)

    def test_a_pending_reviewed_link_shows_the_projected_gain(self):
        p = profile_for(self.user)
        p.links = [{"label": "Instagram", "url": "https://instagram.com/x",
                   "verified": False, "review": "pending", "claimed_followers": 2000}]
        p.save(update_fields=["links"])
        r = self.client.get(VERIFY)
        # [mcz=0, ig=2000] median 1000 -> 100 ⚡/hr, vs 0 now: +100.
        self.assertEqual(r.data["links"][0]["energy_delta"], 100)

    def test_a_match_that_gets_flagged_stashes_a_claimed_count_for_the_projection(self):
        from unittest.mock import patch
        p = profile_for(self.user)
        p.links = [{"label": "Instagram", "url": "https://instagram.com/x"}]
        p.save(update_fields=["links"])
        page = ("bio text", None)
        ai_result = ({"verdict": "unsure", "followers": 3000, "handle": "@x"}, "not sure", None)
        with patch("apps.economy.social_verify._fetch_public_page", return_value=page), \
             patch("apps.economy.social_verify._ai_identity", return_value=ai_result):
            self.client.post(VERIFY, {"action": "match", "url": "https://instagram.com/x"},
                            format="json")
        link = profile_for(self.user).links[0]
        self.assertEqual(link["claimed_followers"], 3000)
