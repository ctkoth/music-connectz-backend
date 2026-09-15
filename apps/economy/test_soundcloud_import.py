"""Bulk SoundCloud import: volume, not access, and no stored credential."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Post, TIER_FREE, TIER_PREMIUM, TIER_STATZ, membership_for

User = get_user_model()


def track(n):
    return {"permalink_url": f"https://soundcloud.com/me/track-{n}", "title": f"Track {n}"}


class Base(TestCase):
    def setUp(self):
        self.me = User.objects.create_user("importer", "i@mcz.test", "hunter2hunter2")
        self.c = APIClient()
        self.c.force_authenticate(self.me)

    def tier(self, t):
        m = membership_for(self.me)
        m.tier = t
        m.save(update_fields=["tier", "updated_at"])

    def run_import(self, n=3):
        with patch("apps.economy.soundcloud_import.access_token_for", return_value="tok"), \
             patch("apps.economy.soundcloud_import._tracks",
                   return_value=[track(i) for i in range(n)]):
            return self.c.post("/api/economy/soundcloud/import/",
                               {"code": "c", "redirect_uri": "r"}, format="json")


class ItIsVolumeNotAccessTests(Base):
    """Posting one SoundCloud link already works at every tier — WidgetZ frames
    the provider's own player. So the tier buys how many at once."""

    def test_a_free_member_can_import(self):
        r = self.run_import(3)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["imported"], 3)

    def test_the_ceiling_ladders_and_free_is_not_zero(self):
        from .soundcloud_import import import_cap
        free, prem, statz = (import_cap(t) for t in (TIER_FREE, TIER_PREMIUM, TIER_STATZ))
        self.assertGreater(free, 0, "an importer that imports nothing is a button that lies")
        self.assertLess(free, prem)
        self.assertLess(prem, statz)

    def test_free_is_capped_at_its_ceiling(self):
        from .soundcloud_import import import_cap
        cap = import_cap(TIER_FREE)
        r = self.run_import(cap + 10)
        self.assertEqual(r.data["imported"], cap)

    def test_statz_brings_in_a_whole_catalogue(self):
        self.tier(TIER_STATZ)
        r = self.run_import(150)
        self.assertEqual(r.data["imported"], 150)


class TheyLandAsDraftsTests(Base):
    def test_nothing_is_published_by_importing(self):
        """200 posts in everybody's feed in one minute reads as spam and buries
        every other member that day."""
        self.run_import(4)
        self.assertEqual(Post.objects.filter(author=self.me).count(), 4)
        for p in Post.objects.filter(author=self.me):
            self.assertEqual(p.visibility, "private")

    def test_the_track_becomes_a_player_not_a_copy(self):
        self.run_import(1)
        p = Post.objects.get(author=self.me)
        self.assertEqual(p.embeds[0]["type"], "soundcloud")
        self.assertIn("soundcloud.com", p.embeds[0]["url"])
        # SoundCloud stays the host; nothing is re-uploaded here.
        self.assertEqual(p.media_url, "")

    def test_importing_costs_nothing(self):
        """An imported draft has been shown to nobody. The cost of a post
        applies when it is published, which is when it reaches anyone."""
        r = self.c.get("/api/economy/soundcloud/import/")
        self.assertEqual(r.data["cost"], 0)
        self.assertEqual(r.data["lands_as"], "draft")


class RunningItTwiceTests(Base):
    def test_the_second_run_is_a_no_op(self):
        self.run_import(3)
        r = self.run_import(3)
        self.assertEqual(r.data["imported"], 0)
        self.assertEqual(r.data["already_here"], 3)
        self.assertEqual(Post.objects.filter(author=self.me).count(), 3)

    def test_a_new_track_still_comes_in(self):
        self.run_import(2)
        r = self.run_import(3)
        self.assertEqual(r.data["imported"], 1)
        self.assertEqual(Post.objects.filter(author=self.me).count(), 3)


class NoStoredCredentialTests(Base):
    def test_nothing_persists_the_token(self):
        """OAuthIdentity has never held an access token and this does not
        change that. A stored SoundCloud token can post and delete on its
        owner's account."""
        from apps.accounts.models import OAuthIdentity
        self.run_import(2)
        for f in OAuthIdentity._meta.get_fields():
            self.assertNotIn("token", f.name.lower())

    def test_the_answer_says_so(self):
        r = self.run_import(1)
        self.assertFalse(r.data["token_kept"])
        self.assertFalse(self.c.get("/api/economy/soundcloud/import/").data["stores_token"])

    def test_a_refused_authorisation_imports_nothing(self):
        from apps.accounts.oauth import OAuthError
        with patch("apps.economy.soundcloud_import.access_token_for",
                   side_effect=OAuthError("SoundCloud said no.")):
            r = self.c.post("/api/economy/soundcloud/import/",
                            {"code": "bad", "redirect_uri": "r"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Post.objects.filter(author=self.me).count(), 0)

    def test_signed_out_cannot_import(self):
        self.c.force_authenticate(None)
        r = self.c.post("/api/economy/soundcloud/import/", {"code": "c"}, format="json")
        self.assertEqual(r.status_code, 401)
