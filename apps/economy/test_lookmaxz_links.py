"""LookZMaxZ takes a photo by its image address from the social apps — only their own image
hosts, never a redirect, nothing kept — and a photo of anybody else gets Look Inspiration:
the look described, the person never scored."""
import json
from unittest.mock import MagicMock, patch

from apps.economy import imagelinks
from apps.economy import lookmaxz as lm
from apps.economy.test_lookmaxz import URL, Base, reply

IG = "https://scontent-lax3-1.cdninstagram.com/v/t51/me.jpg?stp=x"
INSPIRE = "/api/economy/lookmaxz/inspire/"


def image_response(status=200, ctype="image/jpeg", body=b"\xff\xd8" + b"0" * 500):
    r = MagicMock(status_code=status, headers={"Content-Type": ctype})
    r.iter_content.return_value = [body]
    r.__enter__ = lambda s: s
    r.__exit__ = lambda *a: False
    return r


def model(obj):
    class R:
        status_code = 200

        def json(self_):
            return {"candidates": [{"content": {"parts": [{"text": json.dumps(obj)}]}}]}
    return R()


class ClassifyTests(Base):
    def test_platform_image_hosts_pass_and_lookalikes_do_not(self):
        self.assertTrue(imagelinks.classify(IG)["ok"])
        self.assertTrue(imagelinks.classify("https://pbs.twimg.com/media/abc.jpg")["ok"])
        self.assertTrue(imagelinks.classify("https://scontent.xx.fbcdn.net/v/p.jpg")["ok"])
        for bad in ("https://evilcdninstagram.com/x.jpg", "https://cdninstagram.com.evil.example/x.jpg",
                    "http://pbs.twimg.com/x.jpg", "https://user:pw@pbs.twimg.com/x.jpg",
                    "https://pbs.twimg.com:8443/x.jpg", "https://127.0.0.1/x.jpg", "file:///etc/passwd"):
            self.assertFalse(imagelinks.classify(bad)["ok"], bad)

    def test_a_post_page_says_how_to_get_the_image_itself(self):
        c = imagelinks.classify("https://www.instagram.com/p/Cabc123/")
        self.assertFalse(c["ok"])
        self.assertIn("Copy image address", c["why"])
        self.assertIn("Instagram", c["why"])
        self.assertIn("X", imagelinks.classify("https://x.com/me/status/1")["why"])


class ReadingByLinkTests(Base):
    def setUp(self):
        super().setUp()
        self.verify()

    def read(self, url, fetched, parsed=None):
        with patch.object(imagelinks.requests, "get", return_value=fetched) as get, \
                patch.object(lm, "generate_content", return_value=(model(parsed or reply()), ["m"])), \
                patch.object(lm, "_key", return_value="k"):
            r = self.c.post(URL, {"photo_url": url, "confirm_self": "true"}, format="multipart")
        return r, get

    def test_an_instagram_image_address_is_read_once_without_following_redirects(self):
        r, get = self.read(IG, image_response())
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["charged"])
        self.assertIs(get.call_args.kwargs["allow_redirects"], False)

    def test_a_page_or_a_redirect_or_not_an_image_is_refused_and_not_charged(self):
        with patch("apps.economy.lookmaxz_view.charge_ai_usage") as charge:
            r, get = self.read("https://www.facebook.com/photo/?fbid=1", image_response())
            self.assertEqual(r.status_code, 400)
            get.assert_not_called()
            r, _ = self.read(IG, image_response(status=302))
            self.assertEqual(r.status_code, 400)
            r, _ = self.read(IG, image_response(ctype="text/html"))
            self.assertEqual(r.status_code, 400)
        charge.assert_not_called()

    def test_self_only_still_holds_for_a_link(self):
        with patch.object(imagelinks.requests, "get") as get:
            r = self.c.post(URL, {"photo_url": IG}, format="multipart")
        self.assertEqual(r.status_code, 400)
        self.assertIn("yourself", r.json()["detail"])
        get.assert_not_called()

    def test_get_says_which_apps_before_anything_is_pasted(self):
        d = self.c.get(URL).json()
        self.assertIn("Instagram", d["link_hosts"])
        self.assertIn("Look Inspiration", d["inspire"]["what"])


class InspirationTests(Base):
    def setUp(self):
        super().setUp()
        self.verify()

    def inspire(self, parsed):
        with patch.object(imagelinks.requests, "get", return_value=image_response()), \
                patch.object(lm, "generate_content", return_value=(model(parsed), ["m"])) as g, \
                patch.object(lm, "_key", return_value="k"), \
                patch("apps.economy.lookmaxz_view.charge_ai_usage") as charge:
            r = self.c.post(INSPIRE, {"photo_url": IG}, format="multipart")
        return r, g, charge

    def test_anybodys_photo_gets_the_look_described_and_no_number_survives(self):
        r, g, charge = self.inspire({"summary": "A textured crop and a clean fade.",
                                     "parts": {"hair": {"what": "Textured crop, skin fade", "how": ["Ask for a #0 fade"],
                                                        "score": 9},
                                               "jawline": {"what": "strong"},
                                               "styling": {"what": "Boxy overshirt", "how": ["Size up one"]}}})
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertEqual([p["key"] for p in d["parts"]], ["hair", "styling"])     # jawline is not a part
        self.assertNotIn("score", json.dumps(d["parts"]))
        self.assertIn("never the person", d["rule"])
        charge.assert_called_once()
        prompt = g.call_args.args[1]["contents"][0]["parts"][0]["text"]
        for line in ("NO score", "attractiveness", "who they are"):
            self.assertIn(line, prompt)

    def test_nothing_to_describe_is_not_charged(self):
        r, _, charge = self.inspire({"none": "It's a landscape."})
        self.assertEqual(r.json()["parts"], [])
        charge.assert_not_called()

    def test_inspiration_is_adults_only_too(self):
        from apps.economy.models import profile_for
        p = profile_for(self.user); p.verified_18plus = False; p.save(update_fields=["verified_18plus"])
        r, g, _ = self.inspire({"parts": {}})
        self.assertEqual(r.status_code, 403)
        g.assert_not_called()
