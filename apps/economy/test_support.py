"""Support: a private, free, rate-limited way to ask the owner for help — and nobody else can read it."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from . import support
from .models import Notification, SupportMessage, SupportTicket

User = get_user_model()
URL = "/api/economy/support/"


def who(name, **kw):
    u = User.objects.create_user(name, f"{name}@x.test", "hunter2hunter2", **kw)
    c = APIClient(); c.force_authenticate(u)
    return u, c


class OpeningAndReplying(TestCase):
    def test_a_member_opens_a_ticket_and_sees_only_their_own(self):
        a, ca = who("sp_a"); b, cb = who("sp_b")
        r = ca.post(URL, {"subject": "Locked out of BodieZ", "message": "It says my session is open but it isn't."}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["status"], "open")
        self.assertEqual(len(ca.get(URL).data["tickets"]), 1)
        self.assertEqual(cb.get(URL).data["tickets"], [])
        self.assertIn("Only you", ca.get(URL).data["note"])

    def test_blank_and_oversized_are_refused_with_a_reason(self):
        _, c = who("sp_bad")
        self.assertEqual(c.post(URL, {"subject": "", "message": "x"}, format="json").status_code, 400)
        self.assertEqual(c.post(URL, {"subject": "s", "message": " "}, format="json").status_code, 400)
        big = c.post(URL, {"subject": "s", "message": "x" * 2001}, format="json")
        self.assertEqual(big.status_code, 400); self.assertIn("2000", big.data["detail"])

    def test_a_card_number_is_refused_and_nothing_is_stored(self):
        u, c = who("sp_card")
        r = c.post(URL, {"subject": "Charged twice", "message": "my card 4242 4242 4242 4242 was charged"}, format="json")
        self.assertEqual(r.status_code, 400); self.assertIn("card number", r.data["detail"])
        self.assertEqual(SupportTicket.objects.filter(user=u).count(), 0)
        # an ordinary long number that isn't a card passes
        ok = c.post(URL, {"subject": "Order", "message": "reference 1234567890123 please"}, format="json")
        self.assertEqual(ok.status_code, 201)

    def test_the_daily_limit_stops_a_flood_but_not_a_follow_up(self):
        u, c = who("sp_flood")
        for i in range(support.PER_DAY):
            self.assertEqual(c.post(URL, {"subject": f"s{i}", "message": "m"}, format="json").status_code, 201)
        r = c.post(URL, {"subject": "one more", "message": "m"}, format="json")
        self.assertEqual(r.status_code, 429); self.assertIn("nothing was lost", r.data["detail"])
        tid = SupportTicket.objects.filter(user=u).first().id
        self.assertEqual(c.post(URL + f"{tid}/reply/", {"message": "still here"}, format="json").status_code, 200)

    def test_a_reply_reopens_and_only_the_owner_of_the_ticket_can_make_it(self):
        a, ca = who("sp_r1"); _, cb = who("sp_r2")
        tid = ca.post(URL, {"subject": "s", "message": "m"}, format="json").data["id"]
        SupportTicket.objects.filter(pk=tid).update(status="answered")
        self.assertEqual(cb.post(URL + f"{tid}/reply/", {"message": "hi"}, format="json").status_code, 404)
        r = ca.post(URL + f"{tid}/reply/", {"message": "any news?"}, format="json")
        self.assertEqual(r.data["status"], "open"); self.assertEqual(len(r.data["messages"]), 2)


class OwnerQueue(TestCase):
    def setUp(self):
        self.member, self.cm = who("sp_member")
        self.owner, self.co = who("sp_owner", is_staff=True)
        self.tid = self.cm.post(URL, {"subject": "Help", "message": "I can't post"}, format="json").data["id"]

    def test_the_queue_and_answers_are_owner_only(self):
        self.assertEqual(self.cm.get(URL + "queue/").status_code, 403)
        self.assertEqual(self.cm.post(URL + f"{self.tid}/answer/", {"message": "x"}, format="json").status_code, 403)
        q = self.co.get(URL + "queue/")
        self.assertEqual(q.status_code, 200)
        self.assertEqual(q.data["tickets"][0]["username"], "sp_member")

    def test_an_answer_is_stored_marks_it_answered_and_tells_the_member(self):
        r = self.co.post(URL + f"{self.tid}/answer/", {"message": "Try again now — fixed."}, format="json")
        self.assertEqual(r.status_code, 200); self.assertEqual(r.data["status"], "answered")
        self.assertTrue(SupportMessage.objects.filter(ticket_id=self.tid, from_owner=True).exists())
        self.assertTrue(Notification.objects.filter(user=self.member, item_id=f"support:{self.tid}").exists())
        mine = self.cm.get(URL).data["tickets"][0]
        self.assertEqual([m["from_owner"] for m in mine["messages"]], [False, True])

    def test_closing_drops_it_from_the_queue(self):
        self.co.post(URL + f"{self.tid}/answer/", {"message": "Done.", "close": True}, format="json")
        self.assertEqual(self.co.get(URL + "queue/").data["tickets"], [])
        self.assertEqual(self.co.post(URL + f"{self.tid}/answer/", {}, format="json").status_code, 400)


class Private(TestCase):
    def test_deleted_with_the_account(self):
        u, c = who("sp_gone")
        c.post(URL, {"subject": "s", "message": "m"}, format="json")
        u.delete()
        self.assertEqual(SupportTicket.objects.count(), 0); self.assertEqual(SupportMessage.objects.count(), 0)

    def test_no_other_module_reads_the_tables(self):
        import pathlib
        here = pathlib.Path(__file__).parent
        for f in here.glob("*.py"):
            if f.name in ("support.py", "models.py", "urls.py") or f.name.startswith("test_"):
                continue
            src = f.read_text()
            self.assertNotIn("SupportTicket", src, f.name); self.assertNotIn("SupportMessage", src, f.name)
