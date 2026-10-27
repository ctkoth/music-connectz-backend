"""Instrumental ConnectZ: validated notes, a real MIDI file, the price before
the run, no charge for an unusable answer, mood search for StatZ, and the
flat royalty when a loop is used."""
import json
import struct
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.economy import instrumentalz as iz
from apps.economy.models import CollabDeal, InstrumentalWork, Transaction, wallet_for

URL = "/api/economy/instrumentalz/"
LOOP = {"tracks": [
    {"instrument": "drums", "notes": [[36, 0, 0.5, 110], [38, 1, 0.5, 100], [42, 0.5, 0.25, 70]]},
    {"instrument": "bass", "notes": [[36, 0, 1, 100], [43, 2, 1, 90], [999, 0, 1, 90], [40, 99, 1, 90]]},
    {"instrument": "lead", "notes": [[72, 0, 1, 90]]},
]}


def reply(obj):
    r = MagicMock(status_code=200, text="ok")
    r.json.return_value = {"candidates": [{"content": {"parts": [{"text": json.dumps(obj)}]}}]}
    return r


def read_midi(data):
    """Minimal SMF reader: (format, ntracks, tpb, [[(tick, status), ...] per track])."""
    assert data[:4] == b"MThd"
    fmt, ntr, tpb = struct.unpack(">HHH", data[8:14])
    pos, tracks = 14, []
    for _ in range(ntr):
        assert data[pos:pos + 4] == b"MTrk"
        ln = struct.unpack(">I", data[pos + 4:pos + 8])[0]
        body, pos, i, tick, evs = data[pos + 8:pos + 8 + ln], pos + 8 + ln, 0, 0, []
        while i < len(body):
            d = 0
            while True:
                b = body[i]; i += 1; d = (d << 7) | (b & 0x7F)
                if not b & 0x80:
                    break
            tick += d
            st = body[i]
            if st == 0xFF:
                kind, n = body[i + 1], body[i + 2]
                evs.append((tick, ("meta", kind))); i += 3 + n
            elif st & 0xF0 == 0xC0:
                evs.append((tick, ("program", body[i + 1]))); i += 2
            else:
                evs.append((tick, (st & 0xF0, body[i + 1]))); i += 3
        tracks.append(evs)
    return fmt, ntr, tpb, tracks


class MidiTests(TestCase):
    def test_bad_notes_are_dropped_and_unrequested_parts_ignored(self):
        tracks = iz.clean_tracks(LOOP, ["drums", "bass"], 4)
        self.assertEqual([t["instrument"] for t in tracks], ["drums", "bass"])
        self.assertEqual(len(tracks[1]["notes"]), 2)  # pitch 999 and start 99 refused

    def test_the_file_is_a_real_format_1_midi(self):
        tracks = iz.clean_tracks(LOOP, ["drums", "bass"], 4)
        fmt, ntr, tpb, parsed = read_midi(iz.midi_bytes(tracks, 90, "A minor", "t"))
        self.assertEqual((fmt, ntr, tpb), (1, 3, 480))
        self.assertIn((0, ("meta", 0x51)), parsed[0])          # tempo
        self.assertTrue(all(ev[1] != ("meta", 0x2F) or ev is evs[-1] for evs in parsed for ev in evs))
        drum_on = [e for e in parsed[1] if e[1][0] == 0x90]
        self.assertEqual(len(drum_on), 3)
        self.assertIn(("program", 33), [e[1] for e in parsed[2]])  # bass program, not on drums

    def test_key_signatures(self):
        self.assertEqual(iz.key_signature("C major"), (0, 0))
        self.assertEqual(iz.key_signature("A minor"), (0, 1))
        self.assertEqual(iz.key_signature("Eb major"), (-3, 0))
        self.assertEqual(iz.key_signature("E minor"), (1, 1))
        for k in iz.KEY_NAMES:
            iz.key_signature(k)

    def test_the_flat_spelled_key_gets_the_flat_signature(self):
        # Eb minor is six FLATS (its relative major is Gb). It was +6, which is
        # D# minor: the same notes on a keyboard, a different (and unreadable)
        # key signature in a score.
        self.assertEqual(iz.key_signature("Eb minor"), (-6, 1))
        self.assertEqual(iz.key_signature("Gb major"), (-6, 0))
        # ...and the sharp spellings of the same pitches keep the sharp side.
        self.assertEqual(iz.key_signature("D# minor"), (6, 1))
        self.assertEqual(iz.key_signature("F# major"), (6, 0))
        # The rest of the minors in the list, so the fix moved nothing else.
        self.assertEqual(iz.key_signature("Bb minor"), (-5, 1))
        self.assertEqual(iz.key_signature("F# minor"), (3, 1))
        self.assertEqual(iz.key_signature("C# minor"), (4, 1))
        self.assertEqual(iz.key_signature("G# minor"), (5, 1))

    def test_the_midi_key_signature_byte_is_six_flats_for_eb_minor(self):
        tracks = iz.clean_tracks(LOOP, ["drums", "bass"], 4)
        data = iz.midi_bytes(tracks, 90, "Eb minor", "t")
        self.assertIn(b"\xff\x59\x02\xfa\x01", data)            # -6 as a signed byte, minor

    def test_every_key_has_a_mood_and_twenty_four_exist(self):
        self.assertEqual(len(iz.KEYS), 24)
        self.assertTrue(all(m and t for _, m, t in iz.KEYS))

    def test_mood_search_ranks_by_tags(self):
        keys = [r["key"] for r in iz.search_keys("dark and angry")]
        self.assertEqual(keys[0], "F minor")
        self.assertEqual(iz.search_keys(""), [])


