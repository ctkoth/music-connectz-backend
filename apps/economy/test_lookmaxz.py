"""LookmaxZ — the adult wall around the whole screen, server arithmetic, a shop the
model cannot write into, and marketplaces that the tier orders but never removes."""
import inspect
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import lookmaxz as lm
from apps.economy.models import (TIER_STATZ, LookmaxPrefs, award_promptz,
                                 membership_for, profile_for)

User = get_user_model()
URL = "/api/economy/lookmaxz/"


def reply(**over):
    base = {
        "unreadable": None, "photo_quality": 8, "verdict": "Tidy.", "working": ["Good light."],
        "sectors": {
            "face": {"factors": {"hair": 8, "facial_hair": 4, "brows": None}, "advice": ["Trim the neckline."]},
            "skin": {"factors": {"texture": 6, "hydration": 3, "blemishes": 8, "sun_care": 9, "evenness": 7},
                     "advice": ["Moisturise daily."]},
            "teeth": {"factors": {"staining": 5, "cleanliness": 8, "gums": None}, "advice": []},
            "styling": {"factors": {"fit": 9, "colour": 9, "condition": 9}, "advice": []},
        },
    }
    base.update(over)
    return base


def photo():
    return SimpleUploadedFile("me.jpg", b"0" * 1000, content_type="image/jpeg")


