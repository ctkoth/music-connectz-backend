from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import profile_for
from apps.economy.social import ACTIVE_STANCES, STANCE_LEGACY, clean_substances
from apps.economy.substancez import FREQUENCY_KEYS, SUBSTANCE_KEYS, rank, scale, within

User = get_user_model()


class CleanSubstancesTests(TestCase):
    def test_a_frequency_is_kept(self):
        self.assertEqual(clean_substances({"thc": "often", "caffeine": "sometimes"}),
                         {"thc": "often", "caffeine": "sometimes"})

    def test_an_unknown_stance_falls_back_rather_than_being_invented(self):
        # We know they picked it; we do not know how often. Do not guess.
        self.assertEqual(clean_substances({"thc": "weekly"}), {"thc": STANCE_LEGACY})

    def test_the_legacy_list_form_is_accepted(self):
        self.assertEqual(clean_substances(["thc", "caffeine"]),
                         {"thc": STANCE_LEGACY, "caffeine": STANCE_LEGACY})

    def test_junk_becomes_empty_not_an_exception(self):
        for junk in (None, "thc", 7):
            self.assertEqual(clean_substances(junk), {})

    def test_every_stance_it_produces_reads_as_active(self):
        produced = set(clean_substances({"thc": "often", "alcohol": "sometimes", "caffeine": "??"}).values())
        self.assertTrue(produced <= ACTIVE_STANCES, produced)


class SubstanceWriteTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("k", "k@e.com", "pw12345678")
        self.client.force_authenticate(self.user)

    def _post(self, body):
        return self.client.post("/api/economy/profile/", body, format="json")

    def test_frequencies_round_trip(self):
        self._post({"substances": {"thc": "often", "caffeine": "sometimes"}})
        self.assertEqual(profile_for(self.user).substances,
                         {"thc": "often", "caffeine": "sometimes"})

    def test_a_list_from_an_older_client_is_repaired_on_write(self):
        self._post({"substances": ["thc", "alcohol"]})
        saved = profile_for(self.user).substances
        self.assertIsInstance(saved, dict)
        self.assertEqual(saved, {"thc": STANCE_LEGACY, "alcohol": STANCE_LEGACY})

    def test_sober_by_choice_clears_declared_use(self):
        # Holding both would be incoherent on a filter people rely on.
        self._post({"substances": {"thc": "often"}, "sober": True})
        p = profile_for(self.user)
        self.assertTrue(p.sober)
        self.assertEqual(p.substances, {})

    def test_dropping_sober_lets_use_be_declared_again(self):
        self._post({"sober": True})
        self._post({"sober": False, "substances": {"caffeine": "sometimes"}})
        p = profile_for(self.user)
        self.assertFalse(p.sober)
        self.assertEqual(p.substances, {"caffeine": "sometimes"})


class SubstanceSearchTests(TestCase):
    """The filter reads a member's stance. A row saved by the old client holds
    a list, and `subs.get(k)` on a list raised AttributeError — a 500 on Social
    ConnectZ for anyone who had ever saved SubstanceZ."""

    def setUp(self):
        self.client = APIClient()
        self.me = User.objects.create_user("me", "me@e.com", "pw12345678")
        self.client.force_authenticate(self.me)

    def _member(self, name, substances, sober=False):
        u = User.objects.create_user(name, f"{name}@e.com", "pw12345678")
        p = profile_for(u)
        p.substances = substances
        p.sober = sober
        p.save()
        return u

    def _search(self, **params):
        resp = self.client.get("/api/economy/members/", params)
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.data
        rows = data.get("members", data) if isinstance(data, dict) else data
        return {r["username"] for r in rows}

    def test_a_legacy_list_row_does_not_500_the_search(self):
        self._member("legacy", ["thc"])          # the shape the old UI saved
        names = self._search(substances="thc")
        self.assertNotIn("legacy", names)        # they declared it, so filtered out

    def test_someone_who_uses_it_is_filtered_out(self):
        self._member("user_often", {"thc": "often"})
        self._member("user_sometimes", {"thc": "sometimes"})
        self._member("clean", {"caffeine": "often"})
        names = self._search(substances="thc")
        self.assertNotIn("user_often", names)
        self.assertNotIn("user_sometimes", names)
        self.assertIn("clean", names)

    def test_undeclared_reads_as_sober_friendly(self):
        self._member("blank", {})
        self.assertIn("blank", self._search(substances="thc"))

    def test_sober_only_matches_the_explicit_claim(self):
        self._member("sober_by_choice", {}, sober=True)
        self._member("just_blank", {})
        names = self._search(sober="1")
        self.assertIn("sober_by_choice", names)
        self.assertNotIn("just_blank", names)


