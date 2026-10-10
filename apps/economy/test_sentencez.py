"""Sentence ConnectZ: price before the run, persona-gated legal kinds, no
charge for an empty answer, and the royalty scaled by what survives an edit."""
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import sentencez
from apps.economy.models import SentenceWork, Transaction, membership_for, profile_for, wallet_for

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
    """The brief is the material the writer works FROM, so it has its own ladder
    (`catalog.WRITER_BRIEF_CHARS`) rather than the 400 characters a post gets —
    at 400 a resume is impossible, not merely harder, for a Free member."""

    def member(self, name, tier=None):
        u = get_user_model().objects.create_user(name, f"{name}@e.com", "pw-Long-enough-1")
        if tier:
            m = membership_for(u)
            m.tier = tier
            m.save()
        c = APIClient(); c.force_authenticate(u)
        return u, c

    def test_the_brief_answers_to_the_writer_ladder_not_the_post_limit(self):
        from apps.economy.catalog import WRITER_BRIEF_CHARS
        _, c = self.member("capped")
        cap = WRITER_BRIEF_CHARS["free"]
        self.assertGreater(cap, 400)          # a post's limit would make a resume impossible
        r = c.post(URL, {"kind": "caption", "topic": "x" * (cap + 1)}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["char_limit"], cap)

    @patch("apps.economy.sentencez.generate_content", return_value=(reply("ok text"), []))
    @patch("apps.economy.sentencez._key", return_value="k")
    def test_a_free_member_can_send_a_whole_work_history(self, *_):
        _, c = self.member("longbrief")
        r = c.post(URL, {"kind": "resume", "topic": "Acme, 2019-2023, lead. " * 100}, format="json")   # ~2,300 chars
        self.assertEqual(r.status_code, 201, r.content)

    def test_the_ladder_only_goes_up_and_statz_is_unlimited(self):
        from apps.economy.catalog import UNLIMITED_CHARS, WRITER_BRIEF_CHARS
        self.assertLess(WRITER_BRIEF_CHARS["free"], WRITER_BRIEF_CHARS["premium"])
        self.assertEqual(WRITER_BRIEF_CHARS["statz"], UNLIMITED_CHARS)   # Corey: StatZ never gets a number

    def test_the_limit_is_published_before_anything_is_typed(self):
        from apps.economy.catalog import WRITER_BRIEF_CHARS
        _, c = self.member("sees")
        with patch("apps.economy.sentencez._key", return_value="k"):
            d = c.get(URL).json()
        self.assertEqual(d["brief_limit"], WRITER_BRIEF_CHARS["free"])
        self.assertFalse(d["brief_unlimited"])
        _, s = self.member("statzman", "statz")
        with patch("apps.economy.sentencez._key", return_value="k"):
            self.assertTrue(s.get(URL).json()["brief_unlimited"])


class PlainKindsTests(TestCase):
    """Resumes, cover letters, poems and bios belong to the member, not to a house
    voice — and the three that are claims about a person may not invent anything."""

    PLAIN = ("resume", "cover_letter", "poem", "bio")
    CLAIMS = ("resume", "cover_letter", "bio")

    def test_they_are_open_to_every_member(self):
        u = get_user_model().objects.create_user("anyone", "a@e.com", "pw-Long-enough-1")
        kinds = {k["key"]: k for k in sentencez.kinds_for(u)}
        for k in self.PLAIN:
            self.assertTrue(kinds[k]["allowed"], k)
            self.assertEqual(kinds[k]["needs"], [], k)

    def test_none_of_them_is_written_in_k_oths_voice(self):
        with patch.dict("os.environ", {"SENTENCEZ_VOICE": "bars one"}):
            for k in self.PLAIN:
                p = sentencez.prompt_for(k, "my history")
                self.assertNotIn("bars one", p, k)
                self.assertNotIn("radically transparent", p, k)
                self.assertNotIn("VOICE:", p, k)
                self.assertEqual(sentencez.voice_of(k), "plain")

    def test_the_documents_that_claim_a_history_may_not_invent_one(self):
        for k in self.CLAIMS:
            p = sentencez.prompt_for(k, "I worked at Acme")
            self.assertIn("Never invent", p, k)
            self.assertIn("[BRACKETED PLACEHOLDER]", p, k)
        self.assertNotIn("Never invent an employer", sentencez.prompt_for("poem", "rain"))

    def test_the_original_kinds_keep_the_voice_they_had(self):
        self.assertEqual(sentencez.voice_of("lyrics"), "koth")
        self.assertEqual(sentencez.voice_of("caption"), "koth")
        self.assertEqual(sentencez.voice_of("post"), "koth")
        self.assertEqual(sentencez.voice_of("essay"), "academic")
        self.assertEqual(sentencez.voice_of("contract"), "plain")
        self.assertIn("radically transparent", sentencez.prompt_for("lyrics", "rain"))

    def test_every_kind_carries_what_a_screen_needs_to_say_about_it(self):
        u = get_user_model().objects.create_user("seer", "s@e.com", "pw-Long-enough-1")
        for k in sentencez.kinds_for(u):
            self.assertTrue(k["hint"], k["key"])
            self.assertTrue(k["style_label"], k["key"])
            self.assertIn(k["voice"], ("koth", "academic", "plain"), k["key"])
            self.assertIn("invents_nothing", k)

    def test_a_finished_resume_says_to_fill_the_blanks_and_a_poem_says_nothing(self):
        for kind, expect in (("resume", True), ("cover_letter", True), ("bio", True), ("poem", False), ("lyrics", False)):
            u = get_user_model().objects.create_user(f"n_{kind}", f"{kind}@e.com", "pw-Long-enough-1")
            w = SentenceWork.objects.create(user=u, kind=kind, topic="t", text="x", inputs={})
            note = sentencez._work_dict(w)["note"]
            self.assertEqual(bool(note), expect, kind)
            if expect:
                self.assertIn("BRACKETED", note)

    def test_the_ladder_is_published_for_every_tier(self):
        u = get_user_model().objects.create_user("ladder", "l@e.com", "pw-Long-enough-1")
        c = APIClient(); c.force_authenticate(u)
        with patch("apps.economy.sentencez._key", return_value="k"):
            ladder = c.get(URL).json()["brief_ladder"]
        self.assertEqual([r["tier"] for r in ladder], ["free", "premium", "statz"])
        self.assertIsNone(ladder[2]["chars"])
        self.assertLess(ladder[0]["chars"], ladder[1]["chars"])

    def test_the_agreements_are_listed_after_the_kinds_anybody_can_use(self):
        order = list(sentencez.KINDS)
        self.assertLess(order.index("resume"), order.index("contract"))
        self.assertLess(order.index("bio"), order.index("royalties"))

    @patch("apps.economy.sentencez.generate_content", return_value=(reply("A poem\n\nrain"), []))
    @patch("apps.economy.sentencez._key", return_value="k")
    def test_a_poem_is_written_saved_and_labelled(self, *_):
        u = get_user_model().objects.create_user("poet", "p@e.com", "pw-Long-enough-1")
        c = APIClient(); c.force_authenticate(u)
        r = c.post(URL, {"kind": "poem", "topic": "rain on a tin roof", "genre": "haiku"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["label"], "Poem")
        self.assertEqual(r.json()["legal_note"], "")
