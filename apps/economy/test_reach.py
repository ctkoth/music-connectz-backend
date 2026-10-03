"""Who can reach me: range gates on messages and calls sent TO a member."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Follow, profile_for

User = get_user_model()


class ReachGates(TestCase):
    def setUp(self):
        self.me = User.objects.create_user(username="quiet", password="pw")
        self.adult = User.objects.create_user(username="grown", password="pw")
        self.stranger = User.objects.create_user(username="noage", password="pw")
        p = profile_for(self.adult); p.birthday = "1990-01-01"; p.save()

    def dm(self, who):
        self.client.force_login(who)
        return self.client.post("/api/economy/messages/", {"to": "quiet", "body": "hi"}, "application/json")

    def set_gates(self, gates):
        self.client.force_login(self.me)
        return self.client.post("/api/economy/reach/", {"gates": gates}, "application/json")

    def test_open_by_default(self):
        self.assertEqual(self.dm(self.stranger).status_code, 201 if self.dm(self.adult).status_code == 201 else 200)

    def test_gates_block_strangers_outside_them_and_say_why(self):
        self.assertEqual(self.set_gates({"age": [18, None]}).json()["gates"], {"age": [18.0, None]})
        r = self.dm(self.stranger)
        self.assertEqual(r.status_code, 403)
        self.assertIn("age at least 18", r.json()["detail"])
        self.assertIn(self.dm(self.adult).status_code, (200, 201))

    def test_calls_are_gated_too(self):
        self.set_gates({"age": [18, None]})
        self.client.force_login(self.stranger)
        r = self.client.post("/api/economy/callz/", {"username": "quiet"}, "application/json")
        self.assertEqual(r.status_code, 403)
        self.assertTrue(r.json().get("reach"))

    def test_people_i_follow_always_get_through(self):
        self.set_gates({"age": [18, None]})
        Follow.objects.create(follower=self.me, following=self.stranger)
        self.assertIn(self.dm(self.stranger).status_code, (200, 201))

    def test_the_card_says_so_before_pressing(self):
        self.set_gates({"age": [18, None]})
        self.client.force_login(self.stranger)
        r = self.client.get("/api/economy/members/quiet/")
        self.assertIn("age at least 18", r.json()["reach_block"])
        self.client.force_login(self.adult)
        self.assertIsNone(self.client.get("/api/economy/members/quiet/").json()["reach_block"])
