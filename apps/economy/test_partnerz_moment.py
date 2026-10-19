"""The collab (or battle) that makes two FriendZ into PartnerZ❤️ says so on
itself, and both of them are told."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.economy.collab import release_deal
from apps.economy.models import CollabDeal, Follow, Notification

User = get_user_model()


class PartnerzMomentTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user("alpha", "a@e.com", "pw-Long-enough-1")
        self.b = User.objects.create_user("beta", "b@e.com", "pw-Long-enough-1")

    def friends(self):
        Follow.objects.create(follower=self.a, following=self.b)
        Follow.objects.create(follower=self.b, following=self.a)

    def collab(self, title):
        deal = CollabDeal.objects.create(
            initiator=self.a, title=title, currency=CollabDeal.CURRENCY_SPINAZ,
            status=CollabDeal.STATUS_FUNDED, held_spinaz=100,
            participants=[{"username": "beta", "receives_cents": 100, "funded": True}])
        return release_deal(deal)

    def test_the_third_collab_between_friendz_is_marked(self):
        self.friends()
        first, second = self.collab("One"), self.collab("Two")
        third = self.collab("Three")
        self.assertEqual(first.partnered, [])
        self.assertEqual(second.partnered, [])
        self.assertEqual(sorted(third.partnered[0]), ["alpha", "beta"])
        for u in (self.a, self.b):
            n = Notification.objects.filter(user=u, kind="partnerz").get()
            self.assertIn("PartnerZ❤️", n.text)
            self.assertIn("3rd collab", n.text)

    def test_only_once(self):
        self.friends()
        for t in ("One", "Two", "Three"):
            self.collab(t)
        self.assertEqual(self.collab("Four").partnered, [])
        self.assertEqual(Notification.objects.filter(kind="partnerz").count(), 2)

    def test_three_collabs_without_being_friendz_is_not_partnerz(self):
        deals = [self.collab(t) for t in ("One", "Two", "Three")]
        self.assertEqual(deals[-1].partnered, [])
        self.assertFalse(Notification.objects.filter(kind="partnerz").exists())
