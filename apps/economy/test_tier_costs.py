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
    def test_a_prompt_costs_the_tiers_energy_times_the_engine_base(self):
        # One prompt is 10 ⚡ on Free, 6 on Premium, 4 on StatZ, times the engine.
        u = User.objects.create_user("a", "a@e.com", "pw12345678")
        self.assertEqual(ai_energy_cost(u, None), 10)
        self.assertEqual(ai_energy_cost(u, "haiku"), 10)
        self.assertEqual(ai_energy_cost(u, "fable"), 80)
        at(u, "premium"); self.assertEqual(ai_energy_cost(u, None), 6)
        self.assertEqual(ai_energy_cost(u, "opus"), 24)
        at(u, "statz"); self.assertEqual(ai_energy_cost(u, None), 4)
        self.assertEqual(ai_energy_cost(u, "fable"), 32)

    def test_a_free_days_prompts_fit_inside_a_free_days_regeneration(self):
        # The reason the number is what it is: using every free prompt must not leave a
        # Free member unable to afford anything else that day.
        from apps.economy.models import AI_ENERGY_PER_PROMPT, ENERGY_FLOOR_PER_HOUR, PROMPT_ALLOWANCE
        self.assertLessEqual(AI_ENERGY_PER_PROMPT["free"] * PROMPT_ALLOWANCE["free"],
                             ENERGY_FLOOR_PER_HOUR["free"] * 24)
        # And a higher tier never pays more for the same prompt.
        self.assertGreater(AI_ENERGY_PER_PROMPT["free"], AI_ENERGY_PER_PROMPT["premium"])
        self.assertGreater(AI_ENERGY_PER_PROMPT["premium"], AI_ENERGY_PER_PROMPT["statz"])

    def test_a_take_costs_the_same_energy_on_every_tier(self):
        from apps.economy.catalog import COACH_TAKE_ENERGY
        self.assertEqual(len({COACH_TAKE_ENERGY[t] for t in ("free", "premium", "statz")}), 1)

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


class TrialAsMemberTests(TestCase):
    def test_the_trial_result_states_what_joining_is_worth(self):
        from apps.economy.trial import _as_member
        self.assertIsNone(_as_member({"score": None}))
        from apps.economy.models import PROMPT_ALLOWANCE
        self.assertEqual(_as_member({"score": 8, "score_exact": 8.0}),
                         {"daily_prompts": PROMPT_ALLOWANCE["free"], "energy": 12, "xp": 40, "kept": True})
