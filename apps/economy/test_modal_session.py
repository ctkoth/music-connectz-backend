"""A sandbox that lives across tool calls.

`run_source()` creates a container, reads it once and throws it away — right for
the Run button, useless for an agent, which needs to write a file, run the
tests, read the failure, edit and run again. Each of those in a fresh container
is a different machine every time.

These tests never reach Modal. They hold the two things that would be expensive
to get wrong: that the network stays blocked on every member session, and that a
container is always closed — including when the agent loop raises.
"""
from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.economy import modal_session
from apps.economy.modal_sandbox import SandboxError
from apps.economy.modal_session import (
    SESSION_MAX_SECONDS,
    SandboxSession,
    session_languages,
)


def fake_proc(stdout="", stderr="", code=0):
    proc = MagicMock()
    proc.stdout.read.return_value = stdout
    proc.stderr.read.return_value = stderr
    proc.returncode = code
    return proc


class Base(TestCase):
    """Every test runs against a faked Modal — the real one is never called."""

    def setUp(self):
        self.sandbox = MagicMock()
        self.sandbox.exec.return_value = fake_proc()
        self.create = patch("modal.Sandbox.create", return_value=self.sandbox).start()
        patch("modal.App.lookup", return_value=MagicMock()).start()
        patch("modal.Image.from_registry", return_value=MagicMock()).start()
        patch.object(modal_session, "configured", return_value=True).start()
        self.addCleanup(patch.stopall)

    def open(self, **kw):
        return SandboxSession(**kw).open()


class TheNetworkStaysBlocked(Base):
    def test_every_session_blocks_the_network(self):
        # A member's code reaching the internet from the platform's Modal
        # account is our outbound traffic wearing their intent. The default has
        # to be the safe one, because a default is what everybody gets.
        self.open()
        self.assertIs(self.create.call_args.kwargs["block_network"], True)

    def test_there_is_no_way_to_ask_for_network_from_the_public_surface(self):
        # Phase 4 opens this for the owner alone, per session, logged. Until
        # then a caller must not be able to talk itself into an open container.
        import inspect
        signature = inspect.signature(SandboxSession.__init__)
        self.assertNotIn("network", signature.parameters)
        self.assertNotIn("block_network", signature.parameters)


class TheContainerIsAlwaysClosed(Base):
    def test_the_context_manager_closes_on_the_way_out(self):
        with SandboxSession() as session:
            pass
        session.sandbox.terminate.assert_called_once()

    def test_the_context_manager_closes_even_when_the_body_raises(self):
        # A leaked sandbox bills until Modal's own timeout reaps it.
        with self.assertRaises(ValueError):
            with SandboxSession() as session:
                raise ValueError("the agent loop fell over")
        session.sandbox.terminate.assert_called_once()

    def test_closing_twice_is_harmless(self):
        session = self.open()
        session.close()
        session.close()
        session.sandbox.terminate.assert_called_once()

    def test_a_terminate_that_fails_does_not_fail_the_run(self):
        session = self.open()
        session.sandbox.terminate.side_effect = RuntimeError("modal is down")
        session.close()          # must not raise
        self.assertIsNotNone(session.closed_at)


class SessionsRefuseToStartWhenTheyCannot(Base):
    def test_an_unconfigured_sandbox_says_why(self):
        with patch.object(modal_session, "configured", return_value=False), \
             patch.object(modal_session, "unavailable_reason",
                          return_value="tokens aren't set"):
            with self.assertRaises(SandboxError) as caught:
                SandboxSession().open()
        self.assertIn("tokens aren't set", str(caught.exception))

    def test_a_container_that_never_came_up_is_an_error_not_a_session(self):
        self.create.side_effect = RuntimeError("no capacity")
        with self.assertRaises(SandboxError):
            SandboxSession().open()

    def test_the_lifetime_is_capped_however_much_is_asked_for(self):
        session = SandboxSession(seconds=10 ** 6)
        self.assertEqual(session.seconds, SESSION_MAX_SECONDS)

    def test_a_nonsense_lifetime_still_produces_a_usable_one(self):
        self.assertEqual(SandboxSession(seconds=0).seconds, 1)
        self.assertEqual(SandboxSession(seconds=-5).seconds, 1)


