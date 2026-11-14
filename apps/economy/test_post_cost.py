"""Posting costs the skills you put on it — and says so first.

The composer has always shown a skill picker and sent no cost with it, so every
post in this app has been free while the screen implied a price. And the cost
came from the REQUEST, which means the client's zero was the real price.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import Post, membership_for, post_energy_floor, profile_for, wallet_for

User = get_user_model()
PW = "hunter2hunter2"
POSTZ = "/api/economy/postz/"
COST = "/api/economy/postz/cost/"


def pin_small_floor(testcase):
    """These tests check skill-price ARITHMETIC (40 + 25 = 65); the tier floor (a prompt's ⚡:
    2000 / 500 / 100) would swamp every number. The floor has its own tests."""
    from unittest.mock import patch
    p = patch.dict("apps.economy.models.AI_ENERGY_PER_PROMPT",
                   {"free": 1, "premium": 1, "statz": 1, "debug": 1})
    p.start()
    testcase.addCleanup(p.stop)



class CostBase(TestCase):
    def setUp(self):
        pin_small_floor(self)
        self.user = User.objects.create_user(username="maker", password=PW)
        membership_for(self.user)
        p = profile_for(self.user)
        p.personas = [{"key": "producer", "name": "Beat Producer", "skills": [
            {"name": "Beat Producer", "rate_cents": 40},
            {"name": "Mix / Master Engineer", "rate_cents": 25},
            {"name": "Ghost Writer"},              # no rate — costs nothing
        ]}]
        p.save(update_fields=["personas"])
        w = wallet_for(self.user)
        w.energy = 500
        w.save(update_fields=["energy"])
        self.client = APIClient()
        self.client.force_authenticate(self.user)


class ThePriceIsQuotedFirstTests(CostBase):
    def test_the_cost_endpoint_totals_the_skills(self):
        r = self.client.get(f"{COST}?skills=Beat Producer,Mix / Master Engineer")
        self.assertEqual(r.data["cost"], {"resource": "energy", "amount": 65})

    def test_it_breaks_the_price_down_per_skill(self):
        r = self.client.get(f"{COST}?skills=Beat Producer,Ghost Writer")
        lines = {l["skill"]: l["cents"] for l in r.data["lines"]}
        self.assertEqual(lines, {"Beat Producer": 40, "Ghost Writer": 0})

    def test_an_unpriced_skill_costs_only_the_floor_and_says_so(self):
        from apps.economy.models import post_energy_floor
        r = self.client.get(f"{COST}?skills=Ghost Writer")
        self.assertEqual(r.data["cost"]["amount"], post_energy_floor(self.user))
        self.assertIn("haven't priced", r.data["note"])

    def test_no_skills_costs_the_floor(self):
        from apps.economy.models import post_energy_floor
        self.assertEqual(self.client.get(COST).data["cost"]["amount"], post_energy_floor(self.user))

    def test_it_says_what_will_actually_come_off(self):
        w = wallet_for(self.user); w.energy = 30; w.save(update_fields=["energy"])
        r = self.client.get(f"{COST}?skills=Beat Producer")
        self.assertEqual(r.data["cost"]["amount"], 40)
        self.assertEqual(r.data["charged"], 30)      # energy never goes negative
        self.assertFalse(r.data["affordable"])

    def test_it_lists_which_skills_have_a_price_at_all(self):
        r = self.client.get(COST)
        self.assertEqual(r.data["priced_skills"],
                         ["Beat Producer", "Mix / Master Engineer"])


class TheChargeMatchesTheQuoteTests(CostBase):
    def test_posting_charges_the_quoted_amount(self):
        quoted = self.client.get(f"{COST}?skills=Beat Producer").data["cost"]["amount"]
        r = self.client.post(POSTZ, {"title": "Take", "skills_used": ["Beat Producer"]},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["energy_charged"], quoted)
        self.assertEqual(wallet_for(self.user).energy, 460)

    def test_a_post_with_no_skills_costs_only_the_floor(self):
        from apps.economy.models import post_energy_floor
        self.client.post(POSTZ, {"title": "Take"}, format="json")
        # Taken UP TO what is held: the floor (2000 on Free) is more than the 500 in the wallet.
        self.assertEqual(wallet_for(self.user).energy, max(0, 500 - post_energy_floor(self.user)))

    def test_the_cost_comes_from_my_rates_not_from_the_request(self):
        # A client-supplied price is a price the client can set to zero, which
        # is exactly what the composer was doing.
        r = self.client.post(POSTZ, {"title": "Take", "skills_used": ["Beat Producer"],
                                     "skill_cost_cents": 0}, format="json")
        self.assertEqual(r.data["energy_charged"], 40)

    def test_a_request_cannot_inflate_the_price_either(self):
        r = self.client.post(POSTZ, {"title": "Take", "skills_used": ["Beat Producer"],
                                     "skill_cost_cents": 99999}, format="json")
        self.assertEqual(r.data["energy_charged"], 40)

    def test_someone_elses_rates_are_not_mine(self):
        other = User.objects.create_user(username="rich", password=PW)
        p = profile_for(other)
        p.personas = [{"key": "x", "name": "x", "skills": [
            {"name": "Beat Producer", "rate_cents": 5000}]}]
        p.save(update_fields=["personas"])
        r = self.client.post(POSTZ, {"title": "Take", "skills_used": ["Beat Producer"]},
                             format="json")
        self.assertEqual(r.data["energy_charged"], 40)

    def test_the_post_records_what_it_cost(self):
        r = self.client.post(POSTZ, {"title": "Take", "skills_used": ["Beat Producer"]},
                             format="json")
        self.assertEqual(Post.objects.get(pk=r.data["id"]).skill_cost_cents, 40)

    def test_a_broke_member_can_still_post(self):
        # Energy never goes negative and the post is made either way — the
        # charge is what's there, not a refusal.
        w = wallet_for(self.user); w.energy = 10; w.save(update_fields=["energy"])
        r = self.client.post(POSTZ, {"title": "Take", "skills_used": ["Beat Producer"]},
                             format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["energy_charged"], 10)
        self.assertEqual(wallet_for(self.user).energy, 0)


class TheFloorIsWhatAPromptCostsTests(TestCase):
    """Corey: "promptz/postz cost by tier" — a post costs at least what one AI prompt does on
    the member's tier (2000 / 500 / 100 ⚡), and the real numbers are used here, unpinned."""

    def setUp(self):
        self.user = User.objects.create_user(username="floor", password=PW)
        membership_for(self.user)
        p = profile_for(self.user)
        p.personas = [{"key": "producer", "name": "Beat Producer", "skills": [
            {"name": "Beat Producer", "rate_cents": 40}]}]
        p.save()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def at(self, tier):
        m = membership_for(self.user); m.tier = tier; m.save(update_fields=["tier"])

    def test_the_floor_is_the_prompt_price_on_each_tier(self):
        for tier, amount in (("free", 2000), ("premium", 500), ("statz", 100)):
            self.at(tier)
            self.assertEqual(post_energy_floor(self.user), amount)
            self.assertEqual(self.client.get(COST).data["cost"]["amount"], amount)
            self.assertEqual(self.client.get(COST).data["floor"], amount)

    def test_priced_skills_still_count_when_they_cost_more_than_the_floor(self):
        self.at("statz")
        p = profile_for(self.user)
        p.personas = [{"key": "producer", "name": "Beat Producer", "skills": [
            {"name": "Beat Producer", "rate_cents": 400}]}]
        p.save()
        self.assertEqual(self.client.get(f"{COST}?skills=Beat Producer").data["cost"]["amount"], 400)

    def test_a_cheap_skill_is_lifted_to_the_floor_not_added_to_it(self):
        self.at("statz")
        self.assertEqual(self.client.get(f"{COST}?skills=Beat Producer").data["cost"]["amount"], 100)

    def test_the_charge_takes_what_is_held_and_never_refuses(self):
        w = wallet_for(self.user); w.energy = 500; w.save(update_fields=["energy"])
        r = self.client.post(POSTZ, {"title": "Take"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["energy_charged"], 500)          # the Free floor is 2000
        self.assertEqual(wallet_for(self.user).energy, 0)

    def test_the_gifted_discount_reaches_the_floor(self):
        from unittest.mock import patch
        self.at("statz")
        with patch("apps.economy.models.badge_effects", return_value={"post_discount_pct": 25}):
            self.assertEqual(self.client.get(COST).data["cost"]["amount"], 75)   # 100 less 25%
