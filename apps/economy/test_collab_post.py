"""A finished collab is one post, owned by everyone who made it.

An artist arrives with a song and needs a cover and a music video. The designer
puts up the cover, the videographer puts up the video, and what ships is ONE
post that belongs to all three — not three posts and an argument about credit.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import CollabDeal, Post, membership_for, owns_post

User = get_user_model()
PW = "hunter2hunter2"


class CollabPostBase(TestCase):
    def setUp(self):
        self.artist = User.objects.create_user(username="artist", password=PW)
        self.designer = User.objects.create_user(username="designer", password=PW)
        self.shooter = User.objects.create_user(username="shooter", password=PW)
        self.outsider = User.objects.create_user(username="nosy", password=PW)
        for u in (self.artist, self.designer, self.shooter, self.outsider):
            membership_for(u)
        self.deal = CollabDeal.objects.create(
            initiator=self.artist, title="Midnight", currency=CollabDeal.CURRENCY_SPINAZ,
            participants=[{"username": "artist"}, {"username": "designer"},
                          {"username": "shooter"}],
            media_type="audio", media_url="/u/song.mp3", lyrics="rain on the roof",
            needs=[{"slot": "image", "skill": "Designer"},
                   {"slot": "video", "skill": "Videographer"}],
        )
        self.files = f"/api/economy/collab/{self.deal.pk}/files/"
        self.publish = f"/api/economy/collab/{self.deal.pk}/post/"
        self.needs = f"/api/economy/collab/{self.deal.pk}/needs/"

    def as_(self, u):
        c = APIClient(); c.force_authenticate(u); return c

    def bring(self, who, url, kind):
        return self.as_(who).post(self.files, {"url": url, "media_type": kind},
                                  format="json").data

    def full_deal(self):
        self.as_(self.artist).get(self.files)               # seeds the song as v1
        self.bring(self.designer, "/u/cover.png", "image")
        self.bring(self.shooter, "/u/clip.mp4", "video")


class OnePostForAllOfThemTests(CollabPostBase):
    def test_the_finished_collab_posts_once(self):
        self.full_deal()
        r = self.as_(self.artist).post(self.publish, {}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Post.objects.count(), 1)
        self.assertEqual(r.data["media"]["audio"], "/u/song.mp3")
        self.assertEqual(r.data["media"]["image"], "/u/cover.png")
        self.assertEqual(r.data["media"]["video"], "/u/clip.mp4")
        self.assertEqual(r.data["media"]["text"], "rain on the roof")

    def test_credit_says_who_brought_what(self):
        self.full_deal()
        r = self.as_(self.artist).post(self.publish, {}, format="json")
        by_slot = {c["slot"]: c["username"] for c in r.data["contributors"]}
        self.assertEqual(by_slot["audio"], "artist")
        self.assertEqual(by_slot["image"], "designer")
        self.assertEqual(by_slot["video"], "shooter")

    def test_credit_is_derived_from_the_files_not_typed(self):
        # Nobody assigns it, so nobody can misassign it.
        self.full_deal()
        r = self.as_(self.artist).post(self.publish, {"contributors": [{"username": "artist"}]},
                                       format="json")
        names = {c["username"] for c in r.data["contributors"]}
        self.assertEqual(names, {"artist", "designer", "shooter"})

    def test_the_post_belongs_to_every_contributor(self):
        self.full_deal()
        pid = self.as_(self.artist).post(self.publish, {}, format="json").data["id"]
        post = Post.objects.get(pk=pid)
        for u in (self.artist, self.designer, self.shooter):
            self.assertTrue(owns_post(post, u), u.username)
        self.assertFalse(owns_post(post, self.outsider))

    def test_it_reads_as_mine_to_the_designer_too(self):
        # The designer's own work must not look like somebody else's to them.
        self.full_deal()
        self.as_(self.artist).post(self.publish, {}, format="json")
        feed = self.as_(self.designer).get("/api/economy/postz/").data["posts"]
        self.assertTrue(feed[0]["mine"])
        self.assertTrue(feed[0]["co_owned"])

    def test_a_private_collab_post_is_visible_to_all_of_them(self):
        self.full_deal()
        self.as_(self.artist).post(self.publish, {"visibility": "private"}, format="json")
        self.assertEqual(len(self.as_(self.shooter).get("/api/economy/postz/").data["posts"]), 1)
        self.assertEqual(len(self.as_(self.outsider).get("/api/economy/postz/").data["posts"]), 0)

    def test_a_participant_who_brought_no_file_is_still_credited(self):
        # Being on a deal that shipped is a contribution even when it wasn't a
        # file — a manager or a payer belongs on it.
        self.as_(self.artist).get(self.files)
        r = self.as_(self.artist).post(self.publish, {}, format="json")
        names = {c["username"] for c in r.data["contributors"]}
        self.assertEqual(names, {"artist", "designer", "shooter"})

    def test_the_latest_version_of_a_slot_gets_the_credit(self):
        # A cover replaced by a better cover is credited to whoever made the
        # one people will actually see.
        self.full_deal()
        self.bring(self.shooter, "/u/cover2.png", "image")
        r = self.as_(self.artist).post(self.publish, {}, format="json")
        by_slot = {c["slot"]: c["username"] for c in r.data["contributors"]}
        self.assertEqual(by_slot["image"], "shooter")
        self.assertEqual(r.data["media"]["image"], "/u/cover2.png")

    def test_any_of_them_can_publish_it(self):
        self.full_deal()
        r = self.as_(self.designer).post(self.publish, {}, format="json")
        self.assertEqual(r.status_code, 201, r.data)

    def test_an_outsider_cannot(self):
        self.full_deal()
        self.assertEqual(self.as_(self.outsider).post(self.publish, {}, format="json").status_code, 404)

    def test_it_cannot_be_posted_twice(self):
        self.full_deal()
        self.as_(self.artist).post(self.publish, {}, format="json")
        again = self.as_(self.designer).post(self.publish, {}, format="json")
        # Two posts of one collab would split its ratings and its credit.
        self.assertEqual(again.status_code, 409)
        self.assertEqual(Post.objects.count(), 1)

    def test_an_empty_deal_says_so(self):
        deal = CollabDeal.objects.create(
            initiator=self.artist, title="nothing yet", currency=CollabDeal.CURRENCY_SPINAZ,
            participants=[{"username": "artist"}, {"username": "designer"}])
        r = self.as_(self.artist).post(f"/api/economy/collab/{deal.pk}/post/", {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("nothing to post yet", r.data["detail"])

    def test_everyone_credited_is_told(self):
        self.full_deal()
        self.as_(self.artist).post(self.publish, {}, format="json")
        note = self.designer.notifications.first()
        self.assertIsNotNone(note)
        self.assertIn("credited", note.text)
        self.assertIn("image", note.text)


class LookingForTests(CollabPostBase):
    """"An artist can come with a song looking for a designer's cover image.\""""

    def test_a_deal_publishes_what_it_is_looking_for(self):
        r = self.as_(self.designer).get(self.needs)
        slots = {n["slot"]: n["skill"] for n in r.data["open"]}
        self.assertEqual(slots, {"image": "Designer", "video": "Videographer"})

    def test_a_filled_slot_stops_being_asked_for(self):
        self.as_(self.artist).get(self.files)
        self.bring(self.designer, "/u/cover.png", "image")
        r = self.as_(self.designer).get(self.needs)
        self.assertEqual([n["slot"] for n in r.data["open"]], ["video"])
        self.assertEqual(r.data["filled"]["image"], "designer")

    def test_anyone_can_see_what_a_deal_needs(self):
        # A collab only its own members can discover is a collab between people
        # who already knew each other.
        self.assertEqual(self.as_(self.outsider).get(self.needs).status_code, 200)

    def test_only_the_starter_changes_what_it_needs(self):
        r = self.as_(self.designer).patch(self.needs, {"needs": []}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_the_starter_can_change_it(self):
        r = self.as_(self.artist).patch(
            self.needs, {"needs": [{"slot": "video", "skill": "Videographer"}]}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([n["slot"] for n in r.data["needs"]], ["video"])

    def test_junk_slots_are_dropped_rather_than_stored(self):
        r = self.as_(self.artist).patch(self.needs, {"needs": [
            {"slot": "image", "skill": "Designer"},
            {"slot": "image", "skill": "Someone else"},   # duplicate
            {"slot": "nonsense", "skill": "x"},           # not a slot
        ]}, format="json")
        self.assertEqual([n["slot"] for n in r.data["needs"]], ["image"])

    def test_the_slot_menu_is_served_rather_than_guessed(self):
        r = self.as_(self.designer).get(self.needs)
        self.assertEqual([s["slot"] for s in r.data["slots"]],
                         ["audio", "image", "video", "text"])
