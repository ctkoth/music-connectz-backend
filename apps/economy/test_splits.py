"""Splitting money between the people who earned it.

Three fixes in here, and the first is the one that costs real money:

1. RoyaltyAccrueView was open to any authenticated member with a docstring
   reading "open for testing". Anyone could credit themselves any amount and
   cash it out.
2. CollabMember.split_percent was validated and then ignored — a room could
   agree 60/40, watch it validate, and get paid off a different list.
3. Three separate split implementations would eventually disagree about the
   rounding remainder, and whoever loses it never finds out.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from .splits import by_weight, describe
from .models import RoyaltyEntry, wallet_for

User = get_user_model()


def member(name, staff=False):
    return User.objects.create_user(username=name, password="splits-pass-1",
                                    is_staff=staff)


class ByWeightTests(TestCase):
    def setUp(self):
        self.a, self.b, self.c = member("a"), member("b"), member("c")

    def test_an_even_split_is_even(self):
        shares = by_weight(1000, {self.a: 1, self.b: 1}, fallback=self.a)
        self.assertEqual(shares[self.a], 500)
        self.assertEqual(shares[self.b], 500)

    def test_it_divides_by_weight_not_by_head(self):
        shares = by_weight(1000, {self.a: 3, self.b: 1}, fallback=self.a)
        self.assertEqual(shares[self.a], 750)
        self.assertEqual(shares[self.b], 250)

    def test_nothing_evaporates(self):
        """Cents lost to integer division are cents somebody earned."""
        for pot in (1000, 999, 101, 7, 3):
            with self.subTest(pot=pot):
                shares = by_weight(pot, {self.a: 1, self.b: 1, self.c: 1},
                                   fallback=self.a)
                self.assertEqual(sum(shares.values()), pot)

    def test_the_remainder_goes_to_the_named_fallback(self):
        shares = by_weight(100, {self.a: 1, self.b: 1, self.c: 1},
                           fallback=self.c)
        self.assertEqual(sum(shares.values()), 100)
        self.assertEqual(shares[self.c], 34)

    def test_all_zero_weights_pay_the_fallback_not_nobody(self):
        """Everyone on 0% is a collab still being negotiated, not one where
        the money disappears."""
        shares = by_weight(1000, {self.a: 0, self.b: 0}, fallback=self.a)
        self.assertEqual(shares, {self.a: 1000})

    def test_negative_weights_are_ignored_rather_than_inverting_the_split(self):
        shares = by_weight(1000, {self.a: 5, self.b: -5}, fallback=self.a)
        self.assertEqual(shares[self.a], 1000)
        self.assertNotIn(self.b, shares)

    def test_an_empty_pot_pays_nobody(self):
        self.assertEqual(by_weight(0, {self.a: 1}, fallback=self.a), {})

    def test_describe_shows_the_arithmetic(self):
        shares = by_weight(1000, {self.a: 3, self.b: 1}, fallback=self.a)
        out = describe(shares, 1000)
        self.assertTrue(out["balanced"])
        self.assertEqual(out["shares"][0]["percent"], 75.0)


class RoyaltyFaucetIsClosedTests(TestCase):
    """Any member could credit themselves any amount and cash it out."""

    def setUp(self):
        self.u = member("ordinary")
        self.client = APIClient()
        self.client.force_authenticate(self.u)

    def test_an_ordinary_member_cannot_mint_royalties(self):
        r = self.client.post(reverse("economy-royalties-accrue"),
                             {"amount_cents": 1_000_000}, format="json")
        self.assertIn(r.status_code, (401, 403))
        self.assertEqual(wallet_for(self.u).royalties_cents, 0)
        self.assertEqual(RoyaltyEntry.objects.count(), 0)

    def test_staff_can_still_make_an_adjustment(self):
        """Support genuinely needs this sometimes — it just isn't public."""
        staff = member("support", staff=True)
        c = APIClient()
        c.force_authenticate(staff)
        r = c.post(reverse("economy-royalties-accrue"),
                   {"amount_cents": 500, "username": "ordinary"},
                   format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(wallet_for(self.u).royalties_cents, 500)

    def test_the_adjustment_records_who_made_it(self):
        staff = member("support2", staff=True)
        c = APIClient()
        c.force_authenticate(staff)
        c.post(reverse("economy-royalties-accrue"),
               {"amount_cents": 500, "username": "ordinary"}, format="json")
        entry = RoyaltyEntry.objects.get()
        self.assertIn("support2", entry.source)

    def test_the_internal_helper_is_what_earnings_use(self):
        from .views import accrue_royalty

        accrue_royalty(self.u, 250, source="MangaZ sale")
        self.assertEqual(wallet_for(self.u).royalties_cents, 250)

    def test_the_helper_refuses_nonsense_amounts(self):
        from .views import accrue_royalty

        self.assertEqual(accrue_royalty(self.u, 0), 0)
        self.assertEqual(accrue_royalty(self.u, -100), 0)
        self.assertEqual(wallet_for(self.u).royalties_cents, 0)


class CollabSplitsActuallyPayTests(TestCase):
    """`split_percent` was validated and then ignored.

    A room could agree 60/40, watch split_error() confirm it added to 100, and
    get paid off a completely separate escrow list. A number members agreed on
    that the payout ignores is worse than no number at all.
    """

    def setUp(self):
        from apps.collabz.models import CollabMember, CollabProject
        from .models import CollabDeal

        self.owner = member("deal_owner")
        self.helper = member("deal_helper")
        self.deal = CollabDeal.objects.create(
            initiator=self.owner, title="Track", currency="money",
            held_cents=10_000, status=CollabDeal.STATUS_FUNDED,
            participants=[{"username": "deal_owner", "receives_cents": 10_000,
                           "stake_paid": 0}])
        self.project = CollabProject.objects.create(
            owner=self.owner, title="Track", kind="original",
            skills=["Mixing"], deal=self.deal)
        CollabMember.objects.create(project=self.project, user=self.owner,
                                    role="owner", split_percent=60)
        CollabMember.objects.create(project=self.project, user=self.helper,
                                    split_percent=40)

    def test_the_agreed_percentages_are_what_gets_paid(self):
        from .collab import release_deal

        release_deal(self.deal)
        self.assertEqual(wallet_for(self.owner).money_cents, 6000)
        self.assertEqual(wallet_for(self.helper).money_cents, 4000)

    def test_the_collaborator_is_paid_at_all(self):
        """Before this, the helper got nothing — the escrow list named only
        the initiator."""
        from .collab import release_deal

        release_deal(self.deal)
        self.assertGreater(wallet_for(self.helper).money_cents, 0)

    def test_nothing_evaporates_on_an_awkward_pot(self):
        from apps.collabz.models import CollabMember
        from .collab import release_deal
        from .models import CollabDeal

        third = member("deal_third")
        CollabMember.objects.create(project=self.project, user=third,
                                    split_percent=1)
        self.deal.held_cents = 1001
        self.deal.save(update_fields=["held_cents"])
        release_deal(self.deal)
        total = sum(wallet_for(u).money_cents
                    for u in (self.owner, self.helper, third))
        self.assertEqual(total, 1001)

    def test_a_deal_with_no_project_still_uses_the_escrow_list(self):
        """Not every deal has a CollabZ project attached — the old path has to
        keep working."""
        from .collab import release_deal
        from .models import CollabDeal

        solo = member("solo")
        deal = CollabDeal.objects.create(
            initiator=solo, title="Solo", currency="money",
            held_cents=5000, status=CollabDeal.STATUS_FUNDED,
            participants=[{"username": "solo", "receives_cents": 5000,
                           "stake_paid": 0}])
        release_deal(deal)
        self.assertEqual(wallet_for(solo).money_cents, 5000)

    def test_all_zero_percentages_fall_back_to_the_escrow_list(self):
        """Everyone still on 0% means the split is unsettled, which is exactly
        when the negotiated escrow figures are the right answer."""
        from apps.collabz.models import CollabMember
        from .collab import release_deal
        from .models import CollabDeal

        CollabMember.objects.filter(project=self.project).update(split_percent=0)
        release_deal(self.deal)
        self.assertEqual(wallet_for(self.owner).money_cents, 10_000)
        self.assertEqual(wallet_for(self.helper).money_cents, 0)
