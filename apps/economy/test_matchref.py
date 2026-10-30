"""Inspiration: a take heard against a reference, nothing kept, lyrics as direction only."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import matchref, models as m, vocalcoach as vc
from apps.economy.instruments import scores_for
from apps.economy.models import wallet_for
from apps.economy.test_vocalcoach import fake_gemini

User = get_user_model()
REPLY = {
    "unscorable": None, "closeness": 62, "closeness_why": "Cadence close, low end thin.",
    "scores": {k: {"take": 6, "reference": 8} for k in scores_for("rapz")},
    "summary": "Low end is the gap.", "keep": "Your pocket.",
    "eq": [{"region": "low", "direction": "more", "what": "thin", "how": "+3dB at 100Hz"},
           {"region": "bogus", "direction": "more"}, {"region": "air", "direction": "sideways"}],
    "how_to": [{"what": "Weight", "why": "w", "how": "h"}],
    "lyric_direction": "Short punchy bars, internal rhyme.", "invented": "x",
}


def f(name):
    return SimpleUploadedFile(name, b"RIFFxxxxWAVE" * 50, content_type="audio/wav")


class InspirationTests(TestCase):
    def setUp(self):
        self.c = APIClient()
        self.u = User.objects.create_user("i", "i@e.com", "pw12345678")
        self.c.force_authenticate(self.u)
        w = wallet_for(self.u); w.money_cents = 10000; w.save()

    def _post(self, reply=REPLY, **files):
        with patch("apps.economy.matchref._key", return_value="k"), \
             patch("apps.economy.vocalcoach._key", return_value="k"), \
             patch("apps.economy.gemini.requests.post", return_value=fake_gemini(reply)):
            return self.c.post("/api/rapz/match/", files or {"take": f("t.wav"), "reference": f("r.wav")},
                               format="multipart")

    def test_price_is_stated_before_anything_is_sent(self):
        r = self.c.get("/api/rapz/match/")
        self.assertEqual(r.json()["feature"], "Inspiration")
        self.assertFalse(r.json()["charged_on_failure"])

    def test_reply_is_whitelisted_and_nothing_is_kept(self):
        before = {n: getattr(m, n).objects.count() for n in ("TakeScore", "Upload", "Post") if hasattr(m, n)}
        r = self._post()
        self.assertEqual(r.status_code, 200, r.content)
        j = r.json()
        self.assertEqual([e["region"] for e in j["eq"]], ["low"])
        self.assertEqual(j["eq"][0]["hz"], "60-250 Hz")
        self.assertNotIn("invented", j)
        self.assertEqual(j["lyric_direction"], REPLY["lyric_direction"])
        self.assertEqual(before, {n: getattr(m, n).objects.count() for n in before})

    def test_needs_both_files(self):
        r = self._post(take=f("t.wav"))
        self.assertEqual(r.status_code, 400)

    def test_unreadable_reply_is_not_charged(self):
        w0 = wallet_for(self.u).money_cents
        r = self._post(reply={"closeness": None})
        self.assertEqual(r.status_code, 502)
        self.assertEqual(wallet_for(self.u).money_cents, w0)


class InspirationFromPostsTests(TestCase):
    """Either side can already be on the platform — a post, a FileZ upload — through the coach's own
    lookups, so view rights and ownership are the coach's rules. A post costs ⚡ once."""

    def setUp(self):
        self.c = APIClient()
        self.me = User.objects.create_user("me", "me@e.com", "pw12345678")
        self.famous = User.objects.create_user("famous", "f@e.com", "pw12345678")
        self.c.force_authenticate(self.me)
        w = wallet_for(self.me); w.money_cents = 10000; w.energy = 1000; w.save()
        self.cost = vc.coach_post_energy(self.me)

    def stored_post(self, owner, title="Song", visibility="public"):
        up = m.Upload.objects.create(
            user=owner, name=f"{title}.wav", size_bytes=600, content_type="audio/wav",
            file=SimpleUploadedFile(f"{title}.wav", b"RIFFxxxxWAVE" * 50, content_type="audio/wav"))
        post = m.Post.objects.create(author=owner, title=title, media_type="audio",
                                     media_url=up.file.url, visibility=visibility)
        return post, up

    def run_match(self, data, reply=REPLY):
        with patch("apps.economy.matchref._key", return_value="k"), \
             patch("apps.economy.vocalcoach._key", return_value="k"), \
             patch("apps.economy.gemini.requests.post", return_value=fake_gemini(reply)) as call:
            r = self.c.post("/api/rapz/match/", data, format="multipart")
        self.last_call = call
        return r

    def energy(self):
        return wallet_for(self.me).energy

    def baseline(self):
        """The ⚡ every AI run already takes (`_take_ai_energy`), learned from a file-vs-file run so the
        post cost is measured on top of it rather than assumed to be the whole difference."""
        r = self.run_match({"take": f("b.wav"), "reference": f("c.wav")})
        self.assertEqual(r.status_code, 200, r.content)
        spent = 1000 - self.energy()
        w = wallet_for(self.me); w.energy = 1000; w.save()
        return spent

    def test_the_price_of_a_post_is_stated_before_the_button(self):
        j = self.c.get("/api/rapz/match/").json()
        self.assertEqual(j["post_energy_cost"], self.cost)
        self.assertIn(f"{self.cost} ⚡", j["post_note"])
        self.assertIn("post", j["reference_sources"])
        self.assertNotIn("journal", j["reference_sources"])

    def test_a_famous_example_is_any_post_you_may_view(self):
        base = self.baseline()
        ref, _ = self.stored_post(self.famous, "Famous")
        r = self.run_match({"take": f("t.wav"), "reference_post_id": ref.id})
        self.assertEqual(r.status_code, 200, r.content)
        j = r.json()
        self.assertEqual(j["sources"]["reference"], {"kind": "post", "id": ref.id, "title": "Famous", "author": "famous"})
        self.assertEqual(j["sources"]["take"]["kind"], "file")
        self.assertEqual(j["energy_cost"], self.cost)
        self.assertEqual(1000 - self.energy(), base + self.cost)

    def test_nothing_is_written_on_the_post_that_was_used(self):
        ref, _ = self.stored_post(self.famous, "Famous")
        before = m.Post.objects.get(pk=ref.pk).score
        self.run_match({"take": f("t.wav"), "reference_post_id": ref.id})
        self.assertEqual(m.Post.objects.get(pk=ref.pk).score, before)
        self.assertEqual(m.Upload.objects.count(), 1)           # no copy of the reference was kept

    def test_your_own_rapz_post_can_be_the_take(self):
        base = self.baseline()
        mine, _ = self.stored_post(self.me, "My verse")
        r = self.run_match({"take_post_id": mine.id, "reference": f("r.wav")})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["sources"]["take"]["title"], "My verse")
        self.assertEqual(1000 - self.energy(), base + self.cost)

    def test_two_posts_cost_the_energy_once(self):
        base = self.baseline()
        mine, _ = self.stored_post(self.me, "Mine")
        ref, _ = self.stored_post(self.famous, "Famous")
        r = self.run_match({"take_post_id": mine.id, "reference_post_id": ref.id})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(1000 - self.energy(), base + self.cost)       # once, not twice

    def test_files_cost_no_post_energy(self):
        r = self.run_match({"take": f("t.wav"), "reference": f("r.wav")})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["energy_cost"], 0)

    def test_a_post_you_may_not_view_is_refused_and_nothing_runs(self):
        hidden, _ = self.stored_post(self.famous, "Private", visibility="private")
        r = self.run_match({"take": f("t.wav"), "reference_post_id": hidden.id})
        self.assertEqual(r.status_code, 403)
        self.last_call.assert_not_called()
        self.assertEqual(self.energy(), 1000)

    def test_not_enough_energy_says_so_before_the_model_runs(self):
        ref, _ = self.stored_post(self.famous)
        w = wallet_for(self.me); w.energy = self.cost - 1; w.save()
        r = self.run_match({"take": f("t.wav"), "reference_post_id": ref.id})
        self.assertEqual(r.status_code, 402)
        self.assertEqual(r.json()["resource"], "energy")
        self.last_call.assert_not_called()

    def test_a_failed_comparison_costs_no_energy(self):
        ref, _ = self.stored_post(self.famous)
        r = self.run_match({"take": f("t.wav"), "reference_post_id": ref.id}, reply={"closeness": None})
        self.assertEqual(r.status_code, 502)
        self.assertEqual(self.energy(), 1000)

    def test_the_same_post_on_both_sides_is_refused(self):
        mine, _ = self.stored_post(self.me)
        r = self.run_match({"take_post_id": mine.id, "reference_post_id": mine.id})
        self.assertEqual(r.status_code, 400)

    def test_a_filez_upload_of_your_own_works_and_costs_no_post_energy(self):
        _, up = self.stored_post(self.me, "Mine")
        r = self.run_match({"take_upload_id": up.id, "reference": f("r.wav")})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["sources"]["take"]["kind"], "upload")
        self.assertEqual(r.json()["energy_cost"], 0)

    def test_somebody_elses_upload_is_not_reachable_by_id(self):
        _, theirs = self.stored_post(self.famous, "Theirs")
        r = self.run_match({"take": f("t.wav"), "reference_upload_id": theirs.id})
        self.assertEqual(r.status_code, 404)

    def test_a_recording_gone_from_storage_is_a_410_and_is_written_down(self):
        ref, up = self.stored_post(self.famous, "Gone")
        up.file.delete(save=False)
        r = self.run_match({"take": f("t.wav"), "reference_post_id": ref.id})
        self.assertEqual(r.status_code, 410, r.content)
        self.assertTrue(r.json()["take_missing"])
        self.assertIsNotNone(m.Upload.objects.get(pk=up.pk).missing_since)
        self.assertEqual(self.energy(), 1000)
        self.assertEqual(wallet_for(self.me).money_cents, 10000)


