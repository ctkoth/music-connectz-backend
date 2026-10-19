"""IntelligenceZ hub: every app in it, what it costs BEFORE it is opened, and a
shelf of what the member made across all of them.

The hub quotes no number of its own — each price is read from the function the
app's own screen uses — so these tests pin that the two agree, that the hub
never grows a query per row, and that what it says is built is what LogicZ says
is built.
"""
import os
import tempfile
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy import intelligencez, videoz
from apps.economy.catalog import ai_cost, ai_model_for
from apps.economy.logicz import LOGICZ_TABS
from apps.economy.models import (Face, InstrumentalWork, MasterWork, OccOutput, SentenceWork,
                                 VideoWork, daily_prompt_covers, daily_prompt_state, membership_for,
                                 profile_for, wallet_for)

User = get_user_model()
URL = "/api/economy/intelligencez/"
PW = "pw12345!"

ORDER = ["sentenceconnectz", "occ", "instrumentalconnectz", "mixconnectz",
         "videoconnectz", "facez", "imageconnectz"]


def stamp(obj, minutes_ago):
    """created_at is auto_now_add; move it so 'newest first' is not a race."""
    type(obj).objects.filter(pk=obj.pk).update(created_at=timezone.now() - timedelta(minutes=minutes_ago))
    obj.refresh_from_db()
    return obj


class HubBase(TestCase):
    def setUp(self):
        self.me = User.objects.create_user("maker", "m@e.com", PW)
        self.c = APIClient()
        self.c.force_authenticate(self.me)

    def get(self):
        r = self.c.get(URL)
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def app(self, key):
        return next(a for a in self.get()["apps"] if a["key"] == key)


class ShapeTests(HubBase):
    def test_it_needs_a_sign_in(self):
        self.assertIn(APIClient().get(URL).status_code, (401, 403))

    def test_a_brand_new_account_with_nothing_attached_opens(self):
        fresh = User.objects.create_user("fresh", "f@e.com", PW)
        c = APIClient()
        c.force_authenticate(fresh)
        r = c.get(URL)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["recent"], [])

    def test_the_top_level_shape(self):
        d = self.get()
        self.assertEqual(set(d), {"tier", "apps", "recent", "daily"})
        self.assertEqual(set(d["daily"]), {"allowance", "used", "remaining"})

    def test_the_apps_come_in_the_stated_order(self):
        self.assertEqual([a["key"] for a in self.get()["apps"]], ORDER)

    def test_every_app_carries_the_same_keys(self):
        for a in self.get()["apps"]:
            self.assertEqual(set(a), {"key", "label", "emoji", "icon", "desc", "built", "tab",
                                      "configured", "in_app", "standalone", "price", "count"}, a["key"])
            self.assertTrue(a["label"] and a["emoji"] and a["icon"] and a["desc"], a["key"])

    def test_labels_icons_and_emoji(self):
        apps = {a["key"]: a for a in self.get()["apps"]}
        self.assertEqual({k: v["icon"] for k, v in apps.items()}, {
            "sentenceconnectz": "sentencez.png", "occ": "occ.png",
            "instrumentalconnectz": "instrumentalconnectz.png", "mixconnectz": "mixconnectz.png",
            "videoconnectz": "videoconnectz.png", "facez": "facez.png",
            "imageconnectz": "imageconnectz.png"})
        self.assertEqual([apps[k]["emoji"] for k in ORDER], ["✍️", "👁️", "🎹", "🎚️", "🎬", "🙂", "🖼️"])
        self.assertEqual(apps["mixconnectz"]["label"], "Mix ConnectZ")
        self.assertEqual(apps["imageconnectz"]["desc"], "Not built yet.")

    def test_everything_is_built_but_image_and_only_the_built_have_a_tab(self):
        for a in self.get()["apps"]:
            if a["key"] == "imageconnectz":
                self.assertFalse(a["built"])
                self.assertEqual(a["tab"], "", "a door to a screen that cannot do the thing is worse than none")
            else:
                self.assertTrue(a["built"], a["key"])
                self.assertEqual(a["tab"], a["key"])

    def test_which_apps_the_standalone_carries(self):
        got = {a["key"]: a["in_app"] for a in self.get()["apps"]}
        self.assertEqual(got, {"sentenceconnectz": True, "occ": True, "instrumentalconnectz": True,
                               "mixconnectz": True, "videoconnectz": False, "facez": False,
                               "imageconnectz": False})

    def test_standalone_is_the_same_answer_as_in_app(self):
        for a in self.get()["apps"]:
            self.assertEqual(a["standalone"], a["in_app"], a["key"])

    def test_video_is_kept_out_of_the_standalone_because_it_cannot_sell(self):
        # A fixed price with no free tier, in an app that has nothing to take
        # payment with, is a wall.
        v = self.app("videoconnectz")
        self.assertEqual(v["price"]["kind"], "fixed")
        self.assertFalse(v["in_app"])

    def test_the_hub_agrees_with_logicz_about_what_is_built(self):
        hub = {a["tab"] or a["key"]: a for a in self.get()["apps"]}
        logicz = next(t for t in LOGICZ_TABS if t["key"] == "intelligencez")
        by_tab = {a["tab"]: a for a in logicz["apps"] if a["tab"]}
        for key, row in by_tab.items():
            self.assertTrue(hub[key]["built"], key)
            self.assertTrue(row["built"], key)
        unbuilt = [a for a in logicz["apps"] if not a["built"]]
        self.assertEqual([a["name"] for a in unbuilt], ["Image ConnectZ"])
        self.assertEqual(unbuilt[0]["tab"], "")
        self.assertEqual(set(by_tab), {a["key"] for a in self.get()["apps"] if a["built"]})


