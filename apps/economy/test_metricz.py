"""PreferenceZ / SubstanceZ / ZodiacZ apps and the daily horoscope: counts are
of declarations, the adult kinds stay behind the age wall in both directions,
and a sign's reading is written once a day and shared."""
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.metricz import SIGN_NAMES, ZODIAC
from apps.economy.models import Horoscope, profile_for, zodiac_for

User = get_user_model()


def member(name, **fields):
    u = User.objects.create_user(name, f"{name}@e.com", "pw-Long-enough-1")
    p = profile_for(u)
    for k, v in fields.items():
        setattr(p, k, v)
    p.save()
    return u


def teen_birthday():
    t = timezone.localdate()
    return f"{t.year - 15}-01-15"


class MetricCountTests(TestCase):
    def setUp(self):
        self.me = member("me", birthday="1990-11-01", sign="Scorpio", attracted_to=["female"])
        member("a", birthday="1991-11-02", sign="Scorpio", substances={"thc": "often"}, attracted_to=["male", "female"])
        member("b", birthday="1992-04-01", sign="Aries", substances={"alcohol": "sometimes"})
        member("c", sober=True)
        member("teen", birthday=teen_birthday(), substances={"thc": "often"}, attracted_to=["male"])
        self.c = APIClient(); self.c.force_authenticate(self.me)

    def opt(self, d, key):
        return next(o for o in d["options"] if o["key"] == key)

    def test_zodiac_lists_all_twelve_with_dates_and_counts(self):
        d = self.c.get("/api/economy/metricz/zodiacz/").json()
        self.assertEqual([o["key"] for o in d["options"]], SIGN_NAMES)
        self.assertEqual(self.opt(d, "Scorpio")["count"], 2)
        self.assertEqual(self.opt(d, "Aries")["dates"], "March 21 – April 19")
        self.assertEqual(d["mine"], ["Scorpio"])
        self.assertTrue(self.opt(d, "Scorpio")["mine"])

    def test_substance_counts_skip_minors_and_count_the_sober_apart(self):
        d = self.c.get("/api/economy/metricz/substancez/").json()
        self.assertEqual(self.opt(d, "thc")["count"], 1)       # the teen's isn't counted
        self.assertEqual(self.opt(d, "alcohol")["count"], 1)
        self.assertEqual(d["sober"], 1)
        self.assertEqual(len(d["options"]), 11)

    def test_preference_counts(self):
        d = self.c.get("/api/economy/metricz/preferencez/").json()
        self.assertEqual(self.opt(d, "female")["count"], 2)
        self.assertEqual(self.opt(d, "male")["count"], 1)       # not the teen
        self.assertEqual(d["mine"], ["female"])

    def test_a_minor_gets_the_reason_never_the_list(self):
        c = APIClient(); c.force_authenticate(User.objects.get(username="teen"))
        for kind in ("substancez", "preferencez"):
            d = c.get(f"/api/economy/metricz/{kind}/").json()
            self.assertTrue(d["locked"])
            self.assertEqual(d["options"], [])
        self.assertTrue(c.get("/api/economy/metricz/zodiacz/").json()["options"])

    def test_unknown_kind_is_404(self):
        self.assertEqual(self.c.get("/api/economy/metricz/nope/").status_code, 404)

    def test_member_search_lists_who_uses_and_who_is_attracted(self):
        names = lambda q: {m["username"] for m in self.c.get(f"/api/economy/members/?{q}").json()["members"]}
        self.assertEqual(names("uses=thc"), {"a"})
        self.assertEqual(names("uses=thc,alcohol"), {"a", "b"})
        self.assertEqual(names("attracted=male"), {"a"})
        self.assertEqual(names("signs=Scorpio"), {"a"})

    def test_a_minor_cannot_search_by_use(self):
        c = APIClient(); c.force_authenticate(User.objects.get(username="teen"))
        got = {m["username"] for m in c.get("/api/economy/members/?uses=alcohol").json()["members"]}
        self.assertIn("me", got)   # the filter is dropped, not applied


