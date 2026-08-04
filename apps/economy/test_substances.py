from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import profile_for
from apps.economy.social import ACTIVE_STANCES, STANCE_LEGACY, clean_substances

User = get_user_model()


class CleanSubstancesTests(TestCase):
    def test_a_frequency_is_kept(self):
        self.assertEqual(clean_substances({"thc": "often", "caffeine": "sometimes"}),
                         {"thc": "often", "caffeine": "sometimes"})

    def test_an_unknown_stance_falls_back_rather_than_being_invented(self):
        # We know they picked it; we do not know how often. Do not guess.
        self.assertEqual(clean_substances({"thc": "daily"}), {"thc": STANCE_LEGACY})

    def test_the_legacy_list_form_is_accepted(self):
        self.assertEqual(clean_substances(["thc", "caffeine"]),
                         {"thc": STANCE_LEGACY, "caffeine": STANCE_LEGACY})

    def test_junk_becomes_empty_not_an_exception(self):
        for junk in (None, "thc", 7):
            self.assertEqual(clean_substances(junk), {})

    def test_every_stance_it_produces_reads_as_active(self):
        produced = set(clean_substances({"a": "often", "b": "sometimes", "c": "??"}).values())
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
