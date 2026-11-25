"""HealthZ: sleep and conditions are the member's own words, private, and never inferred."""
import datetime
import pathlib

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import HealthCondition, SleepLog

User = get_user_model()
BASE = "/api/economy/healthz/"


def member(name, age):
    """A member of the given age, and their client."""
    from .models import profile_for
    u, c = client(name)
    p = profile_for(u); today = datetime.date.today()
    p.birthday = (today.replace(year=today.year - age) - datetime.timedelta(days=2)).isoformat(); p.save()
    return u, c


def client(name):
    u = User.objects.create_user(name, f"{name}@x.test", "hunter2hunter2")
    c = APIClient(); c.force_authenticate(u)
    return u, c


class Sleep(TestCase):
    def test_an_empty_log_has_no_average_not_a_zero(self):
        _, c = client("hz_empty")
        r = c.get(BASE).data
        self.assertIsNone(r["avg_hours_7d"]); self.assertEqual(r["sleep"], [])
        self.assertIn("doesn't diagnose", r["note"])

    def test_average_is_the_mean_of_what_was_logged(self):
        _, c = client("hz_avg")
        today = timezone.localdate()
        for i, h in enumerate((6, 8)):
            c.post(BASE + "sleep/", {"night": (today - datetime.timedelta(days=i)).isoformat(), "hours": h}, format="json")
        self.assertEqual(c.get(BASE).data["avg_hours_7d"], 7.0)

    def test_logging_a_night_again_edits_it(self):
        u, c = client("hz_edit")
        n = timezone.localdate().isoformat()
        c.post(BASE + "sleep/", {"night": n, "hours": 5}, format="json")
        c.post(BASE + "sleep/", {"night": n, "hours": 7, "quality": 4}, format="json")
        self.assertEqual(SleepLog.objects.filter(user=u).count(), 1)
        self.assertEqual(SleepLog.objects.get(user=u).hours, 7)

    def test_bad_input_is_refused_with_a_reason(self):
        _, c = client("hz_bad")
        self.assertEqual(c.post(BASE + "sleep/", {"hours": 0}, format="json").status_code, 400)
        self.assertEqual(c.post(BASE + "sleep/", {"hours": 25}, format="json").status_code, 400)
        self.assertEqual(c.post(BASE + "sleep/", {"hours": 7, "quality": 9}, format="json").status_code, 400)
        future = (timezone.localdate() + datetime.timedelta(days=5)).isoformat()
        self.assertEqual(c.post(BASE + "sleep/", {"night": future, "hours": 7}, format="json").status_code, 400)


