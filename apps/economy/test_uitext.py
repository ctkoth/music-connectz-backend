"""UiText: one translation serves everybody, and nothing can run the platform's bill up."""
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import uitext
from apps.economy.models import UiString

URL = "/api/economy/uitext/"


class Block:
    def __init__(self, text):
        self.type, self.text = "text", text


def stub(calls, reply=None):
    """A stand-in `anthropic`: answers each string upper-cased and counts the calls."""
    class Messages:
        def create(self, **kw):
            texts = json.loads(kw["messages"][0]["content"])
            calls.append(texts)
            return type("R", (), {"content": [Block(reply if reply is not None else json.dumps([t.upper() for t in texts]))]})()

    class Client:
        messages = Messages()

    return type("anthropic", (), {"Anthropic": lambda *a, **k: Client()})


class UiTextTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="lang", email="l@x.test", password="hunter2hunter2")
        self.member = APIClient()
        self.member.force_authenticate(self.user)
        self.visitor = APIClient()

    def post(self, client, texts, lang="es", calls=None, reply=None):
        calls = [] if calls is None else calls
        with patch.dict("sys.modules", {"anthropic": stub(calls, reply)}):
            return client.post(URL, {"lang": lang, "texts": texts}, format="json")

    def test_the_catalogue_is_open_and_every_language_is_whole(self):
        r = self.visitor.get(URL)
        self.assertEqual(r.status_code, 200)
        langs = r.data["languages"]
        self.assertGreater(len(langs), 90)
        self.assertEqual(len({l["code"] for l in langs}), len(langs))
        for l in langs:
            self.assertTrue(l["name"] and l["own"] and l["flag"], l)
            self.assertLessEqual(len(l["code"]), 12)
        self.assertTrue(r.data["note"])

    def test_a_string_is_translated_once_and_then_served_to_everybody(self):
        calls = []
        r = self.post(self.member, ["Save routine", "Log out"], calls=calls)
        self.assertEqual(r.data["translations"], {"Save routine": "SAVE ROUTINE", "Log out": "LOG OUT"})
        self.assertEqual(len(calls), 1)
        again = self.post(self.member, ["Save routine"], calls=calls)
        self.assertEqual(again.data["translations"], {"Save routine": "SAVE ROUTINE"})
        self.assertEqual(len(calls), 1, "a known string never reaches the model again")
        v = self.post(self.visitor, ["Save routine"], calls=calls)
        self.assertEqual(v.data["translations"], {"Save routine": "SAVE ROUTINE"})

    def test_a_visitor_cannot_cause_a_new_translation(self):
        calls = []
        r = self.post(self.visitor, ["Brand new sentence"], calls=calls)
        self.assertEqual(r.data["translations"], {})
        self.assertEqual(calls, [])
        self.assertEqual(UiString.objects.count(), 0)

    def test_only_strings_worth_translating_are_sent(self):
        calls = []
        self.post(self.member, ["OK", "7", "🎤", " ", "x" * 500, "Play", "Play"], calls=calls)
        self.assertEqual(calls, [["OK", "Play"]])

    def test_english_and_unknown_languages(self):
        calls = []
        self.assertEqual(self.post(self.member, ["Play"], lang="en", calls=calls).data["translations"], {})
        self.assertEqual(self.post(self.member, ["Play"], lang="klingon", calls=calls).status_code, 400)
        self.assertEqual(calls, [])

    def test_a_bad_answer_stores_nothing_and_the_screen_keeps_english(self):
        for reply in ["sorry, no", json.dumps(["only one"]), "[not json"]:
            r = self.post(self.member, ["Play", "Stop"], reply=reply)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.data["translations"], {})
        self.assertEqual(UiString.objects.count(), 0)

    def test_the_daily_cap_stops_new_work_and_says_so(self):
        with patch.object(uitext, "DAILY_NEW", 2):
            calls = []
            r = self.post(self.member, ["One thing", "Two things", "Three things"], calls=calls)
            self.assertTrue(r.data["capped"])
            self.assertEqual(len(r.data["translations"]), 2)
            r2 = self.post(self.member, ["Four things"], calls=calls)
            self.assertTrue(r2.data["capped"])
            self.assertEqual(r2.data["translations"], {})
            self.assertEqual(len(calls), 1)
            known = self.post(self.member, ["One thing"], calls=calls)
            self.assertEqual(known.data["translations"], {"One thing": "ONE THING"})

    def test_the_same_string_in_two_languages_is_two_rows(self):
        self.post(self.member, ["Play"], lang="es")
        self.post(self.member, ["Play"], lang="fr")
        self.assertEqual(UiString.objects.filter(source="Play").count(), 2)

    def test_known_only_never_reaches_the_model_and_takes_a_whole_screen(self):
        calls = []
        self.post(self.member, ["Save routine"], calls=calls)
        with patch.dict("sys.modules", {"anthropic": stub(calls)}):
            r = self.member.post(URL, {"lang": "es", "known_only": True,
                                       "texts": ["Save routine"] + [f"Sentence number {chr(65 + i % 26)}{chr(65 + i // 26)}" for i in range(150)]}, format="json")
        self.assertEqual(r.data["translations"], {"Save routine": "SAVE ROUTINE"})
        self.assertEqual(len(calls), 1)
