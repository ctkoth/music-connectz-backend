"""K-Oth's IntelligenceZ royalty: frozen when a piece is attached, taken only
from the attaching member's own earnings, paid in the currency they earned."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.economy.models import (Battle, BattleWager, CollabDeal, IntelligenceUse, Release,
                                 SentenceWork, Transaction, wallet_for)

User = get_user_model()
TEN_WORDS = "one two three four five six seven eight nine ten"
USES = "/api/economy/intelligence/uses/"


@override_settings(OWNER_USERNAMES=["koth"], OWNER_EMAILS=[])
class RoyaltyPayoutTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("koth", "o@e.com", "pw-Long-enough-1")
        self.a = User.objects.create_user("alpha", "a@e.com", "pw-Long-enough-1")
        self.b = User.objects.create_user("beta", "b@e.com", "pw-Long-enough-1")
        self.work = SentenceWork.objects.create(user=self.a, kind="lyrics", topic="t", text=TEN_WORDS)
        self.c = APIClient()
        self.c.force_authenticate(self.a)

    def deal(self, currency=CollabDeal.CURRENCY_MONEY):
        held = {"held_cents": 2000} if currency == CollabDeal.CURRENCY_MONEY else {"held_spinaz": 2000}
        return CollabDeal.objects.create(
            initiator=self.b, title="EP", currency=currency, status=CollabDeal.STATUS_FUNDED,
            participants=[{"username": "alpha", "receives_cents": 1000, "funded": True},
                          {"username": "beta", "receives_cents": 1000, "funded": True}], **held)

    def attach(self, kind, tid, text=TEN_WORDS):
        return self.c.post(USES, {"source": "sentence", "source_id": self.work.id,
                                  "target_kind": kind, "target_id": tid, "text": text}, format="json")

    def test_the_share_is_stated_when_attaching_and_scaled_by_what_was_kept(self):
        deal = self.deal()
        r = self.attach("collab", deal.id, "one two three four five X Y Z W V")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["royalty_pct"], 5.0)

    def test_only_a_deal_you_are_in(self):
        other = CollabDeal.objects.create(initiator=self.b, title="x", status=CollabDeal.STATUS_FUNDED,
                                          participants=[{"username": "beta", "receives_cents": 1}])
        self.assertEqual(self.attach("collab", other.id).status_code, 400)

    def test_a_collab_release_pays_koth_from_the_attaching_member_only(self):
        from apps.economy.collab import release_deal
        deal = self.deal()
        self.attach("collab", deal.id)
        release_deal(deal)
        self.assertEqual(wallet_for(self.a).money_cents, 900)
        self.assertEqual(wallet_for(self.b).money_cents, 1000)
        self.assertEqual(wallet_for(self.owner).money_cents, 100)
        self.assertTrue(Transaction.objects.filter(user=self.owner, kind=Transaction.KIND_INTELLIGENCE,
                                                   amount_cents=100).exists())
        self.assertEqual(IntelligenceUse.objects.get().paid_cents, 100)
        self.assertFalse(Transaction.objects.filter(note__startswith="CollabZ platform fee").exists())

    def test_a_spinaz_deal_pays_in_spinaz(self):
        from apps.economy.collab import release_deal
        deal = self.deal(CollabDeal.CURRENCY_SPINAZ)
        start = wallet_for(self.owner).spinaz
        self.attach("collab", deal.id)
        release_deal(deal)
        self.assertEqual(wallet_for(self.owner).spinaz - start, 100)
        self.assertEqual(IntelligenceUse.objects.get().paid_spinaz, 100)

    def test_nothing_attached_nothing_taken(self):
        from apps.economy.collab import release_deal
        release_deal(self.deal())
        self.assertEqual(wallet_for(self.a).money_cents, 1000)
        self.assertEqual(wallet_for(self.owner).money_cents, 0)

    def test_the_owner_using_his_own_piece_pays_himself_nothing(self):
        from apps.economy.intelligence_royalty import cut_of
        mine = SentenceWork.objects.create(user=self.owner, kind="post", topic="t", text=TEN_WORDS)
        IntelligenceUse.objects.create(user=self.owner, source_kind="sentence", source_id=mine.id,
                                       target_kind="collab", target_id=1, royalty_pct=10)
        self.assertEqual(cut_of(self.owner, "collab", 1, 1000), (0, 0))

    def test_a_battle_win_pays_koth_in_spinaz_from_the_winner_only(self):
        from apps.economy import battlez
        battle = Battle.objects.create(host=self.a, opponent=self.b, title="16 bars", status=Battle.STATUS_OPEN)
        self.attach("battle", battle.id)
        BattleWager.objects.create(battle=battle, user=self.a, side=BattleWager.SIDE_HOST, amount=100)
        BattleWager.objects.create(battle=battle, user=self.b, side=BattleWager.SIDE_OPPONENT, amount=100)
        board = {"host": {"qualified": True, "median": 9}, "opponent": {"qualified": True, "median": 5}}
        before_a, before_o = wallet_for(self.a).spinaz, wallet_for(self.owner).spinaz
        with patch.object(battlez, "scoreboard", return_value=board):
            battlez.settle_battle(battle)
        self.assertEqual(wallet_for(self.a).spinaz - before_a, 180)
        self.assertEqual(wallet_for(self.owner).spinaz - before_o, 20)

    def test_a_release_credit_keeps_koths_share(self):
        release = Release.objects.create(user=self.a, title="Single")
        self.attach("release", release.id)
        o = APIClient(); o.force_authenticate(self.owner)
        r = o.post("/api/economy/royalties/accrue/", {"amount_cents": 1000, "username": "alpha",
                                                      "release_id": release.id}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(wallet_for(self.a).royalties_cents, 900)
        self.assertEqual(wallet_for(self.owner).royalties_cents, 100)

    def test_detaching_after_payout_is_refused(self):
        from apps.economy.collab import release_deal
        deal = self.deal()
        use_id = self.attach("collab", deal.id).json()["id"]
        release_deal(deal)
        self.assertEqual(self.c.delete(f"{USES}{use_id}/").status_code, 409)

    def test_detaching_before_payout_is_allowed(self):
        use_id = self.attach("collab", self.deal().id).json()["id"]
        self.assertEqual(self.c.delete(f"{USES}{use_id}/").status_code, 204)

    def test_targets_lists_open_deals_battles_and_releases(self):
        self.deal()
        Battle.objects.create(host=self.a, title="b", status=Battle.STATUS_OPEN)
        Release.objects.create(user=self.a, title="r")
        kinds = {t["kind"] for t in self.c.get("/api/economy/intelligence/targets/").json()["targets"]}
        self.assertEqual(kinds, {"collab", "battle", "release"})