class Conditions(TestCase):
    def test_a_condition_is_the_members_own_words(self):
        _, c = client("hz_cond")
        r = c.post(BASE + "conditions/", {"name": "Asthma", "since_year": 2015, "note": "inhaler"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["conditions"][0]["name"], "Asthma")
        self.assertEqual(c.post(BASE + "conditions/", {"name": " "}, format="json").status_code, 400)
        self.assertEqual(c.post(BASE + "conditions/", {"name": "x", "since_year": 1800}, format="json").status_code, 400)


class Private(TestCase):
    def test_nobody_else_can_read_or_delete_it(self):
        a, ca = client("hz_a"); b, cb = client("hz_b")
        ca.post(BASE + "sleep/", {"hours": 7}, format="json")
        ca.post(BASE + "conditions/", {"name": "Migraine"}, format="json")
        self.assertEqual(cb.get(BASE).data["sleep"], [])
        self.assertEqual(cb.get(BASE).data["conditions"], [])
        cb.delete(BASE + f"sleep/{SleepLog.objects.get(user=a).id}/")
        cb.delete(BASE + f"conditions/{HealthCondition.objects.get(user=a).id}/")
        self.assertEqual(SleepLog.objects.filter(user=a).count(), 1)
        self.assertEqual(HealthCondition.objects.filter(user=a).count(), 1)

    def test_deleting_the_account_deletes_both(self):
        a, ca = client("hz_gone")
        ca.post(BASE + "sleep/", {"hours": 7}, format="json")
        ca.post(BASE + "conditions/", {"name": "Migraine"}, format="json")
        a.delete()
        self.assertEqual(SleepLog.objects.count(), 0); self.assertEqual(HealthCondition.objects.count(), 0)

    def test_no_other_module_reads_these_tables(self):
        # A condition or a night's sleep must never reach a rating, price, search or recommendation.
        here = pathlib.Path(__file__).parent
        for f in here.glob("*.py"):
            if f.name in ("healthz.py", "models.py", "urls.py") or f.name.startswith("test_"):
                continue
            src = f.read_text()
            self.assertNotIn("SleepLog", src, f.name)
            self.assertNotIn("HealthCondition", src, f.name)


class FindableByCondition(TestCase):
    """The one exception to private: an adult chose, per condition, to be findable by adults."""

    def names(self, c, **q):
        r = c.get("/api/economy/members/", q)
        self.assertEqual(r.status_code, 200)
        return {m["username"]: m for m in r.data["members"]}

    def setUp(self):
        self.seeker, self.cs = client("hz_seeker"); self.seeker_p = self._adult(self.seeker)
        self.opted, self.co = client("hz_opted"); self._adult(self.opted)
        self.quiet, self.cq = client("hz_quiet"); self._adult(self.quiet)
        self.co.post(BASE + "conditions/", {"name": "Asthma", "shared": True}, format="json")
        self.co.post(BASE + "conditions/", {"name": "Migraine"}, format="json")      # private
        self.cq.post(BASE + "conditions/", {"name": "Asthma"}, format="json")        # not shared

    def _adult(self, u):
        from .models import profile_for
        p = profile_for(u); today = datetime.date.today()
        p.birthday = (today.replace(year=today.year - 30) - datetime.timedelta(days=2)).isoformat(); p.save()
        return p

    def test_only_members_who_shared_that_condition_are_found(self):
        found = self.names(self.cs, condition="asthma")
        self.assertIn("hz_opted", found)
        self.assertNotIn("hz_quiet", found)      # has it, did not share it
        self.assertEqual(found["hz_opted"]["matched_conditions"], ["Asthma"])

    def test_a_private_condition_is_never_found_or_revealed(self):
        self.assertNotIn("hz_opted", self.names(self.cs, condition="migraine"))
        card = self.names(self.cs, condition="asthma")["hz_opted"]
        self.assertNotIn("Migraine", str(card))

    def test_no_filter_means_no_condition_on_any_card(self):
        for m in self.names(self.cs).values():
            self.assertNotIn("matched_conditions", m)

    def test_a_minor_cannot_share_one(self):
        _, ct = member("hz_teen", 15)
        r = ct.post(BASE + "conditions/", {"name": "Asthma", "shared": True}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertTrue(r.data["adult_only"])

    def test_a_minor_owner_stored_as_shared_is_still_never_found(self):
        u, _ = member("hz_teen2", 15)
        HealthCondition.objects.create(user=u, name="Asthma", shared=True)
        self.assertNotIn("hz_teen2", self.names(self.cs, condition="asthma"))

    def test_a_minor_searcher_reads_nothing_of_anyones(self):
        _, ct = member("hz_teen3", 15)
        found = self.names(ct, condition="asthma")
        for m in found.values():
            self.assertNotIn("matched_conditions", m)
        self.assertNotIn("hz_opted", found)

    def test_toggling_shared_off_takes_the_member_out_of_the_search(self):
        cid = HealthCondition.objects.get(user=self.opted, name="Asthma").id
        r = self.co.patch(BASE + f"conditions/{cid}/", {"shared": False}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("hz_opted", self.names(self.cs, condition="asthma"))


class Kinds(TestCase):
    def test_physical_and_mental_are_both_recordable_and_labelled(self):
        _, c = client("hz_kinds")
        c.post(BASE + "conditions/", {"name": "Asthma", "kind": "physical"}, format="json")
        r = c.post(BASE + "conditions/", {"name": "Anxiety", "kind": "mental"}, format="json")
        self.assertEqual({x["name"]: x["kind"] for x in r.data["conditions"]}, {"Asthma": "physical", "Anxiety": "mental"})
        self.assertEqual([k["key"] for k in r.data["kinds"]], ["physical", "mental", "other"])
        self.assertIn("crisis", r.data["crisis_note"])

    def test_kind_defaults_to_physical_and_junk_is_refused(self):
        _, c = client("hz_kinds2")
        self.assertEqual(c.post(BASE + "conditions/", {"name": "Eczema"}, format="json").data["conditions"][0]["kind"], "physical")
        self.assertEqual(c.post(BASE + "conditions/", {"name": "x", "kind": "bogus"}, format="json").status_code, 400)


class HideByCondition(FindableByCondition):
    """?condition_not= removes members who chose to be findable by that, from the searcher's own list."""

    def test_exclude_hides_only_those_who_shared_it(self):
        found = self.names(self.cs, condition_not="asthma")
        self.assertNotIn("hz_opted", found)       # shared Asthma: hidden from this list
        self.assertIn("hz_quiet", found)          # has it but did not share: unaffected, nothing revealed

    def test_include_and_exclude_can_combine(self):
        found = self.names(self.cs, condition="asthma", condition_not="migraine")
        self.assertIn("hz_opted", found)          # migraine is private, so it can't exclude anyone

    def test_a_minor_searcher_cannot_use_it(self):
        _, ct = member("hz_teen4", 15)
        self.assertNotIn("matched_conditions", str(self.names(ct, condition_not="asthma")))
