from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import may_contact, profile_for

User = get_user_model()


def member(name, age=None):
    u = User.objects.create_user(name, f"{name}@e.com", "pw-Long-enough-1")
    if age is not None:
        p = profile_for(u)
        today = date.today()
        p.birthday = f"{today.year - age}-{today.month:02d}-{min(today.day, 28):02d}"
        p.save()
    return u


class AgeGroupContactTests(TestCase):
    """No adult-to-minor contact: not in a message, not in a call, not in a search."""

    def setUp(self):
        self.teen, self.teen2 = member("teena", 15), member("teenb", 16)
        self.adult, self.unknown = member("adulta", 30), member("nobday")

    def test_the_rule_is_symmetric_and_unknown_ages_count_as_adults(self):
        self.assertTrue(may_contact(self.teen, self.teen2))
        self.assertTrue(may_contact(self.adult, self.unknown))
        self.assertFalse(may_contact(self.adult, self.teen))
        self.assertFalse(may_contact(self.teen, self.adult))
        self.assertFalse(may_contact(self.unknown, self.teen))

    def _dm(self, frm, to):
        c = APIClient()
        c.force_authenticate(frm)
        return c.post("/api/economy/messages/", {"to": to.username, "body": "hi"}, format="json")

    def test_an_adult_cannot_message_a_minor_nor_the_reverse_but_peers_can(self):
        self.assertEqual(self._dm(self.adult, self.teen).status_code, 403)
        r = self._dm(self.teen, self.adult)
        self.assertEqual(r.status_code, 403)
        self.assertTrue(r.json()["age_group"])
        self.assertEqual(self._dm(self.teen, self.teen2).status_code, 201)
        self.assertEqual(self._dm(self.adult, self.unknown).status_code, 201)

    def test_a_call_quote_or_ring_to_another_age_group_is_refused_before_anything_rings(self):
        c = APIClient()
        c.force_authenticate(self.adult)
        quote = c.get(f"/api/economy/callz/rate/{self.teen.username}/")
        self.assertEqual(quote.status_code, 403)
        self.assertTrue(quote.json()["age_group"])
        ring = c.post("/api/economy/callz/", {"username": self.teen.username}, format="json")
        self.assertEqual(ring.status_code, 403)
        c.force_authenticate(self.teen)
        self.assertEqual(c.get(f"/api/economy/callz/rate/{self.adult.username}/").status_code, 403)

    def test_member_search_never_mixes_the_groups(self):
        def names(viewer):
            c = APIClient()
            c.force_authenticate(viewer)
            d = c.get("/api/economy/members/").json()
            rows = d.get("members", d) if isinstance(d, dict) else d
            return {r.get("username") for r in rows}
        self.assertNotIn("teena", names(self.adult))
        self.assertNotIn("teenb", names(self.unknown))
        self.assertIn("adulta", names(self.unknown))
        self.assertEqual(names(self.teen) & {"adulta", "nobday"}, set())        # a teen sees no adults
        self.assertIn("teenb", names(self.teen))                                  # …and does see teens
