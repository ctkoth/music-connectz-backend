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
