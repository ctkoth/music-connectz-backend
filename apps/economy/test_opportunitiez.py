"""OpportunitieZ pages over ACTIVE seeking notes, so a page holds what it says."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import Membership, profile_for

User = get_user_model()
URL = "/api/economy/opportunitiez/"


def seeker(name, **seeking):
    u = User.objects.create_user(username=name, password="hunter2hunter2")
    p = profile_for(u)
    p.seeking = seeking
    p.save(update_fields=["seeking"])
    return u


class PagingTests(TestCase):
    def setUp(self):
        self.c = APIClient()
        self.c.force_authenticate(User.objects.create_user(username="viewer", password="hunter2hunter2"))

    def test_inactive_notes_never_eat_a_page(self):
        seeker("a1", active=True, help_needed="a mix engineer")
        seeker("a2", active=True, help_needed="a feature on a drill track")
        for i in range(60):                       # newer, and none of them active
            seeker(f"off{i}", active=False, help_needed="old note")
        seeker("blank", active=True, help_needed="")
        d = self.c.get(URL + "?limit=50").data
        self.assertEqual({r["username"] for r in d["results"]}, {"a1", "a2"})
        self.assertEqual(d["total"], 2)

    def test_pages_follow_on_and_the_total_matches(self):
        for i in range(7):
            seeker(f"s{i}", active=True, help_needed=f"need {i}")
        first = self.c.get(URL + "?limit=5").data
        rest = self.c.get(URL + "?limit=5&offset=5").data
        names = [r["username"] for r in first["results"] + rest["results"]]
        self.assertEqual(len(names), 7)
        self.assertEqual(len(set(names)), 7)
        self.assertEqual(first["total"], 7)

    def test_junk_paging_is_the_default_not_a_500(self):
        seeker("x", active=True, help_needed="anything")
        r = self.c.get(URL + "?limit=lots&offset=-3")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["results"]), 1)

    def test_a_member_with_no_membership_row_is_listed_as_free(self):
        u = seeker("nomem", active=True, help_needed="a producer")
        Membership.objects.filter(user=u).delete()
        row = next(r for r in self.c.get(URL).data["results"] if r["username"] == "nomem")
        self.assertEqual(row["tier"], "free")