class FrequencyScaleTests(TestCase):
    def test_the_scale_runs_lowest_to_highest_and_keeps_the_two_old_names(self):
        self.assertEqual(FREQUENCY_KEYS, ["rarely", "sometimes", "often", "daily"])
        self.assertEqual([rank(k) for k in FREQUENCY_KEYS], [0, 1, 2, 3])

    def test_all_four_frequencies_are_kept_and_read_as_active(self):
        saved = clean_substances({"thc": "rarely", "alcohol": "daily"})
        self.assertEqual(saved, {"thc": "rarely", "alcohol": "daily"})
        self.assertTrue(set(saved.values()) <= ACTIVE_STANCES)

    def test_unknown_substance_keys_are_dropped_not_stored(self):
        self.assertEqual(clean_substances({"thc": "often", "mystery": "often"}), {"thc": "often"})
        self.assertEqual(clean_substances(["thc", "mystery"]), {"thc": STANCE_LEGACY})

    def test_legacy_yes_is_never_rounded_into_a_frequency(self):
        self.assertIsNone(rank(STANCE_LEGACY))
        self.assertEqual(clean_substances({"thc": STANCE_LEGACY}), {"thc": STANCE_LEGACY})

    def test_within_is_inclusive_and_honest_about_unknown(self):
        self.assertTrue(within("rarely", "sometimes"))
        self.assertTrue(within("sometimes", "sometimes"))
        self.assertFalse(within("often", "sometimes"))
        # frequency unknown: cannot be promised under a limit, passes only with no limit
        self.assertFalse(within(STANCE_LEGACY, "often"))
        self.assertTrue(within(STANCE_LEGACY, "daily"))
        self.assertFalse(within("rarely", "nonsense"))

    def test_every_frequency_carries_a_plain_language_hint(self):
        for f in scale()["frequencies"]:
            self.assertTrue(f["hint"], f)

    def test_the_served_substances_are_the_closed_list(self):
        self.assertEqual([s["key"] for s in scale()["substances"]], SUBSTANCE_KEYS)