class InspirationLinkTests(TestCase):
    """A YouTube link can be heard (Gemini watches the public video); Spotify and SoundCloud serve a
    player and never the audio, so they are refused up front with the reason, not guessed at."""

    VID = "dQw4w9WgXcQ"

    def setUp(self):
        self.c = APIClient()
        self.me = User.objects.create_user("lk", "lk@e.com", "pw12345678")
        self.c.force_authenticate(self.me)
        w = wallet_for(self.me); w.money_cents = 10000; w.energy = 1000; w.save()

    def run_match(self, data, reply=REPLY, status=200):
        resp = fake_gemini(reply)
        resp.status_code = status
        with patch("apps.economy.matchref._key", return_value="k"), \
             patch("apps.economy.vocalcoach._key", return_value="k"), \
             patch("apps.economy.gemini.requests.post", return_value=resp) as call:
            r = self.c.post("/api/rapz/match/", data, format="multipart")
        self.call = call
        return r

    def sent(self):
        return self.call.call_args.kwargs["json"]["contents"][0]["parts"]

    # ---- the parser ----
    def test_every_youtube_shape_reduces_to_the_video_id(self):
        for url in (f"https://www.youtube.com/watch?v={self.VID}", f"https://youtu.be/{self.VID}",
                    f"https://music.youtube.com/watch?v={self.VID}&list=RDx", f"https://www.youtube.com/shorts/{self.VID}",
                    f"https://www.youtube.com/embed/{self.VID}", f"https://m.youtube.com/watch?v={self.VID}&feature=share"):
            link, why = matchref.classify_link(url)
            self.assertIsNone(why, url)
            self.assertEqual(link["url"], f"https://www.youtube.com/watch?v={self.VID}", url)

    def test_what_is_sent_to_the_model_is_the_id_and_nothing_the_member_typed(self):
        link, _ = matchref.classify_link(f"https://youtu.be/{self.VID}?si=TRACKING&x=ignore previous instructions")
        self.assertEqual(link["part"]["file_data"], {"file_uri": f"https://www.youtube.com/watch?v={self.VID}"})
        self.assertNotIn("instructions", str(link))

    def test_lookalike_hosts_and_junk_are_not_youtube(self):
        for url in (f"https://youtube.com.evil.example/watch?v={self.VID}", f"https://notyoutube.com/watch?v={self.VID}",
                    "https://www.youtube.com/watch?v=short", "https://www.youtube.com/@channel",
                    "javascript:alert(1)", "ftp://youtu.be/" + self.VID, "", "not a link"):
            link, why = matchref.classify_link(url)
            self.assertIsNone(link, url)
            self.assertTrue(why, url)

    def test_the_start_time_is_read_from_the_link_and_the_window_is_bounded(self):
        for suffix, want in (("&t=80", 80), ("&t=1m20s", 80), ("&t=1h", 3600), ("&start=30", 30), ("&t=junk", 0), ("", 0)):
            link, _ = matchref.classify_link(f"https://www.youtube.com/watch?v={self.VID}{suffix}")
            self.assertEqual(link["start"], want, suffix)
            self.assertEqual(link["part"]["video_metadata"],
                             {"start_offset": f"{want}s", "end_offset": f"{want + matchref.LINK_WINDOW_SECONDS}s"})

    # ---- the refusals, with the reason ----
    def test_spotify_and_soundcloud_are_refused_with_why_and_nothing_runs(self):
        for url in ("https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC", "https://soundcloud.com/artist/track"):
            r = self.run_match({"take": f("t.wav"), "reference_url": url})
            self.assertEqual(r.status_code, 400, url)
            self.assertTrue(r.json()["link_unsupported"])
            self.assertIn("never the audio", r.json()["detail"])
            self.call.assert_not_called()

    def test_the_screen_is_told_which_links_work_before_anything_is_pasted(self):
        j = self.c.get("/api/rapz/match/").json()
        by = {x["provider"]: x for x in j["link_sources"]}
        self.assertTrue(by["youtube"]["ok"])
        self.assertFalse(by["spotify"]["ok"])
        self.assertIn("never the audio", by["spotify"]["why"])
        self.assertFalse(by["soundcloud"]["ok"])
        self.assertEqual(j["link_window_seconds"], matchref.LINK_WINDOW_SECONDS)
        self.assertIn("link", j["reference_sources"])

    # ---- the run ----
    def test_a_youtube_reference_is_sent_by_address_and_costs_no_post_energy(self):
        r = self.run_match({"take": f("t.wav"), "reference_url": f"https://youtu.be/{self.VID}?t=75"})
        self.assertEqual(r.status_code, 200, r.content)
        ref_part = self.sent()[4]
        self.assertEqual(ref_part["file_data"]["file_uri"], f"https://www.youtube.com/watch?v={self.VID}")
        self.assertEqual(ref_part["video_metadata"]["start_offset"], "75s")
        self.assertIn("section of a video", self.sent()[0]["text"])
        j = r.json()
        self.assertEqual(j["energy_cost"], 0)
        self.assertEqual(j["sources"]["reference"]["kind"], "link")
        self.assertEqual(j["sources"]["reference"]["start_seconds"], 75)

    def test_your_own_youtube_work_can_be_the_take(self):
        r = self.run_match({"take_url": f"https://youtu.be/{self.VID}", "reference": f("r.wav")})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["sources"]["take"]["provider"], "youtube")

    def test_nothing_is_kept(self):
        before = (m.Upload.objects.count(), m.Post.objects.count())
        self.run_match({"take": f("t.wav"), "reference_url": f"https://youtu.be/{self.VID}"})
        self.assertEqual(before, (m.Upload.objects.count(), m.Post.objects.count()))

    def test_a_video_the_coach_cannot_open_says_why_and_is_not_charged(self):
        w0 = wallet_for(self.me).money_cents
        r = self.run_match({"take": f("t.wav"), "reference_url": f"https://youtu.be/{self.VID}"}, reply={"error": "x"}, status=400)
        self.assertEqual(r.status_code, 502)
        self.assertTrue(r.json()["link_unreachable"])
        self.assertIn("public", r.json()["detail"])
        self.assertEqual(wallet_for(self.me).money_cents, w0)


