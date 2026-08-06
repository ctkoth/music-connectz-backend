"""Collaborative playlists — three questions, answered deliberately.

1. WHO CAN ADD — the owner and whoever they invite. Not everyone: an open
   playlist anybody can append to is a spam target with the owner's name on it.
2. WHO CAN REORDER — the owner alone. The running order is authorship; a
   collaborator contributes tracks and the owner sequences them. Two people
   with reorder rights means last-save-wins on somebody's set list.
3. WHOSE TALLY — the person who ADDED the link. They found it, their reach
   earns from it. Crediting a contributor's link to the owner would let anyone
   farm reach off other people's work.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import (
    Block,
    LinkCounter,
    Notification,
    Playlist,
    PlaylistCollaborator,
    PlaylistItem,
    Post,
)

User = get_user_model()
PW = "hunter2hunter2"


class CollabBase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user("owner", "o@e.com", PW)
        self.mate = User.objects.create_user("mate", "m@e.com", PW)
        self.stranger = User.objects.create_user("stranger", "s@e.com", PW)
        self.pl = Playlist.objects.create(owner=self.owner, title="The set")
        self.client.force_authenticate(self.owner)

    def invite(self, username="mate"):
        return self.client.post(f"/api/economy/playlistz/{self.pl.pk}/collaborators/",
                                {"username": username}, format="json")

    def add_link(self, url="https://open.spotify.com/track/x", **extra):
        return self.client.post(f"/api/economy/playlistz/{self.pl.pk}/items/",
                                {"url": url, **extra}, format="json")

    def detail(self):
        return self.client.get(f"/api/economy/playlistz/{self.pl.pk}/")


class InviteTests(CollabBase):
    def test_the_owner_can_add_a_collaborator(self):
        resp = self.invite()
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["collaborators"], ["mate"])

    def test_an_invitation_nobody_is_told_about_is_not_an_invitation(self):
        self.invite()
        note = Notification.objects.filter(user=self.mate).first()
        self.assertIsNotNone(note)
        self.assertIn("The set", note.text)

    def test_inviting_twice_is_idempotent_and_does_not_re_notify(self):
        self.invite()
        self.invite()
        self.assertEqual(PlaylistCollaborator.objects.filter(playlist=self.pl).count(), 1)
        self.assertEqual(Notification.objects.filter(user=self.mate).count(), 1)

    def test_an_unknown_member_is_refused_by_name(self):
        resp = self.invite("ghost")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("ghost", resp.data["detail"])

    def test_you_cannot_invite_yourself(self):
        self.assertEqual(self.invite("owner").status_code, 400)

    def test_you_cannot_invite_someone_you_have_blocked(self):
        Block.objects.create(blocker=self.owner, blocked=self.mate)
        self.assertEqual(self.invite().status_code, 403)

    def test_only_the_owner_can_invite(self):
        self.client.force_authenticate(self.mate)
        self.assertEqual(self.invite("stranger").status_code, 404)


class AddingTests(CollabBase):
    def test_a_collaborator_can_add(self):
        self.invite()
        self.client.force_authenticate(self.mate)
        self.assertEqual(self.add_link().status_code, 201)

    def test_a_stranger_cannot_add(self):
        self.client.force_authenticate(self.stranger)
        resp = self.add_link()
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertIn("collaborator", resp.data["detail"])

    def test_the_row_records_who_added_it(self):
        self.invite()
        self.client.force_authenticate(self.mate)
        self.assertEqual(self.add_link().data["item"]["added_by"], "mate")

    def test_an_outside_link_tallies_to_whoever_added_it(self):
        # Question 3. Crediting a contributor's link to the owner would let an
        # owner farm reach off other people's work.
        self.invite()
        self.client.force_authenticate(self.mate)
        self.add_link()
        counter = LinkCounter.objects.get(url="https://open.spotify.com/track/x")
        self.assertEqual(counter.owner_id, self.mate.id)

    def test_the_owner_is_told_when_a_collaborator_adds(self):
        self.invite()
        Notification.objects.all().delete()
        self.client.force_authenticate(self.mate)
        self.add_link()
        note = Notification.objects.filter(user=self.owner).first()
        self.assertIsNotNone(note)
        self.assertIn("@mate", note.text)

    def test_the_owner_adding_does_not_notify_themselves(self):
        self.add_link()
        self.assertFalse(Notification.objects.filter(user=self.owner).exists())

    def test_a_collaborator_can_add_their_own_post(self):
        self.invite()
        post = Post.objects.create(author=self.mate, title="Mate's track", visibility="public")
        self.client.force_authenticate(self.mate)
        resp = self.client.post(f"/api/economy/playlistz/{self.pl.pk}/items/",
                                {"post_id": post.pk}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["item"]["artist"], "mate")


class RemovalTests(CollabBase):
    def setUp(self):
        super().setUp()
        self.invite()
        self.owner_row = self.add_link("https://x.test/owner").data["item"]["id"]
        self.client.force_authenticate(self.mate)
        self.mate_row = self.add_link("https://x.test/mate").data["item"]["id"]

    def rm(self, item_id):
        return self.client.delete(f"/api/economy/playlistz/{self.pl.pk}/items/{item_id}/")

    def test_a_collaborator_can_take_back_what_they_put_in(self):
        self.assertEqual(self.rm(self.mate_row).status_code, 200)

    def test_a_collaborator_cannot_delete_someone_elses_track(self):
        # Otherwise a shared list is a place to be sabotaged.
        resp = self.rm(self.owner_row)
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertTrue(PlaylistItem.objects.filter(pk=self.owner_row).exists())

    def test_the_owner_can_remove_anything_on_their_list(self):
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.rm(self.mate_row).status_code, 200)

    def test_the_payload_says_which_rows_i_may_remove(self):
        rows = {i["id"]: i for i in self.detail().data["items"]}
        self.assertTrue(rows[self.mate_row]["can_remove"])
        self.assertFalse(rows[self.owner_row]["can_remove"])


class ReorderRightsTests(CollabBase):
    def test_only_the_owner_reorders(self):
        # Question 2. The running order is authorship.
        self.invite()
        a = self.add_link("https://x.test/1").data["item"]["id"]
        b = self.add_link("https://x.test/2").data["item"]["id"]
        self.client.force_authenticate(self.mate)
        resp = self.client.post(f"/api/economy/playlistz/{self.pl.pk}/reorder/",
                                {"order": [b, a]}, format="json")
        self.assertEqual(resp.status_code, 404, resp.content)
        self.assertEqual([i["id"] for i in self.detail().data["items"]], [a, b])

    def test_the_payload_tells_the_client_who_may_reorder(self):
        self.invite()
        self.assertTrue(self.detail().data["can_reorder"])
        self.client.force_authenticate(self.mate)
        d = self.detail().data
        self.assertFalse(d["can_reorder"])
        self.assertTrue(d["can_add"])       # …but they can still contribute


class VisibilityTests(CollabBase):
    def test_a_collaborator_sees_a_private_list_they_are_on(self):
        self.pl.visibility = "private"
        self.pl.save(update_fields=["visibility"])
        self.invite()
        self.client.force_authenticate(self.mate)
        self.assertEqual(self.detail().status_code, 200)

    def test_a_stranger_still_cannot(self):
        self.pl.visibility = "private"
        self.pl.save(update_fields=["visibility"])
        self.client.force_authenticate(self.stranger)
        self.assertEqual(self.detail().status_code, 404)

    def test_a_list_i_collaborate_on_appears_among_my_playlists(self):
        # Being a collaborator on something you can't find is absurd.
        self.pl.visibility = "private"
        self.pl.save(update_fields=["visibility"])
        self.invite()
        self.client.force_authenticate(self.mate)
        titles = {p["title"] for p in
                  self.client.get("/api/economy/playlistz/").data["playlists"]}
        self.assertIn("The set", titles)

    def test_it_is_listed_once_not_twice(self):
        self.invite()
        ids = [p["id"] for p in self.client.get("/api/economy/playlistz/").data["playlists"]]
        self.assertEqual(len(ids), len(set(ids)))


class LeavingTests(CollabBase):
    def test_a_collaborator_can_take_themselves_off(self):
        self.invite()
        self.client.force_authenticate(self.mate)
        resp = self.client.delete(f"/api/economy/playlistz/{self.pl.pk}/collaborators/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["collaborators"], [])

    def test_the_owner_can_remove_a_collaborator(self):
        self.invite()
        resp = self.client.delete(
            f"/api/economy/playlistz/{self.pl.pk}/collaborators/?username=mate")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["collaborators"], [])

    def test_a_collaborator_cannot_remove_another_collaborator(self):
        self.invite()
        self.invite("stranger")
        self.client.force_authenticate(self.mate)
        resp = self.client.delete(
            f"/api/economy/playlistz/{self.pl.pk}/collaborators/?username=stranger")
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_leaving_does_not_gut_the_set(self):
        # Their tracks stay. Pulling the set apart because somebody left is the
        # owner's call, not a side effect.
        self.invite()
        self.client.force_authenticate(self.mate)
        self.add_link("https://x.test/mate")
        self.client.delete(f"/api/economy/playlistz/{self.pl.pk}/collaborators/")
        self.assertEqual(self.pl.items.count(), 1)

    def test_once_off_the_list_they_can_no_longer_add(self):
        self.invite()
        self.client.force_authenticate(self.mate)
        self.client.delete(f"/api/economy/playlistz/{self.pl.pk}/collaborators/")
        self.assertEqual(self.add_link("https://x.test/again").status_code, 403)


class CollaboratorListTests(CollabBase):
    def test_the_roster_names_who_invited_whom(self):
        self.invite()
        resp = self.client.get(f"/api/economy/playlistz/{self.pl.pk}/collaborators/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["owner"], "owner")
        self.assertEqual(resp.data["collaborators"][0]["username"], "mate")
        self.assertEqual(resp.data["collaborators"][0]["invited_by"], "owner")
