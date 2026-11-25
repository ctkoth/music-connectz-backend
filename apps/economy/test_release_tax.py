from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Release, membership_for, wallet_for


class ReleaseRoyaltyTaxTests(TestCase):
    def setUp(self):
        U = get_user_model()
        self.owner = U.objects.create_superuser("own", "o@x.io", "pw12345!x")
        self.artist = U.objects.create_user("art", password="pw12345!x")
        self.o = APIClient(); self.o.force_authenticate(self.owner)

    def accrue(self, tier):
        m = membership_for(self.artist); m.tier = tier; m.save()
        w = wallet_for(self.artist); w.royalties_cents = 0; w.save()
        rel = Release.objects.create(user=self.artist, title="Single")
        r = self.o.post("/api/economy/royalties/accrue/", {"amount_cents": 1000, "username": "art", "release_id": rel.id}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()["dev_tax_cents"], wallet_for(self.artist).royalties_cents

    def test_coreys_rates_on_release_royalties(self):
        self.assertEqual(self.accrue("free"), (100, 900))
        self.assertEqual(self.accrue("premium"), (60, 940))
        self.assertEqual(self.accrue("statz"), (30, 970))

    def test_royalties_with_no_release_are_untaxed_as_before(self):
        r = self.o.post("/api/economy/royalties/accrue/", {"amount_cents": 1000, "username": "art"}, format="json")
        self.assertEqual(r.json()["dev_tax_cents"], 0)

    def test_the_rate_is_stated_before_submitting(self):
        c = APIClient(); c.force_authenticate(self.artist)
        t = c.get("/api/economy/distributez/releases/").json()["royalty_tax"]
        self.assertEqual(t["rate"], 0.10)
        self.assertIn("Premium 6%", t["note"])
