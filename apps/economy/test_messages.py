from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import Message

User = get_user_model()
URL = "/api/economy/messages/"


class MessagesShapeTests(TestCase):
    """The MessageZ screen renders data.inbox / data.sent / data.dm_cost_energy
    and calls rows.length on the arrays, so all three must always be present."""

    def setUp(self):
        self.client = APIClient()
        self.me = User.objects.create_user("me", "me@example.com", "pw12345678")
        self.peer = User.objects.create_user("peer", "peer@example.com", "pw12345678")
        self.client.force_authenticate(self.me)

    def test_empty_mailbox_still_returns_arrays(self):
        data = self.client.get(URL).data
        self.assertEqual(data["inbox"], [])
        self.assertEqual(data["sent"], [])
        self.assertEqual(data["dm_cost_energy"], 0)

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
