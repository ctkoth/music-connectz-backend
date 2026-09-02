"""A post whose recording the platform lost says so, on the post.

Render's disk was ephemeral and every deploy took every uploaded file with it.
The `Upload` rows are in Postgres and survived, so the app went on believing
the files existed: the feed rendered a player that sat at 0:00 and explained
nothing, "Coach it in SingZ" was offered and taken, and the member learned that
their own take was gone from a REFUSAL BY THE COACH — one app away from the
post, and framed as the coach turning them down.

The disk is mounted now, so this stops happening. What these pin is the other
half: the app remembers what it has already discovered, says it where the
member is, and stops charging them storage for bytes that are not there.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.crosspost import take_state_for
from apps.economy.models import (Post, Upload, membership_for, storage_used_bytes,
                                 wallet_for, TIER_STATZ)
from apps.economy.postz import media_slots

User = get_user_model()
PW = "pw12345!"


def fake_gemini():
    from unittest.mock import Mock
    m = Mock()
    m.status_code = 200
    m.json.return_value = {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}
    return m


class TheAppRemembersWhatItFoundOutTests(TestCase):

    def setUp(self):
        self.me = User.objects.create_user(username="maker", password=PW)
        m = membership_for(self.me); m.tier = TIER_STATZ; m.save()
        w = wallet_for(self.me); w.money_cents = 100000; w.save()
        self.c = APIClient(); self.c.force_authenticate(self.me)
        self.up = Upload.objects.create(
            user=self.me, name="take.webm", size_bytes=900, content_type="audio/webm",
            file=SimpleUploadedFile("take.webm", b"0" * 900, content_type="audio/webm"))
        self.post = Post.objects.create(
            author=self.me, title="She's too Good for me", genre="Drill",
            media_type="audio", media_url=self.up.file.url)

    def feed_row(self):
        """The card as the member sees it in the feed."""
        body = self.c.get("/api/economy/postz/").json()
        rows = body["posts"] if isinstance(body, dict) else body
        return [r for r in rows if r["id"] == self.post.id][0]

    def mark_gone(self):
        Upload.objects.filter(pk=self.up.pk).update(missing_since="2026-01-01T00:00:00Z")

    def lose_the_file(self):
        self.up.file.storage.delete(self.up.file.name)

    # ---- learning ----
    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    def test_the_coach_writes_down_what_it_discovered(self, _k):
        """It went to storage and there was nothing there. Until now it
        answered 410 and then FORGOT, so the next member to press the same
        button paid the same trip to learn the same thing."""
        self.lose_the_file()
        r = self.c.post("/api/singz/coach/", {"post_id": self.post.id}, format="json")
        self.assertEqual(r.status_code, 410)
        self.up.refresh_from_db()
        self.assertIsNotNone(self.up.missing_since)

    def test_a_read_path_never_guesses_it(self):
        """Nothing walks storage to serve a feed, so a file that quietly
        vanished is not marked until something actually goes looking. Null
        means "no reason to think so", not "checked and present"."""
        self.lose_the_file()
        self.c.get("/api/economy/postz/")
        self.up.refresh_from_db()
        self.assertIsNone(self.up.missing_since)

    # ---- saying it ----
    def test_the_post_says_so_where_the_member_is(self):
        self.lose_the_file()
        self.mark_gone()
        row = self.feed_row()
        self.assertTrue(row["take_missing"])

    def test_a_post_that_is_fine_says_nothing(self):
        row = self.feed_row()
        self.assertFalse(row["take_missing"])

    def test_the_coach_door_closes_on_the_row_not_one_jump_away(self):
        self.mark_gone()
        row = self.feed_row()
        singz = [d for d in row["destinations"] if d["app"] == "singz"][0]
        self.assertFalse(singz["available"])
        self.assertIn("isn't on the server any more", " ".join(singz["needs"]))
        # And the way forward is on it — attaching it again reopens every door.
        self.assertIn("Attach it again", " ".join(singz["needs"]))

    def test_every_door_that_hands_over_a_recording_closes_too(self):
        """BattleZ fills an entry from the post's take. A door that hands over
        a recording cannot open on a recording that is not there either."""
        self.mark_gone()
        row = self.feed_row()
        battlez = [d for d in row["destinations"] if d["app"] == "battlez"][0]
        self.assertFalse(battlez["available"])

    # ---- not billing for it ----
    def test_storage_stops_counting_bytes_that_are_not_there(self):
        """Charging somebody quota for a recording the platform lost is billing
        them for our own failure."""
        self.assertEqual(storage_used_bytes(self.me), 900)
        self.mark_gone()
        self.assertEqual(storage_used_bytes(self.me), 0)

    def test_the_row_survives_so_the_post_can_still_name_what_was_lost(self):
        self.mark_gone()
        self.assertTrue(Upload.objects.filter(pk=self.up.pk).exists())

    # ---- being careful about it ----
    def test_one_readable_file_behind_the_name_clears_the_doubt(self):
        """Two uploads can share a basename. Telling an author their music is
        gone when one of them plays is the same false certainty the <audio>
        element had, pointed at somebody's work."""
        import os
        twin = Upload.objects.create(
            user=self.me, name="take.webm", size_bytes=900, content_type="audio/webm",
            file=SimpleUploadedFile("take.webm", b"0" * 900, content_type="audio/webm"))
        self.mark_gone()
        # The twin ends in the same basename — which is all the tail lookup
        # sees — and is perfectly readable.
        tail = os.path.basename(self.up.file.name)
        Upload.objects.filter(pk=twin.pk).update(file=f"uploads/{self.me.id}/{tail}")
        state = take_state_for([(self.post, media_slots(self.post))])
        self.assertFalse(state[self.post.id]["missing"])

    def test_the_size_and_the_state_still_come_off_one_query(self):
        """Reading them apart would be two passes over the feed to answer one
        question about the same row."""
        with self.assertNumQueries(1):
            take_state_for([(self.post, media_slots(self.post))])


