"""Two list screens, and a deal that disappeared.

`CollabDealsView.get` found the deals you are a PARTICIPANT in by fetching the
300 most recent deals platform-wide and filtering them in Python. So a deal
somebody else put you in silently vanished from your screen once 300 newer
deals existed anywhere on the platform — the row stayed in the database, with
whatever the escrow was holding still held by it. It gets worse the better the
platform does, which is the worst property a bug can have.
"""
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from .models import Battle, BattleEntry, CollabDeal, CollabParticipant

User = get_user_model()
PW = "hunter2hunter2"


class ADealYouAreInDoesNotFallOffTheEndTests(TestCase):

    def setUp(self):
        self.me = User.objects.create_user("me", "me@x.test", PW)
        self.host = User.objects.create_user("host", "h@x.test", PW)
        self.c = APIClient()
        self.c.force_authenticate(self.me)

    def titles(self):
        return [d["title"] for d in self.c.get("/api/economy/collab/").data["deals"]]

    def test_it_survives_three_hundred_newer_deals(self):
        CollabDeal.objects.create(initiator=self.host, title="mine",
                                  participants=[{"username": "me", "share": 50}])
        for i in range(305):
            CollabDeal.objects.create(initiator=self.host, title=f"other {i}",
                                      participants=[{"username": "host", "share": 100}])
        self.assertIn("mine", self.titles())

    def test_deals_i_started_are_still_there(self):
        CollabDeal.objects.create(initiator=self.me, title="i started this")
        self.assertIn("i started this", self.titles())

    def test_a_deal_i_am_not_on_is_not_mine_to_see(self):
        CollabDeal.objects.create(initiator=self.host, title="nothing to do with me",
                                  participants=[{"username": "host", "share": 100}])
        self.assertEqual(self.titles(), [])

    def test_a_deal_is_listed_once_even_when_i_am_both(self):
        """Initiator AND participant — the Q() OR would otherwise duplicate the
        row, which is what `.distinct()` is for."""
        CollabDeal.objects.create(initiator=self.me, title="both",
                                  participants=[{"username": "me", "share": 100}])
        self.assertEqual(self.titles(), ["both"])


class TheLookupTableStaysDerivedTests(TestCase):
    """It is reconciled from the JSON on save rather than appended to at each
    call site, so no writer can forget it."""

    def setUp(self):
        self.a = User.objects.create_user("a", "a@x.test", PW)
        self.b = User.objects.create_user("b", "b@x.test", PW)

    def test_creating_a_deal_indexes_its_people(self):
        d = CollabDeal.objects.create(initiator=self.a, title="t",
                                      participants=[{"username": "a"}, {"username": "b"}])
        self.assertEqual(
            set(CollabParticipant.objects.filter(deal=d).values_list("user__username", flat=True)),
            {"a", "b"})

    def test_removing_somebody_removes_their_row(self):
        d = CollabDeal.objects.create(initiator=self.a, title="t",
                                      participants=[{"username": "a"}, {"username": "b"}])
        d.participants = [{"username": "a"}]
        d.save(update_fields=["participants"])
        self.assertEqual(
            set(CollabParticipant.objects.filter(deal=d).values_list("user__username", flat=True)),
            {"a"})

    def test_a_name_with_no_account_is_skipped_not_raised(self):
        """A lookup table must never be the reason a deal cannot be saved."""
        d = CollabDeal.objects.create(initiator=self.a, title="t",
                                      participants=[{"username": "ghost"}, {"username": "a"}])
        self.assertEqual(CollabParticipant.objects.filter(deal=d).count(), 1)

    def test_junk_in_the_json_does_not_break_the_save(self):
        d = CollabDeal.objects.create(initiator=self.a, title="t",
                                      participants=["not a dict", {"username": "a"}, {}])
        self.assertEqual(CollabParticipant.objects.filter(deal=d).count(), 1)

    def test_a_save_that_cannot_have_changed_the_people_does_not_re_sync(self):
        """`maybe_auto_release` runs on every deal in the list, so an unguarded
        signal would put two queries on every card of a READ."""
        d = CollabDeal.objects.create(initiator=self.a, title="t",
                                      participants=[{"username": "a"}])
        with CaptureQueriesContext(connection) as q:
            d.title = "renamed"
            d.save(update_fields=["title"])
        self.assertEqual(len([x for x in q.captured_queries
                              if "collabparticipant" in x["sql"].lower()]), 0)


