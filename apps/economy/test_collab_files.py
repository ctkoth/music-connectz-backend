"""A collab is a file exchange, and a collab is what usually gets released.

Before this a deal carried one media_url and no way to hand anything back, so
the real work happened in DMs and the deal only held the money.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import CollabDeal, CollabFile, Release, membership_for

User = get_user_model()
PW = "hunter2hunter2"


class DealBase(TestCase):
    def setUp(self):
        self.a = User.objects.create_user(username="alpha", password=PW)   # starter
        self.b = User.objects.create_user(username="beta", password=PW)    # collaborator
        self.outsider = User.objects.create_user(username="nosy", password=PW)
        for u in (self.a, self.b, self.outsider):
            membership_for(u)
        self.deal = CollabDeal.objects.create(
            initiator=self.a, title="Midnight", currency=CollabDeal.CURRENCY_SPINAZ,
            participants=[{"username": "alpha", "worth_cents": 0},
                          {"username": "beta", "worth_cents": 0}],
            media_type="audio", media_url="/u/v1.mp3",
            image_url="/u/cover.png", lyrics="rain on the roof",
        )
        self.url = f"/api/economy/collab/{self.deal.pk}/files/"

    def as_(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c


class TheFirstFileTests(DealBase):
    def test_the_deals_own_work_is_version_one(self):
        r = self.as_(self.a).get(self.url)
        self.assertEqual(len(r.data["files"]), 1)
        self.assertEqual(r.data["files"][0]["version"], 1)
        self.assertEqual(r.data["files"][0]["url"], "/u/v1.mp3")

    def test_the_collaborator_can_download_it(self):
        # The whole point. A file you can see the name of but not open is not
        # a handoff.
        r = self.as_(self.b).get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["files"][0]["url"], "/u/v1.mp3")
        self.assertTrue(r.data["files"][0]["can_download"])

    def test_someone_not_on_the_deal_gets_nothing(self):
        self.assertEqual(self.as_(self.outsider).get(self.url).status_code, 404)

    def test_seeding_v1_happens_once_not_on_every_read(self):
        c = self.as_(self.a)
        c.get(self.url); c.get(self.url); c.get(self.url)
        self.assertEqual(CollabFile.objects.filter(deal=self.deal).count(), 1)

    def test_a_deal_with_no_work_yet_starts_empty(self):
        deal = CollabDeal.objects.create(
            initiator=self.a, title="empty", currency=CollabDeal.CURRENCY_SPINAZ,
            participants=[{"username": "alpha"}, {"username": "beta"}])
        r = self.as_(self.a).get(f"/api/economy/collab/{deal.pk}/files/")
        self.assertEqual(r.data["files"], [])
        self.assertEqual(r.data["next_version"], 1)
        self.assertIsNone(r.data["latest"])


class SendingItBackTests(DealBase):
    def test_the_collaborator_uploads_the_next_version(self):
        # The person doing the work is usually the one who didn't start it.
        r = self.as_(self.b).post(self.url, {"url": "/u/v2.mp3", "name": "my verse",
                                             "media_type": "audio"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["version"], 2)
        self.assertEqual(r.data["uploader"], "beta")

    def test_versions_stack_and_v1_is_never_overwritten(self):
        # An escrowed deal exists so it can be shown what was delivered and
        # when. A v2 replacing v1 in place would destroy that.
        self.as_(self.b).post(self.url, {"url": "/u/v2.mp3"}, format="json")
        self.as_(self.a).post(self.url, {"url": "/u/v3.mp3"}, format="json")
        r = self.as_(self.b).get(self.url)
        self.assertEqual([f["version"] for f in r.data["files"]], [1, 2, 3])
        self.assertEqual(r.data["files"][0]["url"], "/u/v1.mp3")
        self.assertEqual(r.data["latest"]["version"], 3)

    def test_an_outsider_cannot_upload(self):
        r = self.as_(self.outsider).post(self.url, {"url": "/u/junk.mp3"}, format="json")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(CollabFile.objects.count(), 0)

    def test_an_empty_upload_is_refused_in_plain_words(self):
        r = self.as_(self.b).post(self.url, {"url": "  "}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("upload it first", r.data["detail"])

    def test_a_version_carries_the_note_that_explains_it(self):
        r = self.as_(self.b).post(self.url, {"url": "/u/v2.mp3", "note": "added the hook"},
                                  format="json")
        self.assertEqual(r.data["note"], "added the hook")


class TakingOneBackTests(DealBase):
    def upload(self, who, url):
        return self.as_(who).post(self.url, {"url": url}, format="json").data

    def test_i_can_remove_my_own_newest_version(self):
        f = self.upload(self.b, "/u/v2.mp3")
        r = self.as_(self.b).delete(f"{self.url}{f['id']}/")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(CollabFile.objects.filter(pk=f["id"]).exists())

    def test_i_cannot_remove_someone_elses(self):
        f = self.upload(self.b, "/u/v2.mp3")
        r = self.as_(self.a).delete(f"{self.url}{f['id']}/")
        self.assertEqual(r.status_code, 403)

    def test_a_version_someone_built_on_stays(self):
        f = self.upload(self.b, "/u/v2.mp3")
        self.upload(self.a, "/u/v3.mp3")
        r = self.as_(self.b).delete(f"{self.url}{f['id']}/")
        self.assertEqual(r.status_code, 409)
        self.assertIn("already worked from", r.data["detail"])


class CollabToReleaseTests(DealBase):
    """"CollabZ needs distribution most" — a deal is where the master lands."""

    def dist(self, who):
        return self.as_(who).post(f"/api/economy/collab/{self.deal.pk}/distribute/",
                                  {}, format="json")

    def test_a_deal_populates_a_release(self):
        r = self.dist(self.a)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["title"], "Midnight")
        self.assertEqual(r.data["audio_url"], "/u/v1.mp3")
        self.assertEqual(r.data["artwork_url"], "/u/cover.png")
        self.assertEqual(r.data["lyrics"], "rain on the roof")
        self.assertTrue(r.data["ready"])

    def test_everyone_on_the_deal_is_credited(self):
        # A collab released under one name is the argument escrow existed to
        # avoid.
        self.assertEqual(self.dist(self.a).data["artist_name"], "alpha, beta")

    def test_any_participant_can_start_the_paperwork(self):
        r = self.dist(self.b)
        self.assertEqual(r.status_code, 201, r.data)

    def test_an_outsider_cannot(self):
        self.assertEqual(self.dist(self.outsider).status_code, 404)

    def test_it_points_back_at_the_deal(self):
        r = self.dist(self.a)
        self.assertEqual(r.data["source_deal"]["id"], self.deal.pk)
        self.assertEqual(r.data["source_deal"]["open_in"], "collabz")

    def test_distributing_twice_returns_the_same_release(self):
        first, second = self.dist(self.a), self.dist(self.b)
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(second.status_code, 200)
        self.assertEqual(Release.objects.count(), 1)

    def test_the_preview_creates_nothing(self):
        r = self.as_(self.a).get(f"/api/economy/collab/{self.deal.pk}/distribute/")
        self.assertFalse(r.data["exists"])
        self.assertEqual(r.data["release"]["audio_url"], "/u/v1.mp3")
        self.assertEqual(Release.objects.count(), 0)


class EditableAfterItGoesOutTests(DealBase):
    """Stores take an updated cover long after release; so does this."""

    def setUp(self):
        super().setUp()
        rel = self.as_(self.a).post(f"/api/economy/collab/{self.deal.pk}/distribute/",
                                    {}, format="json").data
        self.rel_url = f"/api/economy/distributez/releases/{rel['id']}/"
        self.as_(self.a).post(f"{self.rel_url}submit/", {}, format="json")

    def test_the_cover_the_video_and_the_lyrics_stay_editable(self):
        r = self.as_(self.a).patch(self.rel_url, {"artwork_url": "/u/cover2.png",
                                                  "video_url": "/u/clip.mp4",
                                                  "lyrics": "rain on the roof, again",
                                                  "explicit": True}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["artwork_url"], "/u/cover2.png")
        self.assertEqual(r.data["lyrics"], "rain on the roof, again")
        self.assertTrue(r.data["explicit"])

    def test_the_master_and_the_isrc_are_locked_and_say_why(self):
        # Swapping either makes it a different record under the same name.
        r = self.as_(self.a).patch(self.rel_url, {"audio_url": "/u/other.mp3"},
                                   format="json")
        self.assertEqual(r.status_code, 409)
        self.assertIn("different record", r.data["detail"])
        self.assertIn("audio_url", r.data["locked"])

    def test_the_release_says_which_fields_are_locked(self):
        r = self.as_(self.a).get("/api/economy/distributez/releases/")
        self.assertEqual(sorted(r.data["releases"][0]["locked"]), ["audio_url", "isrc"])

    def test_resending_the_same_master_is_not_an_edit(self):
        # A form that PATCHes every field shouldn't be refused for sending back
        # what's already there.
        r = self.as_(self.a).patch(self.rel_url, {"audio_url": "/u/v1.mp3",
                                                  "lyrics": "tweaked"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["lyrics"], "tweaked")
