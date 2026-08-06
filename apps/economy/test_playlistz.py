"""PlaylistZ — the mix is the point.

A member's catalogue lives half here and half on four distributors. Every
other way to share "the set" makes you pick one platform and abandon the rest.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import (
    PLAYLIST_MAX_ITEMS,
    TIER_FREE,
    ItemRating,
    LinkCounter,
    Playlist,
    PlaylistItem,
    Post,
    link_provider,
    membership_for,
)

User = get_user_model()
PW = "hunter2hunter2"


class LinkProviderTests(TestCase):
    def test_the_distributors_are_recognised(self):
        cases = {
            "https://open.spotify.com/track/x": "spotify",
            "https://spotify.com/album/y": "spotify",
            "https://www.youtube.com/watch?v=z": "youtube",
            "https://youtu.be/z": "youtube",
            "https://music.apple.com/us/album/a": "apple",
            "https://soundcloud.com/k-oth/demo": "soundcloud",
            "https://k-oth.bandcamp.com/track/b": "bandcamp",
            "https://audius.co/k-oth": "audius",
        }
        for url, want in cases.items():
            self.assertEqual(link_provider(url), want, url)

    def test_an_unknown_host_is_still_a_valid_row_it_just_has_no_badge(self):
        self.assertEqual(link_provider("https://my-own-site.example/song"), "")

    def test_junk_never_raises(self):
        for bad in ("", None, "not a url", "javascript:alert(1)"):
            self.assertEqual(link_provider(bad), "")

    def test_a_lookalike_domain_is_not_the_real_one(self):
        # "spotify.com.evil.test" must not read as Spotify.
        self.assertEqual(link_provider("https://spotify.com.evil.test/x"), "")


class PlaylistCrudTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.me = User.objects.create_user("me", "me@e.com", PW)
        self.client.force_authenticate(self.me)

    def make(self, **over):
        payload = {"title": "Late night set", **over}
        return self.client.post("/api/economy/playlistz/", payload, format="json")

    def test_a_playlist_needs_a_name(self):
        self.assertEqual(self.make(title="  ").status_code, 400)

    def test_creating_one_returns_it_with_its_rating_key(self):
        resp = self.make()
        self.assertEqual(resp.status_code, 201, resp.content)
        # Ratings and comments ride the existing item id space rather than a
        # second one grown beside it.
        self.assertEqual(resp.data["item_key"], f"playlist:{resp.data['id']}")
        self.assertEqual(resp.data["items"], [])

    def test_the_description_answers_to_the_tier_limit(self):
        m = membership_for(self.me)
        m.tier = TIER_FREE
        m.save(update_fields=["tier", "updated_at"])
        resp = self.make(description="d" * 401)
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.data["char_limit"], 400)

    def test_renaming_and_reprivatising_works(self):
        pk = self.make().data["id"]
        resp = self.client.patch(f"/api/economy/playlistz/{pk}/",
                                 {"title": "New name", "visibility": "private"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["title"], "New name")
        self.assertEqual(resp.data["visibility"], "private")

    def test_only_the_owner_can_edit_or_delete(self):
        pk = self.make().data["id"]
        self.client.force_authenticate(User.objects.create_user("x", "x@e.com", PW))
        self.assertEqual(self.client.patch(f"/api/economy/playlistz/{pk}/",
                                           {"title": "mine now"}, format="json").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/economy/playlistz/{pk}/").status_code, 404)

    def test_a_private_playlist_is_invisible_to_others_but_not_to_me(self):
        pk = self.make(visibility="private").data["id"]
        self.assertEqual(self.client.get(f"/api/economy/playlistz/{pk}/").status_code, 200)
        self.client.force_authenticate(User.objects.create_user("x", "x@e.com", PW))
        self.assertEqual(self.client.get(f"/api/economy/playlistz/{pk}/").status_code, 404)

    def test_my_private_playlists_still_appear_in_my_own_list(self):
        self.make(visibility="private")
        titles = {p["title"] for p in self.client.get("/api/economy/playlistz/").data["playlists"]}
        self.assertIn("Late night set", titles)


class MixingTests(TestCase):
    """Posts and outside links, in one running order. This is the feature."""

    def setUp(self):
        self.client = APIClient()
        self.me = User.objects.create_user("me", "me@e.com", PW)
        self.client.force_authenticate(self.me)
        self.pl = Playlist.objects.create(owner=self.me, title="Set")
        self.post = Post.objects.create(author=self.me, title="My track", visibility="public")

    def add(self, **payload):
        return self.client.post(f"/api/economy/playlistz/{self.pl.pk}/items/", payload, format="json")

    def test_a_post_and_a_link_sit_in_the_same_list(self):
        self.assertEqual(self.add(post_id=self.post.pk).status_code, 201)
        self.assertEqual(self.add(url="https://open.spotify.com/track/abc").status_code, 201)
        data = self.client.get(f"/api/economy/playlistz/{self.pl.pk}/").data
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["post_count"], 1)
        self.assertEqual(data["link_count"], 1)
        self.assertEqual([i["kind"] for i in data["items"]], ["post", "link"])

    def test_the_kind_is_inferred_from_what_was_sent(self):
        self.assertEqual(self.add(post_id=self.post.pk).data["item"]["kind"], "post")
        self.assertEqual(self.add(url="https://youtu.be/x").data["item"]["kind"], "link")

    def test_a_post_row_carries_where_it_opens(self):
        item = self.add(post_id=self.post.pk).data["item"]
        self.assertEqual(item["open_in"], "social:post")
        self.assertEqual(item["url"], f"/p/{self.post.pk}")     # works with no account
        self.assertEqual(item["title"], "My track")             # borrowed from the post
        self.assertEqual(item["artist"], "me")

    def test_a_link_row_carries_its_provider(self):
        item = self.add(url="https://soundcloud.com/k-oth/demo", title="Demo").data["item"]
        self.assertEqual(item["provider"], "soundcloud")
        self.assertEqual(item["open_in"], "external")
        self.assertEqual(item["title"], "Demo")

    def test_an_outside_link_tallies_like_a_profile_link(self):
        # Otherwise a playlist leaks its value to a page nobody here can measure.
        self.add(url="https://open.spotify.com/track/abc")
        self.assertTrue(LinkCounter.objects.filter(owner=self.me,
                                                   url="https://open.spotify.com/track/abc").exists())

    def test_a_bare_word_is_not_a_link(self):
        resp = self.add(url="spotify.com/track/abc")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("https://", resp.data["detail"])

    def test_you_cannot_smuggle_in_a_post_you_cannot_see(self):
        theirs = Post.objects.create(
            author=User.objects.create_user("them", "t@e.com", PW),
            title="Private", visibility="private")
        self.assertEqual(self.add(post_id=theirs.pk).status_code, 403)

    def test_a_missing_post_is_refused_not_500(self):
        self.assertEqual(self.add(post_id=999999).status_code, 400)

    def test_a_deleted_post_leaves_a_visible_gap_not_a_blank_row(self):
        self.add(post_id=self.post.pk)
        self.post.delete()
        item = self.client.get(f"/api/economy/playlistz/{self.pl.pk}/").data["items"][0]
        self.assertFalse(item["available"])
        self.assertEqual(item["title"], "My track")   # the owner can still tell what it was

    def test_the_list_is_capped(self):
        PlaylistItem.objects.bulk_create([
            PlaylistItem(playlist=self.pl, position=i, kind="link", url=f"https://x.test/{i}")
            for i in range(PLAYLIST_MAX_ITEMS)
        ])
        resp = self.add(url="https://x.test/one-too-many")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["max_items"], PLAYLIST_MAX_ITEMS)

    def test_removing_a_track_leaves_the_rest(self):
        first = self.add(url="https://x.test/1").data["item"]["id"]
        self.add(url="https://x.test/2")
        resp = self.client.delete(f"/api/economy/playlistz/{self.pl.pk}/items/{first}/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["count"], 1)


class ReorderTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.me = User.objects.create_user("me", "me@e.com", PW)
        self.client.force_authenticate(self.me)
        self.pl = Playlist.objects.create(owner=self.me, title="Set")
        self.ids = []
        for n in range(3):
            r = self.client.post(f"/api/economy/playlistz/{self.pl.pk}/items/",
                                 {"url": f"https://x.test/{n}", "title": f"t{n}"}, format="json")
            self.ids.append(r.data["item"]["id"])

    def order(self):
        data = self.client.get(f"/api/economy/playlistz/{self.pl.pk}/").data
        return [i["id"] for i in data["items"]]

    def test_new_tracks_land_at_the_end(self):
        self.assertEqual(self.order(), self.ids)

    def test_the_running_order_can_be_set(self):
        wanted = [self.ids[2], self.ids[0], self.ids[1]]
        resp = self.client.post(f"/api/economy/playlistz/{self.pl.pk}/reorder/",
                                {"order": wanted}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self.order(), wanted)

    def test_a_partial_order_never_drops_a_track(self):
        self.client.post(f"/api/economy/playlistz/{self.pl.pk}/reorder/",
                         {"order": [self.ids[2]]}, format="json")
        self.assertEqual(set(self.order()), set(self.ids))
        self.assertEqual(self.order()[0], self.ids[2])

    def test_ids_from_another_playlist_are_ignored(self):
        other = Playlist.objects.create(owner=self.me, title="Other")
        alien = PlaylistItem.objects.create(playlist=other, position=1, kind="link", url="https://y.test")
        self.client.post(f"/api/economy/playlistz/{self.pl.pk}/reorder/",
                         {"order": [alien.id] + self.ids}, format="json")
        self.assertEqual(self.order(), self.ids)
        alien.refresh_from_db()
        self.assertEqual(alien.playlist_id, other.id)

    def test_junk_in_the_order_does_not_500(self):
        resp = self.client.post(f"/api/economy/playlistz/{self.pl.pk}/reorder/",
                                {"order": ["x", None, self.ids[1]]}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(set(self.order()), set(self.ids))


class SharedPlaylistTests(TestCase):
    """A playlist shares the way a post does — by link, no account needed."""

    def setUp(self):
        self.client = APIClient()          # anonymous
        self.owner = User.objects.create_user("owner", "o@e.com", PW)
        self.pl = Playlist.objects.create(owner=self.owner, title="Public set")
        PlaylistItem.objects.create(playlist=self.pl, position=1, kind="link",
                                    url="https://open.spotify.com/track/x",
                                    provider="spotify", title="A track")

    def test_a_stranger_gets_the_running_order(self):
        resp = self.client.get(f"/api/playlistz/{self.pl.pk}/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["title"], "Public set")
        self.assertEqual(resp.data["items"][0]["url"], "https://open.spotify.com/track/x")
        self.assertTrue(resp.data["public"])

    def test_ownership_flags_stay_behind_the_login(self):
        self.assertNotIn("mine", self.client.get(f"/api/playlistz/{self.pl.pk}/").data)

    def test_restricted_is_members_only(self):
        self.pl.visibility = "restricted"
        self.pl.save(update_fields=["visibility"])
        self.assertEqual(self.client.get(f"/api/playlistz/{self.pl.pk}/").status_code, 404)
        self.client.force_authenticate(User.objects.create_user("m", "m@e.com", PW))
        self.assertEqual(self.client.get(f"/api/playlistz/{self.pl.pk}/").status_code, 200)

    def test_private_answers_404_not_403(self):
        self.pl.visibility = "private"
        self.pl.save(update_fields=["visibility"])
        resp = self.client.get(f"/api/playlistz/{self.pl.pk}/")
        self.assertEqual(resp.status_code, 404)
        self.assertNotIn("Public set", str(resp.data))


class PlaylistRatingTests(TestCase):
    """No second rating system — a playlist rides the one that exists."""

    def setUp(self):
        self.client = APIClient()
        self.me = User.objects.create_user("me", "me@e.com", PW)
        self.client.force_authenticate(self.me)
        self.pl = Playlist.objects.create(
            owner=User.objects.create_user("owner", "o@e.com", PW), title="Set")

    def test_rating_a_playlist_goes_through_the_existing_surface(self):
        resp = self.client.post("/api/economy/social/rate/",
                                {"item": self.pl.item_key, "action": "rate", "score": 9},
                                format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(ItemRating.objects.filter(item_id=self.pl.item_key).exists())

    def test_the_median_shows_up_on_the_playlist(self):
        self.client.post("/api/economy/social/rate/",
                         {"item": self.pl.item_key, "action": "rate", "score": 8}, format="json")
        resp = self.client.get(f"/api/economy/playlistz/{self.pl.pk}/")
        self.assertEqual(resp.data["rating"], 8)
