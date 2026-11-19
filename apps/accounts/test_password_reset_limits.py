from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.passwords import RESET_PER_ACCOUNT, RESET_PER_ADDRESS


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ResetLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        get_user_model().objects.create_user("victim", email="v@example.com", password="pw-long-enough-1")
        self.c = APIClient()

    def test_one_account_gets_at_most_a_few_emails_and_the_answer_never_changes(self):
        answers = set()
        for _ in range(RESET_PER_ACCOUNT + 3):
            r = self.c.post("/api/auth/password/forgot/", {"identifier": "victim"}, format="json")
            self.assertEqual(r.status_code, 200); answers.add(r.data["detail"])
        self.assertEqual(len(mail.outbox), RESET_PER_ACCOUNT)
        self.assertEqual(len(answers), 1, "a limited account must answer exactly like a sent one")

    def test_one_connection_is_capped(self):
        for i in range(RESET_PER_ADDRESS):
            self.c.post("/api/auth/password/forgot/", {"identifier": f"nobody{i}"}, format="json")
        r = self.c.post("/api/auth/password/forgot/", {"identifier": "victim"}, format="json")
        self.assertEqual(r.status_code, 429)