class PriceTests(HubBase):
    def test_sentence_and_instrumental_quote_what_their_own_screens_quote(self):
        _, _, left = daily_prompt_state(self.me)
        cost = ai_cost("standard")
        for key in ("sentenceconnectz", "instrumentalconnectz"):
            self.assertEqual(self.app(key)["price"], {
                "kind": "prompt", "cost_cents": cost,
                "free_today": left > 0 and daily_prompt_covers(cost),
                "daily_remaining": left}, key)

    def test_the_apps_own_screens_say_the_same(self):
        from apps.economy import instrumentalz, sentencez
        with mock.patch.object(sentencez, "_key", return_value="k"), \
                mock.patch.object(instrumentalz, "_key", return_value="k"):
            s = self.c.get("/api/economy/sentencez/").json()
            i = self.c.get("/api/economy/instrumentalz/").json()
        for own, key in ((s, "sentenceconnectz"), (i, "instrumentalconnectz")):
            p = self.app(key)["price"]
            self.assertEqual((p["cost_cents"], p["free_today"], p["daily_remaining"]),
                             (own["cost_cents"], own["free_today"], own["daily_remaining"]), key)

    def test_a_spent_allowance_is_no_longer_free_today(self):
        allowance, _, _ = daily_prompt_state(self.me)
        w = wallet_for(self.me)
        w.prompts_used_today = allowance
        w.save()
        p = self.app("sentenceconnectz")["price"]
        self.assertFalse(p["free_today"])
        self.assertEqual(p["daily_remaining"], 0)
        self.assertEqual(self.get()["daily"], {"allowance": allowance, "used": allowance, "remaining": 0})

    def test_daily_is_the_prompt_state(self):
        allowance, used, left = daily_prompt_state(self.me)
        self.assertEqual(self.get()["daily"], {"allowance": allowance, "used": used, "remaining": left})

    def test_occ_is_priced_on_the_engine_the_member_chose(self):
        key, spec = ai_model_for(profile_for(self.me).ai_model, membership_for(self.me).tier)
        p = self.app("occ")["price"]
        self.assertEqual(p["kind"], "prompt")
        self.assertEqual(p["cost_cents"], spec["cost_cents"])
        self.assertEqual(p["engine"], spec["name"])
        # Haiku, the Free engine, sits under what one free prompt may cover.
        self.assertEqual(key, "haiku")
        self.assertTrue(p["free_today"])

    def test_occ_on_a_dear_engine_is_one_promptz_and_free_today_under_the_flat_rule(self):
        m = membership_for(self.me)
        m.tier = "statz"
        m.save()
        p = profile_for(self.me)
        p.ai_model = "opus"
        p.save()
        price = self.app("occ")["price"]
        self.assertEqual(price["engine"], "Opus")
        self.assertEqual(price["cost_cents"], 1)
        self.assertTrue(price["free_today"], "one task is one PromptZ, which a free daily prompt covers")
        self.assertGreater(price["daily_remaining"], 0)
        p.ai_model = "sonnet"
        p.save()
        self.assertEqual(self.app("occ")["price"]["cost_cents"], 1)

    def test_a_choice_above_the_tier_falls_back_rather_than_being_quoted(self):
        p = profile_for(self.me)
        p.ai_model = "fable"
        p.save()
        price = self.app("occ")["price"]
        self.assertEqual(price["engine"], "Haiku")

    def test_video_is_a_fixed_price(self):
        self.assertEqual(self.app("videoconnectz")["price"],
                         {"kind": "fixed", "cost_cents": videoz.price_cents()})
        with mock.patch.dict(os.environ, {"VIDEO_CONNECTZ_CENTS": "725"}):
            self.assertEqual(self.app("videoconnectz")["price"]["cost_cents"], 725)

    def test_mix_is_a_device_job_facez_is_free_and_image_has_no_price(self):
        self.assertEqual(self.app("mixconnectz")["price"], {"kind": "device"})
        self.assertEqual(self.app("facez")["price"], {"kind": "free"})
        self.assertIsNone(self.app("imageconnectz")["price"])

    def test_the_hub_charges_nothing(self):
        from apps.economy.models import Transaction
        before = (Transaction.objects.count(), wallet_for(self.me).promptz, wallet_for(self.me).spinaz)
        self.get()
        w = wallet_for(self.me)
        self.assertEqual((Transaction.objects.count(), w.promptz, w.spinaz), before)