class ZodiacDatesTests(TestCase):
    def test_every_published_range_agrees_with_zodiac_for(self):
        months = {m: i for i, m in enumerate(
            ["January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December"], 1)}
        for name, _, rng in ZODIAC:
            start, end = [x.strip().split(" ") for x in rng.split("–")]
            for m, d in (start, end):
                self.assertEqual(zodiac_for(f"2001-{months[m]:02d}-{int(d):02d}"), name, rng)


def gemini_reply(payload):
    r = MagicMock(status_code=200, text="ok")
    r.json.return_value = {"candidates": [{"content": {"parts": [{"text": payload}]}}]}
    return r


GOOD = ('{"overview":"Big day.","love":"Be open.","music":"Finish the hook.","money":"Hold.",'
        '"wellbeing":"Sleep.","mood":"bright","lucky_color":"teal","lucky_number":7,"best_match":"leo"}')


@patch("apps.economy.metricz._key", return_value="K")
class HoroscopeTests(TestCase):
    def setUp(self):
        self.c = APIClient(); self.c.force_authenticate(member("me"))

    def test_written_once_a_day_and_shared(self, _):
        with patch("apps.economy.metricz.generate_content", return_value=(gemini_reply(GOOD), ["m"])) as g:
            a = self.c.get("/api/economy/horoscope/scorpio/").json()
            b = self.c.get("/api/economy/horoscope/Scorpio/").json()
        self.assertEqual(g.call_count, 1)
        self.assertEqual(a["reading"], b["reading"])
        self.assertEqual(a["reading"]["best_match"], "Leo")
        self.assertEqual(a["cost"], 0)
        self.assertIn("not a forecast", a["note"])

    def test_a_new_day_is_a_new_reading(self, _):
        Horoscope.objects.create(sign="Leo", day=timezone.localdate() - timedelta(days=1), reading={"overview": "old"})
        with patch("apps.economy.metricz.generate_content", return_value=(gemini_reply(GOOD), ["m"])):
            d = self.c.get("/api/economy/horoscope/leo/").json()
        self.assertEqual(d["reading"]["overview"], "Big day.")

    def test_unusable_answer_is_not_stored_and_the_house_reading_stands_in(self, _):
        with patch("apps.economy.metricz.generate_content", return_value=(gemini_reply('{"overview":"x"}'), ["m"])):
            r = self.c.get("/api/economy/horoscope/leo/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["reading"]["source"], "house")
        self.assertFalse(Horoscope.objects.exists())

    def test_no_key_still_reads_and_the_house_reading_is_the_same_all_day(self, key):
        key.return_value = ""
        a = self.c.get("/api/economy/horoscope/leo/").json()
        b = self.c.get("/api/economy/horoscope/leo/").json()
        self.assertEqual(a["reading"], b["reading"])
        self.assertEqual(a["element"], "Fire")
        self.assertIn("The star.", a["about"])

    def test_compatibility_is_about_signs(self, _):
        with patch("apps.economy.metricz.generate_content", return_value=(gemini_reply(GOOD), ["m"])):
            d = self.c.get("/api/economy/horoscope/leo/?with=aquarius").json()
        c = d["compatibility"]
        self.assertEqual((c["element_a"], c["element_b"]), ("Fire", "Air"))
        self.assertEqual(c["score"], 9)       # complement 8, opposite signs +1
        self.assertIn("complement", c["note"])

    def test_unknown_sign(self, _):
        self.assertEqual(self.c.get("/api/economy/horoscope/ophiuchus/").status_code, 404)


ADV = ('{"love_single":"a.","love_partnered":"b.","money_earning":"c.","money_spending":"d.",'
       '"career":"e.","collab_signs":["leo","Pisces","Ophiuchus"],"collab_why":"f.","friction_sign":"taurus",'
       '"power_hours":"7–9pm","week":["1","2","3","4","5","6","7"],"challenge":"g.","affirmation":"h."}')


@patch("apps.economy.metricz._key", return_value="K")
class AdvancedHoroscopeTests(TestCase):
    def setUp(self):
        self.u = member("adv")
        self.c = APIClient(); self.c.force_authenticate(self.u)

    def tier(self, t):
        from apps.economy.models import membership_for
        m = membership_for(self.u); m.tier = t; m.save()

    def test_free_is_told_what_it_is_and_never_charged_a_call(self, _):
        with patch("apps.economy.metricz.generate_content") as g:
            r = self.c.get("/api/economy/horoscope/leo/?level=advanced")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["tier"], "statz")
        self.assertFalse(r.json()["advanced_available"])
        g.assert_not_called()

    def test_statz_gets_it_cached_apart_from_the_daily_one(self, _):
        self.tier("statz")
        with patch("apps.economy.metricz.generate_content",
                   side_effect=[(gemini_reply(ADV), ["m"]), (gemini_reply(GOOD), ["m"])]) as g:
            a = self.c.get("/api/economy/horoscope/leo/?level=advanced").json()
            again = self.c.get("/api/economy/horoscope/leo/?level=advanced").json()
            basic = self.c.get("/api/economy/horoscope/leo/").json()
        self.assertEqual(g.call_count, 2)
        self.assertEqual(a["reading"], again["reading"])
        self.assertEqual(a["reading"]["collab_signs"], ["Leo", "Pisces"])   # unknown sign dropped
        self.assertEqual(a["reading"]["friction_sign"], "Taurus")
        self.assertEqual(len(a["reading"]["week"]), 7)
        self.assertEqual(basic["reading"]["overview"], "Big day.")
        self.assertEqual(Horoscope.objects.filter(sign="Leo").count(), 2)

    def test_the_statz_sample_opens_it(self, _):
        self.c.post("/api/economy/statz-trial/")
        with patch("apps.economy.metricz.generate_content", return_value=(gemini_reply(ADV), ["m"])):
            self.assertEqual(self.c.get("/api/economy/horoscope/leo/?level=advanced").status_code, 200)

    def test_a_week_that_is_not_seven_days_is_not_stored(self, _):
        self.tier("statz")
        bad = ADV.replace('["1","2","3","4","5","6","7"]', '["1","2"]')
        with patch("apps.economy.metricz.generate_content", return_value=(gemini_reply(bad), ["m"])):
            self.assertEqual(self.c.get("/api/economy/horoscope/leo/?level=advanced").status_code, 503)
        self.assertFalse(Horoscope.objects.exists())


class CompatibilityTests(TestCase):
    def test_the_v22_rules(self):
        from apps.economy.metricz import compatibility
        self.assertEqual(compatibility("Aries", "Leo")["score"], 9)        # same element
        self.assertEqual(compatibility("Aries", "Aries")["score"], 8)      # same sign
        self.assertEqual(compatibility("Aries", "Cancer")["score"], 5)     # clash
        self.assertEqual(compatibility("Aries", "Libra")["score"], 9)      # complement + opposite
        self.assertIsNone(compatibility("Aries", "Ophiuchus"))


class PersonaFilterTests(TestCase):
    def test_members_by_persona(self):
        me = member("me")
        member("prod", personas=[{"key": "producer", "name": "Producer", "skills": []}])
        member("mix", personas=[{"key": "mixengineer", "name": "Mix Engineer", "skills": []}])
        c = APIClient(); c.force_authenticate(me)
        names = lambda q: {m["username"] for m in c.get(f"/api/economy/members/?{q}").json()["members"]}
        self.assertEqual(names("personas=producer"), {"prod"})
        self.assertEqual(names("personas=producer,mixengineer"), {"prod", "mix"})
