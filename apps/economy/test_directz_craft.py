"""The DirectZ rating, now that it watches the video.

`directz_ai_rating` called itself "a deterministic AI craft estimate" and scored
contributor count, skills listed, description length, money spent and duration
fit. `CLAUDE.md`'s third rule is the test it failed: could a member get a good
number without getting good? Trivially — pad the description, add contributors.

These tests hold the replacement to the standard `vocalcoach.py` already meets:
the score comes from watching, and where the video can't be watched there is
**no score at all** rather than a fallback. An empty rating invites a real one
from members; a fabricated one ends the question.

No test reaches Gemini. A suite that can call a paid API is a suite that bills.
"""
import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy import directz_app, directz_craft
from apps.economy.directz_craft import CRAFT_SCORES, too_big
from apps.economy.models import (
    MB,
    DirectZWork,
    Upload,
    award_promptz,
    directz_display_rating,
    daily_prompt_state,
    membership_for,
    wallet_for,
)
from apps.economy.vocalcoach import MAX_MB

User = get_user_model()
PW = "hunter2hunter2"
URL = "/api/economy/directz/"

GOOD = {
    "score": 8,
    "scores": {k: 8 for k in CRAFT_SCORES},
    "verdict": "Confidently shot and tightly cut.",
    "strengths": ["The cut on the downbeat lands."],
    "fixes": ["Key light is hard on the left side."],
}


