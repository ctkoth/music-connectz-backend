"""SocialZ: the screen's read, and the verify door it now sits in front of."""
import socket
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import social_verify
from apps.economy.models import (
    ENERGY_FLOOR_PER_HOUR, ENERGY_REACH_DIVISOR, SocialReview, TIER_FREE, TIER_PREMIUM,
    TIER_STATZ, energy_rate_per_hour, membership_for, profile_for,
)
from apps.economy.substancez import SUBSTANCE_KEYS

User = get_user_model()
PW = "hunter2hunter2"
URL = "/api/economy/socialz/"
VERIFY = "/api/economy/social/verify/"


def public(host="93.184.216.34"):
    """What getaddrinfo answers for a public site."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, 443))]


class Base(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="koth", password=PW, email="k@example.com")
        membership_for(self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def links(self, *rows):
        p = profile_for(self.user)
        p.links = list(rows)
        p.save(update_fields=["links"])


class TheReadTests(Base):
    def test_it_needs_a_login(self):
        self.assertIn(APIClient().get(URL).status_code, (401, 403))

    def test_a_new_member_has_one_source_and_the_floor(self):
        d = self.client.get(URL).data
        self.assertEqual([s["kind"] for s in d["sources"]], ["mcz"])
        self.assertEqual(d["reach"], 0)
        self.assertEqual(d["energy_per_hour"], ENERGY_FLOOR_PER_HOUR[TIER_FREE])

    def test_the_rule_is_built_from_the_constants_that_pay(self):
        d = self.client.get(URL).data
        self.assertEqual(d["divisor"], ENERGY_REACH_DIVISOR[TIER_FREE])
        self.assertEqual(d["floor"], ENERGY_FLOOR_PER_HOUR[TIER_FREE])
        self.assertIn(f"÷ {ENERGY_REACH_DIVISOR[TIER_FREE]}", d["rule"])
        self.assertIn(f"fewer than {ENERGY_FLOOR_PER_HOUR[TIER_FREE]}", d["rule"])

    def test_the_ladder_is_the_payers_own_answer_per_tier(self):
        self.links({"label": "IG", "url": "https://instagram.com/k", "verified": True,
                    "verified_count": 5000, "followers": 5000})
        d = self.client.get(URL).data
        by = {r["tier"]: r for r in d["ladder"]}
        for t in (TIER_FREE, TIER_PREMIUM, TIER_STATZ):
            self.assertEqual(by[t]["per_hour"], energy_rate_per_hour(self.user, tier=t))
        self.assertTrue(by[TIER_FREE]["yours"])
        self.assertGreater(by[TIER_STATZ]["per_hour"], by[TIER_FREE]["per_hour"])

    def test_only_a_verified_account_counts(self):
        self.links(
            {"label": "IG", "url": "https://instagram.com/k", "verified": True,
             "verified_count": 5000, "followers": 5000},
            {"label": "TikTok", "url": "https://tiktok.com/@k", "followers": 900000},
        )
        d = self.client.get(URL).data
        rows = {r["label"]: r for r in d["sources"]}
        self.assertTrue(rows["IG"]["counts"])
        self.assertEqual(rows["TikTok"]["status"], "unverified")
        self.assertFalse(rows["TikTok"]["counts"])
        self.assertEqual(d["counted"], 2)               # Music ConnectZ + IG
        # The big unverified number must not have moved reach.
        self.assertLess(d["reach"], 900000)

    def test_a_pending_and_a_rejected_account_say_so(self):
        self.links(
            {"label": "A", "url": "https://a.example/x", "review": "pending", "code": "MCZ-1"},
            {"label": "B", "url": "https://b.example/x"},
        )
        SocialReview.objects.create(user=self.user, url="https://a.example/x", ai_verdict="unsure",
                                    ai_reason="Handle is close but not the same.")
        SocialReview.objects.create(user=self.user, url="https://b.example/x",
                                    status=SocialReview.STATUS_REJECTED, note="Not your account.")
        rows = {r["label"]: r for r in self.client.get(URL).data["sources"]}
        self.assertEqual(rows["A"]["status"], "pending")
        self.assertIn("close", rows["A"]["note"])
        self.assertEqual(rows["B"]["status"], "rejected")
        self.assertEqual(rows["B"]["note"], "Not your account.")

    def test_a_verified_account_does_not_hand_back_its_code(self):
        self.links({"label": "IG", "url": "https://instagram.com/k", "verified": True,
                    "code": "MCZ-ABC", "verified_count": 10})
        row = self.client.get(URL).data["sources"][1]
        self.assertIsNone(row["code"])

    def test_it_says_a_connected_sign_in_does_not_count_followers(self):
        d = self.client.get(URL).data
        self.assertIn("doesn't read a follower count", d["oauth_note"])

    def test_it_states_the_cost_before_anything_is_pressed(self):
        self.assertIn("costs you nothing", self.client.get(URL).data["cost"])


class TheVerifyDoorTests(Base):
    """The screen puts a button on this endpoint, so what it will fetch and store
    has to be the same as everywhere else a member's link is written."""

    def start(self, url, **extra):
        return self.client.post(VERIFY, {"action": "start", "url": url, **extra}, format="json")

    def test_a_javascript_address_is_refused_and_stores_nothing(self):
        r = self.start("javascript:alert(1)")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(profile_for(self.user).links, [])

    def test_a_mailto_is_not_a_page_to_verify(self):
        self.assertEqual(self.start("mailto:a@b.com").status_code, 400)

    def test_a_bare_domain_is_completed_the_way_the_portfolio_does(self):
        r = self.start("instagram.com/koth")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(profile_for(self.user).links[0]["url"], "https://instagram.com/koth")

    def test_adding_past_the_tier_ceiling_is_refused_with_the_number(self):
        self.links(*[{"label": str(i), "url": f"https://x.example/{i}"} for i in range(25)])
        r = self.start("https://instagram.com/koth")
        self.assertEqual(r.status_code, 400)
        self.assertIn("25", r.data["detail"])
        self.assertEqual(len(profile_for(self.user).links), 25)

    def test_verifying_a_link_already_held_is_never_blocked_by_the_ceiling(self):
        self.links(*[{"label": str(i), "url": f"https://x.example/{i}"} for i in range(25)])
        self.assertEqual(self.start("https://x.example/3").status_code, 200)


