"""Building a game, and serving it without letting it read the app.

The serving half is the one with teeth. A game is member-authored JavaScript;
served from the app's own origin it can read another member's session. So the
tests that matter most here are the ones asserting what every bundle response
carries — and, just as importantly, what it never carries.
"""
import io
import zipfile
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import gamez_build
from apps.economy.gamez_build import MAX_BUNDLE_MB, build_game, bundle_csp
from apps.economy.models import (
    TIER_PREMIUM,
    TIER_STATZ,
    Game,
    OccFile,
    Upload,
    membership_for,
    wallet_for,
)

User = get_user_model()
PW = "hunter2hunter2"


def zip_of(files):
    blob = io.BytesIO()
    with zipfile.ZipFile(blob, "w") as zf:
        for path, data in files.items():
            zf.writestr(path, data)
    return blob.getvalue()


class Base(TestCase):
    tier = TIER_STATZ

    def setUp(self):
        self.user = User.objects.create_user("dev", "d@e.com", PW)
        m = membership_for(self.user)
        m.tier = self.tier
        m.save()
        w = wallet_for(self.user)
        w.energy = 5_000
        w.save()
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.game = Game.objects.create(user=self.user, title="Cave Runner",
                                        project="main")

    def source(self, path, content):
        return OccFile.objects.create(user=self.user, project="main",
                                      path=path, content=content)

    def playable(self, files=None):
        """A game with a real bundle behind it."""
        files = files or {"index.html": "<h1>hi</h1>", "main.js": "console.log(1)"}
        self.game.bundle.save("b.zip", ContentFile(zip_of(files)), save=False)
        self.game.status = Game.STATUS_PLAYABLE
        self.game.entry = "index.html"
        self.game.save()
        return self.game


class BuildingWithoutAContainer(Base):
    """Most small web games have no build step — the files ARE the game."""

    def test_a_project_with_no_build_command_zips_straight_out(self):
        self.source("index.html", "<h1>Cave Runner</h1>")
        self.source("main.js", "start()")
        result = build_game(self.game)
        self.assertTrue(result["ok"])
        self.assertEqual(result["entry"], "index.html")
        self.game.refresh_from_db()
        self.assertTrue(self.game.playable)

    def test_packaging_without_a_command_is_free(self):
        # A sandbox for a job with no compiler in it would be theatre — and a
        # charge for it would be a charge for nothing.
        self.source("index.html", "<h1>hi</h1>")
        before = wallet_for(self.user).energy
        result = build_game(self.game)
        self.assertEqual(result["charged"], 0)
        self.assertEqual(wallet_for(self.user).energy, before)

    def test_the_bundle_actually_contains_the_files(self):
        self.source("index.html", "<h1>hi</h1>")
        self.source("js/main.js", "start()")
        build_game(self.game)
        self.game.refresh_from_db()
        with zipfile.ZipFile(self.game.bundle) as zf:
            self.assertEqual(sorted(zf.namelist()), ["index.html", "js/main.js"])

    def test_binary_assets_are_merged_in(self):
        self.source("index.html", "<img src=hero.png>")
        upload = Upload.objects.create(
            user=self.user, file=SimpleUploadedFile("hero.png", b"\x89PNG\r\n"),
            name="hero.png", size_bytes=6)
        self.game.assets.create(upload=upload, path="hero.png")
        build_game(self.game)
        self.game.refresh_from_db()
        with zipfile.ZipFile(self.game.bundle) as zf:
            self.assertEqual(zf.read("hero.png"), b"\x89PNG\r\n")

    def test_a_game_with_no_index_html_is_refused_with_a_reason(self):
        self.source("main.js", "start()")
        result = build_game(self.game)
        self.assertFalse(result["ok"])
        self.assertIn("index.html", result["detail"])
        self.game.refresh_from_db()
        self.assertEqual(self.game.status, Game.STATUS_FAILED)
        self.assertFalse(self.game.playable)

    def test_an_empty_project_says_so_rather_than_building_nothing(self):
        result = build_game(self.game)
        self.assertFalse(result["ok"])
        self.assertIn("nothing", result["detail"].lower())

    def test_the_shallowest_index_html_wins(self):
        self.source("deep/nested/index.html", "wrong")
        self.source("index.html", "right")
        self.assertEqual(build_game(self.game)["entry"], "index.html")

    def test_rebuilding_replaces_the_bundle_rather_than_piling_up(self):
        # Asserts the CONTENT is the new build, not that the filename changed —
        # two builds in the same second reuse the name, which is harmless
        # because the old file is deleted first and the play URL never contains
        # it. What would not be harmless is the old content surviving.
        self.source("index.html", "one")
        build_game(self.game)
        self.source("extra.js", "two")
        build_game(self.game)
        self.game.refresh_from_db()
        with zipfile.ZipFile(self.game.bundle) as zf:
            self.assertIn("extra.js", zf.namelist())
            self.assertEqual(zf.read("index.html"), b"one")