class SubstanceScaleEndpointTests(TestCase):
    def test_serves_the_vocabulary_and_requires_auth(self):
        self.assertEqual(APIClient().get("/api/economy/substancez/").status_code, 401)
        c = APIClient()
        c.force_authenticate(User.objects.create_user("s1", "s1@e.com", "pw12345678"))
        r = c.get("/api/economy/substancez/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([f["key"] for f in r.data["frequencies"]], FREQUENCY_KEYS)
        self.assertEqual(r.data["legacy"], STANCE_LEGACY)


class FrequencyReachesTheScreensTests(TestCase):
    """Frequency that nothing reads is decoration — these are the readers."""

    def setUp(self):
        self.client = APIClient()
        self.me = User.objects.create_user("me", "me@e.com", "pw12345678")
        self.client.force_authenticate(self.me)
        self._adult(self.me)

    def _adult(self, u):
        p = profile_for(u)
        p.birthday = "1990-01-01"
        p.save()

    def _member(self, name, substances):
        u = User.objects.create_user(name, f"{name}@e.com", "pw12345678")
        p = profile_for(u)
        p.birthday = "1990-01-01"
        p.substances = substances
        p.save()
        return u

    def _names(self, **params):
        r = self.client.get("/api/economy/members/", params)
        self.assertEqual(r.status_code, 200, r.content)
        return {m["username"]: m for m in r.data["members"]}

    # search: "okay with up to"
    def test_substance_max_lets_lighter_use_through_and_still_blocks_heavier(self):
        self._member("rare", {"alcohol": "rarely"})
        self._member("some", {"alcohol": "sometimes"})
        self._member("daily", {"alcohol": "daily"})
        self._member("legacy", {"alcohol": STANCE_LEGACY})
        none = self._names(substances="alcohol")
        self.assertNotIn("rare", none)            # old meaning unchanged: any use filtered
        upto = self._names(substances="alcohol", substance_max="sometimes")
        self.assertIn("rare", upto)
        self.assertIn("some", upto)
        self.assertNotIn("daily", upto)
        self.assertNotIn("legacy", upto)          # unknown frequency can't be promised

    def test_a_bad_substance_max_is_the_same_as_none(self):
        self._member("rare", {"alcohol": "rarely"})
        self.assertNotIn("rare", self._names(substances="alcohol", substance_max="whenever"))

    # the SubstanceZ app
    def test_metricz_splits_each_substance_by_frequency_and_returns_mine(self):
        self._member("a", {"thc": "daily"})
        self._member("b", {"thc": "daily"})
        self._member("c", {"thc": "rarely"})
        self._member("d", {"thc": STANCE_LEGACY})
        p = profile_for(self.me); p.substances = {"thc": "often"}; p.save()
        self.client.force_authenticate(User.objects.get(pk=self.me.pk))  # fresh, uncached profile
        r = self.client.get("/api/economy/metricz/substancez/")
        self.assertEqual(r.status_code, 200)
        thc = next(o for o in r.data["options"] if o["key"] == "thc")
        self.assertEqual(thc["count"], 5)
        self.assertEqual(thc["by_frequency"], {"rarely": 1, "sometimes": 0, "often": 1, "daily": 2, "unsaid": 1})
        self.assertEqual(thc["my_frequency"], "often")
        self.assertEqual([f["key"] for f in r.data["frequencies"]], FREQUENCY_KEYS)

    def test_my_frequency_is_none_for_a_legacy_yes(self):
        p = profile_for(self.me); p.substances = {"thc": STANCE_LEGACY}; p.save()
        self.client.force_authenticate(User.objects.get(pk=self.me.pk))  # fresh, uncached profile
        r = self.client.get("/api/economy/metricz/substancez/")
        thc = next(o for o in r.data["options"] if o["key"] == "thc")
        self.assertTrue(thc["mine"])
        self.assertIsNone(thc["my_frequency"])

    def test_uses_with_use_freq_narrows_and_the_card_says_how_often(self):
        self._member("heavy", {"thc": "daily", "alcohol": "rarely"})
        self._member("light", {"thc": "rarely"})
        self._member("legacy", {"thc": STANCE_LEGACY})
        both = self._names(uses="thc")
        self.assertEqual(set(both) & {"heavy", "light", "legacy"}, {"heavy", "light", "legacy"})
        heavy_only = self._names(uses="thc", use_freq="often,daily")
        self.assertIn("heavy", heavy_only)
        self.assertNotIn("light", heavy_only)
        self.assertNotIn("legacy", heavy_only)    # no frequency to match
        # only the searched substance is disclosed on the card
        self.assertEqual(heavy_only["heavy"]["use_frequency"], {"thc": "daily"})

    def test_no_use_frequency_on_cards_outside_a_uses_search(self):
        self._member("x", {"thc": "daily"})
        self.assertNotIn("use_frequency", self._names()["x"])

    def test_a_minor_cannot_search_by_use_frequency(self):
        p = profile_for(self.me); p.birthday = "2015-01-01"; p.save()
        r = self.client.get("/api/economy/members/", {"uses": "thc", "use_freq": "daily"})
        self.assertNotEqual(r.status_code, 500)
        self.assertFalse(any("use_frequency" in m for m in r.data.get("members", [])))
