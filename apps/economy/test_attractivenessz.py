"""AttractivenessZ — 18+ verified (Stripe Identity, never a birthday), self
only, presentation never identity, nothing stored, no video anywhere near it.

The pattern is `test_coachvoice.py`'s and `test_directz_craft.py`'s: the
model call is mocked (no test reaches Gemini, no test bills a paid API), and
the gate, the shape and the prompt's own boundaries are pinned directly.
"""
import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import attractivenessz, attractivenessz_view
from apps.economy.attractivenessz import PRESENTATION_SCORES
from apps.economy.models import award_promptz, membership_for, profile_for

User = get_user_model()
PW = "hunter2hunter2"
URL = "/api/economy/attractivenessz/"

GOOD = {
    "unreadable": "",
    "score": 7,
    "scores": {k: 7 for k in PRESENTATION_SCORES},
    "verdict": "Clean and put-together, a couple of easy wins here.",
    "working": ["Good lighting, even skin tone in this shot."],
    "advice": ["A light daily moisturizer would even out the texture on your cheeks."],
    "caveat": attractivenessz.CAVEAT,
}


def photo(name="me.jpg", size=1000, ct="image/jpeg"):
    return SimpleUploadedFile(name, b"0" * size, content_type=ct)


class Base(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("m", "m@e.com", PW)
        membership_for(self.user)
        award_promptz(self.user, 1_000)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def verify(self):
        p = profile_for(self.user)
        p.verified_18plus = True
        p.save(update_fields=["verified_18plus"])

    def post(self, confirm_self=True, **extra):
        data = {"photo": photo(), **extra}
        if confirm_self:
            data["confirm_self"] = "true"
        return self.client.post(URL, data, format="multipart")


class TheGateTests(Base):
    def test_get_reports_verified_false_before_verification(self):
        d = self.client.get(URL).data
        self.assertFalse(d["verified"])
        self.assertTrue(d["requires_18plus_verification"])

    def test_an_unverified_member_is_refused(self):
        r = self.post()
        self.assertEqual(r.status_code, 403)
        self.assertIn("18+", r.data["detail"])

    def test_verification_is_the_stripe_identity_flag_not_a_birthday(self):
        # profile_for(...).verified_18plus is the same gate BattleZ money
        # betting and adult content already stand behind — never derived
        # from Profile.birthday here.
        src = open(attractivenessz_view.__file__).read()
        self.assertIn("verified_18plus", src)
        self.assertNotIn(".birthday", src)

    def test_a_verified_member_without_confirm_self_is_refused(self):
        self.verify()
        r = self.post(confirm_self=False)
        self.assertEqual(r.status_code, 400)
        self.assertIn("yourself", r.data["detail"])

    def test_a_verified_member_with_no_photo_is_refused(self):
        self.verify()
        r = self.client.post(URL, {"confirm_self": "true"}, format="multipart")
        self.assertEqual(r.status_code, 400)

    def test_an_oversized_photo_is_refused(self):
        self.verify()
        from apps.economy.vocalcoach import INLINE_MAX_MB
        big = photo(size=int((INLINE_MAX_MB + 5) * 1024 * 1024))
        r = self.client.post(URL, {"photo": big, "confirm_self": "true"}, format="multipart")
        self.assertEqual(r.status_code, 400)


class TheRatedResultTests(Base):
    def test_a_verified_self_photo_gets_rated(self):
        self.verify()
        with patch.object(attractivenessz_view, "rate_presentation", return_value=(GOOD, None)):
            r = self.post()
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["score"], 7)
        self.assertEqual(set(r.data["scores"]), set(PRESENTATION_SCORES))
        self.assertEqual(r.data["caveat"], attractivenessz.CAVEAT)

    def test_the_rater_is_given_the_actual_file(self):
        self.verify()
        with patch.object(attractivenessz_view, "rate_presentation",
                          return_value=(GOOD, None)) as rater:
            self.post()
        fileobj = rater.call_args.args[0]
        self.assertTrue(hasattr(fileobj, "read"))
        self.assertEqual(rater.call_args.args[1], "image/jpeg")

    def test_an_unreadable_photo_is_not_billed(self):
        self.verify()
        unreadable = {**GOOD, "unreadable": "a landscape, not a face",
                      "score": None, "scores": {}, "verdict": "", "working": [], "advice": []}
        from apps.economy.models import daily_prompt_state
        before = daily_prompt_state(self.user)[2]
        with patch.object(attractivenessz_view, "rate_presentation", return_value=(unreadable, None)):
            r = self.post()
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.data["score"])
        after = daily_prompt_state(self.user)[2]
        self.assertEqual(before, after)

    def test_a_scored_result_is_billed(self):
        self.verify()
        from apps.economy.models import daily_prompt_state
        before = daily_prompt_state(self.user)[2]
        with patch.object(attractivenessz_view, "rate_presentation", return_value=(GOOD, None)):
            self.post()
        after = daily_prompt_state(self.user)[2]
        self.assertLess(after, before)

    def test_a_rater_failure_is_never_billed(self):
        self.verify()
        from apps.economy.models import daily_prompt_state
        before = daily_prompt_state(self.user)[2]
        with patch.object(attractivenessz_view, "rate_presentation",
                          return_value=(None, "the coach is having a moment")):
            r = self.post()
        self.assertEqual(r.status_code, 502)
        after = daily_prompt_state(self.user)[2]
        self.assertEqual(before, after)


class NothingIsStoredTests(Base):
    def test_no_model_holds_a_photo_score_or_history(self):
        # Stateless by design — read once and it's gone, the same choice
        # KeyConnectZ's read-aloud makes for the same reason.
        src = open(attractivenessz.__file__).read() + open(attractivenessz_view.__file__).read()
        for banned in (".objects.create(", "models.Model", "class Meta"):
            self.assertNotIn(banned, src)


class NoVideoAnywhereNearItTests(TestCase):
    def test_the_module_declares_it_will_never_generate_video(self):
        src = open(attractivenessz.__file__).read()
        self.assertIn("No video, ever", src)


class PresentationNotIdentityTests(TestCase):
    """The prompt itself is the contract with the model — pinned directly,
    the same way test_instrument_routes pins what the coach is asked for."""

    def test_the_prompt_forbids_scoring_immutable_traits(self):
        for banned in ("bone structure", "body shape", "race", "ethnicity",
                       "age", "disability"):
            self.assertIn(banned, attractivenessz.PROMPT)

    def test_the_prompt_only_asks_for_changeable_things(self):
        self.assertEqual(set(PRESENTATION_SCORES),
                         {"skin", "grooming", "styling", "photo_quality"})

    def test_self_only_is_enforced_by_a_required_attestation(self):
        src = open(attractivenessz_view.__file__).read()
        self.assertIn("confirm_self", src)
