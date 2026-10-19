"""Attractiveness as a member-chosen filter: the standard is the searcher's, the number is the
rated member's to show or hide.

The platform imposes no approval step — the community median is already a range gate on every
member search and every gated door — but a member who switched their score off must not be
filterable by it, or the switch is decoration (a hidden number read back one band at a time).
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.gates import failing_gate, member_metrics
from apps.economy.models import AttractivenessRating, membership_for, profile_for

User = get_user_model()
PW = "hunter2hunter2"


def adult(name):
    u = User.objects.create_user(name, f"{name}@e.com", PW)
    membership_for(u)
    p = profile_for(u)
    p.birthday = "1990-01-01"
    p.save()
    return u


def rated(name, score, shown=True, raters=3):
    u = adult(name)
    for i in range(raters):
        AttractivenessRating.objects.create(rater=adult(f"{name}_r{i}"), target=u, score=score)
    if not shown:
        m = membership_for(u)
        m.attractiveness_public = False
        m.save()
    return u


class HiddenScoresAreNotFilterable(TestCase):
    def setUp(self):
        self.me = adult("searcher")
        self.hi = rated("hi", 9)
        self.hidden = rated("hidden", 9, shown=False)
        self.lo = rated("lo", 3)
        self.c = APIClient()
        self.c.force_authenticate(self.me)

    def names(self, qs):
        return {m["username"] for m in self.c.get("/api/economy/members/" + qs).json()["members"]}

    def test_a_range_finds_shown_scores_only(self):
        got = self.names("?attr_min=8")
        self.assertIn("hi", got)
        self.assertNotIn("hidden", got)
        self.assertNotIn("lo", got)

    def test_stepping_the_range_cannot_read_a_hidden_score_off(self):
        for lo in (1, 5, 9):
            self.assertNotIn("hidden", self.names(f"?attr_min={lo}"))

    def test_the_card_does_not_carry_a_hidden_score(self):
        cards = {m["username"]: m for m in self.c.get("/api/economy/members/").json()["members"]}
        self.assertIsNone(cards["hidden"]["attractiveness"])
        self.assertEqual(cards["hi"]["attractiveness"], 9)

    def test_every_gated_door_uses_the_same_rule(self):
        gates = {"attract": [8, None]}
        self.assertIsNone(failing_gate(member_metrics(profile_for(self.hi)), gates))
        self.assertEqual(failing_gate(member_metrics(profile_for(self.hidden)), gates), "attract")

    def test_a_member_with_it_switched_on_by_default_still_filters_in(self):
        self.assertTrue(membership_for(self.hi).attractiveness_public)
