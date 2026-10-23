"""⚡ per AI run and the XP tier bonus — Corey's numbers, pinned."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.economy.models import ai_energy_cost, membership_for, wallet_for, charge_ai_usage
from apps.economy.vocalcoach import coach_xp_base
from apps.skillz.models import TrainingProfile, tier_xp

User = get_user_model()


def at(user, tier):
    m = membership_for(user); m.tier = tier; m.save(update_fields=["tier"])


class AiEnergyTests(TestCase):
    def test_engine_base_times_tier_factor_rounded_up_at_least_one(self):
        u = User.objects.create_user("a", "a@e.com", "pw12345678")
        self.assertEqual(ai_energy_cost(u, "haiku"), 1)
        self.assertEqual(ai_energy_cost(u, "fable"), 8)
        self.assertEqual(ai_energy_cost(u, None), 1)
        at(u, "premium"); self.assertEqual(ai_energy_cost(u, "opus"), 2)
        at(u, "statz"); self.assertEqual(ai_energy_cost(u, "fable"), 2)
        self.assertEqual(ai_energy_cost(u, "haiku"), 1)

    def test_a_run_takes_its_energy_and_never_more_than_is_held(self):
        u = User.objects.create_user("b", "b@e.com", "pw12345678")
        w = wallet_for(u); w.energy = 5; w.promptz = 100; w.save()
        charge_ai_usage(u, 10, note="test", engine="fable")
        self.assertEqual(wallet_for(u).energy, 0)


class XpTests(TestCase):
    def test_coach_xp_pays_turning_up_and_quality(self):
        self.assertEqual(coach_xp_base(3), 10)
        self.assertEqual(coach_xp_base(5), 10)
        self.assertEqual(coach_xp_base(8), 40)
        self.assertEqual(coach_xp_base(10), 60)
        self.assertEqual(coach_xp_base(None), 10)

    def test_tier_bonus_lands_on_the_profile(self):
        u = User.objects.create_user("c", "c@e.com", "pw12345678")
        self.assertEqual(tier_xp(u, 40), 40)
        at(u, "premium"); self.assertEqual(tier_xp(u, 40), 50)
        at(u, "statz")
        p = TrainingProfile.objects.create(user=u, app_key="singz")
        self.assertEqual(p.add_xp(40), 60)
        self.assertEqual(p.xp, 60)
