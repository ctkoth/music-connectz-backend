"""The 2.2 paradigm on a post: a genre that means something, and the skills
that went into it.

2.2 required "Skills Used" on every example, and it is what makes a post
matchable to the people who have those skills and priceable against their
rates. Without it a post is a file with a caption.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import Post

User = get_user_model()
PW = "hunter2hunter2"


class SkillsUsedTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("k", "k@e.com", PW)
        self.client.force_authenticate(self.user)

    def post(self, **over):
        return self.client.post("/api/economy/postz/",
                                {"title": "Track", "genre": "Trap", **over}, format="json")

    def test_the_skills_survive_the_round_trip(self):
        resp = self.post(skills_used=["flstudio", "any_daw", "mixing"])
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["skills_used"], ["flstudio", "any_daw", "mixing"])
        self.assertEqual(Post.objects.get().skills_used, ["flstudio", "any_daw", "mixing"])

    def test_a_wildcard_is_a_perfectly_good_answer(self):
        # 2.2's own instruction was that "Any DAW" claims the category. Somebody
        # who knows they used a DAW but not which one is telling the truth;
        # forcing a specific pick would make them lie.
        self.assertEqual(self.post(skills_used=["any_daw"]).data["skills_used"], ["any_daw"])

    def test_a_post_with_no_skills_is_still_valid(self):
        self.assertEqual(self.post().data["skills_used"], [])

    def test_junk_entries_are_dropped_not_stored(self):
        resp = self.post(skills_used=["flstudio", {"nope": 1}, None, ["nested"]])
        self.assertEqual(resp.data["skills_used"], ["flstudio"])

    def test_the_list_is_capped(self):
        resp = self.post(skills_used=[f"s{i}" for i in range(80)])
        self.assertEqual(len(resp.data["skills_used"]), 40)

    def test_the_feed_carries_them(self):
        self.post(skills_used=["mixing"])
        self.assertEqual(self.client.get("/api/economy/postz/").data["posts"][0]["skills_used"],
                         ["mixing"])


class GenreTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(User.objects.create_user("k", "k@e.com", PW))

    def test_a_2_2_genre_is_stored_as_its_name(self):
        # The emoji is presentation and lives on the client. Storing "Trap 🏚️"
        # would mean two posts tagged from two screens don't group together —
        # the exact bug that made three genre lists diverge in the first place.
        resp = self.client.post("/api/economy/postz/",
                                {"title": "T", "genre": "Amapiano"}, format="json")
        self.assertEqual(resp.data["genre"], "Amapiano")

    def test_a_long_genre_is_truncated_not_rejected(self):
        resp = self.client.post("/api/economy/postz/",
                                {"title": "T", "genre": "x" * 90}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(len(resp.data["genre"]), 40)
