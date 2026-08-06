"""What a post's author controls once their work is in somebody else's set.

The design call, stated plainly: NO approval queue. Opt-out, attribution, and
an immediate remove.

An approval gate would be theatre — a public post is already public, and anyone
refused could paste `/p/<id>` back in as an outside link and route around the
check in one move. Worse, approval queues don't get drained: a track sitting
"pending" is a hole in somebody's running order for as long as the author
doesn't log in.

So the author gets three real levers instead:
  1. a switch that refuses future adds,
  2. the right to pull their post out of ANY playlist, immediately,
  3. a list of where it currently appears — a control you can't aim isn't one.
And they're told when it happens, because being picked up is reach, and because
that notification is how anyone learns the levers exist.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import Notification, Playlist, PlaylistItem, Post

User = get_user_model()
PW = "hunter2hunter2"


class AuthorConsentTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.author = User.objects.create_user("author", "a@e.com", PW)
        self.curator = User.objects.create_user("curator", "c@e.com", PW)
        self.post = Post.objects.create(author=self.author, title="My track", visibility="public")
        self.pl = Playlist.objects.create(owner=self.curator, title="Curated")
        self.client.force_authenticate(self.curator)

    def add(self):
        return self.client.post(f"/api/economy/playlistz/{self.pl.pk}/items/",
                                {"post_id": self.post.pk}, format="json")

    def test_a_public_post_may_be_curated_by_default(self):
        # Default open: being in someone's set is reach, not a violation.
        self.assertEqual(self.add().status_code, 201)

    def test_the_author_can_switch_it_off(self):
        self.post.allow_in_playlists = False
        self.post.save(update_fields=["allow_in_playlists"])
        resp = self.add()
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertIn("@author", resp.data["detail"])

    def test_the_switch_never_blocks_the_author_themselves(self):
        self.post.allow_in_playlists = False
        self.post.save(update_fields=["allow_in_playlists"])
        mine = Playlist.objects.create(owner=self.author, title="Mine")
        self.client.force_authenticate(self.author)
        resp = self.client.post(f"/api/economy/playlistz/{mine.pk}/items/",
                                {"post_id": self.post.pk}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_the_author_is_told_when_their_work_is_picked_up(self):
        self.add()
        note = Notification.objects.filter(user=self.author).first()
        self.assertIsNotNone(note)
        self.assertIn("My track", note.text)
        self.assertIn("Curated", note.text)

    def test_adding_your_own_post_does_not_notify_you(self):
        mine = Playlist.objects.create(owner=self.author, title="Mine")
        self.client.force_authenticate(self.author)
        self.client.post(f"/api/economy/playlistz/{mine.pk}/items/",
                         {"post_id": self.post.pk}, format="json")
        self.assertFalse(Notification.objects.filter(user=self.author).exists())


class AuthorRemovalTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.author = User.objects.create_user("author", "a@e.com", PW)
        self.curator = User.objects.create_user("curator", "c@e.com", PW)
        self.other = User.objects.create_user("other", "o@e.com", PW)
        self.post = Post.objects.create(author=self.author, title="My track", visibility="public")
        self.pl = Playlist.objects.create(owner=self.curator, title="Curated")
        self.client.force_authenticate(self.curator)
        self.item_id = self.client.post(f"/api/economy/playlistz/{self.pl.pk}/items/",
                                        {"post_id": self.post.pk},
                                        format="json").data["item"]["id"]

    def rm(self):
        return self.client.delete(
            f"/api/economy/playlistz/{self.pl.pk}/items/{self.item_id}/")

    def test_the_author_can_pull_their_work_out_of_someone_elses_list(self):
        self.client.force_authenticate(self.author)
        resp = self.rm()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(PlaylistItem.objects.filter(pk=self.item_id).exists())

    def test_an_uninvolved_member_still_cannot(self):
        self.client.force_authenticate(self.other)
        self.assertEqual(self.rm().status_code, 403)
        self.assertTrue(PlaylistItem.objects.filter(pk=self.item_id).exists())

    def test_the_row_tells_the_author_they_may_remove_it(self):
        self.client.force_authenticate(self.author)
        rows = self.client.get(f"/api/economy/playlistz/{self.pl.pk}/").data["items"]
        self.assertTrue(rows[0]["can_remove"])

    def test_and_tells_an_uninvolved_member_they_may_not(self):
        self.client.force_authenticate(self.other)
        rows = self.client.get(f"/api/economy/playlistz/{self.pl.pk}/").data["items"]
        self.assertFalse(rows[0]["can_remove"])


class AppearancesTests(TestCase):
    """A control you can't aim is not control."""

    def setUp(self):
        self.client = APIClient()
        self.author = User.objects.create_user("author", "a@e.com", PW)
        self.curator = User.objects.create_user("curator", "c@e.com", PW)
        self.post = Post.objects.create(author=self.author, title="My track", visibility="public")
        theirs = Playlist.objects.create(owner=self.curator, title="Curated")
        PlaylistItem.objects.create(playlist=theirs, position=1, kind="post",
                                    post=self.post, added_by=self.curator, title="My track")
        mine = Playlist.objects.create(owner=self.author, title="Mine")
        PlaylistItem.objects.create(playlist=mine, position=1, kind="post",
                                    post=self.post, added_by=self.author, title="My track")
        self.client.force_authenticate(self.author)

    def test_the_author_sees_where_their_post_ended_up(self):
        resp = self.client.get(f"/api/economy/postz/{self.post.pk}/playlists/")
        self.assertEqual(resp.status_code, 200, resp.content)
        appearances = resp.data["appearances"]
        self.assertEqual(len(appearances), 1)          # my own list isn't an "appearance"
        self.assertEqual(appearances[0]["playlist"], "Curated")
        self.assertEqual(appearances[0]["owner"], "curator")
        self.assertTrue(appearances[0]["remove_url"])

    def test_it_reports_the_current_switch_state(self):
        self.assertTrue(self.client.get(
            f"/api/economy/postz/{self.post.pk}/playlists/").data["allow_in_playlists"])

    def test_nobody_else_can_read_my_appearances(self):
        self.client.force_authenticate(self.curator)
        self.assertEqual(self.client.get(
            f"/api/economy/postz/{self.post.pk}/playlists/").status_code, 404)


class ToggleTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.author = User.objects.create_user("author", "a@e.com", PW)
        self.client.force_authenticate(self.author)
        self.post = Post.objects.create(author=self.author, title="My track", visibility="public")

    def toggle(self, value):
        return self.client.post("/api/economy/postz/",
                                {"edit_id": self.post.pk, "allow_in_playlists": value},
                                format="json")

    def test_the_author_can_flip_it_after_posting(self):
        resp = self.toggle(False)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.post.refresh_from_db()
        self.assertFalse(self.post.allow_in_playlists)
        self.toggle(True)
        self.post.refresh_from_db()
        self.assertTrue(self.post.allow_in_playlists)

    def test_it_is_not_held_to_the_tier_edit_window(self):
        # Locking an author out of withdrawing their work four minutes after
        # posting would make the switch useless.
        from datetime import timedelta

        from django.utils import timezone
        Post.objects.filter(pk=self.post.pk).update(
            created_at=timezone.now() - timedelta(days=30))
        self.assertEqual(self.toggle(False).status_code, 200)

    def test_it_can_be_set_at_post_time(self):
        resp = self.client.post("/api/economy/postz/",
                                {"title": "Quiet one", "allow_in_playlists": False},
                                format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertFalse(resp.data["allow_in_playlists"])

    def test_editing_the_title_still_works_alongside_it(self):
        resp = self.client.post("/api/economy/postz/",
                                {"edit_id": self.post.pk, "title": "Renamed",
                                 "allow_in_playlists": False},
                                format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.post.refresh_from_db()
        self.assertEqual(self.post.title, "Renamed")
        self.assertFalse(self.post.allow_in_playlists)


class RestrictedTitleLeakTests(TestCase):
    """A public playlist could hold a members-only post, and the row copied that
    post's TITLE at add time — so a restricted post's name was readable by
    anyone with the share link."""

    def setUp(self):
        self.client = APIClient()
        self.author = User.objects.create_user("author", "a@e.com", PW)
        self.curator = User.objects.create_user("curator", "c@e.com", PW)
        self.post = Post.objects.create(author=self.author, title="Secret demo",
                                        visibility="restricted")
        self.pl = Playlist.objects.create(owner=self.curator, title="Curated",
                                          visibility="public")
        PlaylistItem.objects.create(playlist=self.pl, position=1, kind="post",
                                    post=self.post, added_by=self.curator,
                                    title="Secret demo", artist="author")

    def test_a_stranger_does_not_learn_the_title(self):
        resp = self.client.get(f"/api/playlistz/{self.pl.pk}/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertNotIn("Secret demo", str(resp.data))
        row = resp.data["items"][0]
        self.assertFalse(row["readable"])
        self.assertEqual(row["url"], "")
        self.assertEqual(row["author"], "")

    def test_the_row_keeps_its_place_in_the_running_order(self):
        # It stops saying what it is; it does not vanish and renumber the set.
        row = self.client.get(f"/api/playlistz/{self.pl.pk}/").data["items"][0]
        self.assertEqual(row["position"], 1)
        self.assertEqual(row["title"], "Members-only track")

    def test_a_signed_in_member_sees_it_normally(self):
        self.client.force_authenticate(User.objects.create_user("m", "m@e.com", PW))
        row = self.client.get(f"/api/economy/playlistz/{self.pl.pk}/").data["items"][0]
        self.assertTrue(row["readable"])
        self.assertEqual(row["title"], "Secret demo")

    def test_a_private_post_is_opaque_even_to_members(self):
        self.post.visibility = "private"
        self.post.save(update_fields=["visibility"])
        self.client.force_authenticate(User.objects.create_user("m", "m@e.com", PW))
        row = self.client.get(f"/api/economy/playlistz/{self.pl.pk}/").data["items"][0]
        self.assertFalse(row["readable"])
        self.assertEqual(row["title"], "Members-only track")

    def test_a_public_post_is_unaffected(self):
        self.post.visibility = "public"
        self.post.save(update_fields=["visibility"])
        row = self.client.get(f"/api/playlistz/{self.pl.pk}/").data["items"][0]
        self.assertTrue(row["readable"])
        self.assertEqual(row["title"], "Secret demo")
        self.assertEqual(row["url"], f"/p/{self.post.pk}")


class MyAppearancesTests(TestCase):
    """One call, not N. A panel nobody loads is a control nobody uses."""

    def setUp(self):
        self.client = APIClient()
        self.author = User.objects.create_user("author", "a@e.com", PW)
        self.curator = User.objects.create_user("curator", "c@e.com", PW)
        self.client.force_authenticate(self.author)

    def place(self, post, playlist, by):
        return PlaylistItem.objects.create(playlist=playlist, position=1, kind="post",
                                           post=post, added_by=by, title=post.title)

    def test_it_gathers_every_post_in_one_response(self):
        a = Post.objects.create(author=self.author, title="One", visibility="public")
        b = Post.objects.create(author=self.author, title="Two", visibility="public")
        pl = Playlist.objects.create(owner=self.curator, title="Curated")
        self.place(a, pl, self.curator)
        self.place(b, pl, self.curator)
        resp = self.client.get("/api/economy/playlistz/appearances/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual({r["post"] for r in resp.data["appearances"]}, {"One", "Two"})

    def test_my_own_playlists_are_not_appearances(self):
        post = Post.objects.create(author=self.author, title="One", visibility="public")
        self.place(post, Playlist.objects.create(owner=self.author, title="Mine"), self.author)
        self.assertEqual(self.client.get("/api/economy/playlistz/appearances/").data["appearances"], [])

    def test_other_peoples_posts_are_not_mine(self):
        theirs = Post.objects.create(author=self.curator, title="Theirs", visibility="public")
        self.place(theirs, Playlist.objects.create(owner=self.curator, title="Curated"), self.curator)
        self.assertEqual(self.client.get("/api/economy/playlistz/appearances/").data["appearances"], [])

    def test_the_row_carries_the_switch_state_so_the_panel_can_offer_it(self):
        post = Post.objects.create(author=self.author, title="One", visibility="public",
                                   allow_in_playlists=False)
        self.place(post, Playlist.objects.create(owner=self.curator, title="Curated"), self.curator)
        row = self.client.get("/api/economy/playlistz/appearances/").data["appearances"][0]
        self.assertFalse(row["allow_in_playlists"])
        self.assertEqual(row["owner"], "curator")

    def test_the_route_is_not_shadowed_by_the_detail_view(self):
        # "appearances" would parse as a playlist id lookup if it were declared
        # after playlistz/<int:pk>/ — it isn't an int, so it would 404 instead.
        self.assertEqual(self.client.get("/api/economy/playlistz/appearances/").status_code, 200)