class Base(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("m", "m@e.com", "hunter2hunter2")
        membership_for(self.user)
        award_promptz(self.user, 1000)
        self.c = APIClient()
        self.c.force_authenticate(self.user)

    def verify(self):
        p = profile_for(self.user)
        p.verified_18plus = True
        p.save(update_fields=["verified_18plus"])

    def statz(self):
        m = membership_for(self.user)
        m.tier = TIER_STATZ
        m.save()

    def post(self, parsed=None, **extra):
        with patch.object(lm, "generate_content") as g, patch.object(lm, "_key", return_value="k"):
            import json

            class R:
                status_code = 200

                def json(self_):
                    return {"candidates": [{"content": {"parts": [{"text": json.dumps(parsed or reply())}]}}]}
            g.return_value = (R(), ["m"])
            r = self.c.post(URL, {"photo": photo(), "confirm_self": "true", **extra}, format="multipart")
            return r


class TheAdultWallTests(Base):
    def test_unverified_gets_a_locked_sentence_and_nothing_else(self):
        d = self.c.get(URL).json()
        self.assertIn("locked", d)
        self.assertNotIn("markets", d)
        self.assertNotIn("body", d)

    def test_unverified_cannot_post_browse_or_set_markets(self):
        self.assertEqual(self.post().status_code, 403)
        self.assertEqual(self.c.get(URL + "shop/").status_code, 403)
        self.assertEqual(self.c.get(URL + "markets/").status_code, 403)

    def test_self_attestation_is_required(self):
        self.verify()
        r = self.c.post(URL, {"photo": photo()}, format="multipart")
        self.assertEqual(r.status_code, 400)


class TheReadingTests(Base):
    def setUp(self):
        super().setUp()
        self.verify()

    def test_sector_score_is_the_mean_of_scored_factors_and_none_stays_none(self):
        d = self.post().json()
        self.assertEqual(d["sectors"]["face"]["score"], 6.0)          # (8+4)/2, brows None ignored
        self.assertIsNone(d["sectors"]["face"]["scores"]["brows"])
        self.assertEqual(d["sectors"]["skin"]["score"], 6.6)

    def test_overall_is_the_mean_of_photo_sectors_and_body_is_not_in_it(self):
        d = self.post().json()
        photo_scores = [d["sectors"][k]["score"] for k in lm.PHOTO_SECTORS]
        self.assertEqual(d["overall"], round(sum(photo_scores) / len(photo_scores), 1))

    def test_an_undeclared_sector_or_factor_from_the_model_is_dropped(self):
        r = reply()
        r["sectors"]["skin"]["factors"]["bone_structure"] = 2
        r["sectors"]["jawline"] = {"factors": {"x": 1}}
        d = self.post(r).json()
        self.assertNotIn("jawline", d["sectors"])
        self.assertNotIn("bone_structure", d["sectors"]["skin"]["scores"])

    def test_only_asked_for_sectors_are_read(self):
        d = self.post(sectors="skin").json()
        self.assertIn("skin", d["sectors"])
        self.assertNotIn("teeth", d["sectors"])

    def test_charged_once_per_run_not_per_sector(self):
        with patch("apps.economy.lookmaxz_view.charge_ai_usage") as charge:
            d = self.post().json()
        self.assertTrue(d["charged"])
        self.assertEqual(charge.call_count, 1)

    def test_unreadable_is_not_charged(self):
        with patch("apps.economy.lookmaxz_view.charge_ai_usage") as charge:
            d = self.post(reply(unreadable="Too dark.")).json()
        charge.assert_not_called()
        self.assertFalse(d["charged"])
        self.assertEqual(d["unreadable"], "Too dark.")

    def test_nothing_scorable_is_not_charged(self):
        empty = reply()
        for s in empty["sectors"].values():
            s["factors"] = {k: None for k in s["factors"]}
        with patch("apps.economy.lookmaxz_view.charge_ai_usage") as charge:
            d = self.post(empty).json()
        charge.assert_not_called()
        self.assertTrue(d["unreadable"])

    def test_the_prompt_forbids_immutable_traits_and_brands(self):
        p = lm.build_prompt(lm.PHOTO_SECTORS)
        for word in ("bone structure", "body shape", "race", "null", "brands"):
            self.assertIn(word, p)

    def test_body_is_never_in_the_photo_prompt(self):
        self.assertNotIn("body", lm.PHOTO_SECTORS)
        self.assertEqual(lm.SECTORS["body"]["source"], "bodiez")


class TheShopTests(Base):
    def setUp(self):
        super().setUp()
        self.verify()

    def test_low_factors_get_products_lowest_first_and_high_ones_do_not(self):
        d = self.post().json()
        skin = d["shop"]["skin"]
        self.assertEqual(skin[0]["factor"], "hydration")               # 3 is the lowest
        self.assertNotIn("sun_care", [p["factor"] for p in skin])      # 9 is fine
        self.assertEqual(d["shop"]["styling"], [])                      # all 9s: nothing to sell

    def test_products_come_from_the_server_catalogue_not_the_model(self):
        r = reply()
        r["sectors"]["skin"]["advice"] = ["buy ACME serum at https://evil.example/x"]
        d = self.post(r).json()
        for items in d["shop"].values():
            for p in items:
                for link in p["links"]:
                    self.assertNotIn("evil", link["url"])
                    self.assertNotIn("ACME", link["url"])

    def test_default_markets_are_amazon_ebay_walmart_in_that_order(self):
        d = self.post().json()
        self.assertEqual([m["key"] for m in d["markets"]], ["amazon", "ebay", "walmart"])
        link = d["shop"]["skin"][0]["links"][0]["url"]
        self.assertTrue(link.startswith("https://www.amazon.com/s?k=ceramide+moisturizer"))

    def test_every_product_factor_is_a_declared_factor(self):
        for (sector, factor) in lm.PRODUCTS:
            self.assertIn(factor, lm.SECTORS[sector]["factors"])

    def test_every_factor_has_something_to_buy_or_says_nothing_to_sell(self):
        for sector, s in lm.SECTORS.items():
            for f in s["factors"]:
                self.assertTrue(lm.PRODUCTS.get((sector, f)), f"{sector}.{f}")

    def test_free_shelf_needs_no_reading(self):
        d = self.c.get(URL + "shop/?sector=teeth").json()
        self.assertEqual(list(d["shop"]), ["teeth"])
        self.assertTrue(d["shop"]["teeth"])

    def test_every_sector_states_when_to_see_a_professional(self):
        for s in lm.SECTORS.values():
            self.assertTrue(s["see_pro"])


class TheMarketplaceTests(Base):
    def setUp(self):
        super().setUp()
        self.verify()

    def put(self, markets):
        return self.c.put(URL + "markets/", {"markets": markets}, format="json")

    def test_free_member_is_told_where_the_way_up_is_and_keeps_the_three(self):
        r = self.put([{"name": "Mine", "url": "https://shop.example.com/s?q={q}"}])
        self.assertEqual(r.status_code, 403)
        self.assertEqual([m["key"] for m in r.json()["markets"]], ["amazon", "ebay", "walmart"])
        self.assertEqual(r.json()["upgrade"]["tab"], "membershipz")
        self.assertFalse(LookmaxPrefs.objects.exists())

    def test_statz_replaces_the_list_and_it_orders_the_shop(self):
        self.statz()
        r = self.put([{"key": "walmart"}, {"name": "Mine", "url": "https://shop.example.com/s?q={q}"}])
        self.assertEqual([m["key"] for m in r.json()["markets"]], ["walmart", "mine"])
        d = self.post().json()
        self.assertEqual(d["market_source"], "yours")
        self.assertEqual(d["shop"]["skin"][0]["links"][0]["key"], "walmart")

    def test_unsafe_templates_are_refused_and_counted(self):
        self.statz()
        bad = [
            {"name": "http", "url": "http://shop.example.com/s?q={q}"},
            {"name": "local", "url": "https://localhost/s?q={q}"},
            {"name": "ip", "url": "https://10.0.0.1/s?q={q}"},
            {"name": "creds", "url": "https://u:p@shop.example.com/s?q={q}"},
            {"name": "js", "url": "javascript:alert({q})"},
            {"name": "noq", "url": "https://shop.example.com/s"},
            {"name": "twoq", "url": "https://shop.example.com/{q}?q={q}"},
            {"name": "", "url": "https://shop.example.com/s?q={q}"},
        ]
        r = self.put(bad + [{"name": "ok", "url": "https://shop.example.com/s?q={q}"}])
        self.assertEqual(r.json()["dropped"], len(bad))
        self.assertEqual([m["key"] for m in r.json()["markets"]], ["ok"])

    def test_query_is_percent_encoded_so_it_cannot_break_out_of_the_template(self):
        m = {"key": "x", "name": "x", "url": "https://shop.example.com/s?q={q}"}
        self.assertEqual(lm.link_for(m, "a&b=c #d"), "https://shop.example.com/s?q=a%26b%3Dc+%23d")

    def test_capped(self):
        self.statz()
        many = [{"name": f"m{i}", "url": f"https://s{i}.example.com/?q={{q}}"} for i in range(20)]
        self.assertEqual(len(self.put(many).json()["markets"]), lm.CUSTOM_MAX)

    def test_a_lapse_keeps_the_saved_list_but_serves_the_defaults(self):
        self.statz()
        self.put([{"name": "Mine", "url": "https://shop.example.com/s?q={q}"}])
        m = membership_for(self.user)
        m.tier = "free"
        m.save()
        d = self.c.get(URL).json()
        self.assertEqual([x["key"] for x in d["markets"]], ["amazon", "ebay", "walmart"])
        self.assertEqual(d["saved"], 1)

    def test_a_poisoned_stored_row_is_repaired_on_read(self):
        self.statz()
        LookmaxPrefs.objects.create(user=self.user, markets=[
            {"name": "bad", "url": "http://x.example.com/?q={q}"},
            {"name": "ok", "url": "https://shop.example.com/s?q={q}"}])
        self.assertEqual([m["key"] for m in lm.markets_for(self.user)["markets"]], ["ok"])


class TheBodyTests(Base):
    def test_body_is_free_measured_and_none_without_history(self):
        self.verify()
        b = self.c.get(URL).json()["body"]
        self.assertIsNone(b["score"])
        self.assertEqual(b["open_in"]["tab"], "bodiez")

    def test_the_module_never_sends_a_body_photo_anywhere(self):
        self.assertNotIn("body", inspect.getsource(lm.build_prompt).split("sectors")[0].lower().replace("body shape", ""))


class TheImageMimeTests(TestCase):
    def test_a_photo_is_readable_where_the_audio_list_never_took_one(self):
        from apps.economy import attractivenessz as a
        from apps.economy.vocalcoach import gemini_mime
        self.assertIsNone(gemini_mime("image/jpeg"))          # why AttractivenessZ was dead
        for ct in ("image/jpeg", "image/jpg", "image/png", "image/webp", "image/heic"):
            self.assertTrue(a.gemini_image_mime(ct), ct)
        self.assertIsNone(a.gemini_image_mime("audio/mp3"))
        self.assertIsNone(a.gemini_image_mime("image/svg+xml"))


class TheFactorDescriptionTests(Base):
    def test_every_factor_says_what_why_and_how_and_nothing_extra_is_declared(self):
        declared = {(k, f) for k, s in lm.SECTORS.items() for f in s["factors"]}
        self.assertEqual(set(lm.FACTORS), declared)
        for key, info in lm.FACTORS.items():
            for part in ("what", "why", "how"):
                self.assertTrue(info[part].strip(), f"{key}.{part}")

    def test_the_screen_gets_them_before_any_photo_and_the_prompt_uses_the_same_words(self):
        self.verify()
        d = self.c.get(URL).json()
        info = d["sectors"]["skin"]["factor_info"]["hydration"]
        self.assertEqual(info["what"], lm.FACTORS[("skin", "hydration")]["what"])
        self.assertIn(info["what"], lm.build_prompt(["skin"]))
        self.assertTrue(d["scale"] and d["rating_rule"])

    def test_unverified_still_gets_the_explanations_but_no_data(self):
        d = self.c.get(URL).json()
        self.assertIn("factor_info", d["sectors"]["face"])
        self.assertNotIn("body", d)