class TheSweepTests(TestCase):

    def setUp(self):
        self.me = User.objects.create_user(username="sweeper", password=PW)
        self.up = Upload.objects.create(
            user=self.me, name="t.webm", size_bytes=10, content_type="audio/webm",
            file=SimpleUploadedFile("t.webm", b"0" * 10, content_type="audio/webm"))

    def run_cmd(self, *args):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command("reconcile_uploads", *args, stdout=out, stderr=StringIO())
        return out.getvalue()

    def test_a_dry_run_changes_nothing(self):
        self.up.file.storage.delete(self.up.file.name)
        out = self.run_cmd()
        self.up.refresh_from_db()
        self.assertIsNone(self.up.missing_since)
        self.assertIn("would mark", out)

    def test_write_records_what_is_gone(self):
        self.up.file.storage.delete(self.up.file.name)
        self.run_cmd("--write")
        self.up.refresh_from_db()
        self.assertIsNotNone(self.up.missing_since)

    def test_a_file_that_came_back_stops_being_called_lost(self):
        """A post must not go on saying its audio is gone once it plays."""
        Upload.objects.filter(pk=self.up.pk).update(missing_since="2026-01-01T00:00:00Z")
        self.run_cmd("--write")            # the file is still there
        self.up.refresh_from_db()
        self.assertIsNone(self.up.missing_since)

    def test_a_storage_that_cannot_answer_is_not_a_file_that_is_gone(self):
        """Marking on an unreachable bucket would tell every member on the
        platform their music was lost — worse than the bug this exists for."""
        with patch("django.core.files.storage.FileSystemStorage.exists",
                   side_effect=OSError("bucket unreachable")):
            self.run_cmd("--write")
        self.up.refresh_from_db()
        self.assertIsNone(self.up.missing_since)
