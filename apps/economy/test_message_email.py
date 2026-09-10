"""A message reaches the person, and stops short of pestering them.

`notify()` writes a Notification row and nothing else, which only helps a
member who happens to open the app. A direct message is the one thing here
that is waiting on a person, so it is worth reaching them where they are.

Almost all of these are about NOT sending. Getting that wrong is how a product
teaches people to file it as spam, and then the one message that mattered goes
to the same folder.
"""
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase

from .models import Notification, UserPreferences

User = get_user_model()


class MessageEmail(TestCase):
    def setUp(self):
        self.me = User.objects.create_user(
            username="sender", password="pw", email="sender@example.com")
        self.them = User.objects.create_user(
            username="steve", password="pw", email="steve@example.com")
        self.client.force_login(self.me)
        mail.outbox = []

    def _send(self, body="hello there", to=None):
        return self.client.post("/api/economy/messages/",
                                {"to": to or self.them.username, "body": body},
                                "application/json")

    def test_a_message_emails_the_recipient(self):
        r = self._send()
        self.assertEqual(r.status_code, 201)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("steve@example.com", mail.outbox[0].to)
        self.assertIn("sender", mail.outbox[0].subject)

    def test_the_email_carries_the_message_so_it_is_worth_opening(self):
        self._send(body="come play the loft on saturday")
        self.assertIn("come play the loft on saturday", mail.outbox[0].body)

    def test_a_long_message_is_trimmed_not_dumped(self):
        """350 rather than 900: the free tier caps a message at 400 characters,
        so a longer one never reaches the email path at all — it is refused as
        over the limit, and the test would be proving the wrong thing."""
        self._send(body="x" * 350)
        self.assertIn("...", mail.outbox[0].body)
        self.assertIn("x" * 297, mail.outbox[0].body)
        self.assertNotIn("x" * 350, mail.outbox[0].body)

    def test_the_in_app_notification_still_happens(self):
        """Email is in ADDITION to. It must not have replaced anything."""
        self._send()
        self.assertTrue(Notification.objects.filter(
            user=self.them, actor=self.me, kind="message").exists())

    # ---- the refusals -----------------------------------------------------

    def test_a_second_message_does_not_send_a_second_email(self):
        """Ten messages in a row is one email. A second is worth nothing to
        somebody who has not opened the first."""
        self._send(body="one")
        self._send(body="two")
        self._send(body="three")
        self.assertEqual(len(mail.outbox), 1)

    def test_reading_the_first_makes_the_next_one_mail_again(self):
        """Once they have engaged, the suppression has done its job."""
        self._send(body="one")
        Notification.objects.filter(user=self.them).update(read=True)
        self._send(body="two")
        self.assertEqual(len(mail.outbox), 2)

    def test_a_member_with_no_address_is_not_emailed(self):
        """Every account made through a provider that hands over no email —
        Twitter gives none — holds ''. There is nothing to send to."""
        self.them.email = ""
        self.them.save()
        r = self._send()
        self.assertEqual(r.status_code, 201)
        self.assertEqual(len(mail.outbox), 0)

    def test_opting_out_is_honoured(self):
        UserPreferences.objects.create(user=self.them, notifications_enabled=False)
        self._send()
        self.assertEqual(len(mail.outbox), 0)

    def test_opting_in_explicitly_still_mails(self):
        UserPreferences.objects.create(user=self.them, notifications_enabled=True)
        self._send()
        self.assertEqual(len(mail.outbox), 1)

    def test_a_failing_mail_server_never_fails_the_message(self):
        """The message is already saved and the notification already written.
        A mail server having a bad day must not turn a delivered message into
        a 500 — the sender would retry, and send it twice."""
        from unittest.mock import patch
        with patch("apps.economy.messages_view.send_mail",
                   side_effect=OSError("smtp is down")):
            r = self._send()
        self.assertEqual(r.status_code, 201)
        self.assertTrue(Notification.objects.filter(user=self.them).exists())