class BuildingWithAContainer(Base):
    def test_a_build_command_needs_the_sandbox_tier(self):
        self.game.build_command = "npm run build"
        self.game.save()
        m = membership_for(self.user)
        m.tier = TIER_PREMIUM
        m.save()
        with patch.object(gamez_build, "sandbox_configured", return_value=True):
            resp = self.client.post(f"/api/economy/gamez/{self.game.id}/build/",
                                    {}, format="json")
        self.assertEqual(resp.status_code, 403)
        self.assertIn("StatZ", resp.json()["detail"])

    def test_an_unconfigured_sandbox_is_a_503_that_says_why(self):
        self.game.build_command = "npm run build"
        self.game.save()
        resp = self.client.post(f"/api/economy/gamez/{self.game.id}/build/",
                                {}, format="json")
        self.assertEqual(resp.status_code, 503)
        self.assertIn("sandbox", resp.json()["detail"].lower())

    def test_a_sandbox_that_never_started_is_not_billed(self):
        from apps.economy.modal_sandbox import SandboxError
        self.game.build_command = "npm run build"
        self.source("index.html", "hi")
        before = wallet_for(self.user).energy
        with patch.object(gamez_build.SandboxSession, "open",
                          side_effect=SandboxError("no capacity")):
            result = build_game(self.game)
        self.assertFalse(result["ok"])
        self.assertEqual(result["charged"], 0)
        self.assertEqual(wallet_for(self.user).energy, before)

    def test_a_failing_build_reports_the_output_and_does_not_go_playable(self):
        self.game.build_command = "npm run build"
        self.source("index.html", "hi")
        session = MagicMock()
        session.exec.return_value = {"ok": True, "exit_code": 1,
                                     "stdout": "", "stderr": "Module not found"}
        session.elapsed_seconds = 3
        session.workdir = "/work"
        with patch.object(gamez_build, "SandboxSession", return_value=session):
            result = build_game(self.game)
        self.assertFalse(result["ok"])
        self.assertIn("Module not found", result["detail"])
        self.game.refresh_from_db()
        self.assertEqual(self.game.status, Game.STATUS_FAILED)


class TheGetStatesThePriceFirst(Base):
    def test_a_no_command_build_says_it_is_free(self):
        d = self.client.get(f"/api/economy/gamez/{self.game.id}/build/").json()
        self.assertFalse(d["needs_sandbox"])
        self.assertIsNone(d["cost"])
        self.assertIn("free", d["billing_note"].lower())

    def test_a_command_build_states_the_per_second_rate(self):
        self.game.build_command = "npm run build"
        self.game.save()
        d = self.client.get(f"/api/economy/gamez/{self.game.id}/build/").json()
        self.assertTrue(d["needs_sandbox"])
        self.assertEqual(d["cost"]["resource"], "energy")

    def test_the_no_network_constraint_is_stated_up_front(self):
        # Otherwise a member discovers it when `npm install` hangs.
        d = self.client.get(f"/api/economy/gamez/{self.game.id}/build/").json()
        self.assertIn("npm install", d["network_note"])