@override_settings(OWNER_USERNAMES=["koth"], OWNER_EMAILS=[])
class EndpointTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user("koth", "o@e.com", "pw-Long-enough-1")
        self.user = User.objects.create_user("maker", "m@e.com", "pw-Long-enough-1")
        self.c = APIClient(); self.c.force_authenticate(self.user)

    def body(self, **kw):
        return {"genre": "boom bap", "instruments": ["drums", "bass"], "bpm": 90, "key": "A minor", "bars": 4, **kw}

    def test_price_keys_and_instruments_are_published_first(self):
        d = self.c.get(URL).json()
        self.assertIn("cost_cents", d)
        self.assertEqual(len(d["keys"]), 24)
        self.assertIn("drums", [i["id"] for i in d["instruments"]])
        self.assertFalse(d["mood_search"])

    @patch("apps.economy.instrumentalz._key", return_value="k")
    def test_compose_saves_and_downloads(self, _):
        with patch("apps.economy.gemini.requests.post", return_value=reply(LOOP)) as post:
            r = self.c.post(URL, self.body(), format="json")
        self.assertEqual(r.status_code, 201, r.content)
        sent = post.call_args.kwargs["json"]
        self.assertEqual(sent["generationConfig"]["responseMimeType"], "application/json")
        self.assertIn("A minor", sent["contents"][0]["parts"][0]["text"])
        mid = self.c.get(f"{URL}{r.json()['id']}/midi/")
        self.assertEqual(mid.status_code, 200)
        self.assertEqual(mid["Content-Type"], "audio/midi")
        self.assertEqual(read_midi(mid.content)[1], 3)

    @patch("apps.economy.instrumentalz._key", return_value="k")
    def test_an_unusable_answer_is_not_charged(self, _):
        before = Transaction.objects.count()
        with patch("apps.economy.gemini.requests.post", return_value=reply({"tracks": [{"instrument": "x"}]})):
            r = self.c.post(URL, self.body(), format="json")
        self.assertEqual(r.status_code, 502)
        self.assertIn("Nothing was charged", r.json()["detail"])
        self.assertEqual(Transaction.objects.count(), before)
        self.assertFalse(InstrumentalWork.objects.exists())

    @patch("apps.economy.instrumentalz._key", return_value="k")
    def test_bad_input_is_refused_before_any_model_call(self, _):
        with patch("apps.economy.gemini.requests.post") as post:
            for bad in (self.body(bpm=20), self.body(key="H major"), self.body(instruments=[]), self.body(bars=3)):
                self.assertEqual(self.c.post(URL, bad, format="json").status_code, 400)
        post.assert_not_called()

    def test_mood_search_is_statz(self):
        self.assertEqual(self.c.get(f"{URL}moods/?q=dark").status_code, 403)
        with patch("apps.economy.instrumentalz.can_search_mood", return_value=True):
            self.assertTrue(self.c.get(f"{URL}moods/?q=dark").json()["results"])

    def test_someone_elses_midi_is_not_yours(self):
        other = get_user_model().objects.create_user("o2", "o2@e.com", "pw-Long-enough-1")
        w = InstrumentalWork.objects.create(user=other, bpm=90, key="C major", tracks=[])
        self.assertEqual(self.c.get(f"{URL}{w.id}/midi/").status_code, 404)

    def test_a_used_loop_pays_the_flat_royalty(self):
        from apps.economy.collab import release_deal
        w = InstrumentalWork.objects.create(user=self.user, bpm=90, key="C major", tracks=[])
        deal = CollabDeal.objects.create(
            initiator=self.owner, title="EP", status=CollabDeal.STATUS_FUNDED, held_cents=1000,
            participants=[{"username": "maker", "receives_cents": 1000, "funded": True}])
        r = self.c.post("/api/economy/intelligence/uses/", {"source": "instrumental", "source_id": w.id,
                                                            "target_kind": "collab", "target_id": deal.id},
                        format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["royalty_pct"], 10.0)
        release_deal(deal)
        self.assertEqual(wallet_for(self.user).money_cents, 900)


