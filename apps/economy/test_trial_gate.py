"""Who the trial door says no to, and whether it is telling the truth.

The per-address ceiling was ONE take per IP per 24h, and it was wrong in both
directions at once: it locked out honest visitors sharing a carrier's CGNAT
address, and it stopped nobody, because the address it keyed on came out of a
header the caller writes.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import TRIAL_PER_IP, TrialTake, trial_daily_cap
from .trial import client_ip, trial_state


class TheAddressIsNotThePersonTests(TestCase):

    def take(self, ip="203.0.113.5", anon_id="", ago_hours=0):
        t = TrialTake.objects.create(
            token=f"t{TrialTake.objects.count()}", app_key="singz",
            ip=ip, anon_id=anon_id, result={"score": 7})
        if ago_hours:
            TrialTake.objects.filter(pk=t.pk).update(
                created_at=timezone.now() - timedelta(hours=ago_hours))
        return t

    def test_one_stranger_on_a_carrier_no_longer_shuts_the_door(self):
        """The whole bug. One visitor behind a shared CGNAT address used to
        spend the free take for every other subscriber behind it."""
        self.take(ip="203.0.113.5", anon_id="phone-a")
        _today, browser_done, ip_over = trial_state("203.0.113.5", "phone-b")
        self.assertFalse(browser_done, "a different browser has not had a take")
        self.assertFalse(ip_over, "one take must not close a shared address")

    def test_a_browser_still_only_gets_one(self):
        self.take(ip="203.0.113.5", anon_id="phone-a")
        _today, browser_done, _ip = trial_state("203.0.113.5", "phone-a")
        self.assertTrue(browser_done)

    def test_the_address_still_has_a_ceiling(self):
        """Loosened, not removed. One address may never spend the whole day."""
        for i in range(TRIAL_PER_IP):
            self.take(ip="203.0.113.5", anon_id=f"b{i}")
        _today, _browser, ip_over = trial_state("203.0.113.5", "someone-new")
        self.assertTrue(ip_over)
        self.assertLess(TRIAL_PER_IP, trial_daily_cap(),
                        "one address must not be able to spend the global cap")

    def test_a_blank_anon_id_never_matches_anybody(self):
        """Private-mode browsers cannot read localStorage and send "". Counting
        all of them as one visitor would shut the door on every one at once."""
        self.take(ip="203.0.113.5", anon_id="")
        _today, browser_done, _ip = trial_state("203.0.113.5", "")
        self.assertFalse(browser_done)

    def test_the_window_expires(self):
        self.take(anon_id="phone-a", ago_hours=25)
        _today, browser_done, _ip = trial_state("203.0.113.5", "phone-a")
        self.assertFalse(browser_done)


class TheAddressCameFromTheCallerTests(TestCase):
    """X-Forwarded-For is APPENDED to by each proxy, so entry [0] is whatever
    the caller put there — and that is what the rate limit keyed on."""

    def ip_for(self, header):
        class R:
            META = {"HTTP_X_FORWARDED_FOR": header, "REMOTE_ADDR": "10.0.0.1"}
        return client_ip(R())

    def test_a_caller_cannot_choose_its_own_address(self):
        self.assertEqual(self.ip_for("1.2.3.4, 203.0.113.9"), "203.0.113.9")

    def test_a_plain_request_still_works(self):
        self.assertEqual(self.ip_for("203.0.113.9"), "203.0.113.9")

    def test_no_header_falls_back_to_remote_addr(self):
        class R:
            META = {"REMOTE_ADDR": "10.0.0.1"}
        self.assertEqual(client_ip(R()), "10.0.0.1")


class TheDoorSaysWhichNoItIsTests(TestCase):

    def setUp(self):
        self.c = APIClient()

    def test_a_busy_address_is_not_reported_as_the_visitor_s_own_take(self):
        """Two different refusals. One is answered by making an account, the
        other by us raising a ceiling — and telling somebody they have had a
        take they never had is unanswerable."""
        for i in range(TRIAL_PER_IP):
            TrialTake.objects.create(token=f"x{i}", app_key="singz",
                                     ip="203.0.113.5", anon_id=f"b{i}")
        r = self.c.get("/api/singz/trial/?anon_id=brand-new",
                       HTTP_X_FORWARDED_FOR="203.0.113.5")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["address_busy"])
        self.assertFalse(r.data["already_used"])
        self.assertFalse(r.data["available"])

    def test_the_post_refuses_with_the_same_distinction(self):
        for i in range(TRIAL_PER_IP):
            TrialTake.objects.create(token=f"y{i}", app_key="singz",
                                     ip="203.0.113.5", anon_id=f"b{i}")
        r = self.c.post("/api/singz/trial/", {"anon_id": "brand-new"},
                        HTTP_X_FORWARDED_FOR="203.0.113.5")
        self.assertEqual(r.status_code, 429)
        self.assertTrue(r.data.get("address_busy"))
        self.assertNotIn("already_used", r.data)
        self.assertNotIn("you've had", r.data["detail"].lower())


class PublicStatsTests(TestCase):
    """It queried `visitor_id`, which is not a field, in four places — so every
    request was a 500 and it never once answered."""

    def setUp(self):
        self.c = APIClient()

    def test_it_answers_at_all(self):
        r = self.c.get("/api/economy/trial/public/stats/")
        self.assertEqual(r.status_code, 200, r.content)

    def test_it_stays_quiet_until_the_number_means_something(self):
        r = self.c.get("/api/economy/trial/public/stats/")
        self.assertFalse(r.data["enough"])

    def test_it_counts_takes_rather_than_publishing_our_conversion_rate(self):
        """A funnel rate is a fact about OUR door, not about the coach. Handing
        "Tried → Scored: 5%" to somebody deciding whether to try argues against
        trying, and it was rendered under the heading "What members do"."""
        for i in range(30):
            TrialTake.objects.create(token=f"z{i}", app_key="singz")
        r = self.c.get("/api/economy/trial/public/stats/")
        self.assertTrue(r.data["enough"])
        self.assertEqual(r.data["takes_scored"], 30)
        self.assertGreaterEqual(r.data["doors"], 7)
        self.assertNotIn("headline", r.data)

    def test_a_junk_days_parameter_does_not_500(self):
        self.assertEqual(
            self.c.get("/api/economy/trial/public/stats/?days=banana").status_code, 200)
        self.assertEqual(
            self.c.get("/api/economy/trial/public/stats/?days=-5").status_code, 200)


class AnUnscorableTakeIsNotTheTakeTheyCameForTests(TestCase):
    """The coach listened and there was no performance in the file.

    That row was written exactly like a scored one, so a visitor who uploaded
    the wrong file or recorded silence spent their one free take, got no
    number, and was told "You've had your free take for today" when they tried
    again with a real one. The cost/gain rule broken the most expensive way
    there is, because the thing they spent was a performance.
    """

    def state_for(self, browser="phone-a"):
        return trial_state("203.0.113.5", browser)

    def test_an_unscorable_take_does_not_use_up_the_free_take(self):
        TrialTake.objects.create(token="u1", app_key="singz", ip="203.0.113.5",
                                 anon_id="phone-a", scored=False,
                                 result={"unscorable": "no performance here", "score": None})
        _today, browser_done, _ip = self.state_for()
        self.assertFalse(browser_done)

    def test_a_scored_take_still_does(self):
        TrialTake.objects.create(token="s1", app_key="singz", ip="203.0.113.5",
                                 anon_id="phone-a", scored=True, result={"score": 7})
        _today, browser_done, _ip = self.state_for()
        self.assertTrue(browser_done)

    def test_it_still_counts_against_the_address_and_the_global_cap(self):
        """We paid for the model call either way. A row that did not count
        would be money spent off the books."""
        for i in range(TRIAL_PER_IP):
            TrialTake.objects.create(token=f"u{i}", app_key="singz",
                                     ip="203.0.113.5", anon_id=f"b{i}", scored=False)
        today, _browser, ip_over = self.state_for("brand-new")
        self.assertTrue(ip_over)
        self.assertEqual(today, TRIAL_PER_IP)

    def test_rows_written_before_this_column_existed_still_count(self):
        """Every one of them was scored, so the default has to be True."""
        t = TrialTake.objects.create(token="old", app_key="singz",
                                     ip="203.0.113.5", anon_id="phone-a")
        self.assertTrue(t.scored)
