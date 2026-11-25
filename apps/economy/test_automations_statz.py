"""Corey's rule, held from the outside: anything that acts FOR the member is StatZ's (or the daily sample's) — it is
refused for Free and Premium and allowed for StatZ, whichever screen asks. Each server-side automation is poked at all
three tiers here, so a new one that forgets its gate has a place to be added and an old one cannot lose it quietly.
(Client-side ones — DAW automation, ImageZ Actions — are gated on the device and are listed in statz_trial.FEATURES.)"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.features import FEATURES, TIER_ORDER
from apps.economy.models import Membership, TIER_FREE, TIER_PREMIUM, TIER_STATZ, membership_for

U = get_user_model()


class AutomationsAreStatzTests(TestCase):
    def as_tier(self, tier):
        u = U.objects.create_user(f"u_{tier}_{U.objects.count()}", password="pw12345!x")
        membership_for(u); Membership.objects.filter(user=u).update(tier=tier)
        c = APIClient(); c.force_authenticate(u)
        return c

    def test_lilith_auto_switch(self):
        got = {t: self.as_tier(t).post("/api/economy/lilith/auto/", {"on": True}, format="json").status_code
               for t in (TIER_FREE, TIER_PREMIUM, TIER_STATZ)}
        self.assertEqual(got[TIER_FREE], 403); self.assertEqual(got[TIER_PREMIUM], 403)
        self.assertEqual(got[TIER_STATZ], 200)

    def test_challenge_auto_accept(self):
        url = "/api/economy/battlez/challengez/filters/"
        got = {t: self.as_tier(t).put(url, {"auto_accept": True}, format="json").status_code
               for t in (TIER_FREE, TIER_PREMIUM, TIER_STATZ)}
        self.assertEqual(got[TIER_FREE], 403); self.assertEqual(got[TIER_PREMIUM], 403)
        self.assertEqual(got[TIER_STATZ], 200)

    def test_the_feature_table_agrees_for_the_ones_that_act_on_your_behalf(self):
        for key in ("automationz", "gitz"):
            self.assertEqual(FEATURES[key]["tier"], TIER_STATZ, key)
        self.assertLess(TIER_ORDER.index(TIER_PREMIUM), TIER_ORDER.index(FEATURES["automationz"]["tier"]))
