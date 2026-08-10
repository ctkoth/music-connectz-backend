"""BugZ 🐞 — the endpoint the screen has been calling into thin air.

The page shipped with a form, a queue and a "Squashed = 200 SpinaZ" line, and
`/api/bugz/` was served by nothing. Every report 404'd, so the bounty on the
page was a promise with no code behind it. These tests hold the promise.
"""
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import (
    BUG_BOUNTY_SPINAZ,
    BUG_MAX_MB,
    Badge,
    BugReport,
    membership_for,
    wallet_for,
)

User = get_user_model()
PW = "hunter2hunter2"
URL = "/api/economy/bugz/"


def shot(name="broken.png", ct="image/png", size=1000):
    return SimpleUploadedFile(name, b"0" * size, content_type=ct)


class Base(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("finder", "f@e.com", PW)
        membership_for(self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.owner = User.objects.create_user("owner", "o@e.com", PW,
                                              is_staff=True, is_superuser=True)
        membership_for(self.owner)
        self.oc = APIClient(); self.oc.force_authenticate(self.owner)


class ReportingTests(Base):
    def test_the_endpoint_the_screen_calls_actually_exists(self):
        self.assertEqual(self.client.get(URL).status_code, 200)

    def test_a_plain_text_report_still_works(self):
        # The screen posted JSON before evidence was a thing. A text-only
        # report must not have to pay for a file upload.
        resp = self.client.post(URL, {"title": "Feed is blank", "body": "After posting."},
                                format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data["reporter"], "finder")
        self.assertEqual(resp.data["status"], "open")

    def test_a_title_is_the_least_it_takes(self):
        self.assertEqual(self.client.post(URL, {"title": "  "}, format="json").status_code, 400)

    def test_the_bounty_is_published_so_the_page_does_not_hardcode_it(self):
        self.assertEqual(self.client.get(URL).data["bounty_spinaz"], BUG_BOUNTY_SPINAZ)


class EvidenceTests(Base):
    """A screenshot beats a paragraph. One slot, either kind."""

    def test_a_screenshot_rides_with_the_report(self):
        resp = self.client.post(URL, {"title": "Button overlaps", "shot": shot()},
                                format="multipart")
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data["shot_type"], "image")
        self.assertTrue(resp.data["shot_url"])

    def test_a_screen_recording_does_too(self):
        resp = self.client.post(URL, {"title": "Scroll jumps", "shot": shot("clip.mp4", "video/mp4")},
                                format="multipart")
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data["shot_type"], "video")

    def test_the_kind_is_named_so_the_client_never_guesses_from_the_extension(self):
        self.client.post(URL, {"title": "a", "shot": shot("weird", "video/webm")}, format="multipart")
        row = self.client.get(URL).data["bugs"][0]
        self.assertEqual(row["shot_type"], "video")

    def test_something_that_is_neither_is_refused(self):
        resp = self.client.post(URL, {"title": "a", "shot": shot("notes.pdf", "application/pdf")},
                                format="multipart")
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(BugReport.objects.exists())

    def test_an_oversize_attachment_says_the_limit(self):
        big = SimpleUploadedFile("huge.mp4", b"0" * ((BUG_MAX_MB + 1) * 1024 * 1024),
                                 content_type="video/mp4")
        resp = self.client.post(URL, {"title": "a", "shot": big}, format="multipart")
        self.assertEqual(resp.status_code, 413)
        self.assertEqual(resp.data["max_mb"], BUG_MAX_MB)


class BountyTests(Base):
    """200 🍥 is printed on the page, so it has to be 200 🍥 that moves — once."""

    def report(self):
        self.client.post(URL, {"title": "Broken"}, format="json")
        return BugReport.objects.first()

    def squash(self, bug):
        return self.oc.patch(f"{URL}{bug.id}/", {"status": "squashed"}, format="json")

    def test_squashing_pays_the_reporter_and_hands_them_the_badge(self):
        bug = self.report()
        before = wallet_for(self.user).spinaz
        resp = self.squash(bug)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(resp.data["just_paid"])
        self.assertEqual(wallet_for(self.user).spinaz, before + BUG_BOUNTY_SPINAZ)
        self.assertTrue(Badge.objects.filter(user=self.user, key="bug_hunter").exists())

    def test_it_pays_once_however_many_times_it_is_squashed(self):
        # Reopened and re-squashed must not mint a second bounty.
        bug = self.report()
        self.squash(bug)
        paid_once = wallet_for(self.user).spinaz
        self.oc.patch(f"{URL}{bug.id}/", {"status": "open"}, format="json")
        resp = self.squash(bug)
        self.assertFalse(resp.data["just_paid"])
        self.assertEqual(wallet_for(self.user).spinaz, paid_once)

    def test_moving_it_to_in_progress_pays_nothing(self):
        bug = self.report()
        before = wallet_for(self.user).spinaz
        resp = self.oc.patch(f"{URL}{bug.id}/", {"status": "in_progress"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["just_paid"])
        self.assertEqual(wallet_for(self.user).spinaz, before)

    def test_only_the_owner_triages(self):
        bug = self.report()
        resp = self.client.patch(f"{URL}{bug.id}/", {"status": "squashed"}, format="json")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(wallet_for(self.user).spinaz, wallet_for(self.user).spinaz)
        self.assertIsNone(BugReport.objects.get(pk=bug.id).paid_at)

    def test_a_nonsense_status_is_refused_with_the_real_list(self):
        bug = self.report()
        resp = self.oc.patch(f"{URL}{bug.id}/", {"status": "fixedish"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("squashed", resp.data["statuses"])


class TheQueueTests(Base):
    def test_a_reporter_can_see_their_report_landed(self):
        self.client.post(URL, {"title": "Mine"}, format="json")
        titles = [b["title"] for b in self.client.get(URL).data["bugs"]]
        self.assertIn("Mine", titles)

    def test_declined_reports_leave_the_queue(self):
        self.client.post(URL, {"title": "Not a bug"}, format="json")
        bug = BugReport.objects.first()
        self.oc.patch(f"{URL}{bug.id}/", {"status": "declined"}, format="json")
        self.assertEqual(self.client.get(URL).data["bugs"], [])
