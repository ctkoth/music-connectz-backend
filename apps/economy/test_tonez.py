from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.catalog import limits_for
from apps.economy.models import Membership, TonePreset, membership_for
from apps.economy.tonez import clean_chain

U = get_user_model()
VOCAL = [{"type": "filter", "on": True, "params": {"mode": 1, "freq": 90, "q": 0.7}},
         {"type": "comp", "on": True, "params": {"threshold": -20, "ratio": 3, "attack": 5, "release": 120, "knee": 6, "makeup": 4}}]


class ToneZTests(TestCase):
    def setUp(self):
        self.me = U.objects.create_user("singer", password="pw12345!x")
        self.c = APIClient()
        self.c.force_authenticate(self.me)

    def save(self, name, chain=VOCAL, **extra):
        return self.c.post("/api/economy/tonez/", {"name": name, "chain": chain, **extra}, format="json")

    def test_the_ladder_is_coreys_numbers(self):
        self.assertEqual([limits_for(t)["tone_presets"] for t in ("free", "premium", "statz")], [3, 6, None])

    def test_save_list_update_delete(self):
        r = self.save("My vocal", note="for the verses")
        self.assertEqual(r.status_code, 201)
        pid = r.data["preset"]["id"]
        self.assertEqual(r.data["count"], 1)
        self.assertEqual(r.data["limit"], 3)
        g = self.c.get("/api/economy/tonez/").data
        self.assertEqual(g["presets"][0]["name"], "My vocal")
        self.assertEqual(g["presets"][0]["chain"][1]["params"]["ratio"], 3)
        r = self.save("My vocal v2", chain=VOCAL[:1], id=pid)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(TonePreset.objects.count(), 1)
        self.assertEqual(TonePreset.objects.get().name, "My vocal v2")
        self.assertEqual(self.c.delete(f"/api/economy/tonez/{pid}/").status_code, 200)
        self.assertFalse(TonePreset.objects.exists())

    def test_free_keeps_three_and_says_what_premium_keeps(self):
        for i in range(3):
            self.assertEqual(self.save(f"Tone {i}").status_code, 201)
        r = self.save("Tone 4")
        self.assertEqual(r.status_code, 403)
        self.assertIn("3 tone presets", r.data["detail"])
        self.assertIn("Premium keeps 6", r.data["detail"])
        # an update is never refused by the ceiling
        pid = TonePreset.objects.first().id
        self.assertEqual(self.save("Renamed", id=pid).status_code, 201)

    def test_over_the_ceiling_after_a_downgrade_keeps_everything(self):
        membership_for(self.me)
        Membership.objects.filter(user=self.me).update(tier="premium")
        for i in range(5):
            self.save(f"Tone {i}")
        Membership.objects.filter(user=self.me).update(tier="free")
        g = self.c.get("/api/economy/tonez/").data
        self.assertEqual(g["count"], 5)
        self.assertTrue(g["full"])
        self.assertEqual(self.save("Another").status_code, 403)

    def test_statz_is_unlimited(self):
        membership_for(self.me)
        Membership.objects.filter(user=self.me).update(tier="statz")
        for i in range(10):
            self.assertEqual(self.save(f"Tone {i}").status_code, 201)
        self.assertIsNone(self.c.get("/api/economy/tonez/").data["limit"])

    def test_names_are_unique_per_member_and_never_empty(self):
        self.save("My vocal")
        self.assertEqual(self.save("my VOCAL").status_code, 409)
        self.assertEqual(self.save("   ").status_code, 400)
        other = U.objects.create_user("rapper", password="pw12345!x")
        c2 = APIClient(); c2.force_authenticate(other)
        self.assertEqual(c2.post("/api/economy/tonez/", {"name": "My vocal", "chain": VOCAL}, format="json").status_code, 201)

    def test_only_your_own(self):
        pid = self.save("Mine").data["preset"]["id"]
        other = U.objects.create_user("rapper", password="pw12345!x")
        c2 = APIClient(); c2.force_authenticate(other)
        self.assertEqual(c2.get("/api/economy/tonez/").data["count"], 0)
        self.assertEqual(c2.delete(f"/api/economy/tonez/{pid}/").status_code, 404)
        self.assertEqual(c2.post("/api/economy/tonez/", {"name": "x", "chain": VOCAL, "id": pid}, format="json").status_code, 404)
        self.assertEqual(APIClient().get("/api/economy/tonez/").status_code, 401)

    def test_a_chain_keeps_only_the_shape_of_real_effects(self):
        dirty = [{"type": "eq", "params": {"lowGain": "3", "lowFreq": "nan", "evil": 9, "highGain": 1e999}},
                 {"type": "<script>", "params": {}}, "junk",
                 {"type": "gain", "on": False, "params": {"db": -6}}] + [{"type": "gain", "params": {"db": 1}}] * 20
        out = clean_chain(dirty)
        self.assertEqual(out[0], {"type": "eq", "on": True, "params": {"lowGain": 3.0}})
        self.assertEqual(out[1], {"type": "gain", "on": False, "params": {"db": -6.0}})
        self.assertEqual(len(out), 8)
        self.assertEqual(self.save("Empty", chain=[{"type": "nope"}]).status_code, 400)

    def test_limits_endpoint_serves_the_number(self):
        self.assertEqual(self.c.get("/api/economy/limits/").data.get("tone_presets"), 3)
