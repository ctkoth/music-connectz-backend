from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .models import profile_for

User = get_user_model()


def mk(name):
    return User.objects.create_user(name, f"{name}@e.com", "pw-Long-enough-1")


class GenreFilterTests(TestCase):
    def setUp(self):
        self.me = mk("seeker")
        self.c = APIClient(); self.c.force_authenticate(self.me)
        a, b, n = mk("metalhead"), mk("rapper"), mk("nogenre")
        pa = profile_for(a); pa.genres = ["Metal"]; pa.save()
        pb = profile_for(b)
        pb.personas = [{"name": "Independent Artist", "skills": [{"name": "Rapping", "genres": ["Hip Hop"]}]}]
        pb.save()
        profile_for(n)

    def _names(self, q):
        r = self.c.get(f"/api/economy/members/?genres={q}")
        self.assertEqual(r.status_code, 200)
        return {m["username"] for m in r.data["members"]}

    def test_a_profile_genre_matches_case_insensitively(self):
        self.assertEqual(self._names("metal") & {"metalhead", "rapper", "nogenre"}, {"metalhead"})

    def test_a_skill_genre_matches_too(self):
        self.assertEqual(self._names("hip hop") & {"metalhead", "rapper", "nogenre"}, {"rapper"})

    def test_any_wanted_genre_passes_and_undeclared_never_does(self):
        got = self._names("metal,hip hop") & {"metalhead", "rapper", "nogenre"}
        self.assertEqual(got, {"metalhead", "rapper"})
