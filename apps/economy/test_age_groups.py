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


class DatingIs18PlusAndCollabsAreOpenTests(TestCase):
    """Corey's calls: VybeZ (finding someone) is 18+; collabs stay open at any age."""

    def setUp(self):
        from apps.economy.models import profile_for
        self.teen = User.objects.create_user("teenmaker", "t@e.com", "pw-Long-enough-1")
        self.adult = User.objects.create_user("adultmaker", "a@e.com", "pw-Long-enough-1")
        for u, bd in ((self.teen, "2010-03-01"), (self.adult, "1990-03-01")):
            p = profile_for(u); p.birthday = bd; p.save()

    def _as(self, u):
        c = APIClient(); c.force_authenticate(User.objects.get(pk=u.pk)); return c

    def test_vybez_refuses_a_minor_with_the_servers_sentence_and_serves_an_adult(self):
        r = self._as(self.teen).get("/api/economy/members/?vybez=1")
        self.assertEqual(r.status_code, 403)
        self.assertTrue(r.data["adult_only"])
        self.assertIn("18+", r.data["detail"])
        self.assertIn("CollabZ", r.data["detail"])                  # the door that stays open
        self.assertEqual(self._as(self.adult).get("/api/economy/members/?vybez=1").status_code, 200)

    def test_the_plain_member_search_stays_open_to_a_minor_for_picking_collaborators(self):
        r = self._as(self.teen).get("/api/economy/members/")
        self.assertEqual(r.status_code, 200)                         # age-grouped, but not refused

    def test_a_minor_and_an_adult_can_make_a_collab_together(self):
        r = self._as(self.teen).post("/api/economy/collab/", {
            "title": "Cross-age beat", "currency": "spinaz",
            "participants": [{"username": "teenmaker", "share": 50}, {"username": "adultmaker", "share": 50}],
        }, format="json")
        self.assertIn(r.status_code, (200, 201), getattr(r, "data", None))
        self.assertNotEqual(r.status_code, 403)

    def test_the_age_rule_still_closes_a_direct_channel_between_them(self):
        from apps.economy.models import may_contact
        self.assertFalse(may_contact(self.teen, self.adult))         # collab is open; a DM or call is not
