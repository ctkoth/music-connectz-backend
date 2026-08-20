"""A post is no longer a dead end — the author can send it to the coach.

PostZ showed a member a median, a like count and nothing to do about either.
`CLAUDE.md`'s crux calls a read-only surface an unfinished one, and this is the
missing leg: the work is already up, the question "why isn't this landing?" is
already being asked, and the coach that listens to takes was one route away.

What these tests hold it to is the same three rules the Boss Take meets:

1. **The price is knowable before it is paid.** GET answers it, and a read the
   coach couldn't produce is never billed.
2. **The score measures the recording.** Not the title, not the description,
   not how many contributors are credited — the audio.
3. **The coach's number is not the members'.** `coach_rating` and `rating` are
   separate fields and must never be blended.

No test reaches Gemini. A suite that can call a paid API is a suite that bills.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import post_coach
from apps.economy.instruments import profile_for_app
from apps.economy.models import (
    ItemRating,
    Post,
    Upload,
    award_promptz,
    daily_prompt_state,
    membership_for,
    wallet_for,
)
from apps.economy.vocalcoach import MAX_MB

User = get_user_model()
PW = "hunter2hunter2"

GOOD = {
    "score": 7,
    "scores": {k: 7 for k in profile_for_app("singz")["scores"]},
    "verdict": "The hook lands; the second verse loses the pocket.",
    "strengths": ["The first chorus sits dead centre of pitch."],
    "fixes": ["You're rushing the pickup into verse two."],
    "next_drill": "Sing verse two to a metronome at 90.",
}


class Base(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("poster", "p@e.com", PW)
        membership_for(self.user)
        # A coached read costs a prompt and the free tier's allowance is one.
        # Without a balance the SECOND read in a test quietly becomes a test
        # about affordability instead of about the coach.
        award_promptz(self.user, 1_000)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        # Configured, but never reachable: `score_take` is stubbed in every
        # test that gets past the gate. A suite that can call a paid API is a
        # suite that bills.
        keyed = patch("apps.economy.directz_craft._key", return_value="test-key")
        keyed.start()
        self.addCleanup(keyed.stop)

    def upload(self, name="take.m4a", size=1000, ct="audio/mp4"):
        return Upload.objects.create(
            user=self.user, file=SimpleUploadedFile(name, b"0" * size, content_type=ct),
            name=name, size_bytes=size, content_type=ct)

    def make_post(self, *, author=None, media=True, size=1000, **kw):
        up = self.upload(size=size) if media else None
        return Post.objects.create(
            author=author or self.user, title="Take One",
            media_type="audio", media_url=up.file.url if up else "",
            genre=kw.pop("genre", "R&B"), skills_used=kw.pop("skills_used", ["Vocals"]),
            **kw)

    def url(self, post):
        return f"/api/economy/postz/{post.id}/coach/"

    def coach(self, post, payload=GOOD, err=None, **body):
        with patch.object(post_coach, "score_take", return_value=(payload, err)) as scorer:
            resp = self.client.post(self.url(post), body, format="json")
        return resp, scorer


class ThePriceIsOnTheButtonTests(Base):
    """A price discovered by paying it is not a price, it's a bill."""

    def test_the_cost_and_the_free_allowance_read_before_anything_is_sent(self):
        post = self.make_post()
        d = self.client.get(self.url(post)).json()
        self.assertIn("cost_cents", d)
        self.assertIn("free_today", d)
        self.assertIn("daily_remaining", d)
        self.assertIn("daily_allowance", d)
        self.assertTrue(d["allowed"])

    def test_it_says_a_failed_read_is_not_charged(self):
        post = self.make_post()
        self.assertFalse(self.client.get(self.url(post)).json()["charged_on_failure"])

    def test_the_dimensions_come_from_the_server_not_the_client(self):
        post = self.make_post(skills_used=["Vocals"])
        d = self.client.get(self.url(post)).json()
        self.assertEqual(d["app_key"], "singz")
        self.assertEqual(set(d["scores"]), set(profile_for_app("singz")["scores"]))

    def test_why_it_cant_run_is_said_before_the_press_not_after(self):
        post = self.make_post(media=False)
        d = self.client.get(self.url(post)).json()
        self.assertFalse(d["allowed"])
        self.assertIn("no audio or video", d["blocked_because"])

    def test_a_file_too_big_to_hear_is_refused_up_front(self):
        post = self.make_post(size=(MAX_MB + 1) * 1024 * 1024)
        d = self.client.get(self.url(post)).json()
        self.assertFalse(d["allowed"])
        self.assertIn(f"{MAX_MB}MB", d["blocked_because"])


