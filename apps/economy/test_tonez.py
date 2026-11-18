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
        self.assertEqual(r.data["kinds"]["tone"]["count"], 1)
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
        self.assertIn("3 track tone presets", r.data["detail"])
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
        self.assertEqual(g["kinds"]["tone"]["count"], 5)
        self.assertTrue(g["kinds"]["tone"]["full"])
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
        self.assertEqual(len(c2.get("/api/economy/tonez/").data["presets"]), 0)
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


class PresetKindTests(TestCase):
    """Corey: presets of each type get the same numbers, so FX never impede on tones."""

    def setUp(self):
        self.me = U.objects.create_user("producer", password="pw12345!x")
        self.c = APIClient(); self.c.force_authenticate(self.me)

    def save(self, kind, name, chain=VOCAL, **extra):
        return self.c.post("/api/economy/tonez/", {"kind": kind, "name": name, "chain": chain, **extra}, format="json")

    def test_each_kind_has_its_own_three(self):
        for i in range(3):
            self.assertEqual(self.save("tone", f"T{i}").status_code, 201)
        self.assertEqual(self.save("tone", "T4").status_code, 403)
        for i in range(3):
            self.assertEqual(self.save("fx", f"F{i}").status_code, 201)
        master = {"style": "warm", "intensity": "medium", "target": "streaming", "trims": {"low": 1, "mid": 0, "high": -1}, "bitDepth": 24}
        for i in range(3):
            self.assertEqual(self.save("master", f"M{i}", chain=master).status_code, 201)
        r = self.save("fx", "F4")
        self.assertEqual(r.status_code, 403)
        self.assertIn("3 track fx presets", r.data["detail"])
        k = self.c.get("/api/economy/tonez/").data["kinds"]
        self.assertEqual({n: v["count"] for n, v in k.items()}, {"tone": 3, "fx": 3, "master": 3})

    def test_the_same_name_may_live_in_two_kinds(self):
        self.assertEqual(self.save("tone", "Vocal").status_code, 201)
        self.assertEqual(self.save("fx", "Vocal").status_code, 201)
        self.assertEqual(self.save("fx", "vocal").status_code, 409)

    def test_a_master_preset_keeps_the_sound_not_the_export(self):
        r = self.save("master", "Loud", chain={"style": "warm", "intensity": "high", "bitDepth": 24, "dither": True, "junk": 1})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["preset"]["chain"], {"style": "warm", "intensity": "high"})

    def test_a_preset_cannot_change_kind_to_dodge_a_ceiling(self):
        pid = self.save("tone", "Mine").data["preset"]["id"]
        self.assertEqual(self.save("fx", "Mine", id=pid).status_code, 400)

    def test_an_unknown_kind_is_refused(self):
        self.assertEqual(self.save("hacks", "x").status_code, 400)


class EqBandTests(TestCase):
    def test_eq_bands_are_coreys_numbers(self):
        self.assertEqual([limits_for(t)["eq_bands"] for t in ("free", "premium", "statz")], [3, 6, None])

    def test_a_preset_keeps_its_eq_bands_cleaned(self):
        chain = clean_chain([{"type": "eq", "params": {}, "bands": [
            {"type": "peaking", "f": 1000, "gain": -3, "q": 1}, {"type": "evil", "f": 1}, {"type": "lowshelf", "gain": 2},
            {"type": "highshelf", "f": "nan", "gain": 1}] + [{"type": "peaking", "f": 500}] * 40}])
        bands = chain[0]["bands"]
        self.assertEqual(bands[0], {"type": "peaking", "f": 1000.0, "gain": -3.0, "q": 1.0})
        self.assertEqual(len(bands), 32)              # the engine's bound; unknown types and bands with no frequency dropped
        self.assertNotIn("bands", clean_chain([{"type": "comp", "bands": [{"type": "peaking", "f": 1}]}])[0])
