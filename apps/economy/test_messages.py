from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.catalog import DM_COLD_ENERGY
from apps.economy.models import Follow, Message, Wallet, wallet_for

User = get_user_model()
URL = "/api/economy/messages/"


class ColdMessageCostTests(TestCase):
    """Opening a conversation with a stranger costs ⚡; everything else is free."""

    def setUp(self):
        self.client = APIClient()
        self.me = User.objects.create_user("me", "me@example.com", "pw12345678")
        self.peer = User.objects.create_user("peer", "peer@example.com", "pw12345678")
        self.client.force_authenticate(self.me)
        Wallet.objects.update_or_create(user=self.me, defaults={"energy": 10})

    def energy(self):
        return wallet_for(self.me).energy

    def test_quote_is_given_before_sending(self):
        q = self.client.get(URL, {"cost_for": "peer"}).data
        self.assertTrue(q["cold"])
        self.assertEqual(q["cost_energy"], DM_COLD_ENERGY)

    def test_first_message_to_a_stranger_is_charged_once(self):
        r = self.client.post(URL, {"to": "peer", "body": "hi"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["cost_energy"], DM_COLD_ENERGY)
        self.assertEqual(self.energy(), 10 - DM_COLD_ENERGY)
        self.client.post(URL, {"to": "peer", "body": "again"}, format="json")
        self.assertEqual(self.energy(), 10 - DM_COLD_ENERGY)          # follow-up is free

    def test_reply_follower_are_free(self):
        Message.objects.create(sender=self.peer, recipient=self.me, body="hello")
        self.assertEqual(self.client.get(URL, {"cost_for": "peer"}).data["cost_energy"], 0)
        self.client.post(URL, {"to": "peer", "body": "reply"}, format="json")
        self.assertGreaterEqual(self.energy(), 10)      # a cold reply even earns
        other = User.objects.create_user("fan", "fan@example.com", "pw12345678")
        Follow.objects.create(follower=other, following=self.me)
        before = self.energy()
        self.client.post(URL, {"to": "fan", "body": "thanks"}, format="json")
        self.assertEqual(self.energy(), before)

    def test_too_little_energy_refuses_and_sends_nothing(self):
        Wallet.objects.filter(user=self.me).update(energy=DM_COLD_ENERGY - 1)
        r = self.client.post(URL, {"to": "peer", "body": "hi"}, format="json")
        self.assertEqual(r.status_code, 402)
        self.assertEqual(Message.objects.count(), 0)
        self.assertEqual(self.energy(), DM_COLD_ENERGY - 1)


class MessagesShapeTests(TestCase):
    """The MessageZ screen renders data.inbox / data.sent / data.dm_cost_energy
    and calls rows.length on the arrays, so all three must always be present."""

    def setUp(self):
        self.client = APIClient()
        self.me = User.objects.create_user("me", "me@example.com", "pw12345678")
        self.peer = User.objects.create_user("peer", "peer@example.com", "pw12345678")
        self.client.force_authenticate(self.me)
        Wallet.objects.update_or_create(user=self.me, defaults={"energy": 10})

    def test_empty_mailbox_still_returns_arrays(self):
        data = self.client.get(URL).data
        self.assertEqual(data["inbox"], [])
        self.assertEqual(data["sent"], [])
        self.assertEqual(data["dm_cost_energy"], DM_COLD_ENERGY)

    def test_inbox_and_sent_are_split_by_direction(self):
        Message.objects.create(sender=self.peer, recipient=self.me, body="incoming")
        Message.objects.create(sender=self.me, recipient=self.peer, body="outgoing")
        data = self.client.get(URL).data
        self.assertEqual([m["body"] for m in data["inbox"]], ["incoming"])
        self.assertEqual([m["body"] for m in data["sent"]], ["outgoing"])

    def test_rows_carry_the_fields_the_list_renders(self):
        Message.objects.create(sender=self.peer, recipient=self.me, body="hi")
        row = self.client.get(URL).data["inbox"][0]
        for field in ("id", "from", "to", "body"):
            self.assertIn(field, row)
        self.assertEqual(row["from"], "peer")

    def test_conversations_still_returned_for_a_threaded_view(self):
        Message.objects.create(sender=self.peer, recipient=self.me, body="hi")
        data = self.client.get(URL).data
        self.assertEqual(len(data["conversations"]), 1)
        self.assertEqual(data["conversations"][0]["user"], "peer")

    def test_sending_returns_a_row_of_the_same_shape(self):
        resp = self.client.post(URL, {"to": "peer", "body": "yo"}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        for field in ("id", "from", "to", "body"):
            self.assertIn(field, resp.data)
