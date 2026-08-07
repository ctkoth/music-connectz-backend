"""A post populates a release — nothing gets retyped.

The four slots a post carries ARE the four assets a distributor asks for:
the lyrics, the song, the music video and the cover art. What's left is only
what a post genuinely can't know — the date, the ISRC, the explicit flag.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import Post, Release, TIER_STATZ, membership_for, profile_for

User = get_user_model()
PW = "hunter2hunter2"
RELEASES = "/api/economy/distributez/releases/"

AUDIO = {"url": "/u/song.mp3", "type": "audio", "title": "song", "lyrics": ""}
VIDEO = {"url": "/u/clip.mp4", "type": "video", "title": "clip", "lyrics": ""}
COVER = {"url": "/u/cover.png", "type": "image", "title": "cover", "lyrics": ""}
SCRIPT = {"url": "", "type": "text", "title": "script", "lyrics": "rain on the roof"}


class ReleaseBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="maker", password=PW)
        m = membership_for(self.user)
        m.tier = TIER_STATZ
        m.save(update_fields=["tier", "updated_at"])
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def make_post(self, items=(AUDIO, VIDEO, COVER, SCRIPT), **kw):
        r = self.client.post("/api/economy/postz/",
                             {"title": "Midnight", "genre": "Trap",
                              "items": list(items), **kw}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data["id"]

    def distribute(self, pk):
        return self.client.post(f"/api/economy/postz/{pk}/distribute/", {}, format="json")


class AutoPopulateTests(ReleaseBase):
    def test_the_four_slots_become_the_four_assets(self):
        r = self.distribute(self.make_post())
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["audio_url"], "/u/song.mp3")     # the song
        self.assertEqual(r.data["video_url"], "/u/clip.mp4")     # the music video
        self.assertEqual(r.data["artwork_url"], "/u/cover.png")  # the cover
        self.assertEqual(r.data["lyrics"], "rain on the roof")   # the txt lyrics

    def test_the_title_and_genre_come_across_too(self):
        r = self.distribute(self.make_post())
        self.assertEqual(r.data["title"], "Midnight")
        self.assertEqual(r.data["genre"], "Trap")

    def test_the_artist_name_is_the_members_display_name(self):
        p = profile_for(self.user)
        p.display_name = "K-Oth"
        p.save(update_fields=["display_name"])
        r = self.distribute(self.make_post())
        self.assertEqual(r.data["artist_name"], "K-Oth")

    def test_it_falls_back_to_the_username_when_there_is_no_display_name(self):
        r = self.distribute(self.make_post())
        self.assertEqual(r.data["artist_name"], "maker")

    def test_a_complete_post_is_ready_with_nothing_missing(self):
        r = self.distribute(self.make_post())
        self.assertEqual(r.data["missing"], [])
        self.assertTrue(r.data["ready"])
        self.assertEqual(r.data["status"], Release.STATUS_READY)

    def test_the_release_points_back_at_the_post(self):
        pk = self.make_post()
        r = self.distribute(pk)
        self.assertEqual(r.data["source_post"]["id"], pk)
        self.assertEqual(r.data["source_post"]["target"], f"post-{pk}")


class SaysWhatIsMissingTests(ReleaseBase):
    def test_no_cover_art_is_named_before_anyone_sends_it(self):
        # Every store rejects a release with no artwork, and learning that from
        # the distributor tomorrow is the worst place to learn it.
        r = self.distribute(self.make_post(items=(AUDIO,)))
        self.assertIn("cover art", r.data["missing"])
        self.assertFalse(r.data["ready"])
        self.assertEqual(r.data["status"], Release.STATUS_DRAFT)

    def test_no_song_is_named_too(self):
        r = self.distribute(self.make_post(items=(COVER,)))
        self.assertIn("the song itself", r.data["missing"])

    def test_the_preview_answers_before_anything_is_created(self):
        # So a Distribute button can say what it will still need, rather than
        # creating a draft to find out.
        pk = self.make_post(items=(AUDIO,))
        r = self.client.get(f"/api/economy/postz/{pk}/distribute/")
        self.assertFalse(r.data["exists"])
        self.assertIn("cover art", r.data["release"]["missing"])
        self.assertEqual(Release.objects.count(), 0)

    def test_submitting_an_incomplete_release_is_refused_by_name(self):
        pk = self.make_post(items=(AUDIO,))
        rel = self.distribute(pk).data
        r = self.client.post(f"{RELEASES}{rel['id']}/submit/", {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("cover art", r.data["detail"])
        self.assertIn("cover art", r.data["missing"])


class OneReleasePerPostTests(ReleaseBase):
    def test_pressing_distribute_twice_returns_the_same_release(self):
        pk = self.make_post()
        first = self.distribute(pk)
        second = self.distribute(pk)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(Release.objects.count(), 1)

    def test_repopulating_does_not_overwrite_an_edit(self):
        # The post is where the assets come from, not an authority over what
        # someone fixed on the release afterwards.
        pk = self.make_post()
        rel = self.distribute(pk).data
        self.client.patch(f"{RELEASES}{rel['id']}/", {"title": "Midnight (Radio Edit)"},
                          format="json")
        again = self.distribute(pk)
        self.assertEqual(again.data["title"], "Midnight (Radio Edit)")

    def test_a_gap_left_on_the_release_is_filled_on_the_next_pass(self):
        pk = self.make_post(items=(AUDIO,))
        rel = self.distribute(pk).data
        self.assertFalse(rel["artwork_url"])
        Post.objects.filter(pk=pk).update(items=[AUDIO, COVER])
        again = self.distribute(pk)
        self.assertEqual(again.data["artwork_url"], "/u/cover.png")
        self.assertTrue(again.data["ready"])


class TheFieldsAPostCannotKnowTests(ReleaseBase):
    def test_date_isrc_and_explicit_are_editable(self):
        rel = self.distribute(self.make_post()).data
        r = self.client.patch(f"{RELEASES}{rel['id']}/",
                              {"release_date": "2026-09-01", "isrc": "USRC17607839",
                               "explicit": True}, format="json")
        self.assertEqual(r.data["release_date"], "2026-09-01")
        self.assertEqual(r.data["isrc"], "USRC17607839")
        self.assertTrue(r.data["explicit"])

    def test_a_bad_date_is_refused_in_plain_words(self):
        rel = self.distribute(self.make_post()).data
        r = self.client.patch(f"{RELEASES}{rel['id']}/", {"release_date": "next tuesday"},
                              format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("YYYY-MM-DD", r.data["detail"])


class SubmittedIsFinalTests(ReleaseBase):
    def submitted(self):
        rel = self.distribute(self.make_post()).data
        r = self.client.post(f"{RELEASES}{rel['id']}/submit/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        return r.data

    def test_submitting_stamps_the_time(self):
        s = self.submitted()
        self.assertEqual(s["status"], Release.STATUS_SUBMITTED)
        self.assertTrue(s["submitted_at"])

    def test_a_sent_release_cannot_be_deleted_or_resent(self):
        s = self.submitted()
        self.assertEqual(self.client.delete(f"{RELEASES}{s['id']}/").status_code, 409)
        self.assertEqual(self.client.post(f"{RELEASES}{s['id']}/submit/", {},
                                          format="json").status_code, 409)

    def test_but_it_stays_editable_because_stores_accept_changes(self):
        # Refusing every edit after release would be stricter than the shops
        # we send to, which take an updated cover and corrected lyrics for
        # years afterwards.
        s = self.submitted()
        r = self.client.patch(f"{RELEASES}{s['id']}/",
                              {"title": "Midnight (Radio Edit)", "artwork_url": "/u/new.png"},
                              format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["title"], "Midnight (Radio Edit)")
        self.assertEqual(r.data["status"], Release.STATUS_SUBMITTED)   # still out


class MineOnlyTests(ReleaseBase):
    def test_i_cannot_distribute_someone_elses_post(self):
        other = User.objects.create_user(username="stranger", password=PW)
        post = Post.objects.create(author=other, title="theirs")
        self.assertEqual(self.distribute(post.pk).status_code, 404)

    def test_the_list_is_mine_and_states_what_a_release_requires(self):
        self.distribute(self.make_post())
        r = self.client.get(RELEASES)
        self.assertEqual(len(r.data["releases"]), 1)
        self.assertEqual(r.data["ready"], 1)
        self.assertIn("cover art", r.data["required"])

    def test_dropping_a_release_leaves_the_post_up(self):
        pk = self.make_post()
        rel = self.distribute(pk).data
        r = self.client.delete(f"{RELEASES}{rel['id']}/")
        self.assertTrue(r.data["deleted"])
        self.assertTrue(Post.objects.filter(pk=pk).exists())