class ConfiguredTests(HubBase):
    def test_the_gemini_apps_follow_the_gemini_key(self):
        with mock.patch.object(intelligencez, "_key", return_value=""):
            apps = {a["key"]: a["configured"] for a in self.get()["apps"]}
        for k in ("sentenceconnectz", "instrumentalconnectz", "videoconnectz"):
            self.assertFalse(apps[k], k)
        with mock.patch.object(intelligencez, "_key", return_value="k"):
            apps = {a["key"]: a["configured"] for a in self.get()["apps"]}
        for k in ("sentenceconnectz", "instrumentalconnectz", "videoconnectz"):
            self.assertTrue(apps[k], k)

    def test_mix_and_facez_need_no_key_and_image_is_not_there_to_configure(self):
        with mock.patch.object(intelligencez, "_key", return_value=""):
            apps = {a["key"]: a["configured"] for a in self.get()["apps"]}
        self.assertTrue(apps["mixconnectz"])
        self.assertTrue(apps["facez"])
        self.assertFalse(apps["imageconnectz"])

    def test_occ_follows_the_anthropic_key_the_chat_view_reads(self):
        fake = mock.MagicMock()
        with mock.patch.dict("sys.modules", {"anthropic": fake}):
            with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
                self.assertTrue(self.app("occ")["configured"])
            env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertFalse(self.app("occ")["configured"])

    def test_occ_without_the_package_is_not_configured_either(self):
        with mock.patch.dict("sys.modules", {"anthropic": None}):
            with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
                self.assertFalse(self.app("occ")["configured"])


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class CountTests(HubBase):
    def test_each_count_is_the_members_own_rows(self):
        other = User.objects.create_user("other", "o@e.com", PW)
        for u, n in ((self.me, 2), (other, 5)):
            for _ in range(n):
                SentenceWork.objects.create(user=u, kind="post", topic="t", text="x")
        InstrumentalWork.objects.create(user=self.me, genre="Trap", bpm=140, key="Cm")
        MasterWork.objects.create(user=self.me, title="m")
        MasterWork.objects.create(user=self.me, title="n")
        MasterWork.objects.create(user=self.me, title="o")
        VideoWork.objects.create(user=self.me, kind="music", prompt="p", status="pending")
        Face.objects.create(owner=self.me, image="facez/1/a.png")
        Face.objects.create(owner=other, image="facez/2/a.png")
        OccOutput.objects.create(user=self.me, title="w")
        got = {a["key"]: a["count"] for a in self.get()["apps"]}
        self.assertEqual(got, {"sentenceconnectz": 2, "occ": 1, "instrumentalconnectz": 1,
                               "mixconnectz": 3, "videoconnectz": 1, "facez": 1, "imageconnectz": 0})