class InspirationElsewhereTests(TestCase):
    def setUp(self):
        self.c = APIClient()
        self.u = User.objects.create_user("j", "j@e.com", "pw12345678")
        self.c.force_authenticate(self.u)
        w = wallet_for(self.u); w.money_cents = 10000; w.save()

    def test_instrumental_setup_is_validated(self):
        from apps.economy.instrumentalz import clean_inspiration
        out = clean_inspiration({"bpm": 999, "key": "Zz", "instruments": ["drums", "kazoo"], "bars": 5,
                                 "brief": "b"})
        self.assertEqual((out["bpm"], out["key"], out["instruments"], out["bars"]), (200, "", ["drums"], 4))
        self.assertIsNone(clean_inspiration({"bpm": 90, "instruments": ["kazoo"]}))

    def test_instrumental_inspiration_endpoint(self):
        reply = {"unscorable": None, "genre": "trap", "bpm": 140, "key": "A minor",
                 "instruments": ["drums", "bass"], "bars": 8, "brief": "dark", "feel": "f"}
        with patch("apps.economy.instrumentalz._key", return_value="k"), \
             patch("apps.economy.vocalcoach._key", return_value="k"), \
             patch("apps.economy.gemini.requests.post", return_value=fake_gemini(reply)):
            r = self.c.post("/api/economy/instrumentalz/inspiration/",
                            {"reference": f("r.wav"), "lyrics": "my words"}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["bpm"], 140)

    def test_image_inspiration_needs_a_picture(self):
        with patch("apps.economy.gemini._key", return_value="k"):
            r = self.c.post("/api/economy/gemini/image/", {"prompt": "cover", "inspiration": "1"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("inspiration_note", self.c.get("/api/economy/gemini/image/").json())


class SentenceInspirationTests(TestCase):
    def setUp(self):
        self.c = APIClient()
        self.u = User.objects.create_user("k", "k@e.com", "pw12345678")
        self.c.force_authenticate(self.u)
        w = wallet_for(self.u); w.money_cents = 10000; w.save()

    def test_depth_fixer_exists_and_finds_feelz(self):
        from apps.economy import sentencez
        self.assertEqual(sentencez.FIXER_FOR_DIM["feelz"], "depth")

    def test_direction_for_a_fixer(self):
        reply = {"unscorable": None, "direction": "Setup then twist; plain words.", "moves": ["reversal"]}
        with patch("apps.economy.sentencez._key", return_value="k"), \
             patch("apps.economy.vocalcoach._key", return_value="k"), \
             patch("apps.economy.gemini.requests.post", return_value=fake_gemini(reply)):
            r = self.c.post("/api/economy/sentencez/inspiration/",
                            {"reference": f("r.wav"), "kind": "punchlines"}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["moves"], ["reversal"])

    def test_refuses_a_contract_kind_and_missing_song(self):
        self.assertEqual(self.c.post("/api/economy/sentencez/inspiration/", {"kind": "punchlines"},
                                     format="multipart").status_code, 400)
        self.assertEqual(self.c.post("/api/economy/sentencez/inspiration/",
                                     {"reference": f("r.wav"), "kind": "contract"},
                                     format="multipart").status_code, 400)


class WitDepthTests(TestCase):
    def test_opt_in_only_where_there_are_words(self):
        from apps.economy.instruments import prompt_for, scores_for
        self.assertNotIn("wit", scores_for("rapz"))
        self.assertIn("wit", scores_for("rapz", extras=("wit",)))
        self.assertNotIn("wit", scores_for("drumz", extras=("wit",)))
        self.assertIn('"depth"', prompt_for("singz", "pop", "x", "builder", extras=("depth",)))
        self.assertNotIn("wit_note", prompt_for("singz", "pop", "x", "builder"))

    def test_counted_only_when_opted_in(self):
        from apps.economy import vocalcoach as vc
        from apps.economy.instruments import scores_for
        base = {k: 6 for k in scores_for("rapz")}
        good = {**GOODISH, "scores": {**base, "wit": 10, "depth": 10}, "wit_note": "n"}
        def run(counted):
            with patch("apps.economy.vocalcoach._key", return_value="k"), \
                 patch("apps.economy.gemini.requests.post", return_value=fake_gemini(good)):
                out, err = vc.score_take("rapz", f("t.wav"), "audio/wav", genre="trap", target=None,
                                         difficulty="builder", think=False,
                                         extras=("wit", "depth"), counted=counted)
            self.assertIsNone(err)
            return out
        beside, inside = run(()), run(("wit",))
        self.assertEqual(beside["scores"]["wit"], 10)
        self.assertEqual(beside["counted_extras"], [])
        self.assertEqual(inside["counted_extras"], ["wit"])
        self.assertGreater(inside["score_exact"], beside["score_exact"])


from apps.economy.test_vocalcoach import GOOD as GOODISH  # noqa: E402


class BothTakesAreRatedAndComparedTests(TestCase):
    """Corey: Inspiration must rate and compare both takes. The model rates both on one scale;
    the server does the subtraction."""

    def test_each_side_gets_an_overall_and_the_gap_is_server_arithmetic(self):
        from apps.economy.matchref import clean_reply
        keys = list(scores_for("rapz"))
        scores = {k: {"take": 6, "reference": 8} for k in keys}
        scores[keys[0]] = {"take": 9, "reference": 7}
        scores[keys[1]] = {"take": 5, "reference": 5}
        out = clean_reply({**REPLY, "scores": scores, "overall": {"take": 6, "reference": 9, "take_why": "pocket",
                                                                   "reference_why": "breath control", "x": 1}}, "rapz")
        self.assertEqual(out["overall"], {"take": 6, "reference": 9, "take_why": "pocket", "reference_why": "breath control"})
        c = out["compare"]
        self.assertEqual((c["take_leads"], c["even"], c["reference_leads"]), (1, 1, len(keys) - 2))
        self.assertEqual((c["overall_gap"], c["overall_leads"]), (-3, "reference"))
        self.assertEqual(c["closest"], keys[0])
        self.assertEqual(c["dimensions"][0], {"key": keys[0], "take": 9, "reference": 7, "gap": 2, "leads": "take"})

    def test_half_an_overall_is_no_overall(self):
        from apps.economy.matchref import clean_reply
        out = clean_reply({**REPLY, "overall": {"take": 7}}, "rapz")
        self.assertIsNone(out["overall"])
        self.assertIsNone(out["compare"]["overall_leads"])

    def test_the_take_ahead_everywhere_has_no_widest_gap(self):
        from apps.economy.matchref import compare
        c = compare({"flow": {"take": 9, "reference": 6}}, None)
        self.assertIsNone(c["widest"])

    def test_the_prompt_asks_for_both_on_one_scale(self):
        from apps.economy.matchref import _prompt
        p = _prompt("rapz", "trap")
        self.assertIn("Rate BOTH recordings", p)
        self.assertIn('"overall": {"take"', p)
        self.assertIn("SAME 1-10 scale", p)
