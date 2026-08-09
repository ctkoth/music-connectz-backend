"""One of each: a post carries one audio, one video, one image, one script.

A track with its video, its cover and its lyrics is ONE piece of work and was
always meant to post as one thing. Several of a kind is an album, and an album
has to be asked for — inferring it from the item count turned "a track plus its
cover art" into an album of two.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import Post, membership_for, wallet_for, TIER_STATZ

User = get_user_model()
PW = "hunter2hunter2"
POSTZ = "/api/economy/postz/"

AUDIO = {"url": "/u/take.mp3", "type": "audio", "title": "take", "lyrics": ""}
VIDEO = {"url": "/u/clip.mp4", "type": "video", "title": "clip", "lyrics": ""}
IMAGE = {"url": "/u/cover.png", "type": "image", "title": "cover", "lyrics": ""}
SCRIPT = {"url": "", "type": "text", "title": "script", "lyrics": "rain, rain"}


class SlotsBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="maker", password=PW)
        m = membership_for(self.user)
        m.tier = TIER_STATZ
        m.save(update_fields=["tier", "updated_at"])
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def post(self, **kw):
        return self.client.post(POSTZ, {"title": "Midnight take", **kw}, format="json")


class OneOfEachTests(SlotsBase):
    def test_a_post_carries_all_four_kinds_at_once(self):
        r = self.post(items=[AUDIO, VIDEO, IMAGE, SCRIPT])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["media"], {
            "audio": "/u/take.mp3", "video": "/u/clip.mp4",
            "image": "/u/cover.png", "text": "rain, rain",
        })

    def test_four_attachments_is_not_an_album(self):
        # The old rule was `len(items) > 1`, which made a track plus its cover
        # art an "album" of two.
        r = self.post(items=[AUDIO, VIDEO, IMAGE, SCRIPT])
        self.assertFalse(r.data["is_album"])
        self.assertFalse(Post.objects.get(pk=r.data["id"]).is_album)

    def test_a_track_and_its_cover_is_one_post(self):
        r = self.post(items=[AUDIO, IMAGE])
        self.assertFalse(r.data["is_album"])
        self.assertEqual(r.data["media"]["audio"], "/u/take.mp3")
        self.assertEqual(r.data["media"]["image"], "/u/cover.png")

    def test_two_of_a_kind_is_refused_and_says_which(self):
        r = self.post(items=[IMAGE, {**IMAGE, "url": "/u/cover2.png"}])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["duplicate_type"], "image")
        self.assertIn("one image", r.data["detail"])
        self.assertIn("album", r.data["detail"])   # …and how to do it anyway
        self.assertEqual(Post.objects.count(), 0)

    def test_two_audio_tracks_is_refused_the_same_way(self):
        r = self.post(items=[AUDIO, {**AUDIO, "url": "/u/take2.mp3"}])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["duplicate_type"], "audio")

    def test_the_slot_names_come_back_so_a_client_need_not_guess(self):
        r = self.post(items=[AUDIO])
        self.assertEqual(r.data["slots"], ["audio", "video", "image", "text"])


class AlbumStillWorksTests(SlotsBase):
    def test_an_album_is_asked_for_and_carries_several_of_a_kind(self):
        r = self.post(is_album=True, items=[AUDIO, {**AUDIO, "url": "/u/take2.mp3"},
                                            {**AUDIO, "url": "/u/take3.mp3"}])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["is_album"])
        self.assertEqual(len(r.data["items"]), 3)

    def test_an_album_shows_the_first_of_each_kind_in_its_slots(self):
        r = self.post(is_album=True, items=[AUDIO, {**AUDIO, "url": "/u/take2.mp3"}, IMAGE])
        self.assertEqual(r.data["media"]["audio"], "/u/take.mp3")
        self.assertEqual(r.data["media"]["image"], "/u/cover.png")


class PrimaryMediaTests(SlotsBase):
    def test_the_primary_media_slot_fills_its_own_kind(self):
        r = self.post(media_type="audio", media_url="/u/primary.mp3", items=[IMAGE])
        self.assertEqual(r.data["media"]["audio"], "/u/primary.mp3")
        self.assertEqual(r.data["media"]["image"], "/u/cover.png")

    def test_the_primary_wins_over_an_item_of_the_same_kind(self):
        # It's the one the feed plays inline, so it has to be the one reported.
        r = self.post(media_type="audio", media_url="/u/primary.mp3", items=[AUDIO])
        self.assertEqual(r.data["media"]["audio"], "/u/primary.mp3")

    def test_an_empty_post_reports_empty_slots_not_missing_keys(self):
        r = self.post()
        self.assertEqual(r.data["media"], {"audio": "", "video": "", "image": "", "text": ""})


class FreestyleIsNotAGenreTests(TestCase):
    """🆓 Freestyle rides alongside the genre, never instead of it.

    A freestyle is a way of MAKING the thing, not a kind of music. Putting it in
    the genre list would force a choice between "Trap" and "Freestyle" for a
    freestyle Trap verse, and split the tag across every genre family that has
    one — so ChartZ could never slice freestyles, or Trap, cleanly again.
    """

    def setUp(self):
        self.user = User.objects.create_user("mc", "mc@e.com", PW)
        membership_for(self.user)
        w = wallet_for(self.user); w.energy = 500; w.save()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def post(self, **over):
        return self.client.post("/api/economy/postz/",
                                {"title": "Off the dome", **over}, format="json")

    def test_a_post_can_be_a_freestyle(self):
        resp = self.post(freestyle=True, genre="Trap")
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertTrue(resp.data["freestyle"])

    def test_it_keeps_its_genre(self):
        # The whole point: both facts survive, so a freestyle Trap verse is
        # still findable as Trap.
        resp = self.post(freestyle=True, genre="Trap")
        self.assertEqual(resp.data["genre"], "Trap")
        self.assertTrue(resp.data["freestyle"])

    def test_any_genre_can_be_freestyled(self):
        for g in ("Trap", "Jazz", "R&B", "Drill"):
            with self.subTest(g):
                resp = self.post(freestyle=True, genre=g)
                self.assertEqual(resp.status_code, 201, resp.data)
                self.assertTrue(resp.data["freestyle"])
                self.assertEqual(resp.data["genre"], g)

    def test_posts_are_not_freestyles_by_default(self):
        self.assertFalse(self.post(genre="Trap").data["freestyle"])

    def test_freestyle_is_not_in_the_genre_list(self):
        # If it ever shows up as a genre, the two facts have collapsed into one
        # and this test is the thing that says so.
        from apps.economy.models import Post
        resp = self.post(freestyle=True, genre="Freestyle")
        self.assertEqual(resp.status_code, 201, resp.data)
        p = Post.objects.get(pk=resp.data["id"])
        # The server stores what it was given, but the flag is what the app
        # reads — a genre string is never how a freestyle is recorded.
        self.assertTrue(p.freestyle)
