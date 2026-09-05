"""CallZ — the rate before it connects, and the money after it ends.

CallZ was sold at StatZ and did not exist: LessonZ's "CallZ" was a delivery
method on a booking, priced identically to remote and in-person. `CLAUDE.md`
has carried it as an open cost/gain violation the whole time for one reason —

    the other member's rate has to be visible before it connects

— and there was no rate to state because there was no call.

These tests are mostly about money, because that is the part that can go wrong
quietly: escrow taken for a call nobody answered, escrow held forever by a
closed tab, a rate that moves while somebody is talking, a caller billed twice
because both ends pressed End.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.callz import (CALL_STALE_SECONDS, MAX_ESCROW_MINUTES,
                                cost_for_seconds, rate_per_min_cents)
from apps.economy.models import (Block, Call, TIER_FREE, TIER_STATZ,
                                 membership_for, profile_for, wallet_for)

User = get_user_model()
PW = "hunter2hunter2"


def priced(user, cents_per_hour):
    p = profile_for(user)
    p.personas = [{"key": "producer", "name": "Producer",
                   "skills": [{"name": "Mixing", "rate_cents": cents_per_hour}]}]
    p.save(update_fields=["personas"])
    return user


def tier(user, t):
    m = membership_for(user)
    m.tier = t
    m.save(update_fields=["tier"])
    return user


def fund(user, cents):
    w = wallet_for(user)
    w.money_cents = cents
    w.save(update_fields=["money_cents"])
    return w


class Base(TestCase):
    def setUp(self):
        self.caller = tier(User.objects.create_user("caller", "c@e.com", PW), TIER_STATZ)
        self.callee = priced(User.objects.create_user("callee", "e@e.com", PW), 6000)  # $60/hr
        fund(self.caller, 100_00)
        self.c = APIClient(); self.c.force_authenticate(self.caller)
        self.e = APIClient(); self.e.force_authenticate(self.callee)

    def ring(self):
        return self.c.post("/api/economy/callz/", {"username": "callee", "offer_sdp": "OFFER"},
                           format="json")

    def answer(self, pk):
        return self.e.post(f"/api/economy/callz/{pk}/answer/", {"answer_sdp": "ANSWER"},
                           format="json")


class ThePriceIsVisibleBeforeItConnects(Base):
    def test_the_rate_answers_the_whole_question(self):
        d = self.c.get("/api/economy/callz/rate/callee/").data
        self.assertEqual(d["rate_cents_per_min"], 100)          # $60/hr -> 100c/min
        self.assertEqual(d["your_money_cents"], 100_00)
        self.assertEqual(d["affordable_minutes"], 100)
        self.assertTrue(d["can_call"])

    def test_a_member_who_has_priced_nothing_is_free(self):
        # Their rate is what makes it cost, and they have not set one. A call
        # with them should connect, not refuse.
        nobody = User.objects.create_user("nobody", "n@e.com", PW)
        self.assertEqual(rate_per_min_cents(nobody), 0)
        d = self.c.get("/api/economy/callz/rate/nobody/").data
        self.assertTrue(d["free"])
        self.assertIsNone(d["affordable_minutes"])

    def test_the_rate_is_snapshot_at_ring_and_cannot_move_mid_call(self):
        pk = self.ring().data["id"]
        priced(self.callee, 600_00)                              # they raise it 10x
        self.assertEqual(Call.objects.get(pk=pk).rate_cents_per_min, 100)

    def test_a_caller_who_cannot_cover_a_minute_is_refused_before_it_rings(self):
        # Being cut off mid-sentence for money is worse than being told first.
        fund(self.caller, 50)
        r = self.ring()
        self.assertEqual(r.status_code, 402)
        self.assertEqual(r.data["rate_cents_per_min"], 100)
        self.assertFalse(Call.objects.exists())

    def test_the_ice_servers_say_they_are_stun_only(self):
        # Calls between two symmetric NATs need a TURN relay, which is a paid
        # service and is not configured. Saying so beats a mystery failure.
        d = self.c.get("/api/economy/callz/rate/callee/").data
        self.assertTrue(d["stun_only"])
        self.assertTrue(d["ice_servers"])


class TheGate(Base):
    def test_placing_a_call_is_the_statz_perk(self):
        tier(self.caller, TIER_FREE)
        r = self.ring()
        self.assertEqual(r.status_code, 403)

    def test_receiving_one_is_free_at_every_tier(self):
        # Gating both sides would mean nobody can ever call anybody, and the
        # receiving side is the side that gets PAID.
        tier(self.callee, TIER_FREE)
        pk = self.ring().data["id"]
        self.assertEqual(self.answer(pk).status_code, 200)

    def test_a_blocked_member_cannot_be_called(self):
        Block.objects.create(blocker=self.callee, blocked=self.caller)
        self.assertEqual(self.ring().status_code, 403)
        self.assertEqual(self.c.get("/api/economy/callz/rate/callee/").status_code, 403)


class TheMoney(Base):
    def test_nobody_pays_for_a_call_that_was_never_answered(self):
        self.ring()
        self.assertEqual(wallet_for(self.caller).money_cents, 100_00)

    def test_declining_costs_nothing(self):
        pk = self.ring().data["id"]
        self.e.post(f"/api/economy/callz/{pk}/decline/", {}, format="json")
        self.assertEqual(wallet_for(self.caller).money_cents, 100_00)
        self.assertEqual(Call.objects.get(pk=pk).status, Call.STATUS_DECLINED)

    def test_escrow_is_taken_on_answer_and_bounded(self):
        pk = self.ring().data["id"]
        self.answer(pk)
        call = Call.objects.get(pk=pk)
        self.assertEqual(call.held_cents, 100 * MAX_ESCROW_MINUTES)
        self.assertEqual(wallet_for(self.caller).money_cents, 100_00 - call.held_cents)

    def test_ending_bills_the_seconds_and_returns_the_rest(self):
        pk = self.ring().data["id"]
        self.answer(pk)
        call = Call.objects.get(pk=pk)
        call.started_at = timezone.now() - timezone.timedelta(seconds=90)
        call.save(update_fields=["started_at"])

        self.c.post(f"/api/economy/callz/{pk}/end/", {}, format="json")
        call.refresh_from_db()
        self.assertEqual(call.status, Call.STATUS_ENDED)
        self.assertEqual(call.charged_cents, 150)        # 90s at 100c/min
        self.assertEqual(call.held_cents, 0)
        # Caller is out exactly what the call cost, and no more.
        self.assertEqual(wallet_for(self.caller).money_cents, 100_00 - 150)

    def test_the_callee_is_paid_net_of_the_developer_tax(self):
        pk = self.ring().data["id"]
        self.answer(pk)
        call = Call.objects.get(pk=pk)
        call.started_at = timezone.now() - timezone.timedelta(seconds=60)
        call.save(update_fields=["started_at"])
        self.c.post(f"/api/economy/callz/{pk}/end/", {}, format="json")
        paid = wallet_for(self.callee).money_cents
        self.assertGreater(paid, 0)
        self.assertLessEqual(paid, 100)                  # 100c gross, less the tax

    def test_both_ends_pressing_end_bills_once(self):
        pk = self.ring().data["id"]
        self.answer(pk)
        call = Call.objects.get(pk=pk)
        call.started_at = timezone.now() - timezone.timedelta(seconds=60)
        call.save(update_fields=["started_at"])
        self.c.post(f"/api/economy/callz/{pk}/end/", {}, format="json")
        after = wallet_for(self.caller).money_cents
        self.e.post(f"/api/economy/callz/{pk}/end/", {}, format="json")
        self.assertEqual(wallet_for(self.caller).money_cents, after)

    def test_a_free_call_moves_no_money_and_still_connects(self):
        free = User.objects.create_user("free", "f@e.com", PW)
        fc = APIClient(); fc.force_authenticate(free)
        r = self.c.post("/api/economy/callz/", {"username": "free"}, format="json")
        pk = r.data["id"]
        self.assertEqual(fc.post(f"/api/economy/callz/{pk}/answer/", {}, format="json").status_code, 200)
        self.assertEqual(Call.objects.get(pk=pk).held_cents, 0)
        self.assertEqual(wallet_for(self.caller).money_cents, 100_00)

    def test_a_closed_tab_does_not_hold_escrow_forever(self):
        pk = self.ring().data["id"]
        self.answer(pk)
        call = Call.objects.get(pk=pk)
        stale = timezone.now() - timezone.timedelta(seconds=CALL_STALE_SECONDS + 30)
        Call.objects.filter(pk=pk).update(started_at=stale, last_seen_at=stale)

        self.c.get("/api/economy/callz/")            # any read settles it
        call.refresh_from_db()
        self.assertEqual(call.status, Call.STATUS_ENDED)
        self.assertEqual(call.held_cents, 0)
        self.assertIn("connection lost", call.end_reason)
        # Billed for the time it actually ran, and the rest returned.
        self.assertEqual(wallet_for(self.caller).money_cents,
                         100_00 - call.charged_cents)

    def test_the_charge_is_prorated_by_the_second(self):
        self.assertEqual(cost_for_seconds(100, 30), 50)
        self.assertEqual(cost_for_seconds(100, 1), 2)      # rounds up to the cent
        self.assertEqual(cost_for_seconds(0, 600), 0)


class TheHandshake(Base):
    def test_each_side_reads_the_other_half(self):
        pk = self.ring().data["id"]
        # The callee sees the offer; the caller does not read back its own.
        self.assertEqual(self.e.get(f"/api/economy/callz/{pk}/").data["offer_sdp"], "OFFER")
        self.assertEqual(self.c.get(f"/api/economy/callz/{pk}/").data["offer_sdp"], "")
        self.answer(pk)
        self.assertEqual(self.c.get(f"/api/economy/callz/{pk}/").data["answer_sdp"], "ANSWER")

    def test_ice_goes_into_your_own_bucket_and_out_of_theirs(self):
        pk = self.ring().data["id"]
        self.c.post(f"/api/economy/callz/{pk}/ice/",
                    {"candidates": [{"candidate": "a"}]}, format="json")
        self.assertEqual(self.e.get(f"/api/economy/callz/{pk}/").data["remote_ice"],
                         [{"candidate": "a"}])
        self.assertEqual(self.c.get(f"/api/economy/callz/{pk}/").data["remote_ice"], [])

    def test_a_stranger_cannot_read_somebody_else_s_call(self):
        pk = self.ring().data["id"]
        nosy = APIClient()
        nosy.force_authenticate(User.objects.create_user("nosy", "x@e.com", PW))
        self.assertEqual(nosy.get(f"/api/economy/callz/{pk}/").status_code, 404)

    def test_only_the_callee_may_answer(self):
        pk = self.ring().data["id"]
        self.assertEqual(self.c.post(f"/api/economy/callz/{pk}/answer/", {}, format="json").status_code, 403)

    def test_you_cannot_ring_while_already_on_a_call(self):
        self.ring()
        self.assertEqual(self.ring().status_code, 409)

    def test_the_running_cost_is_visible_during_the_call(self):
        pk = self.ring().data["id"]
        self.answer(pk)
        Call.objects.filter(pk=pk).update(
            started_at=timezone.now() - timezone.timedelta(seconds=120))
        d = self.c.get(f"/api/economy/callz/{pk}/").data
        self.assertGreaterEqual(d["elapsed_seconds"], 120)
        self.assertEqual(d["cost_cents"], 200)