BUDGET = iz.BUDGET_SECONDS


@override_settings(OWNER_USERNAMES=["koth"], OWNER_EMAILS=[])
class BudgetTests(TestCase):
    """The screen gave up at 30s while the server let the model run 90s and then
    charged and saved a piece the member had been told cost nothing."""

    def setUp(self):
        User = get_user_model()
        User.objects.create_user("koth", "o@e.com", "pw-Long-enough-1")
        self.user = User.objects.create_user("maker", "m@e.com", "pw-Long-enough-1")
        self.c = APIClient(); self.c.force_authenticate(self.user)

    def body(self, **kw):
        return {"genre": "boom bap", "instruments": ["drums", "bass"], "bpm": 90, "key": "A minor", "bars": 4, **kw}

    def test_the_budget_is_published_and_shorter_than_the_old_model_wait(self):
        d = self.c.get(URL).json()
        self.assertEqual(d["budget_seconds"], 60)
        self.assertLess(d["budget_seconds"], 90)

    @patch("apps.economy.instrumentalz._key", return_value="k")
    @patch("apps.economy.instrumentalz.generate_content")
    def test_the_model_call_gets_what_is_left_of_the_budget_not_ninety_seconds(self, gen, _):
        gen.return_value = (reply(LOOP), ["m"])
        r = self.c.post(URL, self.body(), format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertLessEqual(gen.call_args.kwargs["timeout"], BUDGET)

    @patch("apps.economy.instrumentalz.BUDGET_SECONDS", 0.05)
    @patch("apps.economy.instrumentalz._key", return_value="k")
    def test_an_answer_that_arrives_after_the_budget_is_a_504_and_is_not_billed(self, _):
        import time

        def slow(*a, **k):
            time.sleep(0.2)
            return reply(LOOP), ["m"]

        before = Transaction.objects.count()
        w0 = wallet_for(self.user)
        with patch("apps.economy.instrumentalz.generate_content", side_effect=slow):
            r = self.c.post(URL, self.body(), format="json")
        self.assertEqual(r.status_code, 504, r.content)
        d = r.json()
        self.assertTrue(d["timed_out"])
        self.assertIn("Nothing was charged", d["detail"])
        self.assertEqual(Transaction.objects.count(), before)
        self.assertFalse(InstrumentalWork.objects.exists())
        w1 = wallet_for(self.user)
        self.assertEqual((w1.money_cents, w1.promptz, w1.prompts_used_today or 0),
                         (w0.money_cents, w0.promptz, w0.prompts_used_today or 0))

    @patch("apps.economy.instrumentalz._key", return_value="k")
    def test_an_answer_inside_the_budget_is_billed_as_before(self, _):
        with patch("apps.economy.instrumentalz.generate_content", return_value=(reply(LOOP), ["m"])):
            r = self.c.post(URL, self.body(), format="json")
        self.assertEqual(r.status_code, 201)


@override_settings(OWNER_USERNAMES=["koth"], OWNER_EMAILS=[])
class MissingPartsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        User.objects.create_user("koth", "o@e.com", "pw-Long-enough-1")
        self.user = User.objects.create_user("maker", "m@e.com", "pw-Long-enough-1")
        self.c = APIClient(); self.c.force_authenticate(self.user)

    @patch("apps.economy.instrumentalz._key", return_value="k")
    def test_a_part_that_was_asked_for_and_not_returned_is_named(self, _):
        asked = ["drums", "bass", "piano"]                  # LOOP has no piano
        with patch("apps.economy.instrumentalz.generate_content", return_value=(reply(LOOP), ["m"])):
            r = self.c.post(URL, {"instruments": asked, "bpm": 90, "key": "A minor", "bars": 4}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()
        self.assertEqual(d["missing"], ["piano"])
        self.assertEqual([t["instrument"] for t in d["tracks"]], ["drums", "bass"])

    @patch("apps.economy.instrumentalz._key", return_value="k")
    def test_a_part_whose_every_note_was_refused_counts_as_missing(self, _):
        loop = {"tracks": [{"instrument": "drums", "notes": [[36, 0, 0.5, 110]]},
                           {"instrument": "bass", "notes": [[999, 0, 1, 90]]}]}      # every note invalid
        with patch("apps.economy.instrumentalz.generate_content", return_value=(reply(loop), ["m"])):
            r = self.c.post(URL, {"instruments": ["drums", "bass"], "bpm": 90, "key": "A minor", "bars": 4},
                            format="json")
        self.assertEqual(r.json()["missing"], ["bass"])

    @patch("apps.economy.instrumentalz._key", return_value="k")
    def test_nothing_is_missing_when_everything_came_back(self, _):
        with patch("apps.economy.instrumentalz.generate_content", return_value=(reply(LOOP), ["m"])):
            r = self.c.post(URL, {"instruments": ["drums", "bass", "lead"], "bpm": 90, "key": "A minor", "bars": 4},
                            format="json")
        self.assertEqual(r.json()["missing"], [])

    def test_the_saved_list_says_it_too(self):
        InstrumentalWork.objects.create(user=self.user, bpm=90, key="C major", instruments=["drums", "pad"],
                                        tracks=[{"instrument": "drums", "notes": [[36, 0, 1, 100]]}])
        w = self.c.get(URL).json()["works"][0]
        self.assertEqual(w["missing"], ["pad"])


@override_settings(OWNER_USERNAMES=["koth"], OWNER_EMAILS=[])
class DownloadAndRoyaltyTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("maker", "m@e.com", "pw-Long-enough-1")
        self.c = APIClient(); self.c.force_authenticate(self.user)

    def test_a_sharp_in_the_key_survives_into_the_file_name(self):
        for key, slug in (("F# minor", "f-sharp-minor"), ("C# minor", "c-sharp-minor"), ("A minor", "a-minor")):
            w = InstrumentalWork.objects.create(user=self.user, bpm=90, key=key,
                                                tracks=[{"instrument": "bass", "notes": [[36, 0, 1, 100]]}])
            disp = self.c.get(f"{URL}{w.id}/midi/")["Content-Disposition"]
            self.assertIn(f"-in-{slug}-at-90-bpm.mid", disp)
            self.assertNotIn("#", disp)

    def test_f_sharp_minor_and_f_minor_no_longer_share_a_name(self):
        a = InstrumentalWork.objects.create(user=self.user, bpm=90, key="F# minor", tracks=[])
        b = InstrumentalWork.objects.create(user=self.user, bpm=90, key="F minor", tracks=[])
        self.assertNotEqual(self.c.get(f"{URL}{a.id}/midi/")["Content-Disposition"],
                            self.c.get(f"{URL}{b.id}/midi/")["Content-Disposition"])

    def test_every_work_carries_the_royalty_so_the_client_never_types_a_ten(self):
        InstrumentalWork.objects.create(user=self.user, bpm=90, key="C major", tracks=[])
        d = self.c.get(URL).json()
        self.assertEqual(d["royalty_pct"], iz.ROYALTY_PCT)
        self.assertEqual(d["works"][0]["royalty_pct"], iz.ROYALTY_PCT)

    @patch("apps.economy.instrumentalz._key", return_value="k")
    def test_a_fresh_piece_carries_it_too(self, _):
        with patch("apps.economy.instrumentalz.generate_content", return_value=(reply(LOOP), ["m"])):
            r = self.c.post(URL, {"instruments": ["drums"], "bpm": 90, "key": "A minor", "bars": 4}, format="json")
        self.assertEqual(r.json()["royalty_pct"], iz.ROYALTY_PCT)


class InstrumentMixLevelsTests(TestCase):
    """The coach sets a level per instrument; Premium can change; StatZ can change and keep."""

    def setUp(self):
        from rest_framework.test import APIClient
        from apps.economy.models import InstrumentalWork, membership_for
        self.User = get_user_model()
        self.u = self.User.objects.create_user("mixer", "m@e.com", "pw-Long-enough-1")
        self.work = InstrumentalWork.objects.create(
            user=self.u, genre="trap", instruments=["drums", "pad"], bpm=90, key="C major", bars=4,
            tracks=[{"instrument": "drums", "gain": 0.9, "notes": [[36, 0, 1, 100]]},
                    {"instrument": "pad", "gain": 0.5, "notes": [[60, 0, 4, 100]]}])
        self.c = APIClient(); self.c.force_authenticate(self.u)
        self.membership_for = membership_for

    def _tier(self, t):
        m = self.membership_for(self.u); m.tier = t; m.save()

    def test_the_coach_gain_is_validated_with_a_role_fallback(self):
        from apps.economy.instrumentalz import clean_tracks
        out = clean_tracks({"tracks": [
            {"instrument": "drums", "gain": 7, "notes": [[36, 0, 1, 100]]},
            {"instrument": "pad", "gain": "loud", "notes": [[60, 0, 1, 100]]}]}, ["drums", "pad"], 4)
        self.assertEqual({t["instrument"]: t["gain"] for t in out}, {"drums": 1.0, "pad": 0.5})

    def test_rights_follow_the_tier(self):
        from apps.economy.instrumentalz import mix_rights
        self._tier("free");    self.assertEqual(mix_rights(self.u), {"can_change": False, "can_keep": False})
        self._tier("premium"); self.assertEqual(mix_rights(self.u), {"can_change": True, "can_keep": False})
        self._tier("statz");   self.assertEqual(mix_rights(self.u), {"can_change": True, "can_keep": True})

    def test_the_list_says_each_levels_and_what_the_member_may_do(self):
        self._tier("premium")
        w = self.c.get("/api/economy/instrumentalz/").data["works"][0]
        self.assertEqual(w["mix"]["gains"], {"drums": 0.9, "pad": 0.5})
        self.assertTrue(w["mix"]["can_change"]); self.assertFalse(w["mix"]["can_keep"])

    def test_only_statz_keeps_levels_and_the_others_are_told_why(self):
        for t in ("free", "premium"):
            self._tier(t)
            r = self.c.patch(f"/api/economy/instrumentalz/{self.work.id}/mix/", {"gains": {"pad": 0.1}}, format="json")
            self.assertEqual(r.status_code, 403, t)
        self.work.refresh_from_db()
        self.assertEqual({x["instrument"]: x["gain"] for x in self.work.tracks}, {"drums": 0.9, "pad": 0.5})
        self._tier("statz")
        r = self.c.patch(f"/api/economy/instrumentalz/{self.work.id}/mix/", {"gains": {"pad": 0.2, "bogus": 1}}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.work.refresh_from_db()
        self.assertEqual({x["instrument"]: x["gain"] for x in self.work.tracks}, {"drums": 0.9, "pad": 0.2})

    def test_the_download_scales_velocity_by_the_level_and_premium_can_name_a_version(self):
        from apps.economy.instrumentalz import midi_bytes
        title = "trap in C major at 90 BPM"                                  # what the download names itself
        base = midi_bytes(self.work.tracks, 90, "C major", title)
        louder = midi_bytes([{**t, "gain": 1.0} for t in self.work.tracks], 90, "C major", title)
        self.assertNotEqual(base, louder)                                   # the pad at 0.5 is quieter
        self._tier("free")
        a = self.c.get(f"/api/economy/instrumentalz/{self.work.id}/midi/?gains=pad:0").content
        self.assertEqual(a, base)                                           # free cannot name a version
        self._tier("premium")
        b = self.c.get(f"/api/economy/instrumentalz/{self.work.id}/midi/?gains=pad:1,drums:1").content
        self.assertEqual(b, louder)
        self.work.refresh_from_db()
        self.assertEqual({x["instrument"]: x["gain"] for x in self.work.tracks}, {"drums": 0.9, "pad": 0.5})  # not kept
