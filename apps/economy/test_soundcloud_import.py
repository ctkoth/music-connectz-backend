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
                   return_value=([track(i) for i in range(n)], True)):
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
        # StatZ is the whole catalogue — not a bigger number (Corey's call).
        self.assertIsNone(statz)

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
        # The actual widget address, not the bare permalink — a stored
        # permalink would frame soundcloud.com's own site, which is not
        # built to be framed that way, instead of the provider's dedicated
        # w.soundcloud.com/player embed the manual "add a track" flow has
        # always used. Same assertion shape as test_widgetz.py's.
        self.assertTrue(p.embeds[0]["url"].startswith("https://w.soundcloud.com/player/?url="))
        self.assertIn("height", p.embeds[0])
        # SoundCloud stays the host; nothing is re-uploaded here.
        self.assertEqual(p.media_url, "")

    def test_a_track_whose_permalink_cannot_be_resolved_is_skipped_not_broken(self):
        """A shortlink or a garbage URL from the API must not become a post
        whose embed cannot play — better to import one fewer than a dead
        player nobody notices until they open it."""
        with patch("apps.economy.soundcloud_import.access_token_for", return_value="tok"), \
             patch("apps.economy.soundcloud_import._tracks", return_value=([
                 track(0),
                 {"permalink_url": "https://on.soundcloud.com/xyz", "title": "Shortlink"},
             ], True)):
            r = self.c.post("/api/economy/soundcloud/import/",
                            {"code": "c", "redirect_uri": "r"}, format="json")
        self.assertEqual(r.data["imported"], 1)
        self.assertEqual(Post.objects.filter(author=self.me).count(), 1)

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

    def test_a_track_added_by_hand_first_is_recognised_as_already_here(self):
        """The import path and the one-at-a-time `PostEmbedsView` path store
        the identical widget shape now, so a track posted by hand and then
        imported in bulk is caught as a duplicate rather than doubled."""
        from .views import _parse_embed_url
        parsed = _parse_embed_url(track(0)["permalink_url"])
        Post.objects.create(author=self.me, title="By hand",
                            embeds=[{"type": "soundcloud", "url": parsed["url"],
                                    "title": "By hand"}],
                            visibility="public")
        r = self.run_import(1)
        self.assertEqual(r.data["imported"], 0)
        self.assertEqual(r.data["already_here"], 1)


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


class TheWholeCatalogueTests(Base):
    """StatZ used to read ONE page of 200 and stop, so a bigger catalogue came
    in short with nothing saying so. These drive the real pager against a
    fake SoundCloud rather than mocking it away."""

    def fake_soundcloud(self, total, page=200, host="api.soundcloud.com", fail_after=None):
        calls = []

        class R:
            def __init__(self, body, code=200):
                self.body, self.status_code = body, code

            def json(self):
                return self.body

        def get(url, headers=None, params=None, timeout=None):
            n = len(calls)
            calls.append(url)
            if fail_after is not None and n >= fail_after:
                return R({}, 500)
            start = n * page
            batch = [dict(track(i), sharing="public") for i in range(start, min(start + page, total))]
            more = start + page < total
            return R({"collection": batch,
                      "next_href": f"https://{host}/me/tracks?cursor={n + 1}" if more else None})
        return get, calls

    def go(self, get):
        with patch("apps.economy.soundcloud_import.access_token_for", return_value="tok"), \
             patch("apps.economy.soundcloud_import.requests.get", side_effect=get):
            return self.c.post("/api/economy/soundcloud/import/",
                               {"code": "c", "redirect_uri": "r"}, format="json")

    def test_statz_follows_every_page(self):
        self.tier(TIER_STATZ)
        get, calls = self.fake_soundcloud(450)
        r = self.go(get)
        self.assertEqual(r.data["imported"], 450)
        self.assertTrue(r.data["complete"])
        self.assertEqual(len(calls), 3)

    def test_free_stops_at_its_cap_and_reads_one_page(self):
        get, calls = self.fake_soundcloud(450)
        r = self.go(get)
        self.assertEqual(r.data["imported"], 5)
        self.assertEqual(len(calls), 1)

    def test_a_next_link_off_soundclouds_api_is_never_followed(self):
        """The token rides on every page request; a next_href pointing
        anywhere else would hand it to whoever served it."""
        self.tier(TIER_STATZ)
        get, calls = self.fake_soundcloud(450, host="evil.example.com")
        r = self.go(get)
        self.assertEqual(r.data["imported"], 200)
        self.assertEqual(calls, ["https://api.soundcloud.com/me/tracks"])

    def test_a_page_failing_partway_keeps_what_came_in_and_says_so(self):
        self.tier(TIER_STATZ)
        get, _ = self.fake_soundcloud(450, fail_after=1)
        r = self.go(get)
        self.assertEqual(r.data["imported"], 200)
        self.assertFalse(r.data["complete"])
        self.assertIn("run it again", r.data["detail"])

    def test_running_it_again_finishes_the_job(self):
        self.tier(TIER_STATZ)
        self.go(self.fake_soundcloud(450, fail_after=1)[0])
        r = self.go(self.fake_soundcloud(450)[0])
        self.assertEqual(r.data["imported"], 250)
        self.assertEqual(r.data["already_here"], 200)

    def test_get_says_whole_catalogue_rather_than_a_number(self):
        self.tier(TIER_STATZ)
        d = self.c.get("/api/economy/soundcloud/import/").data
        self.assertTrue(d["whole_catalogue"])
        self.assertIsNone(d["max_tracks"])


