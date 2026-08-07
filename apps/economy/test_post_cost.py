"""Posting costs the skills you put on it — and says so first.

The composer has always shown a skill picker and sent no cost with it, so every
post in this app has been free while the screen implied a price. And the cost
came from the REQUEST, which means the client's zero was the real price.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import Post, membership_for, profile_for, wallet_for

User = get_user_model()
PW = "hunter2hunter2"
POSTZ = "/api/economy/postz/"
COST = "/api/economy/postz/cost/"


class CostBase(TestCase):
    def setUp(self):
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

    def test_an_unpriced_skill_costs_nothing_and_says_so(self):
        r = self.client.get(f"{COST}?skills=Ghost Writer")
        self.assertEqual(r.data["cost"]["amount"], 0)
        self.assertIn("haven't priced", r.data["note"])

    def test_no_skills_is_free(self):
        self.assertEqual(self.client.get(COST).data["cost"]["amount"], 0)

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

    def test_a_post_with_no_skills_is_still_free(self):
        self.client.post(POSTZ, {"title": "Take"}, format="json")
        self.assertEqual(wallet_for(self.user).energy, 500)

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
