"""SoundZ — a stored choice, a tier gate, and a line this module must not cross.

The sounds are synthesised in `src/sound.js`. This file stores WHICH set a
member picked and nothing about how any of them sound, and the tests below hold
that line as much as they hold the gate: the moment Python knows what "arcade"
sounds like there are two sources of truth for it and the client drifts from
this one the first time somebody tunes a waveform.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import (TIER_FREE, TIER_PREMIUM, TIER_STATZ,
                                 membership_for, profile_for)
from apps.economy.soundz import MAX_OVERRIDES, clean_overrides, clean_pack

User = get_user_model()
PW = "hunter2hunter2"
URL = "/api/economy/soundz/"


def tier(user, t):
    m = membership_for(user)
    m.tier = t
    m.save(update_fields=["tier"])
    return user


class TheGateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("s", "s@e.com", PW)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_everyone_can_read_their_settings(self):
        # Reading is not the perk. A Free member still needs to know what they
        # are hearing, and that the house set is what they have.
        d = self.client.get(URL).data
        self.assertEqual(d["pack"], "")
        self.assertFalse(d["can_customize"])

    def test_a_free_member_cannot_set_a_pack(self):
        r = self.client.patch(URL, {"pack": "arcade"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(profile_for(self.user).sound_pack, "")

    def test_the_refusal_says_what_is_still_free(self):
        # Sound itself is not sold — only choosing a different set is.
        r = self.client.patch(URL, {"pack": "arcade"}, format="json")
        self.assertIn("free at every tier", r.data["detail"])

    def test_premium_may_set_one(self):
        tier(self.user, TIER_PREMIUM)
        r = self.client.patch(URL, {"pack": "arcade"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(profile_for(self.user).sound_pack, "arcade")

    def test_statz_may_too(self):
        tier(self.user, TIER_STATZ)
        self.assertEqual(self.client.patch(URL, {"pack": "soft"}, format="json").status_code, 200)

    def test_it_follows_the_account_not_the_browser(self):
        # The whole reason this is not in localStorage: it is sold, and a perk
        # that evaporates on your phone is a browser setting somebody paid for.
        tier(self.user, TIER_PREMIUM)
        self.client.patch(URL, {"pack": "retro"}, format="json")
        other_device = APIClient()
        other_device.force_authenticate(self.user)
        self.assertEqual(other_device.get(URL).data["pack"], "retro")


class TheShapeTests(TestCase):
    """The server checks shape; the client checks meaning."""

    def setUp(self):
        self.user = tier(User.objects.create_user("p", "p@e.com", PW), TIER_PREMIUM)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_a_pack_key_is_a_slug(self):
        self.assertEqual(clean_pack("arcade"), "arcade")
        self.assertEqual(clean_pack("  ARCADE  "), "arcade")
        self.assertEqual(clean_pack("has spaces"), "")
        self.assertEqual(clean_pack("<script>"), "")
        self.assertEqual(clean_pack("x" * 64), "")
        self.assertEqual(clean_pack(None), "")

    def test_junk_falls_back_to_the_house_sound_rather_than_erroring(self):
        # Worst case here is hearing the standard set, so refusing the whole
        # save over one bad value would be the more annoying failure.
        r = self.client.patch(URL, {"pack": "not a slug!"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["pack"], "")

    def test_one_bad_override_does_not_cost_the_others(self):
        r = self.client.patch(URL, {"overrides": {
            "spinaz_gain": "arcade", "bad key": "soft", "error": "not valid!",
        }}, format="json")
        self.assertEqual(r.data["overrides"], {"spinaz_gain": "arcade"})

    def test_overrides_are_bounded(self):
        big = {f"k{i}": "arcade" for i in range(MAX_OVERRIDES + 40)}
        self.assertLessEqual(len(clean_overrides(big)), MAX_OVERRIDES)

    def test_overrides_must_be_a_map(self):
        self.assertEqual(clean_overrides(["arcade"]), {})
        self.assertEqual(clean_overrides("arcade"), {})

    def test_a_pack_the_server_has_never_heard_of_is_still_stored(self):
        # This is the point of the split. The server cannot know what packs
        # exist without holding a copy of the client's audio design, so it
        # accepts any plausible slug and the client falls back if it does not
        # recognise it.
        r = self.client.patch(URL, {"pack": "some-future-pack"}, format="json")
        self.assertEqual(r.data["pack"], "some-future-pack")


class TheLineTests(TestCase):
    def test_the_server_stores_no_waveforms(self):
        """If this ever fails, someone has copied the audio design into Python.

        A pack is oscillator settings. Two copies of those means the client
        drifts from this one the first time a sound is tuned, and the drift is
        silent — the wrong sound is still a sound.
        """
        from apps.economy import soundz
        src = open(soundz.__file__).read()
        for word in ("sine", "square", "sawtooth", "triangle", "oscillator", "frequency"):
            self.assertNotIn(word, src.lower().split("\"\"\"")[-1],
                             f"synthesis detail '{word}' leaked into the server")
