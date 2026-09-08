"""One voice everywhere, and the part of it a member does not get to turn off.

The split under test: the TONE is the member's — emoji, style, colloquialisms,
how much reasoning — and the FOUR RULES are not. No setting removes "say the
price before they pay it", because that is what the app promises rather than
how it sounds, and a member who could dial it away would be choosing to be told
less about what things cost.

The other half is that the voice is one row rather than one app's request
field. It used to arrive from the client on every OCC call, so a member who
turned the emoji down in OCC met the founder voice at full volume in the coach
five seconds later.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import voice
from apps.economy.models import VoicePrefs, voice_prefs_for
from apps.economy.resources import ENERGY, MONEY, PROMPTZ, SPINAZ, XP

User = get_user_model()
PW = "hunter2hunter2"


def member(name="singer"):
    return User.objects.create_user(name, f"{name}@x.com", PW)


def client_for(u):
    c = APIClient()
    c.force_authenticate(u)
    return c


class TheRulesAreNotAPreferenceTests(TestCase):
    def test_the_paradigm_is_in_every_prompt_at_every_setting(self):
        u = member()
        for style in ("corey", "standard", "technical"):
            for emoji in ("heavy", "light", "off"):
                for depth in ("brief", "normal", "deep"):
                    p = voice.voice_prompt(u, override={
                        "style": style, "emoji": emoji, "depth": depth})
                    self.assertIn("THE FOUR RULES", p, (style, emoji, depth))
                    self.assertIn("not a price, it's a bill", p)

    def test_the_marks_are_in_the_prompt_and_come_from_one_place(self):
        p = voice.voice_prompt(member())
        for mark in (ENERGY, SPINAZ, PROMPTZ, MONEY, XP):
            self.assertIn(mark, p)

    def test_emoji_off_still_keeps_the_resource_marks(self):
        # "Off" is about decoration. A bare number is the rule-1 violation, and
        # the mark is what makes a cost a price rather than a quantity.
        p = voice.voice_prompt(member(), override={"emoji": "off"})
        self.assertIn("except the resource marks", p)
        self.assertIn(SPINAZ, p)

    def test_the_banned_phrases_are_named_rather_than_implied(self):
        p = voice.voice_prompt(member())
        for phrase in ("Oops", "Something went wrong", "member"):
            self.assertIn(phrase, p)

    def test_it_is_told_never_to_invent_a_number(self):
        # The drift that put "20 free prompts" in nine places, with a model
        # able to make a new one every reply.
        self.assertIn("never invent a tier limit", voice.voice_prompt(member()))


class ThePreferencesTests(TestCase):
    def test_the_default_is_the_house_style_not_a_neutral_one(self):
        # A member who never opens the setting gets the product as designed.
        # The setting exists for the contract they are writing in OCC, not to
        # make them opt in to the app having a voice.
        p = voice.prefs_dict(member())
        self.assertEqual(p, {"style": "corey", "emoji": "heavy",
                             "depth": "normal", "slang": False})

    def test_a_nonsense_value_falls_back_instead_of_raising(self):
        self.assertEqual(voice.clean_prefs({"style": "pirate", "emoji": 7})["style"], "corey")
        self.assertEqual(voice.clean_prefs({"emoji": "gigantic"})["emoji"], "heavy")

    def test_the_tone_dials_actually_move_the_prompt(self):
        u = member()
        heavy = voice.voice_prompt(u, override={"emoji": "heavy"})
        off = voice.voice_prompt(u, override={"emoji": "off"})
        self.assertNotEqual(heavy, off)
        self.assertIn("go heavy", heavy)
        self.assertNotIn("go heavy", off)

    def test_tone_settings_do_not_leak_into_the_neutral_styles(self):
        # A heavy-emoji instruction inside "technical" fights the mode it was
        # chosen for.
        p = voice.voice_prompt(member(), override={"style": "technical", "emoji": "heavy"})
        self.assertNotIn("go heavy", p)

    def test_the_colloquialisms_are_off_until_asked_for(self):
        u = member()
        self.assertNotIn("good looks", voice.voice_prompt(u))
        self.assertIn("good looks", voice.voice_prompt(u, override={"slang": True}))

    def test_the_reversal_is_capped_at_one(self):
        # A model handed "use the reversal" with no ceiling writes a page of
        # them, which reads as a tic rather than a punch.
        self.assertIn("ONCE per reply at most", voice.voice_prompt(member()))


class OneRowNotOneAppTests(TestCase):
    def test_a_setting_saved_once_is_read_by_every_surface(self):
        u = member()
        client_for(u).patch("/api/economy/voicez/", {"emoji": "off"}, format="json")
        # The coach reads the same row OCC wrote.
        self.assertNotIn("go heavy", voice.voice_prompt(u))
        self.assertEqual(voice_prefs_for(u).emoji, "off")

    def test_an_override_is_this_request_only(self):
        u = member()
        voice.voice_prompt(u, override={"style": "technical"})
        self.assertEqual(voice_prefs_for(u).style, "corey")


class TheEndpointTests(TestCase):
    def setUp(self):
        self.u = member()
        self.c = client_for(self.u)

    def test_get_publishes_the_options_and_what_cannot_be_changed(self):
        r = self.c.get("/api/economy/voicez/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["voice"]["style"], "corey")
        self.assertTrue(r.data["options"]["style"])
        # Said out loud rather than left as an absence, so nobody hunts for a
        # switch that is deliberately not there.
        self.assertTrue(r.data["always_on"])
        self.assertTrue(any(SPINAZ in line for line in r.data["always_on"]))

    def test_patch_changes_only_what_it_names(self):
        self.c.patch("/api/economy/voicez/", {"depth": "brief"}, format="json")
        p = voice.prefs_dict(self.u)
        self.assertEqual(p["depth"], "brief")
        self.assertEqual(p["emoji"], "heavy")

    def test_patch_refuses_nothing_and_falls_back_instead(self):
        r = self.c.patch("/api/economy/voicez/", {"style": "shakespeare"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["voice"]["style"], "corey")

    def test_it_needs_a_login(self):
        self.assertIn(APIClient().get("/api/economy/voicez/").status_code, (401, 403))

    def test_one_row_per_member(self):
        for _ in range(3):
            voice_prefs_for(self.u)
        self.assertEqual(VoicePrefs.objects.filter(user=self.u).count(), 1)


class StructuredSurfacesTests(TestCase):
    """The coach and DirectZ parse what comes back, so they get the short form."""

    def test_the_prose_voice_says_nothing_about_shape(self):
        p = voice.prose_voice(member())
        for word in ("JSON", "field name", "schema", '"scores"'):
            self.assertNotIn(word, p)

    def test_it_is_short_enough_not_to_crowd_the_contract(self):
        u = member()
        # The full preamble competing with an output contract risks the one
        # thing that must not break: a take that scored fine coming back
        # unparseable.
        self.assertLess(len(voice.prose_voice(u)), len(voice.voice_prompt(u)) / 3)

    def test_it_still_carries_the_things_that_reach_the_member(self):
        p = voice.prose_voice(member())
        self.assertIn("take", p)
        self.assertIn("Oops", p)      # named as banned
        self.assertIn("what to do next", p)

    def test_technical_members_get_a_plain_one(self):
        u = member()
        p = voice_prefs_for(u)
        p.style = "technical"
        p.save(update_fields=["style", "updated_at"])
        self.assertIn("plainly", voice.prose_voice(u))

    def test_no_member_at_all_is_the_house_default(self):
        # The logged-out trial shares the coach's rubric and gets its voice too.
        self.assertTrue(voice.prose_voice(None))
