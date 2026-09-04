"""VoiceZ — how hard the app is allowed to talk to a given member.

Three independent switches, and exactly one of them has a gate. The tests
that matter are the gate's: a platform that starts at 13 must not be one
swear word away from swearing at a thirteen-year-old because a client sent
{"voice": {"explicit": true}}.
"""
import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import EXPLICIT_MIN_AGE, may_be_explicit, profile_for

User = get_user_model()
PW = "hunter2hunter2"
ME = "/api/auth/me/"


def dob(years_ago):
    d = datetime.date.today().replace(day=1) - datetime.timedelta(days=365 * years_ago)
    return d.isoformat()


class VoiceDefaultsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="v", password=PW)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_the_house_voice_is_the_default(self):
        # Slang and emoji ON is how Music ConnectZ already talks; turning them
        # off is the deliberate act, not turning them on.
        v = self.client.get(ME).data["voice"]
        self.assertTrue(v["slang"])
        self.assertTrue(v["emoji"])
        self.assertFalse(v["explicit"])

    def test_emoji_and_slang_have_no_gate(self):
        r = self.client.patch(ME, {"voice": {"emoji": False, "slang": False}}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["voice"]["emoji"])
        self.assertFalse(r.data["voice"]["slang"])


class ExplicitGateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="v", password=PW)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def patch_bday(self, years_ago):
        return self.client.patch(ME, {"birthday": dob(years_ago)}, format="json")

    def test_no_birthday_means_no(self):
        # AdZ treats an unknown age as under-age rather than over it, and the
        # same answer is the right one here.
        self.assertFalse(may_be_explicit(profile_for(self.user)))
        r = self.client.patch(ME, {"voice": {"explicit": True}}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(self.client.get(ME).data["voice"]["explicit"])

    def test_a_minor_is_refused_out_loud(self):
        self.patch_bday(15)
        r = self.client.patch(ME, {"voice": {"explicit": True}}, format="json")
        # Refused, and SAID so — silently storing False for something somebody
        # just switched on is how a settings screen starts lying.
        self.assertEqual(r.status_code, 400)
        self.assertIn(str(EXPLICIT_MIN_AGE), r.data["detail"])
        self.assertFalse(r.data["voice_explicit_allowed"])

    def test_an_adult_may_switch_it_on(self):
        self.patch_bday(30)
        r = self.client.patch(ME, {"voice": {"explicit": True}}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["voice"]["explicit"])
        self.assertTrue(r.data["voice"]["explicit_allowed"])

    def test_turning_it_off_never_needs_permission(self):
        self.patch_bday(30)
        self.client.patch(ME, {"voice": {"explicit": True}}, format="json")
        r = self.client.patch(ME, {"voice": {"explicit": False}}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["voice"]["explicit"])

    def test_editing_the_birthday_younger_revokes_it(self):
        self.patch_bday(30)
        self.client.patch(ME, {"voice": {"explicit": True}}, format="json")
        r = self.patch_bday(14)
        self.assertFalse(r.data["voice"]["explicit"])
        self.assertFalse(r.data["voice"]["explicit_allowed"])
        # Cleared at the source, not just hidden on the way out.
        self.assertFalse(profile_for(self.user).voice_explicit)

    def test_a_stored_true_never_reads_true_for_a_minor(self):
        # Belt and braces for the row above: even if a True gets in there by
        # some other path, the READ applies the gate too.
        p = profile_for(self.user)
        p.birthday = dob(15)
        p.voice_explicit = True
        p.save(update_fields=["birthday", "voice_explicit"])
        self.assertFalse(self.client.get(ME).data["voice"]["explicit"])