class ServingIsSandboxed(Base):
    """The half with teeth."""

    def test_every_response_carries_a_csp_sandbox(self):
        self.playable()
        resp = self.client.get(f"/api/economy/gamez/{self.game.id}/play/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("sandbox", resp["Content-Security-Policy"])

    def test_allow_same_origin_is_never_sent(self):
        # Paired with allow-scripts it lets the document remove its own sandbox,
        # which would make the whole header decorative.
        self.assertIn("allow-scripts", bundle_csp())
        self.assertNotIn("allow-same-origin", bundle_csp())

    def test_the_policy_is_on_the_response_not_just_an_iframe_attribute(self):
        # An iframe attribute protects the frame our app renders and does
        # nothing when somebody opens the bundle URL directly. This test IS
        # that scenario — a direct GET, no iframe anywhere.
        self.playable()
        resp = self.client.get(f"/api/economy/gamez/{self.game.id}/play/index.html")
        self.assertIn("sandbox allow-scripts", resp["Content-Security-Policy"])

    def test_a_rebuilt_game_is_not_served_from_a_stale_cache(self):
        # The play URL carries no bundle name or version, so a max-age here
        # would show a member their old game after they rebuilt it, with
        # nothing on screen to explain why.
        self.playable()
        resp = self.client.get(f"/api/economy/gamez/{self.game.id}/play/")
        self.assertIn("no-cache", resp["Cache-Control"])
        self.assertIn("private", resp["Cache-Control"])

    def test_the_etag_changes_when_the_game_is_rebuilt(self):
        from django.utils import timezone
        self.playable()
        self.game.built_at = timezone.now()
        self.game.save()
        first = self.client.get(f"/api/economy/gamez/{self.game.id}/play/")["ETag"]
        self.game.built_at = timezone.now() + timezone.timedelta(minutes=5)
        self.game.save()
        second = self.client.get(f"/api/economy/gamez/{self.game.id}/play/")["ETag"]
        self.assertNotEqual(first, second)

    def test_sniffing_is_turned_off(self):
        self.playable()
        resp = self.client.get(f"/api/economy/gamez/{self.game.id}/play/")
        self.assertEqual(resp["X-Content-Type-Options"], "nosniff")

    def test_files_come_back_with_their_own_content_type(self):
        self.playable()
        resp = self.client.get(f"/api/economy/gamez/{self.game.id}/play/main.js")
        self.assertIn("javascript", resp["Content-Type"])

    def test_the_entry_page_is_served_when_no_path_is_given(self):
        self.playable()
        resp = self.client.get(f"/api/economy/gamez/{self.game.id}/play/")
        self.assertIn(b"<h1>hi</h1>", resp.content)

    def test_a_missing_file_is_a_404_not_the_entry_page(self):
        # A missing sprite.png answered with index.html is a 200 carrying the
        # wrong content type — far more confusing for a game than a plain 404.
        self.playable()
        resp = self.client.get(f"/api/economy/gamez/{self.game.id}/play/sprite.png")
        self.assertEqual(resp.status_code, 404)


class ServingIsScoped(Base):
    def test_an_unbuilt_game_has_nothing_to_play(self):
        resp = self.client.get(f"/api/economy/gamez/{self.game.id}/play/")
        self.assertEqual(resp.status_code, 404)

    def test_another_members_unshared_game_is_not_playable(self):
        # A bundle URL is not a capability to hand out.
        self.playable()
        other = User.objects.create_user("other", "o@e.com", PW)
        membership_for(other)
        theirs = APIClient()
        theirs.force_authenticate(other)
        self.assertEqual(
            theirs.get(f"/api/economy/gamez/{self.game.id}/play/").status_code, 404)

    def test_anonymous_callers_are_turned_away(self):
        self.playable()
        self.assertEqual(
            APIClient().get(f"/api/economy/gamez/{self.game.id}/play/").status_code,
            401)

    def test_a_traversal_in_the_requested_path_cannot_escape_the_bundle(self):
        self.playable()
        resp = self.client.get(
            f"/api/economy/gamez/{self.game.id}/play/../../etc/passwd")
        # Normalised away, so it falls back to the entry page rather than
        # reaching anything. Either way it must not 200 with something else.
        self.assertIn(resp.status_code, (200, 404))
        if resp.status_code == 200:
            self.assertIn(b"<h1>hi</h1>", resp.content)

    def test_a_traversal_baked_into_the_bundle_is_filtered_out(self):
        # A bundle is built from member paths, so it can contain `..` entries.
        self.playable({"index.html": "hi", "../escape.txt": "pwned"})
        with zipfile.ZipFile(self.game.bundle) as zf:
            self.assertIn("../escape.txt", zf.namelist())
        safe = gamez_build._safe_members(["../escape.txt", "index.html"])
        self.assertNotIn("../escape.txt", safe.values())
        self.assertIn("index.html", safe)

    def test_a_corrupt_bundle_says_rebuild_rather_than_500ing_silently(self):
        self.game.bundle.save("b.zip", ContentFile(b"not a zip"), save=False)
        self.game.status = Game.STATUS_PLAYABLE
        self.game.save()
        resp = self.client.get(f"/api/economy/gamez/{self.game.id}/play/")
        self.assertEqual(resp.status_code, 500)
        self.assertIn("Rebuild", resp.json()["detail"])

    def test_playing_the_entry_counts_a_play(self):
        self.playable()
        self.client.get(f"/api/economy/gamez/{self.game.id}/play/")
        self.game.refresh_from_db()
        self.assertEqual(self.game.plays, 1)


class TheBundleHasACeiling(Base):
    def test_a_bundle_over_the_cap_is_refused(self):
        # Zipped, so the content has to be incompressible to actually exceed it.
        import os
        self.source("index.html", "hi")
        big = Upload.objects.create(
            user=self.user,
            file=SimpleUploadedFile("big.bin", os.urandom(1024)),
            name="big.bin", size_bytes=1024)
        self.game.assets.create(upload=big, path="big.bin")
        with patch.object(gamez_build, "MAX_BUNDLE_MB", 0):
            result = build_game(self.game)
        self.assertFalse(result["ok"])
        self.assertIn("limit", result["detail"].lower())
        self.game.refresh_from_db()
        self.assertFalse(self.game.playable)

    def test_the_cap_is_published_so_the_screen_can_state_it(self):
        d = self.client.get(f"/api/economy/gamez/{self.game.id}/build/").json()
        self.assertEqual(d["max_bundle_mb"], MAX_BUNDLE_MB)