class Base(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("director", "d@e.com", PW)
        membership_for(self.user)
        # A craft rating costs a prompt, and the free tier's daily allowance is
        # one. Without a balance the SECOND post in a test silently gets no
        # rating — which is the gate working, but it makes every test about the
        # rating quietly a test about affordability instead.
        award_promptz(self.user, 1_000)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def upload(self, name="take.mp4", size=1000, ct="video/mp4"):
        return Upload.objects.create(
            user=self.user, file=SimpleUploadedFile(name, b"0" * size, content_type=ct),
            name=name, size_bytes=size, content_type=ct)

    def post(self, media_url="", **body):
        return self.client.post(
            URL, {"title": "Take One", "fmt": "reelz", "duration_sec": 60,
                  "media_url": media_url, "craft_rating": True, **body},
            format="json")


class TheScoreComesFromWatching(Base):
    def test_a_rated_video_carries_the_dimensions_behind_its_score(self):
        up = self.upload()
        with patch.object(directz_craft, "rate_video", return_value=(GOOD, None)):
            d = self.post(media_url=up.file.url).json()
        self.assertEqual(d["rating"], 8)
        self.assertEqual(d["source"], "ai")
        self.assertEqual(set(d["craft"]["scores"]), set(CRAFT_SCORES))
        self.assertIn("downbeat", d["craft"]["strengths"][0])

    def test_the_rater_is_given_the_actual_file(self):
        up = self.upload(size=2048)
        with patch.object(directz_craft, "rate_video",
                          return_value=(GOOD, None)) as rater:
            self.post(media_url=up.file.url)
        fileobj = rater.call_args.args[0]
        self.assertTrue(hasattr(fileobj, "read"))
        self.assertEqual(rater.call_args.args[1], "video/mp4")

    def test_the_dimensions_are_things_you_can_see(self):
        # None of these can be satisfied by filling in a form, which is the
        # whole point of replacing the old formula.
        self.assertEqual(set(CRAFT_SCORES),
                         {"framing", "editing", "lighting", "sound", "story"})

    def test_padding_the_form_no_longer_moves_the_number(self):
        # The old formula paid for contributors, description length and money
        # spent. The new one never sees them.
        up = self.upload()
        with patch.object(directz_craft, "rate_video", return_value=(GOOD, None)):
            lean = self.post(media_url=up.file.url, description="").json()
            padded = self.post(
                media_url=up.file.url, description="x" * 300,
                contributors=[{"name": "a", "skills": [{"name": "DP", "price": 500}]},
                              {"name": "b", "skills": [{"name": "Editor", "price": 500}]}],
            ).json()
        self.assertEqual(lean["rating"], padded["rating"])


class WhenItCannotWatchThereIsNoNumber(Base):
    def test_a_work_with_no_video_gets_no_rating(self):
        d = self.post().json()
        self.assertIsNone(d["rating"])
        self.assertIsNone(d["source"])
        self.assertIn("no video", d["rating_note"])

    def test_a_video_too_large_to_watch_says_so_instead_of_guessing(self):
        # A MovieZ is one to three hours. Rating a three-hour film from its
        # metadata is exactly what this replaced.
        up = self.upload(size=int((MAX_MB + 5) * MB))
        d = self.post(media_url=up.file.url).json()
        self.assertIsNone(d["rating"])
        self.assertIn(str(MAX_MB), d["rating_note"])

    def test_a_rater_failure_leaves_no_rating_and_still_posts_the_work(self):
        # Losing a member's video because a third-party API was slow would be
        # the worse outcome by far.
        up = self.upload()
        with patch.object(directz_craft, "rate_video",
                          return_value=(None, "the rater is having a moment")):
            resp = self.post(media_url=up.file.url)
        self.assertEqual(resp.status_code, 201)
        self.assertIsNone(resp.json()["rating"])
        self.assertIn("having a moment", resp.json()["rating_note"])
        self.assertTrue(DirectZWork.objects.filter(owner=self.user).exists())

    def test_a_rater_that_raises_does_not_lose_the_post(self):
        up = self.upload()
        with patch.object(directz_craft, "rate_video", side_effect=RuntimeError("boom")):
            resp = self.post(media_url=up.file.url)
        self.assertEqual(resp.status_code, 201)
        self.assertIsNone(resp.json()["rating"])

    def test_no_rating_is_never_reported_as_a_zero(self):
        # 0.0 on screen is a fake number wearing a real one's clothes — the
        # thing the third rule exists to stop.
        work = DirectZWork.objects.create(owner=self.user, title="Unrated")
        disp = directz_display_rating(work)
        self.assertIsNone(disp["rating"])
        self.assertIsNone(disp["source"])
        self.assertNotEqual(disp["rating"], 0)


class TheRatingIsAskedForAndPricedFirst(Base):
    """It shipped free and silent — unbounded Gemini spend on the platform's
    key, by the code that enforces the cost/gain rule everywhere else."""

    def test_posting_does_not_rate_unless_asked(self):
        # Otherwise posting quietly becomes a paid action.
        up = self.upload()
        with patch.object(directz_craft, "rate_video",
                          return_value=(GOOD, None)) as rater:
            resp = self.client.post(
                URL, {"title": "Take", "fmt": "reelz", "duration_sec": 60,
                      "media_url": up.file.url}, format="json")
        rater.assert_not_called()
        self.assertIsNone(resp.json()["rating"])
        self.assertIn("no craft rating", resp.json()["rating_note"])

    def test_posting_without_a_rating_costs_nothing(self):
        before = wallet_for(self.user).promptz
        up = self.upload()
        self.client.post(URL, {"title": "T", "fmt": "reelz", "duration_sec": 60,
                               "media_url": up.file.url}, format="json")
        self.assertEqual(wallet_for(self.user).promptz, before)

    def test_the_feed_states_the_price_before_the_box_that_spends_it(self):
        d = self.client.get(URL).json()
        self.assertGreater(d["craft"]["cost_cents"], 0)
        self.assertIn("cost_cents", d["craft"])
        self.assertIn("affordable", d["craft"])
        self.assertEqual(set(d["craft"]["scores"]), set(CRAFT_SCORES))

    def test_the_raters_ceiling_is_published_so_the_box_can_state_it(self):
        """The same failure the Boss Take coach had, next door: the rater has
        its own per-request ceiling and the screen could not name it, because
        nothing served it. So a 100MB video went up with the box ticked and the
        refusal arrived afterwards as a note on the finished work."""
        from apps.economy.vocalcoach import MAX_MB
        craft = self.client.get(URL).json()["craft"]
        self.assertEqual(craft["max_mb"], MAX_MB)
        # And whose limit it is — reading it as the tier's is how a StatZ member
        # concludes the plan they paid for is being ignored.
        self.assertFalse(craft["max_mb_is_tier_limit"])
        self.assertIn("isn't your tier's upload limit", craft["max_mb_why"])
        self.assertFalse(craft["charged_on_failure"])

    def test_a_rating_is_billed_once_a_usable_result_exists(self):
        up = self.upload()
        before = wallet_for(self.user).promptz
        with patch.object(directz_craft, "rate_video", return_value=(GOOD, None)):
            self.post(media_url=up.file.url)
        # The daily allowance covers the first one, so either the free prompt
        # went or PromptZ did — never both, and never nothing.
        _, _, left = daily_prompt_state(self.user)
        spent = before - wallet_for(self.user).promptz
        self.assertTrue(spent > 0 or left < 1)

    def test_a_video_the_rater_could_not_read_is_never_billed(self):
        # The rule vocalcoach.py bills on.
        up = self.upload()
        before = wallet_for(self.user).promptz
        with patch.object(directz_craft, "rate_video",
                          return_value=(None, "the rater is having a moment")):
            self.post(media_url=up.file.url)
        self.assertEqual(wallet_for(self.user).promptz, before)

    def test_a_video_too_big_to_watch_is_never_billed(self):
        before = wallet_for(self.user).promptz
        up = self.upload(size=int((MAX_MB + 5) * MB))
        self.post(media_url=up.file.url)
        self.assertEqual(wallet_for(self.user).promptz, before)

    def test_a_member_who_cannot_afford_it_still_gets_their_post(self):
        # A rating is a bonus, not the post. Refusing the whole thing would lose
        # a member's video over a number.
        #
        # The allowance is spent directly rather than by posting: a post with no
        # video is never billed, so five of them leave the allowance untouched —
        # which is right, and made an earlier version of this test measure
        # nothing at all.
        w = wallet_for(self.user)
        w.promptz = 0
        w.money_cents = 0
        w.prompts_used_today = 10_000
        w.prompt_day = timezone.now().strftime("%Y-%m-%d")
        w.save()
        up = self.upload()
        with patch.object(directz_craft, "rate_video",
                          return_value=(GOOD, None)) as rater:
            resp = self.post(media_url=up.file.url)
        self.assertEqual(resp.status_code, 201)
        # Never bought a rating we couldn't bill for.
        rater.assert_not_called()
        self.assertIn("🏷️", resp.json()["rating_note"])
        self.assertIsNone(resp.json()["rating"])


class MembersStillOutrankTheModel(Base):
    def test_three_real_ratings_take_over_from_the_model(self):
        work = DirectZWork.objects.create(owner=self.user, title="Take", ai_rating=4)
        for i in range(3):
            rater = User.objects.create_user(f"r{i}", f"r{i}@e.com", PW)
            membership_for(rater)
            work.ratings.create(rater=rater, score=9)
        disp = directz_display_rating(work)
        self.assertEqual(disp["source"], "users")
        self.assertEqual(disp["rating"], 9)

    def test_members_can_rate_a_work_the_model_never_saw(self):
        # An empty rating invites a real one — that is the argument for leaving
        # it empty rather than seeding a number.
        work = DirectZWork.objects.create(owner=self.user, title="Unwatched")
        for i in range(3):
            rater = User.objects.create_user(f"r{i}", f"r{i}@e.com", PW)
            membership_for(rater)
            work.ratings.create(rater=rater, score=7)
        self.assertEqual(directz_display_rating(work)["rating"], 7)


class TheSizeGateMatchesTheTransport(TestCase):
    def test_the_ceiling_is_the_one_the_coach_already_honours(self):
        self.assertFalse(too_big(MAX_MB * MB))
        self.assertTrue(too_big(int((MAX_MB + 1) * MB)))

    def test_an_unknown_size_is_not_treated_as_too_big(self):
        self.assertFalse(too_big(0))


class TheUploadLookupIsScopedToItsOwner(Base):
    def test_another_members_upload_cannot_be_reached_by_pasting_its_url(self):
        other = User.objects.create_user("other", "o@e.com", PW)
        membership_for(other)
        theirs = Upload.objects.create(
            user=other, file=SimpleUploadedFile("secret.mp4", b"0" * 10),
            name="secret.mp4", size_bytes=10, content_type="video/mp4")
        self.assertIsNone(directz_app._find_upload(self.user, theirs.file.url))

    def test_a_members_own_upload_is_found(self):
        mine = self.upload()
        self.assertEqual(directz_app._find_upload(self.user, mine.file.url), mine)

    def test_an_empty_url_finds_nothing(self):
        self.assertIsNone(directz_app._find_upload(self.user, ""))


class TheRaterRefusesWhatItCannotRead(TestCase):
    def test_an_unsupported_container_is_refused_before_the_call(self):
        # Same normalisation the coach uses — imported, never copied.
        with patch.object(directz_craft, "_key", return_value="k"):
            payload, why = directz_craft.rate_video(io.BytesIO(b"x"), "application/pdf")
        self.assertIsNone(payload)
        self.assertIn("can't read", why)

    def test_a_missing_key_is_reported_rather_than_crashing(self):
        with patch.object(directz_craft, "_key", return_value=""):
            payload, why = directz_craft.rate_video(io.BytesIO(b"x"), "video/mp4")
        self.assertIsNone(payload)
        self.assertIn("configured", why)