class CommandsRunAndFailUsefully(Base):
    def test_output_comes_back(self):
        self.sandbox.exec.return_value = fake_proc(stdout="hello\n")
        out = self.open().exec("echo hello")
        self.assertTrue(out["ok"])
        self.assertEqual(out["stdout"], "hello\n")
        self.assertEqual(out["exit_code"], 0)

    def test_a_failing_command_is_a_result_not_an_error(self):
        # A failing test suite is the output the agent asked for — it is the
        # whole reason the container is held open.
        self.sandbox.exec.return_value = fake_proc(stderr="1 failed", code=1)
        out = self.open().exec("pytest")
        self.assertTrue(out["ok"])
        self.assertEqual(out["exit_code"], 1)
        self.assertIn("failed", out["stderr"])

    def test_a_command_that_could_not_run_is_reported_not_raised(self):
        session = self.open()
        session.sandbox.exec.side_effect = RuntimeError("container gone")
        out = session.exec("echo hi")
        self.assertFalse(out["ok"])
        self.assertIn("didn't run", out["error"])

    def test_running_before_opening_is_refused(self):
        with self.assertRaises(SandboxError):
            SandboxSession().exec("echo hi")

    def test_output_is_truncated_rather_than_stored_whole(self):
        from apps.economy.modal_sandbox import MAX_OUTPUT_CHARS
        self.sandbox.exec.return_value = fake_proc(stdout="x" * (MAX_OUTPUT_CHARS * 2))
        out = self.open().exec("yes")
        self.assertEqual(len(out["stdout"]), MAX_OUTPUT_CHARS)


class FilesGoInSafely(Base):
    def test_files_are_written_into_the_container(self):
        result = self.open().materialise([("src/main.py", "print(1)")])
        self.assertEqual(result["written"], ["src/main.py"])
        self.assertEqual(result["refused"], [])

    def test_a_traversal_is_refused_at_this_layer_too(self):
        # The tool executor already checks. This is where a bad path would
        # become a real file outside the root, so it checks again — two gates
        # on one value is cheap, the failure it prevents is not.
        result = self.open().materialise([("../../etc/passwd", "pwned")])
        self.assertEqual(result["written"], [])
        self.assertEqual(result["refused"], ["../../etc/passwd"])
        self.sandbox.exec.assert_not_called()

    def test_a_refused_path_does_not_stop_the_good_ones(self):
        result = self.open().materialise([
            ("../escape.py", "x"), ("main.py", "print(1)")])
        self.assertEqual(result["written"], ["main.py"])
        self.assertIn("../escape.py", result["refused"])

    def test_member_source_is_not_expanded_by_the_shell(self):
        # A quoted heredoc delimiter, same technique run_source uses. Without
        # it, `$(rm -rf /)` in a member's file executes on the way in.
        self.open().materialise([("a.sh", "echo $(whoami) `id` $HOME")])
        script = self.sandbox.exec.call_args.args[-1]
        self.assertIn("<<'MCZ_EOF'", script)


class BillingCountsTheWallClock(Base):
    def test_an_unopened_session_has_no_billable_time(self):
        self.assertEqual(SandboxSession().elapsed_seconds, 0)

    def test_an_open_session_always_bills_at_least_a_second(self):
        self.assertGreaterEqual(self.open().elapsed_seconds, 1)

    def test_time_stops_when_the_session_closes(self):
        session = self.open()
        session.close()
        settled = session.elapsed_seconds
        self.assertEqual(settled, session.elapsed_seconds)


class TheLanguageListIsInherited(TestCase):
    def test_sessions_never_keep_a_second_copy_of_the_language_list(self):
        from apps.economy.modal_sandbox import RUNNERS
        self.assertEqual(session_languages(), sorted(RUNNERS.keys()))
