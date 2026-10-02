"""A post's earnings are split among everyone credited on it."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from .models import (CollabDeal, ItemRating, ListenProgress, Playlist, PlaylistItem, Post,
                     RoyaltyEntry, contributor_item_key, wallet_for)
from .playlistz import accrue_playlist_royalties_for_date
from .postsplit import post_shares

User = get_user_model()


def shares(post, cents):
    return {u.username: c for u, c, _ in post_shares(post, cents)}


class PostShares(TestCase):
    def setUp(self):
        self.a = User.objects.create_user(username="ann", password="pw")
        self.b = User.objects.create_user(username="ben", password="pw")
        self.c = User.objects.create_user(username="cal", password="pw")

    def _post(self, names, deal=None):
        return Post.objects.create(author=self.a, title="T", visibility="public",
                                   contributors=[{"username": n, "slot": ""} for n in names],
                                   source_deal=deal)

    def test_solo_post_pays_the_author(self):
        self.assertEqual(shares(self._post([]), 1000), {"ann": 1000})

    def test_credited_without_a_deal_is_equal_and_exact(self):
        s = shares(self._post(["ann", "ben", "cal"]), 1000)
        self.assertEqual(sum(s.values()), 1000)
        self.assertEqual(sorted(s.values()), [333, 333, 334])

    def _deal(self, worth):
        return CollabDeal.objects.create(initiator=self.a, title="D", participants=[
            {"username": u, "worth_cents": w, "receives_cents": w} for u, w in worth.items()])

    def test_from_a_deal_splits_on_agreed_worth_until_rated(self):
        deal = self._deal({"ann": 3000, "ben": 1000})
        self.assertEqual(shares(self._post(["ann", "ben"], deal), 1000), {"ann": 750, "ben": 250})

    def test_from_a_deal_splits_on_rating_once_three_outsiders_rate(self):
        deal = self._deal({"ann": 3000, "ben": 1000})
        for i in range(3):
            r = User.objects.create_user(username=f"rater{i}", password="pw")
            ItemRating.objects.create(user=r, item_id=contributor_item_key(deal.id, "ann"), score=4)
            ItemRating.objects.create(user=r, item_id=contributor_item_key(deal.id, "ben"), score=6)
        self.assertEqual(shares(self._post(["ann", "ben"], deal), 1000), {"ann": 400, "ben": 600})


class PaidOutToEveryone(TestCase):
    def setUp(self):
        self.a = User.objects.create_user(username="ann", password="pw")
        self.b = User.objects.create_user(username="ben", password="pw")
        self.buyer = User.objects.create_user(username="buy", password="pw")
        w = wallet_for(self.buyer); w.money_cents = 10000; w.save()
        self.post = Post.objects.create(author=self.a, title="Duet", visibility="public", price_cents=1000,
                                        contributors=[{"username": "ann", "slot": ""},
                                                      {"username": "ben", "slot": ""}])

    def test_a_purchase_pays_every_contributor(self):
        self.client.force_login(self.buyer)
        r = self.client.post(f"/api/economy/postz/{self.post.id}/sale/", {}, "application/json")
        self.assertEqual(r.status_code, 201)
        got_a, got_b = wallet_for(self.a).money_cents, wallet_for(self.b).money_cents
        self.assertGreater(got_b, 0)
        self.assertLessEqual(abs(got_a - got_b), 1)
        self.assertEqual(wallet_for(self.buyer).money_cents, 9000)

    def test_playlist_royalties_reach_every_contributor_but_not_their_own_plays(self):
        listener = User.objects.create_user(username="ear", password="pw")
        pl = Playlist.objects.create(owner=listener, title="Mix", visibility="public")
        PlaylistItem.objects.create(playlist=pl, kind=PlaylistItem.KIND_POST, post=self.post,
                                    position=0, title="Duet", added_by=listener)
        for i in range(4):
            u = User.objects.create_user(username=f"fan{i}", password="pw")
            ListenProgress.objects.create(user=u, item_id=f"post:{self.post.id}", seconds=30)
        ListenProgress.objects.create(user=self.b, item_id=f"post:{self.post.id}", seconds=30)
        accrue_playlist_royalties_for_date(timezone.now().date())
        users = set(RoyaltyEntry.objects.filter(kind=RoyaltyEntry.KIND_ACCRUAL).values_list("user__username", flat=True))
        self.assertEqual(users, {"ann", "ben"})
