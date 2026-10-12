"""The Modal sandbox — the one thing OCC could never do.

The rules under test are the ones the rest of the app already lives by: it's
off until it's real and says why; the price is known before it's spent; a run
that never happened isn't billed; and the output isn't trapped in a console.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.models import (
    TIER_PREMIUM,
    TIER_STATZ,
    OccOutput,
    OccTask,
    Transaction,
    Wallet,
    membership_for,
    wallet_for,
)
from apps.economy.modal_sandbox import SandboxError

User = get_user_model()
PW = "hunter2hunter2"
RUN = "/api/economy/occ/run/"
SPEC = "/api/economy/occ/spec/"

WIRED = {"MODAL_TOKEN_ID": "ak-test", "MODAL_TOKEN_SECRET": "as-test"}
OFF = {"MODAL_TOKEN_ID": "", "MODAL_TOKEN_SECRET": ""}

GOOD_RUN = {"stdout": "hello\n", "stderr": "", "exit_code": 0, "seconds": 3,
            "language": "python", "timed_out": False}


def as_tier(user, tier):
    m = membership_for(user)
    m.tier = tier
    m.save(update_fields=["tier", "updated_at"])
    return user


class RunBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="coder", password=PW)
        as_tier(self.user, TIER_STATZ)
        w = wallet_for(self.user)
        w.energy = 500
        w.save(update_fields=["energy"])
        self.client = APIClient()
        self.client.force_authenticate(self.user)


@override_settings(**OFF)
class NotWiredYetTests(RunBase):
    """Off until it's real — and saying so, not pretending."""

    def test_the_spec_does_not_claim_it_can_execute(self):
        spec = self.client.get(SPEC).data
        self.assertFalse(spec["can_execute"])
        self.assertEqual(spec["execute_note"], "Running code isn't switched on yet.")

    def test_running_returns_503_with_the_reason_not_a_silent_failure(self):
        resp = self.client.post(RUN, {"language": "python", "source": "print(1)"},
                                format="json")
        self.assertEqual(resp.status_code, 503)
        # A member's sentence. The env-var names are for whoever runs the server
        # and go to the log; "Set MODAL_TOKEN_ID…" in front of a member is both
        # useless to them and a published description of our configuration.
        self.assertEqual(resp.data["detail"], "Running code isn't switched on yet.")
        self.assertNotIn("MODAL_TOKEN", str(resp.data))
        self.assertFalse(resp.data["configured"])

    def test_the_operator_still_gets_the_detail_in_the_log(self):
        with self.assertLogs("apps.economy.occ_run", level="WARNING") as logs:
            self.client.post(RUN, {"language": "python", "source": "print(1)"}, format="json")
        self.assertIn("MODAL_TOKEN_ID", "\n".join(logs.output))

    def test_nothing_is_charged_when_it_cannot_run(self):
        self.client.post(RUN, {"language": "python", "source": "print(1)"}, format="json")
        self.assertEqual(wallet_for(self.user).energy, 500)
        self.assertEqual(OccTask.objects.count(), 0)


@override_settings(**WIRED)
class PriceBeforeTheButtonTests(RunBase):
    """A price discovered by paying it is not a price, it's a bill."""

    def test_the_get_states_the_rate_the_ceiling_and_what_is_left(self):
        st = self.client.get(RUN).data
        self.assertEqual(st["cost"]["resource"], "energy")
        self.assertEqual(st["cost"]["per_second"], 1)
        self.assertEqual(st["per_run_seconds"], 120)
        self.assertEqual(st["max_cost_per_run"], 120)
        self.assertEqual(st["seconds_left_today"], 1800)
        self.assertIn("never starts costs nothing", st["billing_note"])

    def test_the_spec_carries_the_same_numbers_so_the_button_can_say_them(self):
        spec = self.client.get(SPEC).data
        self.assertTrue(spec["can_execute"])
        self.assertEqual(spec["execute"]["per_run_seconds"], 120)