class TheScoreComesFromListeningTests(Base):
    def test_the_coach_is_handed_the_actual_file(self):
        post = self.make_post(size=2048)
        resp, scorer = self.coach(post)
        self.assertEqual(resp.status_code, 200, resp.data)
        fileobj = scorer.call_args.args[1]
        self.assertTrue(hasattr(fileobj, "read"))
        self.assertEqual(scorer.call_args.args[2], "audio/mp4")

    def test_padding_the_post_does_not_move_the_number(self):
        """The old DirectZ formula paid for description length and contributor
        count. Nothing on this path ever sees them."""
        lean = self.make_post(description="")
        padded = self.make_post(description="x" * 3000,
                                contributors=[{"username": "a"}, {"username": "b"}])
        self.assertEqual(self.coach(lean)[0].json()["score"],
                         self.coach(padded)[0].json()["score"])

    def test_the_posts_own_genre_reaches_the_coach(self):
        post = self.make_post(genre="Drill")
        _, scorer = self.coach(post)
        self.assertEqual(scorer.call_args.kwargs["genre"], "Drill")

    def test_the_full_boss_take_shape_comes_back(self):
        resp, _ = self.coach(self.make_post())
        d = resp.json()
        for key in ("score", "scores", "verdict", "strengths", "fixes", "next_drill"):
            self.assertIn(key, d, key)
        self.assertIn("pocket", d["verdict"])


class TheCoachsNumberIsNotTheMembersTests(Base):
    """`rating` is the median of what PEOPLE scored it. This is one model's
    opinion of the recording. Blending them hides a machine's number inside a
    count of humans."""

    def test_a_coached_read_never_becomes_the_posts_rating(self):
        post = self.make_post()
        self.coach(post)
        d = self.client.get("/api/economy/postz/").json()
        row = next(r for r in (d if isinstance(d, list) else d["posts"]) if r["id"] == post.id)
        self.assertEqual(row["coach_rating"], 7)
        self.assertIsNone(row["rating"], "the coach's score leaked into the members' median")

    def test_the_members_median_still_wins_its_own_field(self):
        post = self.make_post()
        self.coach(post)
        other = User.objects.create_user("rater", "r@e.com", PW)
        ItemRating.objects.create(user=other, item_id=f"post:{post.id}", score=3)
        d = self.client.get("/api/economy/postz/").json()
        row = next(r for r in (d if isinstance(d, list) else d["posts"]) if r["id"] == post.id)
        self.assertEqual(row["rating"], 3)
        self.assertEqual(row["coach_rating"], 7)

    def test_an_unrated_post_carries_none_not_zero(self):
        post = self.make_post()
        d = self.client.get("/api/economy/postz/").json()
        row = next(r for r in (d if isinstance(d, list) else d["posts"]) if r["id"] == post.id)
        self.assertIsNone(row["coach_rating"])


