"""Owner post powers — edit any post at any age, add media, delete, share.

The edit window exists so a post can't be quietly rewritten after people have
read and rated it. That protection belongs to READERS, and the owner is exempt
from it because somebody has to be able to fix a dead media link on a two-year
-old post. Exempt is not invisible: an edit to somebody else's post is recorded
against the name of whoever made it, and the post says so.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.models import Notification, Post, membership_for

User = get_user_model()
PW = "hunter2hunter2"
POSTZ = "/api/economy/postz/"


class OwnerPostPowersTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="boss", password=PW,
                                              is_staff=True, is_superuser=True)
        self.member = User.objects.create_user(username="maker", password=PW)
        self.other = User.objects.create_user(username="rando", password=PW)
        for u in (self.owner, self.member, self.other):
            membership_for(u)
        self.oc = APIClient(); self.oc.force_authenticate(self.owner)
        self.mc = APIClient(); self.mc.force_authenticate(self.member)
        self.rc = APIClient(); self.rc.force_authenticate(self.other)

    def old_post(self, author=None, **kw):
        p = Post.objects.create(author=author or self.member, title="She's too Good for me",
                                description="verse one", **kw)
        # Two years old — far outside every tier's edit window.
        Post.objects.filter(pk=p.pk).update(created_at=timezone.now() - timedelta(days=730))
        p.refresh_from_db()
        return p

    # ---- the window ----
    def test_a_member_still_cannot_edit_their_own_old_post(self):
        p = self.old_post()
        r = self.mc.post(POSTZ, {"edit_id": p.id, "title": "new"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data["detail"], "edit_window_passed")

    def test_the_owner_can_edit_their_own_post_at_any_age(self):
        p = self.old_post(author=self.owner)
        r = self.oc.post(POSTZ, {"edit_id": p.id, "title": "She's too Good for me (v2)"},
                         format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Post.objects.get(pk=p.pk).title, "She's too Good for me (v2)")

    def test_the_owner_can_edit_somebody_elses_old_post(self):
        p = self.old_post()
        r = self.oc.post(POSTZ, {"edit_id": p.id, "description": "fixed the link"},
                         format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Post.objects.get(pk=p.pk).description, "fixed the link")

    def test_an_ordinary_member_cannot_touch_another_members_post(self):
        p = self.old_post()
        r = self.rc.post(POSTZ, {"edit_id": p.id, "title": "mine now"}, format="json")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(Post.objects.get(pk=p.pk).title, "She's too Good for me")

    # ---- media, which is the point ----
    def test_media_can_be_added_to_an_old_post(self):
        p = self.old_post(author=self.owner)
        r = self.oc.post(POSTZ, {"edit_id": p.id, "media_url": "https://cdn.test/take.mp3",
                                 "media_type": "audio"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        p.refresh_from_db()
        self.assertEqual(p.media_url, "https://cdn.test/take.mp3")
        self.assertEqual(p.media_type, "audio")

    def test_album_items_can_be_added(self):
        p = self.old_post(author=self.owner)
        r = self.oc.post(POSTZ, {"edit_id": p.id, "is_album": True, "items": [
            {"url": "https://cdn.test/a.mp3", "type": "audio", "title": "A"},
            {"url": "https://cdn.test/b.mp3", "type": "audio", "title": "B"},
        ]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(len(Post.objects.get(pk=p.pk).items), 2)

    def test_two_of_a_slot_is_still_refused_unless_it_is_an_album(self):
        # Same rule as posting: a track plus its cover isn't an album of two.
        p = self.old_post(author=self.owner)
        r = self.oc.post(POSTZ, {"edit_id": p.id, "items": [
            {"url": "https://cdn.test/a.mp3", "type": "audio"},
            {"url": "https://cdn.test/b.mp3", "type": "audio"},
        ]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["duplicate_type"], "audio")

    # ---- exempt is not invisible ----
    def test_an_owner_edit_of_another_post_is_named_on_the_post(self):
        p = self.old_post()
        r = self.oc.post(POSTZ, {"edit_id": p.id, "description": "tidied"}, format="json")
        self.assertEqual(r.data["edited_by"], "boss")
        self.assertEqual(r.data["edit_history"][-1]["by"], "boss")
        # And the previous text is kept, not overwritten out of existence.
        self.assertEqual(r.data["edit_history"][-1]["description"], "verse one")

    def test_editing_your_own_post_does_not_brand_it_as_someone_elses(self):
        p = self.old_post(author=self.owner)
        r = self.oc.post(POSTZ, {"edit_id": p.id, "description": "tidied"}, format="json")
        self.assertEqual(r.data["edited_by"], "")

    def test_the_author_is_told_their_post_was_edited(self):
        p = self.old_post()
        self.oc.post(POSTZ, {"edit_id": p.id, "description": "tidied"}, format="json")
        n = Notification.objects.filter(user=self.member).first()
        self.assertIsNotNone(n)
        self.assertIn("edited your post", n.text)

    def test_an_edit_that_changes_nothing_writes_no_history(self):
        p = self.old_post()
        r = self.oc.post(POSTZ, {"edit_id": p.id, "title": p.title}, format="json")
        self.assertEqual(r.data["edit_history"], [])
        self.assertFalse(Notification.objects.filter(user=self.member).exists())

    # ---- delete ----
    def test_you_can_delete_your_own_post_however_old(self):
        p = self.old_post()
        r = self.mc.delete(f"/api/economy/postz/{p.id}/delete/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(Post.objects.filter(pk=p.pk).exists())

    def test_the_owner_can_delete_anybodys_post(self):
        p = self.old_post()
        r = self.oc.delete(f"/api/economy/postz/{p.id}/delete/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(Post.objects.filter(pk=p.pk).exists())

    def test_the_author_is_told_when_the_owner_removes_their_post(self):
        p = self.old_post()
        self.oc.delete(f"/api/economy/postz/{p.id}/delete/")
        n = Notification.objects.filter(user=self.member).first()
        self.assertIsNotNone(n)
        self.assertIn("removed your post", n.text)

    def test_an_ordinary_member_cannot_delete_another_members_post(self):
        p = self.old_post()
        r = self.rc.delete(f"/api/economy/postz/{p.id}/delete/")
        self.assertEqual(r.status_code, 403)
        self.assertTrue(Post.objects.filter(pk=p.pk).exists())

    def test_delete_also_answers_post_for_clients_that_cant_send_one(self):
        p = self.old_post()
        r = self.mc.post(f"/api/economy/postz/{p.id}/delete/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(Post.objects.filter(pk=p.pk).exists())