class TheFetchIsNotAWayIntoOurNetworkTests(TestCase):
    def problem(self, url, answer):
        with patch("apps.economy.social_verify.socket.getaddrinfo", return_value=answer):
            return social_verify._public_host_problem(url)

    def test_a_public_address_passes(self):
        self.assertIsNone(self.problem("https://instagram.com/koth", public()))

    def test_loopback_private_and_metadata_addresses_are_refused(self):
        for ip in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "172.16.0.9"):
            self.assertIsNotNone(self.problem("https://x.example/", public(ip)), ip)

    def test_an_ipv4_address_wearing_an_ipv6_coat_is_still_refused(self):
        v6 = [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::ffff:127.0.0.1", 443, 0, 0))]
        self.assertIsNotNone(self.problem("https://x.example/", v6))

    def test_one_private_answer_among_public_ones_refuses_the_name(self):
        both = public("93.184.216.34") + public("10.0.0.1")
        self.assertIsNotNone(self.problem("https://x.example/", both))

    def test_only_http_and_https_and_no_credentials(self):
        for url in ("file:///etc/passwd", "ftp://x.example/", "https://user:pw@x.example/"):
            self.assertIsNotNone(self.problem(url, public()), url)

    def test_an_unresolvable_name_is_a_sentence_not_a_crash(self):
        with patch("apps.economy.social_verify.socket.getaddrinfo", side_effect=socket.gaierror):
            self.assertEqual(social_verify._public_host_problem("https://nope.invalid/"),
                             "couldn't find that site")

    def test_a_redirect_to_a_private_address_is_not_followed(self):
        hop = MagicMock(status_code=302, headers={"Location": "http://169.254.169.254/latest"})
        calls = []

        def resolve(host, *a, **k):
            calls.append(host)
            return public("169.254.169.254") if host == "169.254.169.254" else public()

        with patch("apps.economy.social_verify.socket.getaddrinfo", side_effect=resolve), \
                patch("requests.get", return_value=hop) as get:
            text, err = social_verify._fetch_public_page("https://x.example/")
        self.assertIsNone(text)
        self.assertEqual(err, "that isn't a public website")
        self.assertEqual(get.call_count, 1)             # the private hop was never requested

    def test_a_good_page_comes_back_as_visible_text(self):
        resp = MagicMock(status_code=200, headers={}, encoding="utf-8")
        resp.iter_content.return_value = [b"<html><script>x()</script><p>K-Oth 12.4k followers</p></html>"]
        with patch("apps.economy.social_verify.socket.getaddrinfo", return_value=public()), \
                patch("requests.get", return_value=resp):
            text, err = social_verify._fetch_public_page("https://x.example/")
        self.assertIsNone(err)
        self.assertIn("12.4k followers", text)
        self.assertNotIn("x()", text)


class TheSubstanceListIsTheOneMembersAskedFor(TestCase):
    def test_every_substance_is_there_in_the_order_given(self):
        self.assertEqual(SUBSTANCE_KEYS, [
            "cigarettes", "caffeine", "alcohol", "thc", "heroin", "crack", "meth",
            "dxm", "adderall", "opioids", "benzos"])
