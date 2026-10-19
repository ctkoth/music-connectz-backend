"""LogZ was the app that made every balance leadable-back-to, and led nowhere.

A member could read "+300 🍥 referral (referrer)" and do nothing with it: not
tell the person it was about, not keep it, not post it, not open the app it
came from. That is exactly the read-only surface the cross-pollination rule
calls unfinished, on the app whose whole job is closing that gap elsewhere.

Two things under test, and the second is the one that stays true under
pressure: a row goes somewhere, and the text that travels is the platform's,
never the client's.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.crosspost import LOG_ORIGINS, log_destinations, log_line
from apps.economy.models import (
    JournalEntry, Message, Transaction, award_promptz, award_spinaz, wallet_for,
)

User = get_user_model()
PW = "hunter2hunter2"


def member(name="ledger"):
    return User.objects.create_user(name, f"{name}@x.com", PW)


def client_for(u):
    c = APIClient()
    c.force_authenticate(u)
    return c


class OriginIsRecordedNotGuessedTests(TestCase):
    def test_a_writer_that_says_where_it_came_from_gets_a_door_back(self):
        u = member()
        award_spinaz(u, 300, "referral (referrer)", app_key="profilez", target="referral-code")
        t = Transaction.objects.get(user=u)
        self.assertEqual(t.app_key, "profilez")
        self.assertEqual(t.target, "referral-code")
        doors = log_destinations({"display": "+300 🍥"}, app_key=t.app_key, target=t.target)
        self.assertEqual(doors[0]["app"], "profilez")
        self.assertEqual(doors[0]["action"], "open")

    def test_a_writer_that_says_nothing_gets_no_door_back(self):
        # Blank is a real state — "nobody said" — and it is never inferred from
        # the note. A guessed origin is a door onto the wrong screen, and the
        # rule about not asserting what you only inferred covers navigation.
        award_spinaz(member(), 50, "rating")
        t = Transaction.objects.get()
        self.assertEqual(t.app_key, "")
        doors = log_destinations({"display": "+50 🍥"}, app_key="")
        self.assertNotIn("open", [d["action"] for d in doors])

    def test_an_unmounted_app_never_becomes_a_door(self):
        # A recorded origin for a tab that does not exist would be a door onto
        # a 404.
        doors = log_destinations({"display": "+1 ⚡"}, app_key="nosuchapp")
        self.assertNotIn("nosuchapp", [d["app"] for d in doors])

    def test_every_origin_named_is_an_app_that_exists(self):
        for key in LOG_ORIGINS:
            self.assertTrue(key.islower() and key.isalnum(), key)


class PromptZFinallyLeavesALineTests(TestCase):
    def test_granting_promptz_writes_a_logz_row(self):
        # SpinaZ and Energy have written a line since LogZ shipped. PromptZ
        # moved silently, so "where did my 🏷️ come from" had no answer except
        # watching the number — the same bug LogZ exists to fix, left open on
        # one resource because this helper predates it.
        u = member()
        award_promptz(u, 25, "bought", app_key="membershipz")
        t = Transaction.objects.get(user=u)
        self.assertEqual(t.resource, Transaction.RES_PROMPTZ)
        self.assertEqual(t.amount, 25)
        self.assertEqual(t.app_key, "membershipz")
        self.assertEqual(wallet_for(u).promptz, 25)


class TheDoorsOutTests(TestCase):
    def test_every_row_can_be_posted_sent_and_kept(self):
        actions = {d["app"] for d in log_destinations({"display": "+5 ⚡"})}
        self.assertEqual(actions, {"postz", "messagez", "journalz"})

    def test_every_door_states_its_cost_rather_than_omitting_it(self):
        # A blank cost and an unstated one look identical on screen.
        for d in log_destinations({"display": "+5 ⚡"}, app_key="postz"):
            self.assertTrue(d["cost"], d)

    def test_one_wording_for_one_fact(self):
        # Three wordings for one movement is how a member ends up unable to
        # tell whether they are looking at the same thing twice.
        row = {"display": "+300 🍥", "note": "referral (referrer)", "at": "2026-09-06T10:00:00Z"}
        line = log_line(row)
        self.assertIn("+300 🍥", line)
        self.assertIn("referral (referrer)", line)
        self.assertIn("2026-09-06", line)
        for d in log_destinations(row):
            if d["action"] == "seed":
                self.assertEqual(d["carry"]["text"], line)

    def test_the_feed_carries_the_doors(self):
        u = member()
        award_spinaz(u, 300, "referral", app_key="profilez")
        r = client_for(u).get("/api/economy/logz/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["entries"][0]["destinations"])


class TheExportTests(TestCase):
    def setUp(self):
        self.u = member("me")
        award_spinaz(self.u, 300, "referral (referrer)")
        self.row = Transaction.objects.get(user=self.u)
        self.c = client_for(self.u)

    def test_the_text_is_read_from_the_ledger_never_from_the_client(self):
        # A client that could hand us the text is one that could post
        # "+50,000 💵 royalty" over somebody's name. The whole value of a LogZ
        # line is that the platform wrote it.
        r = self.c.post("/api/economy/logz/export/",
                        {"ids": [self.row.id], "to": "journalz",
                         "text": "+50000 💵 royalty"}, format="json")
        self.assertEqual(r.status_code, 201)
        entry = JournalEntry.objects.get()
        self.assertIn("+300", entry.body)
        self.assertNotIn("50000", entry.body)

    def test_you_can_only_export_your_own_rows(self):
        other = member("other")
        award_spinaz(other, 999, "not yours")
        theirs = Transaction.objects.get(user=other)
        r = self.c.post("/api/economy/logz/export/",
                        {"ids": [theirs.id], "to": "journalz"}, format="json")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(JournalEntry.objects.count(), 0)

    def test_a_journal_export_is_private_like_the_diary_always_is(self):
        self.c.post("/api/economy/logz/export/",
                    {"ids": [self.row.id], "to": "journalz"}, format="json")
        self.assertEqual(JournalEntry.objects.get().visibility, "private")

    def test_a_message_needs_somebody_to_send_it_to(self):
        r = self.c.post("/api/economy/logz/export/",
                        {"ids": [self.row.id], "to": "messagez"}, format="json")
        self.assertEqual(r.status_code, 400)
        # The refusal says what is missing rather than just refusing.
        self.assertEqual(r.data["needs"], ["to_username"])

    def test_a_message_lands_and_notifies(self):
        mate = member("mate")
        r = self.c.post("/api/economy/logz/export/",
                        {"ids": [self.row.id], "to": "messagez", "to_username": "mate"},
                        format="json")
        self.assertEqual(r.status_code, 201)
        self.assertIn("+300", Message.objects.get().body)
        self.assertTrue(mate.notifications.filter(item_id="logz").exists())

    def test_posting_is_seeded_not_created(self):
        # A post has a price, a slot limit and a composer. Creating one here
        # would be spending something from a screen that never showed the cost.
        from apps.economy.models import Post
        r = self.c.post("/api/economy/logz/export/",
                        {"ids": [self.row.id], "to": "postz"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["seeded"])
        self.assertIn("+300", r.data["text"])
        self.assertEqual(Post.objects.count(), 0)

    def test_an_unknown_destination_is_refused_by_name(self):
        r = self.c.post("/api/economy/logz/export/",
                        {"ids": [self.row.id], "to": "twitter"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("postz", r.data["detail"])

    def test_no_rows_is_a_refusal_with_the_way_forward(self):
        r = self.c.post("/api/economy/logz/export/", {"to": "journalz"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Pick at least one", r.data["detail"])

    def test_several_rows_come_out_as_several_lines(self):
        award_spinaz(self.u, 100, "AdZ")
        ids = list(Transaction.objects.filter(user=self.u).values_list("id", flat=True))
        r = self.c.post("/api/economy/logz/export/",
                        {"ids": ids, "to": "journalz"}, format="json")
        self.assertEqual(len(JournalEntry.objects.get().body.splitlines()), 2)

    def test_it_needs_a_login(self):
        self.assertIn(APIClient().post("/api/economy/logz/export/", {}, format="json").status_code,
                      (401, 403))
