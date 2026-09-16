"""The login door accepted unlimited password guesses.

There was no rate limiting anywhere in this project — not configured in
settings, not applied to a single view. 25 wrong passwords in a row all
answered 400, and 25 million would have too.
"""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from .ratelimit import PER_ADDRESS, PER_IDENTIFIER

User = get_user_model()
PW = "hunter2hunter2"


class GuessingIsBoundedTests(TestCase):

    def setUp(self):
        cache.clear()
        self.c = APIClient()
        User.objects.create_user("target", "t@x.test", PW)

    def tearDown(self):
        cache.clear()

    def wrong(self, ident="target", ip="203.0.113.1"):
        return self.c.post("/api/auth/login/",
                           {"identifier": ident, "password": "nope"},
                           format="json", HTTP_X_FORWARDED_FOR=ip)

    def right(self, ident="target", ip="203.0.113.1"):
        return self.c.post("/api/auth/login/",
                           {"identifier": ident, "password": PW},
                           format="json", HTTP_X_FORWARDED_FOR=ip)

    def test_an_account_cannot_be_guessed_at_forever(self):
        for _ in range(PER_IDENTIFIER):
            self.assertEqual(self.wrong().status_code, 400)
        self.assertEqual(self.wrong().status_code, 429)

    def test_the_refusal_says_what_to_do(self):
        for _ in range(PER_IDENTIFIER):
            self.wrong()
        self.assertIn("reset your password", self.wrong().data["detail"].lower())

    def test_it_follows_the_account_across_addresses(self):
        """Keyed on the account too, so walking a botnet does not reset it."""
        for i in range(PER_IDENTIFIER):
            self.wrong(ip=f"203.0.113.{i + 10}")
        self.assertEqual(self.wrong(ip="198.51.100.7").status_code, 429)

    def test_a_good_password_clears_the_account_bucket(self):
        for _ in range(PER_IDENTIFIER - 1):
            self.wrong()
        self.assertEqual(self.right().status_code, 200)
        self.assertEqual(self.wrong().status_code, 400,
                         "a successful sign-in must reset the count")

    def test_a_successful_login_never_costs_anything(self):
        """Honest members must not slowly run themselves out of budget — which
        is what counting every request rather than every failure would do."""
        for _ in range(PER_IDENTIFIER * 3):
            self.assertEqual(self.right().status_code, 200)


class OneAddressIsNotOnePersonTests(TestCase):
    """The trial door's lesson, applied here before it could bite: a mobile
    carrier's CGNAT address fronts thousands of people."""

    def setUp(self):
        cache.clear()
        self.c = APIClient()
        for i in range(12):
            User.objects.create_user(f"member{i}", f"m{i}@x.test", PW)

    def tearDown(self):
        cache.clear()

    def test_the_address_limit_is_loose_enough_for_a_shared_carrier(self):
        self.assertGreater(PER_ADDRESS, PER_IDENTIFIER * 3)

    def test_one_persons_typos_do_not_lock_out_the_carrier(self):
        for _ in range(PER_IDENTIFIER):
            self.c.post("/api/auth/login/",
                        {"identifier": "member0", "password": "nope"},
                        format="json", HTTP_X_FORWARDED_FOR="203.0.113.5")
        other = self.c.post("/api/auth/login/",
                            {"identifier": "member1", "password": PW},
                            format="json", HTTP_X_FORWARDED_FOR="203.0.113.5")
        self.assertEqual(other.status_code, 200,
                         "a stranger on the same carrier address must still get in")

    def test_the_address_is_read_through_the_one_reader(self):
        """DRF's own get_ident uses the WHOLE X-Forwarded-For when NUM_PROXIES
        is unset, so varying that header hands an attacker a fresh bucket per
        request and the limit stops nobody."""
        for i in range(PER_IDENTIFIER):
            self.c.post("/api/auth/login/",
                        {"identifier": "member0", "password": "nope"}, format="json",
                        # A different spoofed prefix every time. The real
                        # address is the last hop and does not change.
                        HTTP_X_FORWARDED_FOR=f"10.0.0.{i}, 203.0.113.9")
        r = self.c.post("/api/auth/login/",
                        {"identifier": "member0", "password": "nope"}, format="json",
                        HTTP_X_FORWARDED_FOR="10.0.0.99, 203.0.113.9")
        self.assertEqual(r.status_code, 429,
                         "a spoofed prefix must not buy a fresh bucket")
