"""Lilith's voice and "Not now": every suggestion says what it stands on, then what it means to the member, then
one call. Everyone hears the default voice; a StatZ member may choose another, and a lapsed choice rests. "Not now"
sets a suggestion aside for a while, for that member only, and it comes back on its own."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy import lilith_suggest as SG
from apps.economy import lilith_voice as V
from apps.economy.models import (HealthCondition, LilithRoutine, LilithTask, LilithVoice, Membership,
                                 OfferDismissal, TakeScore, membership_for)

User = get_user_model()
BOARD = "/api/economy/lilith/"
VOICE = "/api/economy/lilith/voice/"
NOT_NOW = "/api/economy/lilith/suggest/not-now/"


def member(name, tier=None):
    u = User.objects.create_user(name, f"{name}@mcz.test", "pw12345!")
    if tier:
        membership_for(u)
        Membership.objects.filter(user=u).update(tier=tier)
    return u


def rapper(u):
    for _ in range(4):
        TakeScore.objects.create(user=u, app_key="rapz", scores={"flow": 6}, overall=6)


class VoiceLinesTests(TestCase):
    def test_every_line_states_the_record_first_and_ends_on_one_call(self):
        for style, s in V.STYLES.items():
            line = V.say(style, "habit", "You've done this 4 times in the last 14 days.")
            self.assertTrue(line.startswith("You've done this 4 times in the last 14 days."), style)
            self.assertTrue(line.endswith(s["call"]), style)

    def test_no_voice_shouts(self):
        for style in V.STYLES:
            for kind in ("persona", "instrument", "habit", "gap", "activity", "profile", "start"):
                self.assertNotIn("!", V.say(style, kind, "A record."), (style, kind))

    def test_an_unknown_voice_falls_back_to_the_default(self):
        self.assertEqual(V.say("shouting", "habit", "A record."), V.say(V.DEFAULT, "habit", "A record."))

    def test_the_default_is_the_quiet_invited_voice(self):
        self.assertEqual(V.DEFAULT, "lilith")
        self.assertTrue(V.say("lilith", "activity", "A record.").endswith("Want it on your board?"))


class VoiceChoiceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.free = member("freeling")
        self.statz = member("statzling", tier="statz")
        self.c_free = APIClient(); self.c_free.force_authenticate(self.free)
        self.c_statz = APIClient(); self.c_statz.force_authenticate(self.statz)

    def test_everyone_hears_the_default(self):
        d = self.c_free.get(BOARD).data
        self.assertEqual(d["voice"]["style"], V.DEFAULT)
        self.assertFalse(d["voice"]["allowed"])
        self.assertTrue(d["voice"]["locked"])

    def test_a_free_member_cannot_choose_and_is_told_why(self):
        r = self.c_free.post(VOICE, {"style": "plain"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertIn("StatZ", r.json()["detail"])
        self.assertFalse(LilithVoice.objects.filter(user=self.free).exists())

    def test_a_statz_member_chooses_and_the_suggestions_speak_in_that_voice(self):
        rapper(self.statz)
        r = self.c_statz.post(VOICE, {"style": "plain"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["style"], "plain")
        cache.clear()
        d = self.c_statz.get(BOARD).data
        self.assertEqual(d["voice"]["style"], "plain")
        self.assertTrue(d["suggested"])
        for s in d["suggested"]:
            self.assertTrue(s["say"].endswith(V.STYLES["plain"]["call"]), s["key"])

    def test_an_unknown_voice_is_refused(self):
        self.assertEqual(self.c_statz.post(VOICE, {"style": "shouting"}, format="json").status_code, 400)

    def test_a_lapsed_choice_rests_and_the_default_is_heard_meanwhile(self):
        LilithVoice.objects.create(user=self.statz, style="warm")
        Membership.objects.filter(user=self.statz).update(tier="free")
        self.assertEqual(V.style_for(self.statz), V.DEFAULT)
        self.assertEqual(LilithVoice.objects.get(user=self.statz).style, "warm")

    def test_the_picker_offers_all_four_each_with_an_example(self):
        styles = self.c_free.get(VOICE).data["styles"]
        self.assertEqual({s["key"] for s in styles}, {"lilith", "plain", "warm", "quiet"})
        self.assertTrue(all(s["sample"] and s["about"] for s in styles))


class NotNowTests(TestCase):
    # A FREE member: a StatZ member's automation would add daily_rapz on the first board load, and then it is
    # on the board rather than suggested. The automation has its own test below.
    def setUp(self):
        cache.clear()
        self.u = member("nownow")
        self.c = APIClient(); self.c.force_authenticate(self.u)
        rapper(self.u)

    def routine_keys(self):
        cache.clear()
        return {s["key"] for s in self.c.get(BOARD).json()["suggested"] if s["kind"] == "routine"}

    def test_not_now_sets_a_suggestion_aside_for_this_member_only(self):
        self.assertIn("daily_rapz", self.routine_keys())
        self.assertEqual(self.c.post(NOT_NOW, {"kind": "routine", "key": "daily_rapz"}, format="json").status_code, 200)
        self.assertNotIn("daily_rapz", self.routine_keys())
        other = member("othernow")
        rapper(other)
        oc = APIClient(); oc.force_authenticate(other)
        cache.clear()
        self.assertIn("daily_rapz", {s["key"] for s in oc.get(BOARD).json()["suggested"]})

    def test_it_comes_back_once_the_wait_is_over(self):
        self.c.post(NOT_NOW, {"kind": "routine", "key": "daily_rapz"}, format="json")
        OfferDismissal.objects.filter(user=self.u).update(
            created_at=timezone.now() - timedelta(days=SG.NOT_NOW_DAYS + 1))
        self.assertIn("daily_rapz", self.routine_keys())

    def test_pressing_again_restarts_the_wait_and_makes_no_second_row(self):
        self.c.post(NOT_NOW, {"kind": "routine", "key": "daily_rapz"}, format="json")
        OfferDismissal.objects.filter(user=self.u).update(created_at=timezone.now() - timedelta(days=10))
        self.c.post(NOT_NOW, {"kind": "routine", "key": "daily_rapz"}, format="json")
        self.assertEqual(OfferDismissal.objects.filter(user=self.u, offer_key="lilith:routine:daily_rapz").count(), 1)
        self.assertNotIn("daily_rapz", self.routine_keys())

    def test_only_a_real_suggestion_can_be_set_aside(self):
        self.assertEqual(self.c.post(NOT_NOW, {"kind": "routine", "key": "no_such_thing"}, format="json").status_code, 404)
        self.assertEqual(self.c.post(NOT_NOW, {"kind": "banana", "key": "daily_rapz"}, format="json").status_code, 404)

    def test_the_automation_does_not_add_what_was_set_aside(self):
        s = member("statznow", tier="statz")
        rapper(s)
        sc = APIClient(); sc.force_authenticate(s)
        self.assertEqual(sc.post(NOT_NOW, {"kind": "routine", "key": "daily_rapz"}, format="json").status_code, 200)
        sc.get(BOARD)
        self.assertFalse(LilithRoutine.objects.filter(user=s, source="auto", template="daily_rapz").exists())


class ObservantTests(TestCase):
    def test_her_greeting_names_the_member_by_their_own_handle(self):
        u = member("handled")
        LilithTask.objects.create(user=u, title="Stretch", bucket="today")
        c = APIClient(); c.force_authenticate(u)
        self.assertIn("handled", c.get(BOARD).json()["said"])


class HealthRecordsTests(TestCase):
    """HealthZ says a diagnosis is never read by a recommendation. Lilith's suggestions are recommendations, so
    these pin the rule: a condition on the record never shows up in a suggestion, and a medication routine is
    only ever added by the member, never by automation."""

    def test_a_health_condition_is_never_read_by_a_suggestion(self):
        u = member("careful")
        HealthCondition.objects.create(user=u, name="Asthma", kind="physical")
        rapper(u)
        c = APIClient(); c.force_authenticate(u)
        cache.clear()
        data = c.get(BOARD).json()
        blob = str(data["suggested"]) + str(data["voice"]) + str(data["said"])
        self.assertNotIn("Asthma", blob)
        self.assertNotIn("health_meds", [s["key"] for s in data["suggested"]])

    def test_automation_never_adds_a_medication_routine(self):
        s = member("statzcare", tier="statz")
        rapper(s)
        c = APIClient(); c.force_authenticate(s)
        c.get(BOARD)
        self.assertFalse(LilithRoutine.objects.filter(user=s, template="health_meds").exists())
