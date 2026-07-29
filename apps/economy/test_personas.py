from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import profile_for
from apps.economy.social import profile_max_experience

User = get_user_model()


class PersonaShapeTests(TestCase):
    """Personas are stored as dicts once the skill picker is used, and as bare
    key strings from before it existed. Both must survive every code path."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("k", "k@e.com", "pw12345678")
        self.client.force_authenticate(self.user)

    def test_string_personas_do_not_crash_the_experience_metric(self):
        """This raised AttributeError inside _profile_card, so viewing any
        member who had picked a PersonaZ answered 500."""
        p = profile_for(self.user)
        p.personas = ["producer", "designer"]
        p.save()
        self.assertIsNone(profile_max_experience(p))

    def test_a_member_with_string_personas_is_viewable(self):
        p = profile_for(self.user)
        p.personas = ["producer"]
        p.save()
        other = User.objects.create_user("o", "o@e.com", "pw12345678")
        self.client.force_authenticate(other)
        self.assertEqual(self.client.get("/api/economy/members/k/").status_code, 200)

    def test_experience_comes_from_the_earliest_skill_start_date(self):
        p = profile_for(self.user)
        p.personas = [{
            "key": "producer", "name": "Producer",
            "skills": [{"name": "Beat Making 🎚️", "start": f"{date.today().year - 12}-01-01"},
                       {"name": "Mixing 🎛️", "start": f"{date.today().year - 3}-01-01"}],
        }]
        p.save()
        self.assertEqual(profile_max_experience(p), 12)

    def test_patch_keeps_skills_and_dates_instead_of_stringifying_them(self):
        """PATCH used to str() each persona, flattening the dict to "{'key':…}"
        and destroying the start dates the experience metric runs on."""
        payload = [{"key": "developer", "name": "Developer",
                    "skills": [{"name": "Rust 🦀", "start": "2015-06-01"},
                               {"name": "Go 🐹"}]}]
        resp = self.client.patch("/api/auth/me/", {"personas": payload}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        stored = profile_for(self.user).personas
        self.assertEqual(stored[0]["key"], "developer")
        self.assertEqual(stored[0]["skills"][0], {"name": "Rust 🦀", "start": "2015-06-01"})
        self.assertEqual(stored[0]["skills"][1], {"name": "Go 🐹"})  # undated is fine

    def test_patch_still_accepts_the_old_string_form(self):
        resp = self.client.patch("/api/auth/me/", {"personas": ["mime"]}, format="json")
        self.assertEqual(resp.status_code, 200)
        stored = profile_for(self.user).personas
        self.assertEqual(stored[0]["key"], "mime")
        self.assertEqual(stored[0]["skills"], [])