class OnlyTheAuthorSpendsThePromptTests(Base):
    def test_someone_elses_post_is_not_yours_to_coach(self):
        stranger = User.objects.create_user("other", "o@e.com", PW)
        theirs = self.make_post(author=stranger)
        self.assertEqual(self.client.get(self.url(theirs)).status_code, 404)
        self.assertEqual(self.client.post(self.url(theirs), {}, format="json").status_code, 404)

    def test_a_credited_collaborator_can_send_it(self):
        """A collab post belongs to everyone on it, so the decision does too."""
        mate = User.objects.create_user("mate", "m@e.com", PW)
        award_promptz(mate, 100)
        post = self.make_post(contributors=[{"username": "mate", "slot": "audio"}])
        self.client.force_authenticate(mate)
        with patch.object(post_coach, "score_take", return_value=(GOOD, None)):
            resp = self.client.post(self.url(post), {}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_a_missing_post_and_someone_elses_answer_the_same_way(self):
        stranger = User.objects.create_user("other", "o@e.com", PW)
        theirs = self.make_post(author=stranger)
        self.assertEqual(self.client.get(self.url(theirs)).status_code,
                         self.client.get("/api/economy/postz/999999/coach/").status_code)


class AReadTheCoachCouldNotGiveIsNotBilledTests(Base):
    def test_a_failed_read_costs_nothing_and_says_why_on_the_post(self):
        post = self.make_post()
        before = daily_prompt_state(self.user)[2]
        err = ({"detail": "The coach couldn't read that take — the coach refused that one."}, 502)
        resp, _ = self.coach(post, payload=None, err=err)
        self.assertEqual(resp.status_code, 502)
        self.assertEqual(daily_prompt_state(self.user)[2], before)
        post.refresh_from_db()
        self.assertIsNone(post.coach_rating)
        self.assertIn("couldn't read", post.coach_note)

    def test_a_post_with_no_media_is_refused_before_any_spend(self):
        post = self.make_post(media=False)
        before = daily_prompt_state(self.user)[2]
        resp = self.client.post(self.url(post), {}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(daily_prompt_state(self.user)[2], before)

    def test_an_empty_wallet_with_free_prompts_left_still_gets_a_read(self):
        w = wallet_for(self.user); w.money_cents = 0; w.promptz = 0
        w.save(update_fields=["money_cents", "promptz"])
        resp, _ = self.coach(self.make_post())
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.json()["cost_cents"], 0)

    def test_the_free_daily_prompt_is_spent_before_any_balance(self):
        w = wallet_for(self.user); w.money_cents = 0; w.promptz = 0
        w.save(update_fields=["money_cents", "promptz"])
        before = daily_prompt_state(self.user)[2]
        self.coach(self.make_post())
        self.assertEqual(daily_prompt_state(self.user)[2], before - 1)

    def test_no_prompts_and_no_balance_is_refused_before_the_model_runs(self):
        w = wallet_for(self.user); w.money_cents = 0; w.promptz = 0
        w.save(update_fields=["money_cents", "promptz"])
        allowance = daily_prompt_state(self.user)[0]
        for _ in range(allowance):
            self.coach(self.make_post())
        with patch.object(post_coach, "score_take") as scorer:
            resp = self.client.post(self.url(self.make_post()), {}, format="json")
        self.assertEqual(resp.status_code, 402)
        scorer.assert_not_called()


class TheRightCoachForThePostTests(Base):
    def test_the_skills_on_the_post_pick_the_coach(self):
        for skills, expected in ((["Vocals"], "singz"), (["Rap verse"], "rapz"),
                                 (["Lead guitar"], "guitarz"), (["Drum programming"], "drumz")):
            with self.subTest(skills=skills):
                _, scorer = self.coach(self.make_post(skills_used=skills))
                self.assertEqual(scorer.call_args.args[0], expected)

    def test_the_author_can_name_the_coach_and_wins(self):
        post = self.make_post(skills_used=["Vocals"])
        _, scorer = self.coach(post, app_key="rapz")
        self.assertEqual(scorer.call_args.args[0], "rapz")

    def test_a_post_with_no_instrument_signal_gets_the_generic_dimensions(self):
        """No signal is not a reason to invent one — a post that says nothing
        about what was played is scored on what's true of any instrument."""
        _, scorer = self.coach(self.make_post(skills_used=["Mixing"]))
        self.assertEqual(scorer.call_args.args[0], "instrumentz")
        self.assertNotIn("breath", profile_for_app("instrumentz")["scores"])

    def test_the_labels_travel_with_the_read(self):
        """A dimension renamed in instruments.py next year must not silently
        relabel a score that was never given on that dimension."""
        resp, _ = self.coach(self.make_post(skills_used=["Vocals"]))
        self.assertEqual(set(resp.json()["scores_labels"]),
                         set(profile_for_app("singz")["scores"]))