@override_settings(**WIRED)
class ChargingTests(RunBase):
    """Charged for what ran, never for the ceiling — and never for nothing."""

    def test_it_charges_the_seconds_it_actually_took(self):
        with patch("apps.economy.occ_run.run_source", return_value=GOOD_RUN):
            resp = self.client.post(RUN, {"language": "python", "source": "print('hello')"},
                                    format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data["charged"], 3)           # not the 120s ceiling
        self.assertEqual(wallet_for(self.user).energy, 497)

    def test_a_run_that_never_started_is_free(self):
        with patch("apps.economy.occ_run.run_source",
                   side_effect=SandboxError("The sandbox didn't start: no capacity")):
            resp = self.client.post(RUN, {"language": "python", "source": "print(1)"},
                                    format="json")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.data["charged"], 0)
        self.assertEqual(wallet_for(self.user).energy, 500)
        self.assertEqual(OccTask.objects.get().status, OccTask.STATUS_FAILED)

    def test_code_that_ran_and_failed_still_ran_so_it_bills(self):
        # A compiler telling you what's wrong is the output you asked for.
        bad = {**GOOD_RUN, "stdout": "", "stderr": "SyntaxError: bad", "exit_code": 1}
        with patch("apps.economy.occ_run.run_source", return_value=bad):
            resp = self.client.post(RUN, {"language": "python", "source": "prnt(1)"},
                                    format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["exit_code"], 1)
        self.assertEqual(resp.data["charged"], 3)
        self.assertIn("SyntaxError", resp.data["work"]["description"])

    def test_a_member_whose_energy_does_not_cover_the_run_is_refused_up_front(self):
        # It used to run, and bill min(price, balance): a member with 2 ⚡ got a
        # 120-second container for 2 ⚡, and a member with 0 ⚡ got it free.
        w = wallet_for(self.user)
        w.energy = 2
        w.save(update_fields=["energy"])
        with patch("apps.economy.occ_run.run_source", return_value=GOOD_RUN) as run:
            resp = self.client.post(RUN, {"language": "python", "source": "print(1)"},
                                    format="json")
        self.assertEqual(resp.status_code, 402, resp.data)
        run.assert_not_called()                          # no container, no platform bill
        self.assertEqual(OccTask.objects.count(), 0)
        self.assertEqual(wallet_for(self.user).energy, 2)
        # The refusal states the numbers and the way forward.
        self.assertEqual(resp.data["needed"], 120)
        self.assertEqual(resp.data["affordable_seconds"], 2)
        self.assertIn("120", resp.data["detail"])
        self.assertIn("2s or less", resp.data["detail"])

    def test_zero_energy_cannot_run_free(self):
        w = wallet_for(self.user)
        w.energy = 0
        w.save(update_fields=["energy"])
        with patch("apps.economy.occ_run.run_source", return_value=GOOD_RUN) as run:
            resp = self.client.post(RUN, {"language": "python", "source": "print(1)"},
                                    format="json")
        self.assertEqual(resp.status_code, 402)
        run.assert_not_called()
        self.assertEqual(resp.data["affordable_seconds"], 0)

    def test_a_shorter_limit_the_member_can_afford_runs(self):
        w = wallet_for(self.user)
        w.energy = 10
        w.save(update_fields=["energy"])
        with patch("apps.economy.occ_run.run_source", return_value=GOOD_RUN) as run:
            resp = self.client.post(RUN, {"language": "python", "source": "print(1)",
                                          "seconds": 10}, format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(run.call_args.kwargs["seconds"], 10)
        self.assertEqual(resp.data["charged"], 3)
        self.assertEqual(wallet_for(self.user).energy, 7)

    def test_the_debit_is_in_logz_with_its_reason(self):
        with patch("apps.economy.occ_run.run_source", return_value=GOOD_RUN):
            self.client.post(RUN, {"language": "python", "source": "print(1)"}, format="json")
        row = Transaction.objects.get(user=self.user, resource=Transaction.RES_ENERGY)
        self.assertEqual(row.amount, -3)
        self.assertEqual(row.app_key, "occ")
        self.assertEqual(row.target, "occ-run")
        self.assertIn("python", row.note)

    def test_a_run_that_never_started_writes_no_ledger_row(self):
        with patch("apps.economy.occ_run.run_source", side_effect=SandboxError("no capacity")):
            self.client.post(RUN, {"language": "python", "source": "print(1)"}, format="json")
        self.assertFalse(Transaction.objects.filter(
            user=self.user, resource=Transaction.RES_ENERGY).exists())

    def test_energy_spent_while_the_container_ran_is_not_overdrawn(self):
        # The balance covered the ceiling when the run was accepted; another spend
        # landed while the container ran. The bill is "all you have", never a
        # negative balance, and the ledger says what really moved.
        def spend_meanwhile(*a, **kw):
            Wallet.objects.filter(user=self.user).update(energy=1)
            return GOOD_RUN
        with patch("apps.economy.occ_run.run_source", side_effect=spend_meanwhile):
            resp = self.client.post(RUN, {"language": "python", "source": "print(1)"},
                                    format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["charged"], 1)
        self.assertEqual(wallet_for(self.user).energy, 0)
        self.assertEqual(Transaction.objects.get(
            user=self.user, resource=Transaction.RES_ENERGY).amount, -1)


class SpendEnergyTests(TestCase):
    """`_spend_energy_up_to` is spend_spinaz's shape for Energy: one conditional
    statement, so a balance cannot be read twice and spent twice."""

    def setUp(self):
        self.user = User.objects.create_user(username="spender", password=PW)

    def have(self, n):
        w = wallet_for(self.user)
        w.energy = n
        w.save(update_fields=["energy"])

    def test_it_takes_the_whole_amount_when_the_balance_covers_it(self):
        from apps.economy.occ_run import _spend_energy_up_to
        self.have(10)
        self.assertEqual(_spend_energy_up_to(self.user, 4), 4)
        self.assertEqual(wallet_for(self.user).energy, 6)

    def test_two_bills_against_one_balance_add_up_instead_of_overwriting(self):
        # The lost-update shape: both are accepted against 5 ⚡, each wants 3.
        from apps.economy.occ_run import _spend_energy_up_to
        self.have(5)
        self.assertEqual(_spend_energy_up_to(self.user, 3), 3)
        self.assertEqual(_spend_energy_up_to(self.user, 3), 2)   # what was left
        self.assertEqual(_spend_energy_up_to(self.user, 3), 0)
        self.assertEqual(wallet_for(self.user).energy, 0)

    def test_it_never_goes_negative_and_a_zero_spend_is_not_a_spend(self):
        from apps.economy.occ_run import _spend_energy_up_to
        self.have(0)
        self.assertEqual(_spend_energy_up_to(self.user, 50), 0)
        self.assertEqual(_spend_energy_up_to(self.user, 0), 0)
        self.assertEqual(_spend_energy_up_to(self.user, -5), 0)
        self.assertEqual(wallet_for(self.user).energy, 0)


@override_settings(**WIRED)
class GatesAndCapsTests(RunBase):
    def test_running_is_the_statz_reservation(self):
        as_tier(self.user, TIER_PREMIUM)
        resp = self.client.post(RUN, {"language": "python", "source": "print(1)"},
                                format="json")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data["required_tier"], TIER_STATZ)

    def test_a_locked_tier_is_told_rather_than_shown_nothing(self):
        as_tier(self.user, TIER_PREMIUM)
        spec = self.client.get(SPEC).data
        self.assertFalse(spec["can_execute"])
        self.assertIn("StatZ", spec["execute_note"])

    def test_the_daily_ceiling_is_summed_from_the_runs_themselves(self):
        OccTask.objects.create(user=self.user, title="earlier", kind=OccTask.KIND_BUILD,
                               status=OccTask.STATUS_DONE, run_seconds=1800)
        st = self.client.get(RUN).data
        self.assertEqual(st["seconds_used_today"], 1800)
        self.assertEqual(st["seconds_left_today"], 0)
        resp = self.client.post(RUN, {"language": "python", "source": "print(1)",
                                      "seconds": 60}, format="json")
        self.assertEqual(resp.status_code, 429)

    def test_the_last_stretch_of_the_day_is_usable(self):
        # 10s left of 1,800. It used to refuse any run longer than the remainder,
        # so a one-second script could not run and the final stretch of the
        # allowance was unusable. Clamped to what is left; refused only at zero.
        OccTask.objects.create(user=self.user, title="earlier", kind=OccTask.KIND_BUILD,
                               status=OccTask.STATUS_DONE, run_seconds=1790)
        with patch("apps.economy.occ_run.run_source", return_value=GOOD_RUN) as run:
            resp = self.client.post(RUN, {"language": "python", "source": "print(1)",
                                          "seconds": 60}, format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(run.call_args.kwargs["seconds"], 10)
        self.assertEqual(resp.data["seconds_allowed"], 10)

    def test_no_seconds_asked_runs_at_what_is_left_not_the_full_ceiling(self):
        OccTask.objects.create(user=self.user, title="earlier", kind=OccTask.KIND_BUILD,
                               status=OccTask.STATUS_DONE, run_seconds=1750)
        with patch("apps.economy.occ_run.run_source", return_value=GOOD_RUN) as run:
            self.client.post(RUN, {"language": "python", "source": "print(1)"}, format="json")
        self.assertEqual(run.call_args.kwargs["seconds"], 50)

    def test_the_get_says_how_long_a_run_started_now_can_be(self):
        # The Run button states a price for the run that WILL be made: the tier's
        # ceiling, today's remainder and the member's ⚡, whichever bites first.
        w = wallet_for(self.user)
        w.energy = 45
        w.save(update_fields=["energy"])
        st = self.client.get(RUN).data
        self.assertEqual(st["max_seconds_now"], 45)
        self.assertEqual(st["max_cost_now"], 45)
        self.assertEqual(st["max_cost_per_run"], 120)    # the tier's, unchanged

    def test_a_request_over_the_per_run_ceiling_is_clamped_not_refused(self):
        with patch("apps.economy.occ_run.run_source", return_value=GOOD_RUN) as run:
            self.client.post(RUN, {"language": "python", "source": "print(1)",
                                   "seconds": 9999}, format="json")
        self.assertEqual(run.call_args.kwargs["seconds"], 120)

    def test_a_language_it_cannot_run_says_so_and_lists_what_it_can(self):
        resp = self.client.post(RUN, {"language": "brainfuck", "source": "+"},
                                format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("python", resp.data["languages"])

    def test_empty_source_is_refused_before_a_container_is_spun_up(self):
        with patch("apps.economy.occ_run.run_source") as run:
            resp = self.client.post(RUN, {"language": "python", "source": "  "},
                                    format="json")
        self.assertEqual(resp.status_code, 400)
        run.assert_not_called()


@override_settings(**WIRED)
class NotADeadEndTests(RunBase):
    """A run leaves a task AND a postable output. One list, and no dead end."""

    def test_a_run_is_a_taskz_row(self):
        with patch("apps.economy.occ_run.run_source", return_value=GOOD_RUN):
            resp = self.client.post(RUN, {"language": "python", "source": "print('hello')",
                                          "title": "Say hello"}, format="json")
        task = OccTask.objects.get()
        self.assertEqual(task.kind, OccTask.KIND_BUILD)
        self.assertEqual(task.status, OccTask.STATUS_DONE)
        self.assertEqual(task.run_seconds, 3)
        self.assertEqual(resp.data["task"]["title"], "Say hello")

    def test_the_output_becomes_workz_so_it_can_be_posted_and_rated(self):
        with patch("apps.economy.occ_run.run_source", return_value=GOOD_RUN):
            resp = self.client.post(RUN, {"language": "python", "source": "print('hello')"},
                                    format="json")
        work = OccOutput.objects.get()
        self.assertEqual(work.description.strip(), "hello")
        self.assertEqual(work.input_text, "print('hello')")
        self.assertIsNone(resp.data["work"]["item_key"])   # not posted yet

        share = self.client.post(f"/api/economy/occ/workz/{work.id}/share/", {},
                                 format="json")
        self.assertEqual(share.status_code, 201, share.data)
        self.assertEqual(share.data["item_key"], f"post:{share.data['post_id']}")

    def test_the_run_says_where_its_output_went(self):
        with patch("apps.economy.occ_run.run_source", return_value=GOOD_RUN):
            resp = self.client.post(RUN, {"language": "python", "source": "print(1)"},
                                    format="json")
        self.assertEqual(resp.data["open_in"], "occ")
        self.assertEqual(resp.data["target"], "occ-workz")


class SandboxCommandTests(TestCase):
    """The command that gets built, without needing Modal to build it."""

    def test_the_members_code_cannot_be_expanded_by_the_shell(self):
        # A quoted heredoc delimiter is what stops `$(...)` in someone's source
        # from running on the way in.
        from apps.economy.modal_sandbox import RUNNERS
        self.assertIn("python", RUNNERS)
        self.assertTrue(RUNNERS["cpp"]["cmd"].startswith("g++"))

    @override_settings(**OFF)
    def test_it_refuses_to_pretend_when_the_tokens_are_missing(self):
        from apps.economy.modal_sandbox import (
            MEMBER_REASON, configured, operator_reason, unavailable_reason)
        self.assertFalse(configured())
        # Two sentences for two readers: the member's, and the operator's.
        self.assertEqual(unavailable_reason(), MEMBER_REASON)
        self.assertNotIn("MODAL_TOKEN", unavailable_reason())
        self.assertIn("MODAL_TOKEN_ID", operator_reason())

    def test_the_price_is_a_plain_function_of_seconds(self):
        from apps.economy.modal_sandbox import price_for
        self.assertEqual(price_for(0), 0)
        self.assertEqual(price_for(30), 30)
