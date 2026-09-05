"""What a logged-out visitor can and cannot reach.

The client shipped `/p/:id` share links pointing at `/api/postz/<id>/` with
`auth: false` long before that endpoint existed, so every link a member has
ever shared off-platform has been landing on a 404.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.models import TRIAL_MAX_MB, Post, TrialTake, profile_for

User = get_user_model()
PW = "hunter2hunter2"


def make_post(author, visibility="public", title="Track"):
    return Post.objects.create(author=author, title=title, description="d",
                               visibility=visibility)


class PublicPostTests(TestCase):
    """By link, not by browse."""

    def setUp(self):
        self.client = APIClient()          # deliberately NOT authenticated
        self.author = User.objects.create_user("author", "a@e.com", PW)

    def test_a_public_post_opens_with_no_account(self):
        p = make_post(self.author)
        resp = self.client.get(f"/api/postz/{p.pk}/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["title"], "Track")
        self.assertEqual(resp.data["author"], "author")

    def test_the_same_post_also_answers_under_economy(self):
        p = make_post(self.author)
        self.assertEqual(self.client.get(f"/api/economy/postz/{p.pk}/").status_code, 200)

    def test_a_restricted_post_is_members_only(self):
        p = make_post(self.author, visibility="restricted")
        self.assertEqual(self.client.get(f"/api/postz/{p.pk}/").status_code, 404)
        self.client.force_authenticate(User.objects.create_user("m", "m@e.com", PW))
        self.assertEqual(self.client.get(f"/api/postz/{p.pk}/").status_code, 200)

    def test_a_private_post_answers_404_not_403(self):
        # A 403 confirms the post exists, which is itself the leak.
        p = make_post(self.author, visibility="private")
        resp = self.client.get(f"/api/postz/{p.pk}/")
        self.assertEqual(resp.status_code, 404)
        self.assertNotIn("Track", str(resp.data))

    def test_the_author_still_opens_their_own_private_post(self):
        p = make_post(self.author, visibility="private")
        self.client.force_authenticate(self.author)
        self.assertEqual(self.client.get(f"/api/postz/{p.pk}/").status_code, 200)

    def test_the_public_payload_is_built_up_not_stripped_down(self):
        p = make_post(self.author)
        keys = set(self.client.get(f"/api/postz/{p.pk}/").data)
        # Member-only bookkeeping must not ride along on the anonymous response.
        self.assertFalse(keys & {"edit_history", "joins", "mine", "skill_cost_cents",
                                 "visibility", "flagged"})

    def test_the_anonymous_feed_stays_shut(self):
        make_post(self.author)
        self.assertEqual(self.client.get("/api/economy/postz/").status_code, 401)

    def test_anonymous_member_search_stays_shut(self):
        # Search carries age and attractiveness — it does not leave the login.
        self.assertEqual(self.client.get("/api/economy/members/").status_code, 401)


class PublicProfileTests(TestCase):
    """Without this the author line on a shared post is a dead name."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("k-oth", "k@e.com", PW)
        p = profile_for(self.user)
        p.display_name = "K-Oth"
        p.bio = "I make things."
        p.birthday = "1990-01-20"
        p.location = "Denver"
        p.gender = "male"
        p.personas = [{"key": "musician", "name": "Musician", "skills": [
            {"name": "Violin", "start": "2000-01-01", "rate_cents": 4500},
        ]}]
        p.save()

    def test_a_stranger_gets_the_work(self):
        resp = self.client.get("/api/economy/public/members/k-oth/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["display_name"], "K-Oth")
        skill = resp.data["personas"][0]["skills"][0]
        self.assertEqual(skill["name"], "Violin")
        self.assertEqual(skill["rate_cents"], 4500)   # what they charge is the point

    def test_a_stranger_does_not_get_the_person(self):
        keys = set(self.client.get("/api/economy/public/members/k-oth/").data)
        self.assertFalse(keys & {"birthday", "age", "location", "gender", "sign",
                                 "attractiveness", "substances", "spinaz", "energy"})

    def test_lookup_is_case_insensitive_like_login(self):
        self.assertEqual(self.client.get("/api/economy/public/members/K-OTH/").status_code, 200)

    def test_unknown_member_is_404(self):
        self.assertEqual(self.client.get("/api/economy/public/members/ghost/").status_code, 404)

    def test_the_full_member_profile_still_needs_an_account(self):
        self.assertEqual(self.client.get("/api/economy/members/k-oth/").status_code, 401)


SCORED = {
    "score": 7,
    "scores": {},
    "verdict": "Solid.",
    "strengths": ["pitch"],
    "fixes": ["breath"],
    "next_drill": "sirens",
}


def a_take():
    return SimpleUploadedFile("take.webm", b"audio-bytes", content_type="audio/webm")


class TrialTakeTests(TestCase):
    """One scored take, no account — graded by the member rubric, capped hard."""

    def setUp(self):
        self.client = APIClient()

    def _post(self, app="singz", **extra):
        with patch("apps.economy.trial.score_take", return_value=(dict(SCORED), None)):
            return self.client.post(f"/api/{app}/trial/",
                                    {"take": a_take(), "genre": "rock", **extra},
                                    format="multipart")

    @patch("apps.economy.trial._key", return_value="k")
    def test_a_stranger_gets_a_score_and_a_claim_token(self, _k):
        resp = self._post()
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["score"], 7)
        self.assertTrue(resp.data["claim_token"])
        self.assertEqual(resp.data["cost_cents"], 0)
        self.assertEqual(resp.data["open_in"], "singz:coach")   # not a dead end

    @patch("apps.economy.trial._key", return_value="k")
    def test_rapz_has_its_own_door(self, _k):
        self.assertEqual(self._post(app="rapz").status_code, 201)
        self.assertEqual(TrialTake.objects.get().app_key, "rapz")

    @patch("apps.economy.trial._key", return_value="k")
    def test_one_per_address_per_day(self, _k):
        self.assertEqual(self._post().status_code, 201)
        second = self._post()
        self.assertEqual(second.status_code, 429, second.content)
        self.assertTrue(second.data["already_used"])
        self.assertEqual(TrialTake.objects.count(), 1)

    @patch("apps.economy.trial.trial_daily_cap", return_value=0)
    @patch("apps.economy.trial._key", return_value="k")
    def test_the_global_daily_ceiling_refuses_rather_than_overspends(self, _k, _cap):
        # An unauthenticated endpoint that spends real money is a bill anybody
        # with curl can run up.
        resp = self._post()
        self.assertEqual(resp.status_code, 503, resp.content)
        self.assertFalse(TrialTake.objects.exists())

    @patch("apps.economy.trial._key", return_value="k")
    def test_a_take_the_coach_cannot_read_does_not_burn_the_free_run(self, _k):
        err = ({"detail": "The coach couldn't process that take."}, 502)
        with patch("apps.economy.trial.score_take", return_value=(None, err)):
            self.assertEqual(self.client.post("/api/singz/trial/", {"take": a_take()},
                                              format="multipart").status_code, 502)
        self.assertFalse(TrialTake.objects.exists())
        self.assertEqual(self._post().status_code, 201)   # still theirs to use

    def test_a_missing_key_is_said_plainly_not_500(self):
        with patch("apps.economy.trial._key", return_value=""):
            resp = self.client.get("/api/singz/trial/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["configured"])
        self.assertFalse(resp.data["available"])

    @patch("apps.economy.trial._key", return_value="k")
    def test_the_offer_states_what_it_costs_before_they_commit(self, _k):
        resp = self.client.get("/api/singz/trial/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.data["free"])
        self.assertTrue(resp.data["available"])
        # The number, not a literal — this read 8 and so pinned the trial to a
        # ceiling set before the Files API path existed. What matters is that
        # the offer STATES it, and that it is the one the door enforces.
        self.assertEqual(resp.data["max_mb"], TRIAL_MAX_MB)
        self.assertIn("difficulties", resp.data)

    @patch("apps.economy.trial._key", return_value="k")
    def test_a_non_audio_file_is_refused_before_any_model_run(self, _k):
        bad = SimpleUploadedFile("x.txt", b"hi", content_type="text/plain")
        resp = self.client.post("/api/singz/trial/", {"take": bad}, format="multipart")
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(TrialTake.objects.exists())

    @patch("apps.economy.trial._key", return_value="k")
    def test_a_trial_take_reads_back_by_token(self, _k):
        token = self._post().data["claim_token"]
        resp = self.client.get(f"/api/trial/{token}/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["score"], 7)
        self.assertFalse(resp.data["claimed"])

    def test_an_unknown_token_is_404(self):
        self.assertEqual(self.client.get("/api/trial/nope/").status_code, 404)


class TrialClaimTests(TestCase):
    """Signing up with the token attaches the take — the trial opens in the app
    rather than vanishing with the tab."""

    def setUp(self):
        self.client = APIClient()
        self.take = TrialTake.objects.create(token="tok123", app_key="singz", result=SCORED)

    def _register(self, **extra):
        return self.client.post("/api/auth/register/", {
            "username": "newbie", "email": "n@e.com", "password": PW, **extra,
        }, format="json")

    def test_registering_with_the_token_claims_the_take(self):
        self.assertEqual(self._register(trial_token="tok123").status_code, 201)
        self.take.refresh_from_db()
        self.assertEqual(self.take.claimed_by.username, "newbie")
        self.assertIsNotNone(self.take.claimed_at)

    def test_a_claimed_take_cannot_be_claimed_again(self):
        self._register(trial_token="tok123")
        self.client.post("/api/auth/register/", {
            "username": "other", "email": "o@e.com", "password": PW, "trial_token": "tok123",
        }, format="json")
        self.take.refresh_from_db()
        self.assertEqual(self.take.claimed_by.username, "newbie")

    def test_a_junk_token_never_costs_somebody_their_registration(self):
        resp = self._register(trial_token="not-a-real-token")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertTrue(User.objects.filter(username="newbie").exists())

    def test_an_expired_take_is_not_claimed(self):
        from datetime import timedelta
        TrialTake.objects.filter(pk=self.take.pk).update(
            created_at=timezone.now() - timedelta(days=90))
        self.assertEqual(self._register(trial_token="tok123").status_code, 201)
        self.take.refresh_from_db()
        self.assertIsNone(self.take.claimed_by)

    def test_registering_without_a_token_is_unaffected(self):
        self.assertEqual(self._register().status_code, 201)
        self.take.refresh_from_db()
        self.assertIsNone(self.take.claimed_by)
