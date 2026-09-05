"""The five instruments that had a profile and no door.

`apps/economy/instruments.py` has carried a full scored profile for guitarz,
bassz, keyz, drumz and violinz since it was written — dimensions, a caveat,
and `prompt_for()` tested against all of them (`test_vocalcoach.py` calls
`prompt_for("drumz", ...)` directly). None of that was reachable: the coach,
trial and SkillZ routes are generated from `INSTRUMENT_APP_KEYS` in
`music_connectz/urls.py`, and that list held only `singz` and `rapz`. A
guitarist opening `/api/guitarz/coach/` got a 404 from a coach that was
already built and already tested — just never mounted.

This is not a test of the coach's judgement (`test_vocalcoach.py` already
owns that). It is a test that the wiring itself is not silently narrowed back
to two instruments by a future edit to this one list.
"""
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import NoReverseMatch, reverse
from rest_framework.test import APIClient

from apps.economy.instruments import INSTRUMENTS
from apps.economy.models import membership_for
from music_connectz.urls import INSTRUMENT_APP_KEYS

User = get_user_model()
PW = "pw12345!"

# The five that had a profile and nowhere to send it. Named explicitly,
# rather than "all but singz/rapz", so this fails loudly if one is ever
# dropped back off the list instead of quietly passing on a smaller set.
NEWLY_MOUNTED = ("guitarz", "bassz", "keyz", "drumz", "violinz")


class TheProfileAndTheRouteNowAgreeTests(TestCase):

    def test_every_scored_profile_has_a_mounted_key(self):
        """The reverse of the bug: a profile with no route. INSTRUMENTS is
        the source of truth for what the coach can score; every one of those
        should be reachable, not just the two that shipped first."""
        for app_key in INSTRUMENTS:
            self.assertIn(app_key, INSTRUMENT_APP_KEYS, app_key)

    def test_the_five_are_actually_in_the_mounted_list(self):
        for app_key in NEWLY_MOUNTED:
            self.assertIn(app_key, INSTRUMENT_APP_KEYS, app_key)


class TheRoutesResolveForEveryInstrumentTests(TestCase):
    """`reverse()` raises if a name is not mounted at all — the exact failure
    mode `INSTRUMENT_APP_KEYS = ["singz", "rapz"]` produced for the other
    five before this change."""

    def test_coach_and_trial_names_resolve_for_every_mounted_instrument(self):
        for app_key in INSTRUMENT_APP_KEYS:
            try:
                reverse(f"{app_key}-coach")
                reverse(f"{app_key}-trial")
            except NoReverseMatch as e:                       # pragma: no cover
                self.fail(f"{app_key}: {e}")

    def test_the_skillz_training_tree_resolves_too(self):
        # `include((training_urlpatterns(key), key))` namespaces the name
        # (it becomes "<key>:<key>-skillz-profile"), which reverse() would
        # have to guess right — hitting the literal path a member's client
        # calls is the same proof without that guesswork.
        me = User.objects.create_user(username="route-check", password=PW)
        membership_for(me)
        c = APIClient()
        c.force_authenticate(me)
        for app_key in INSTRUMENT_APP_KEYS:
            r = c.get(f"/api/{app_key}/skillz/profile/")
            self.assertEqual(r.status_code, 200, app_key)


class ANewlyMountedCoachActuallyAnswersTests(TestCase):
    """Not a 404. `_take_from_post`/`score_take` genericity is already
    covered by test_vocalcoach.py; this only pins that the route a member
    would hit is live, end to end, for an instrument that used to 404."""

    def setUp(self):
        self.me = User.objects.create_user(username="guitarist", password=PW)
        membership_for(self.me)
        self.c = APIClient()
        self.c.force_authenticate(self.me)

    def test_guitarz_coach_reads_a_take_instead_of_404ing(self):
        f = SimpleUploadedFile("take.webm", b"0" * 900, content_type="audio/webm")
        r = self.c.post("/api/guitarz/coach/", {"take": f}, format="multipart")
        # No GEMINI_API_KEY in CI, so 503 ("isn't configured") is the honest
        # answer — the point is that it is THAT, and not a 404 from an
        # unmounted route.
        self.assertNotEqual(r.status_code, 404)

    def test_guitarz_skillz_profile_answers_for_a_real_member(self):
        r = self.c.get("/api/guitarz/skillz/profile/")
        self.assertEqual(r.status_code, 200, r.data)
