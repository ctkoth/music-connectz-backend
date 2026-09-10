"""What the deploy can tell you about payments without a Render login.

Every failure here is invisible from the code, because the code is fine — they
are all facts about the environment. The webhook one is why this exists: it is
the only failure where a member is charged and nothing arrives, and nothing
inside the app can see it happen.
"""
from django.test import TestCase, override_settings

from .payments_health import payments_state

LIVE = dict(STRIPE_SECRET_KEY="sk_live_x", STRIPE_PUBLISHABLE_KEY="pk_live_y",
            STRIPE_WEBHOOK_SECRET="whsec_z")


class PaymentsHealth(TestCase):
    @override_settings(**LIVE)
    def test_a_complete_live_setup_is_ready(self):
        st = payments_state()
        self.assertTrue(st["ready"])
        self.assertEqual(st["problems"], [])
        self.assertEqual(st["stripe"]["mode"], "live")

    @override_settings(**{**LIVE, "STRIPE_WEBHOOK_SECRET": ""})
    def test_a_missing_webhook_secret_is_reported(self):
        """The quiet one: checkout works, the wallet never gets credited."""
        st = payments_state()
        self.assertFalse(st["ready"])
        self.assertFalse(st["stripe"]["webhook_configured"])
        self.assertTrue(any("WEBHOOK" in p for p in st["problems"]))

    @override_settings(**{**LIVE, "STRIPE_SECRET_KEY": "sk_test_x"})
    def test_mismatched_key_modes_are_reported(self):
        st = payments_state()
        self.assertFalse(st["stripe"]["modes_agree"])
        self.assertTrue(any("disagree" in p for p in st["problems"]))

    @override_settings(**{**LIVE, "STRIPE_SECRET_KEY": "sk_test_x",
                          "STRIPE_PUBLISHABLE_KEY": "pk_test_y"})
    def test_test_mode_is_called_out_even_when_consistent(self):
        """Consistent test keys are a correct staging deploy and a broken live
        one, so it is said either way rather than passing silently."""
        st = payments_state()
        self.assertTrue(st["stripe"]["modes_agree"])
        self.assertTrue(any("TEST mode" in p for p in st["problems"]))

    @override_settings(STRIPE_SECRET_KEY="", STRIPE_PUBLISHABLE_KEY="",
                       STRIPE_WEBHOOK_SECRET="")
    def test_one_side_unset_is_not_called_a_mismatch(self):
        """Unconfigured and mismatched are different problems with different
        fixes; reporting one as the other sends somebody after the wrong bug."""
        st = payments_state()
        self.assertTrue(st["stripe"]["modes_agree"])
        self.assertTrue(any("not set" in p for p in st["problems"]))

    @override_settings(**LIVE)
    def test_it_never_publishes_any_part_of_a_key(self):
        """This endpoint is open to anybody. `configured` is the whole question."""
        blob = repr(payments_state())
        for secret in ("sk_live_x", "pk_live_y", "whsec_z", "sk_live", "whsec"):
            self.assertNotIn(secret, blob)

    @override_settings(**LIVE)
    def test_the_health_endpoint_serves_it(self):
        d = self.client.get("/").json()
        self.assertIn("payments", d)
        self.assertTrue(d["payments"]["ready"])
