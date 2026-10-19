"""One embed list, one sandbox posture.

There were two of each. `views._parse_embed_url` knew three providers, wrote
its own regexes, and for Spotify and SoundCloud stored THE MEMBER'S OWN URL to
be framed verbatim. `widgetz` was written days later around the opposite rule —
read an id out of the link, build the provider's address here — and the client
rendered the old path's iframes with no `sandbox` attribute at all.

What these pin is that the two cannot come apart again: a provider added to
`widgetz.PLAYERS` is a provider a post can embed, and the URL that gets framed
is one this codebase wrote.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import Post, membership_for
from apps.economy.views import _parse_embed_url
from apps.economy.widgetz import PLAYER_LABELS, PLAYERS

User = get_user_model()
PW = "hunter2hunter2"
URL = "/api/economy/postz/embeds/"


class OneListTests(TestCase):
    def test_the_embed_resolver_is_the_widget_resolver(self):
        # Nine providers where there were three. Adding one to widgetz.PLAYERS
        # is all it takes for a post to embed it.
        self.assertGreaterEqual(len(PLAYERS), 9)
        for url in ("https://youtu.be/dQw4w9WgXcQ",
                    "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT",
                    "https://soundcloud.com/artist/track",
                    "https://music.apple.com/us/album/thriller/1234",
                    "https://vimeo.com/123456789"):
            self.assertTrue(_parse_embed_url(url)["valid"], url)

    def test_the_framed_url_is_one_we_built_not_the_one_pasted(self):
        # The old path stored the member's Spotify URL and framed it verbatim.
        pasted = "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT?si=abc&x=1"
        out = _parse_embed_url(pasted)
        self.assertNotEqual(out["url"], pasted)
        self.assertTrue(out["url"].startswith("https://open.spotify.com/embed/track/"))

    def test_the_url_decides_the_type_not_the_radio_button(self):
        # A member picking the wrong option in the composer used to be told
        # their perfectly good link was invalid.
        self.assertEqual(_parse_embed_url("https://youtu.be/dQw4w9WgXcQ",
                                          "spotify")["type"], "youtube")

    def test_a_link_with_no_player_is_refused(self):
        self.assertFalse(_parse_embed_url("https://example.com/page")["valid"])
        self.assertFalse(_parse_embed_url("")["valid"])
        self.assertFalse(_parse_embed_url("javascript:alert(1)")["valid"])

    def test_a_channel_link_is_not_a_player(self):
        self.assertFalse(_parse_embed_url("https://www.youtube.com/@someartist")["valid"])


class TheEndpointTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("poster", "p@x.com", PW)
        self.c = APIClient()
        self.c.force_authenticate(self.u)
        self.post = Post.objects.create(author=self.u, title="A post")

    def test_an_embed_carries_its_own_size(self):
        # So the client sizes the frame from the same place the widget board
        # does, rather than keeping its own table of provider heights.
        r = self.c.post(URL, {"post_id": self.post.id,
                              "url": "https://youtu.be/dQw4w9WgXcQ"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        embed = r.data["embeds"][0]
        self.assertEqual(embed["type"], "youtube")
        self.assertEqual(embed["aspect"], "16/9")
        self.assertIn("youtube-nocookie.com/embed/", embed["url"])

    def test_a_bar_player_gets_a_height_instead_of_an_aspect(self):
        r = self.c.post(URL, {"post_id": self.post.id,
                              "url": "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"},
                        format="json")
        self.assertEqual(r.data["embeds"][0]["height"], 152)
        self.assertEqual(r.data["embeds"][0]["aspect"], "")

    def test_the_refusal_names_what_does_work(self):
        # "invalid youtube URL" on a link that was never YouTube is a refusal
        # that helps nobody.
        r = self.c.post(URL, {"post_id": self.post.id,
                              "url": "https://example.com/thing"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["players"], PLAYER_LABELS)
        self.assertIn("Apple Music", r.data["detail"])

    def test_the_title_falls_back_to_the_provider_not_the_type_key(self):
        r = self.c.post(URL, {"post_id": self.post.id,
                              "url": "https://music.apple.com/us/album/thriller/1234"},
                        format="json")
        self.assertEqual(r.data["embeds"][0]["title"], "Apple Music")

    def test_you_can_only_embed_on_your_own_post(self):
        other = User.objects.create_user("other", "o@x.com", PW)
        theirs = Post.objects.create(author=other, title="Theirs")
        r = self.c.post(URL, {"post_id": theirs.id,
                              "url": "https://youtu.be/dQw4w9WgXcQ"}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_the_tier_limit_still_holds(self):
        lim = membership_for(self.u)
        for i in range(3):
            self.c.post(URL, {"post_id": self.post.id,
                              "url": f"https://vimeo.com/12345{i}789"}, format="json")
        r = self.c.post(URL, {"post_id": self.post.id,
                              "url": "https://vimeo.com/999888777"}, format="json")
        self.assertEqual(r.status_code, 403, r.content)
