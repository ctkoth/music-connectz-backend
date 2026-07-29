from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

User = get_user_model()


class MemberProfileLookupTests(TestCase):
    """The online list on the CommunityBar opens any member by username, and a
    member who has never opened ProfileZ has no Profile row yet."""

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(User.objects.create_user("me", "me@e.com", "pw12345678"))

    def test_member_without_a_profile_row_still_opens(self):
        User.objects.create_user("fresh", "fresh@e.com", "pw12345678")
        resp = self.client.get("/api/economy/members/fresh/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["username"], "fresh")

    def test_lookup_is_case_insensitive_like_login(self):
        User.objects.create_user("MixedCase", "mc@e.com", "pw12345678")
        resp = self.client.get("/api/economy/members/mixedcase/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["username"], "MixedCase")

    def test_unknown_username_is_still_404(self):
        self.assertEqual(self.client.get("/api/economy/members/ghost/").status_code, 404)