class RecentTests(HubBase):
    def test_the_shelf_merges_every_app_newest_first(self):
        stamp(SentenceWork.objects.create(user=self.me, kind="resume", topic="Senior engineer at a label", text="x"), 50)
        stamp(InstrumentalWork.objects.create(user=self.me, genre="Trap", bpm=140, key="Cm"), 40)
        stamp(MasterWork.objects.create(user=self.me, title="Night drive"), 30)
        stamp(VideoWork.objects.create(user=self.me, kind="music", prompt="neon alley", status="done"), 20)
        stamp(OccOutput.objects.create(user=self.me, title="Release plan"), 10)
        recent = self.get()["recent"]
        self.assertEqual([r["app"] for r in recent],
                         ["occ", "videoconnectz", "mixconnectz", "instrumentalconnectz", "sentenceconnectz"])
        stamps = [r["created_at"] for r in recent]
        self.assertEqual(stamps, sorted(stamps, reverse=True))

    def test_every_row_says_what_it_is_and_where_to_open_it(self):
        s = stamp(SentenceWork.objects.create(user=self.me, kind="resume", topic="Senior engineer at a label", text="x"), 50)
        i = stamp(InstrumentalWork.objects.create(user=self.me, genre="Trap", bpm=140, key="Cm"), 40)
        m = stamp(MasterWork.objects.create(user=self.me, title="Night drive"), 30)
        v = stamp(VideoWork.objects.create(user=self.me, kind="music", prompt="neon alley", status="done"), 20)
        o = stamp(OccOutput.objects.create(user=self.me, title="Release plan"), 10)
        rows = {r["app"]: r for r in self.get()["recent"]}
        for r in rows.values():
            self.assertEqual(set(r), {"app", "id", "label", "created_at", "tab", "target"})
            self.assertEqual(r["tab"], r["app"])
        self.assertEqual(rows["sentenceconnectz"]["label"], "Resume · Senior engineer at a label")
        self.assertEqual(rows["instrumentalconnectz"]["label"], "Trap · Cm · 140 BPM")
        self.assertEqual(rows["mixconnectz"]["label"], "Night drive")
        self.assertEqual(rows["videoconnectz"]["label"], "Music video · neon alley")
        self.assertEqual(rows["occ"]["label"], "Release plan")
        self.assertEqual({k: r["target"] for k, r in rows.items()}, {
            "sentenceconnectz": "sentencez-recent", "instrumentalconnectz": "instrumental-recent",
            "mixconnectz": "mixz-recent", "videoconnectz": "videoz-recent", "occ": "occ-workz"})
        self.assertEqual({k: r["id"] for k, r in rows.items()}, {
            "sentenceconnectz": s.id, "instrumentalconnectz": i.id, "mixconnectz": m.id,
            "videoconnectz": v.id, "occ": o.id})

    def test_every_tab_on_the_shelf_is_an_app_the_hub_lists(self):
        MasterWork.objects.create(user=self.me, title="m")
        OccOutput.objects.create(user=self.me, title="w")
        d = self.get()
        keys = {a["key"] for a in d["apps"] if a["built"]}
        for r in d["recent"]:
            self.assertIn(r["tab"], keys)

    def test_a_render_that_is_not_finished_is_not_on_the_shelf(self):
        VideoWork.objects.create(user=self.me, kind="music", prompt="p", status="pending")
        VideoWork.objects.create(user=self.me, kind="music", prompt="p", status="failed")
        self.assertEqual(self.get()["recent"], [])
        # ...but both still count as the member's own work.
        self.assertEqual(self.app("videoconnectz")["count"], 2)

    def test_it_is_capped_at_twelve_and_keeps_the_newest_of_them_all(self):
        for n in range(15):
            stamp(MasterWork.objects.create(user=self.me, title=f"m{n}"), 100 - n)
        for n in range(15):
            stamp(OccOutput.objects.create(user=self.me, title=f"o{n}"), 5 + n)
        recent = self.get()["recent"]
        self.assertEqual(len(recent), 12)
        # The twelve newest overall are the OCC rows that are 5..16 minutes old.
        self.assertEqual({r["app"] for r in recent}, {"occ"})

    def test_it_is_only_your_own(self):
        other = User.objects.create_user("other", "o@e.com", PW)
        MasterWork.objects.create(user=other, title="theirs")
        SentenceWork.objects.create(user=other, kind="post", topic="theirs", text="x")
        self.assertEqual(self.get()["recent"], [])

    def test_a_kind_the_server_no_longer_knows_still_gets_a_label(self):
        SentenceWork.objects.create(user=self.me, kind="old_kind", topic="legacy", text="x")
        VideoWork.objects.create(user=self.me, kind="retired", prompt="p", status="done")
        labels = [r["label"] for r in self.get()["recent"]]
        self.assertTrue(any(l.startswith("Old Kind") for l in labels), labels)
        self.assertTrue(any(l.startswith("Retired") for l in labels), labels)

    def test_a_long_topic_is_shortened_not_sent_whole(self):
        SentenceWork.objects.create(user=self.me, kind="essay", topic="word " * 400, text="x" * 5000)
        label = self.get()["recent"][0]["label"]
        self.assertLess(len(label), 80)
        self.assertTrue(label.endswith("…"))