class NeitherListScalesWithItsOwnLengthTests(TestCase):

    def test_the_deal_list_is_flat(self):
        me = User.objects.create_user("m", "m@x.test", PW)
        host = User.objects.create_user("h", "hh@x.test", PW)
        c = APIClient()
        c.force_authenticate(me)

        def cost(n):
            CollabDeal.objects.all().delete()
            for i in range(n):
                CollabDeal.objects.create(initiator=host, title=f"d{i}",
                                          participants=[{"username": "m"}])
            c.get("/api/economy/collab/")
            with CaptureQueriesContext(connection) as q:
                r = c.get("/api/economy/collab/")
            return len(q), len(r.data["deals"])

        small, n_small = cost(2)
        big, n_big = cost(40)
        self.assertGreater(n_big, n_small)
        self.assertEqual(small, big, f"{n_small} deals cost {small}, {n_big} cost {big}")

    def test_the_battle_list_is_flat(self):
        me = User.objects.create_user("m2", "m2@x.test", PW)
        host = User.objects.create_user("h2", "h2@x.test", PW)
        c = APIClient()
        c.force_authenticate(me)

        def cost(n):
            Battle.objects.all().delete()
            for i in range(n):
                b = Battle.objects.create(host=host, title=f"b{i}")
                BattleEntry.objects.create(battle=b, user=host)
            c.get("/api/economy/battlez/")
            with CaptureQueriesContext(connection) as q:
                r = c.get("/api/economy/battlez/")
            return len(q), len(r.data["battles"])

        small, n_small = cost(2)
        big, n_big = cost(40)
        self.assertGreater(n_big, n_small)
        self.assertEqual(small, big, f"{n_small} battles cost {small}, {n_big} cost {big}")


class TheBattleNumbersAreStillRightTests(TestCase):
    """A batch that changes an answer is worse than the N+1 it replaced."""

    def setUp(self):
        self.me = User.objects.create_user("me3", "me3@x.test", PW)
        self.host = User.objects.create_user("host3", "h3@x.test", PW)
        self.c = APIClient()
        self.c.force_authenticate(self.me)

    def rows(self):
        return {b["title"]: b for b in self.c.get("/api/economy/battlez/").data["battles"]}

    def test_entry_counts_are_per_battle_not_pooled(self):
        a = Battle.objects.create(host=self.host, title="A")
        b = Battle.objects.create(host=self.host, title="B")
        BattleEntry.objects.create(battle=a, user=self.host)
        BattleEntry.objects.create(battle=a, user=self.me)
        BattleEntry.objects.create(battle=b, user=self.host)
        rows = self.rows()
        self.assertEqual(rows["A"]["entry_count"], 2)
        self.assertEqual(rows["B"]["entry_count"], 1)

    def test_entered_is_about_me_and_nobody_else(self):
        a = Battle.objects.create(host=self.host, title="A")
        b = Battle.objects.create(host=self.host, title="B")
        BattleEntry.objects.create(battle=a, user=self.me)
        BattleEntry.objects.create(battle=b, user=self.host)
        rows = self.rows()
        self.assertTrue(rows["A"]["entered"])
        self.assertFalse(rows["B"]["entered"])

    def test_an_unrated_battle_is_None_not_zero(self):
        Battle.objects.create(host=self.host, title="A")
        self.assertIsNone(self.rows()["A"]["rating"])

    def test_the_detail_view_still_works_with_nothing_batched(self):
        a = Battle.objects.create(host=self.host, title="A")
        BattleEntry.objects.create(battle=a, user=self.host)
        r = self.c.get(f"/api/economy/battlez/{a.pk}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["entry_count"], 1)


class TheIndexHasAWayBackTests(TestCase):
    """The sync runs from a SWALLOWED signal — an index must never be the
    reason money fails to move — so it can drift, and anything that can drift
    needs a rebuild. Same shape as `rebuild_partnerships`."""

    def setUp(self):
        self.a = User.objects.create_user("ra", "ra@x.test", PW)
        self.b = User.objects.create_user("rb", "rb@x.test", PW)
        self.deal = CollabDeal.objects.create(
            initiator=self.a, title="t",
            participants=[{"username": "ra"}, {"username": "rb"}])

    def run_cmd(self, *args):
        from io import StringIO

        from django.core.management import call_command
        out = StringIO()
        call_command("rebuild_collab_participants", *args, stdout=out)
        return out.getvalue()

    def test_a_dry_run_reports_and_changes_nothing(self):
        CollabParticipant.objects.all().delete()
        text = self.run_cmd()
        self.assertIn("missing          2", text)
        self.assertIn("Dry run", text)
        self.assertEqual(CollabParticipant.objects.count(), 0)

    def test_write_restores_what_drifted_away(self):
        CollabParticipant.objects.all().delete()
        self.run_cmd("--write")
        self.assertEqual(
            set(CollabParticipant.objects.values_list("user__username", flat=True)),
            {"ra", "rb"})

    def test_it_replaces_rather_than_only_adding(self):
        """A row set you can only add to is one a bad write corrupts
        permanently — `rebuild_partnerships` says the same thing."""
        ghost = User.objects.create_user("ghost", "g@x.test", PW)
        CollabParticipant.objects.create(deal=self.deal, user=ghost)
        self.run_cmd("--write")
        self.assertNotIn(
            "ghost",
            set(CollabParticipant.objects.values_list("user__username", flat=True)))

    def test_it_is_idempotent(self):
        self.run_cmd("--write")
        before = set(CollabParticipant.objects.values_list("deal_id", "user_id"))
        self.run_cmd("--write")
        self.assertEqual(
            set(CollabParticipant.objects.values_list("deal_id", "user_id")), before)
