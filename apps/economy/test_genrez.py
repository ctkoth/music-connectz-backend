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


class DerivedPostTests(TestCase):
    def setUp(self):
        from .models import Post
        self.Post = Post
        self.a, self.b = mk("origauth"), mk("coverer")
        self.orig = Post.objects.create(author=self.a, title="Song", visibility="public")
        self.c = APIClient(); self.c.force_authenticate(self.b)

    def _post(self, derived):
        return self.c.post("/api/economy/postz/", {"title": "My cover", "derived": derived}, format="json")

    def test_a_cover_carries_credit_to_the_original(self):
        r = self._post({"id": self.orig.id, "kind": "cover"})
        self.assertIn(r.status_code, (200, 201), r.data)
        p = self.Post.objects.get(author=self.b)
        self.assertEqual(p.derived, {"id": self.orig.id, "kind": "cover", "title": "Song", "author": "origauth"})

    def test_private_own_or_unknown_originals_are_refused(self):
        priv = self.Post.objects.create(author=self.a, title="P", visibility="private")
        mine = self.Post.objects.create(author=self.b, title="M", visibility="public")
        for d in ({"id": priv.id, "kind": "remix"}, {"id": mine.id, "kind": "remix"},
                  {"id": 99999, "kind": "remix"}, {"id": self.orig.id, "kind": "steal"}):
            self.assertEqual(self._post(d).status_code, 400, d)