class QueryCountTests(HubBase):
    """The screen every IntelligenceZ visit starts on. A handful of queries,
    fixed — never one per piece a member has made."""

    CEILING = 24

    def count(self):
        with CaptureQueriesContext(connection) as q:
            self.assertEqual(self.c.get(URL).status_code, 200)
        return len(q)

    def fill(self, n):
        for i in range(n):
            SentenceWork.objects.create(user=self.me, kind="post", topic=f"t{i}", text="x" * 2000)
            InstrumentalWork.objects.create(user=self.me, genre="Trap", bpm=140, key="Cm")
            MasterWork.objects.create(user=self.me, title=f"m{i}")
            VideoWork.objects.create(user=self.me, kind="music", prompt="p", status="done")
            OccOutput.objects.create(user=self.me, title=f"o{i}")
            Face.objects.create(owner=self.me, image=f"facez/1/{i}.png")

    def test_the_cost_does_not_grow_with_what_the_member_has_made(self):
        self.count()                      # first touch creates the membership, wallet, profile
        empty = self.count()
        self.fill(1)
        one = self.count()
        self.fill(29)
        many = self.count()
        self.assertEqual(one, empty, "rows exist but the query count must not move")
        self.assertEqual(many, one, "thirty of each costs the same as one of each")

    def test_and_it_is_a_handful(self):
        self.fill(3)
        self.count()
        self.assertLessEqual(self.count(), self.CEILING)