class PrivateTracksAndDetailsTests(Base):
    def run_with(self, tracks):
        with patch("apps.economy.soundcloud_import.access_token_for", return_value="tok"), \
             patch("apps.economy.soundcloud_import._tracks", return_value=(tracks, True)):
            return self.c.post("/api/economy/soundcloud/import/",
                               {"code": "c", "redirect_uri": "r"}, format="json")

    def test_a_private_track_is_left_on_soundcloud_and_counted(self):
        """Its public player can't play it, and putting its secret token in a
        post the member might publish would leak it."""
        r = self.run_with([track(0), dict(track(1), sharing="private")])
        self.assertEqual(r.data["imported"], 1)
        self.assertEqual(r.data["private_skipped"], 1)
        self.assertIn("private", r.data["detail"])

    def test_genre_and_description_come_with_the_track(self):
        self.run_with([dict(track(0), genre="Hip-hop & Rap", description="Recorded at home.")])
        p = Post.objects.get(author=self.me)
        self.assertEqual((p.genre, p.description), ("Hip-hop & Rap", "Recorded at home."))

    def test_a_description_is_trimmed_to_the_tier_not_refused(self):
        self.run_with([dict(track(0), description="x" * 5000)])
        p = Post.objects.get(author=self.me)
        self.assertEqual(len(p.description), 400)


class PrivateTracksComeInLockedTests(Base):
    """A track private on SoundCloud comes in as a private draft, played
    through its secret link — and publishing it is asked, never assumed."""

    SECRET = "https://api.soundcloud.com/tracks/777?secret_token=s-abc123"

    def run_with(self, tracks):
        with patch("apps.economy.soundcloud_import.access_token_for", return_value="tok"), \
             patch("apps.economy.soundcloud_import._tracks", return_value=(tracks, True)):
            return self.c.post("/api/economy/soundcloud/import/",
                               {"code": "c", "redirect_uri": "r"}, format="json")

    def private_track(self, **kw):
        return {**track(9), "id": 777, "sharing": "private", "secret_uri": self.SECRET, **kw}

    def test_it_imports_with_a_player_that_can_play_it(self):
        r = self.run_with([self.private_track()])
        self.assertEqual(r.data["imported"], 1)
        self.assertEqual(r.data["private_imported"], 1)
        e = Post.objects.get(author=self.me).embeds[0]
        self.assertTrue(e["private_on_sc"])
        self.assertTrue(e["url"].startswith("https://w.soundcloud.com/player/?url="))
        self.assertIn("secret_token", e["url"])

    def test_a_secret_link_off_soundclouds_api_is_refused(self):
        r = self.run_with([self.private_track(secret_uri="https://evil.example.com/tracks/1?secret_token=s-x")])
        self.assertEqual(r.data["imported"], 0)
        self.assertEqual(r.data["private_skipped"], 1)

    def test_publishing_it_asks_first(self):
        self.run_with([self.private_track()])
        p = Post.objects.get(author=self.me)
        url = "/api/economy/postz/"
        r = self.c.post(url, {"edit_id": p.pk, "visibility": "public"}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data["needs_confirm"], "share_private_track")
        p.refresh_from_db()
        self.assertEqual(p.visibility, "private")
        r = self.c.post(url, {"edit_id": p.pk, "visibility": "public", "share_private_track": True}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        p.refresh_from_db()
        self.assertEqual(p.visibility, "public")

    def test_a_track_made_public_later_is_not_imported_twice(self):
        self.run_with([self.private_track()])
        r = self.run_with([dict(track(9), id=777, sharing="public")])
        self.assertEqual(r.data["imported"], 0)
        self.assertEqual(r.data["already_here"], 1)
