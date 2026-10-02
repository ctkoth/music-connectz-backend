"""Sentence ConnectZ: price before the run, persona-gated legal kinds, no
charge for an empty answer, and the royalty scaled by what survives an edit."""
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import sentencez
from apps.economy.models import SentenceWork, Transaction, profile_for, wallet_for

URL = "/api/economy/sentencez/"


def reply(text):
    r = MagicMock(status_code=200, text="ok")
    r.json.return_value = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    return r


class SentenceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("writer", "w@e.com", "pw-Long-enough-1")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def give_persona(self, key):
        p = profile_for(self.user)
        p.personas = [{"key": key, "name": key, "skills": []}]
        p.save()

    def test_price_kinds_and_royalty_are_published_before_anything_runs(self):
        with patch("apps.economy.sentencez._key", return_value="k"):
            d = self.client.get(URL).json()
        self.assertIn("cost_cents", d)
        self.assertIn("free_today", d)
        self.assertEqual(d["royalty_pct"], 10)
        self.assertIn("5%", d["royalty_rule"])
        kinds = {k["key"]: k for k in d["kinds"]}
        self.assertTrue(kinds["lyrics"]["allowed"])
        self.assertFalse(kinds["contract"]["allowed"])
        self.assertFalse(kinds["royalties"]["allowed"])

    @patch("apps.economy.sentencez._key", return_value="k")
    def test_contracts_need_manager_or_ar_scout(self, _):
        r = self.client.post(URL, {"kind": "contract", "topic": "a deal"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.give_persona("arscout")
        with patch("apps.economy.gemini.requests.post", return_value=reply("AGREEMENT [ARTIST NAME]")):
            r = self.client.post(URL, {"kind": "contract", "topic": "a deal"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertIn("not legal advice", r.json()["legal_note"])

    @patch("apps.economy.sentencez._key", return_value="k")
    def test_an_empty_answer_is_not_charged_and_not_saved(self, _):
        before = Transaction.objects.count()
        with patch("apps.economy.gemini.requests.post", return_value=reply("")):
            r = self.client.post(URL, {"kind": "post", "topic": "new single"}, format="json")
        self.assertEqual(r.status_code, 502)
        self.assertIn("Nothing was charged", r.json()["detail"])
        self.assertEqual(Transaction.objects.count(), before)
        self.assertFalse(SentenceWork.objects.exists())
        self.assertEqual(wallet_for(self.user).prompts_used_today or 0, 0)

    @patch("apps.economy.sentencez._key", return_value="k")
    def test_a_written_piece_is_saved_and_listed(self, _):
        with patch("apps.economy.gemini.requests.post", return_value=reply("Verse 1\nline")) as post:
            r = self.client.post(URL, {"kind": "lyrics", "topic": "rain", "genre": "drill",
                                       "majority": 2, "minority": 1}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        sent = post.call_args.kwargs["json"]["contents"][0]["parts"][0]["text"]
        self.assertIn("last 2 syllables", sent)
        self.assertIn("last 1 syllable.", sent)
        self.assertIn("drill", sent)
        self.assertEqual(SentenceWork.objects.get().text, "Verse 1\nline")
        works = self.client.get(URL).json()["works"]
        self.assertEqual(works[0]["kind"], "lyrics")

    def test_rhyme_numbers_are_clamped(self):
        self.assertEqual(sentencez._int(99, 0, 4), 4)
        self.assertIsNone(sentencez._int("x", 0, 4))

    @patch("apps.economy.sentencez._key", return_value="")
    def test_unconfigured_says_so(self, _):
        r = self.client.post(URL, {"kind": "post", "topic": "x"}, format="json")
        self.assertEqual(r.status_code, 503)


class RoyaltyTests(TestCase):
    def test_kept_whole_pays_ten_half_pays_five(self):
        original = "one two three four five six seven eight nine ten"
        self.assertEqual(sentencez.royalty_pct(original, original), 10)
        self.assertEqual(sentencez.royalty_pct(original, "one two three four five X Y Z W V"), 5)
        self.assertEqual(sentencez.royalty_pct(original, "totally different words"), 0)

    def test_the_royalty_endpoint_reads_the_stored_original(self):
        user = get_user_model().objects.create_user("w2", "w2@e.com", "pw-Long-enough-1")
        work = SentenceWork.objects.create(user=user, kind="post", topic="t", text="a b c d")
        c = APIClient(); c.force_authenticate(user)
        d = c.post(f"{URL}{work.id}/royalty/", {"text": "a b x y"}, format="json").json()
        self.assertEqual(d["kept_share"], 0.5)
        self.assertEqual(d["royalty_pct"], 5)
        other = get_user_model().objects.create_user("w3", "w3@e.com", "pw-Long-enough-1")
        c.force_authenticate(other)
        self.assertEqual(c.post(f"{URL}{work.id}/royalty/", {"text": ""}, format="json").status_code, 404)


class VoiceTests(TestCase):
    def test_voice_is_read_from_the_secret_not_the_repo(self):
        with patch.dict("os.environ", {"SENTENCEZ_VOICE": "bars one\n---\nbars two"}):
            self.assertEqual(sentencez.voice_samples(), ["bars one", "bars two"])
            p = sentencez.prompt_for("lyrics", "rain")
        self.assertIn("bars two", p)
        self.assertIn("never reuse their lines", p)

    def test_contracts_are_not_written_in_a_lyric_voice(self):
        with patch.dict("os.environ", {"SENTENCEZ_VOICE": "bars one"}):
            p = sentencez.prompt_for("contract", "a deal")
        self.assertNotIn("bars one", p)
        self.assertNotIn("VOICE:", p)


class RegisterTests(TestCase):
    def test_essays_take_the_academic_register_and_never_invent_sources(self):
        p = sentencez.prompt_for("essay", "streaming payouts")
        self.assertIn("APA 7", p)
        self.assertIn("never invent a source", p)
        self.assertNotIn("radically transparent", p)

    def test_lyrics_take_the_personal_register_not_the_academic_one(self):
        p = sentencez.prompt_for("lyrics", "rain")
        self.assertIn("radically transparent", p)
        self.assertIn("homophones", p)
        self.assertNotIn("APA", p)

    def test_posts_get_the_personal_register_without_lyric_tricks(self):
        p = sentencez.prompt_for("post", "new single")
        self.assertIn("radically transparent", p)
        self.assertNotIn("homophones", p)


class SentenceTierCapTests(TestCase):
    def test_the_brief_answers_to_the_tier_char_limit(self):
        u = get_user_model().objects.create_user("capped", "c@e.com", "pw-Long-enough-1")
        c = APIClient(); c.force_authenticate(u)
        r = c.post(URL, {"kind": "caption", "topic": "x" * 401}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["char_limit"], 400)
