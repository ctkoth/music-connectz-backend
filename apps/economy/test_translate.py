"""TranslateZ must leave a paid batch kept, not just handed back once.

Corey's rule: a PromptZ spend — real model money — leaves the member
something tangible. Before this, `TranslateView` billed the charge and
returned the strings with nothing saved; a member who didn't immediately
use the result paid again to get it back.
"""
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import Translation, wallet_for

URL = "/api/economy/translate/"


class Block:
    def __init__(self, text):
        self.type, self.text = "text", text


def anthropic_stub(texts):
    """A stand-in for the `anthropic` package: translate.py imports it
    locally (`try: import anthropic`), so it must be patched in sys.modules
    rather than as a module attribute."""
    reply = json.dumps([t.upper() for t in texts])

    class C:
        class messages:
            @staticmethod
            def create(**kw):
                return type("R", (), {"content": [Block(reply)]})()
    fake = type("anthropic", (), {"Anthropic": C})
    return fake


class TranslatePersistenceTests(TestCase):
    def setUp(self):
        self.u = get_user_model().objects.create_user("linguist", "l@e.com", "pw-Long-enough-1")
        w = wallet_for(self.u); w.money_cents = 1000; w.promptz = 100; w.save()
        self.c = APIClient(); self.c.force_authenticate(self.u)

    def _post(self, texts, target_lang="es"):
        with patch.dict("sys.modules", {"anthropic": anthropic_stub(texts)}):
            return self.c.post(URL, {"texts": texts, "target_lang": target_lang}, format="json")

    def test_a_paid_batch_is_kept(self):
        before = Translation.objects.count()
        r = self._post(["hello", "world"])
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Translation.objects.count(), before + 1)
        row = Translation.objects.get(pk=r.json()["kept_id"])
        self.assertEqual(row.user, self.u)
        self.assertEqual(row.target_lang, "es")
        self.assertEqual(row.texts, ["hello", "world"])
        self.assertEqual(row.translations, ["HELLO", "WORLD"])

    def test_past_batches_are_reopenable(self):
        self._post(["hi"])
        r = self.c.get(URL)
        self.assertEqual(r.status_code, 200)
        rows = r.json()["translations"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["texts"], ["hi"])

    def test_a_free_english_noop_keeps_nothing(self):
        before = Translation.objects.count()
        r = self.c.post(URL, {"texts": ["hi"], "target_lang": "en"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Translation.objects.count(), before)

    def test_only_your_own_batches_come_back(self):
        other = get_user_model().objects.create_user("other", "o@e.com", "pw-Long-enough-1")
        Translation.objects.create(user=other, target_lang="fr", texts=["x"], translations=["y"])
        r = self.c.get(URL)
        self.assertEqual(r.json()["translations"], [])
