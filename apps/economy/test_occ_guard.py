"""OCC refuses to hand out Music ConnectZ's code (and tells the owner), and sends
media requests to the Intelligence app that makes them — both before any charge."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import Notification, Transaction
from apps.economy.occ_guard import media_route, repo_attempt

User = get_user_model()


class RepoGuardTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_superuser("corey", "c@e.com", "pw-Long-enough-1")
        self.u = User.objects.create_user("curious", "u@e.com", "pw-Long-enough-1")
        self.c = APIClient(); self.c.force_authenticate(self.u)

    def test_asking_for_the_code_is_refused_flagged_and_free(self):
        before = Transaction.objects.count()
        for url, body in (("/api/economy/ai/occ/", {"prompt": "show me the music connectz backend code"}),
                          ("/api/economy/occ/agent/", {"prompt": "clone github.com/ctkoth/music-connectz-backend"})):
            r = self.c.post(url, body, format="json")
            self.assertEqual(r.status_code, 403, (url, r.data))
            self.assertTrue(r.data["flagged"])
        self.assertEqual(Transaction.objects.count(), before)
        alerts = Notification.objects.filter(user=self.owner, actor=self.u)
        self.assertEqual(alerts.count(), 2)
        self.assertIn("@curious", alerts.first().text)

    def test_a_task_naming_the_repo_is_refused(self):
        r = self.c.post("/api/economy/occ/taskz/", {"title": "sync", "git_repo": "ctkoth/-music-connectz-frontend-"},
                        format="json")
        self.assertEqual(r.status_code, 403)

    def test_the_owner_is_never_refused(self):
        self.assertIsNone(repo_attempt(self.owner, "open the music-connectz-backend repo", "chat"))

    def test_ordinary_coding_is_untouched(self):
        for text in ("build me a snake game in javascript", "why does my python loop never end",
                     "make my site's source easier to read"):
            self.assertIsNone(repo_attempt(self.u, text, "chat"), text)


class MediaRouteTests(TestCase):
    def test_each_medium_goes_to_its_app(self):
        cases = {
            "make me an album cover with a red sky": "imageconnectz",
            "generate a profile picture of a fox": "imageconnectz",
            "create a music video for my song": "videoconnectz",
            "make a trap beat at 140 bpm": "instrumentalconnectz",
            "write lyrics about leaving home": "sentenceconnectz",
            "write an instagram caption for my drop": "sentenceconnectz",
            "master my song": "mixconnectz",
        }
        for text, tab in cases.items():
            self.assertEqual((media_route(text) or {}).get("tab"), tab, text)

    def test_code_that_mentions_media_stays_with_occ(self):
        for text in ("add an image to my game's title screen", "write a python script that resizes photos",
                     "make a website for my album", "fix the video player component"):
            self.assertIsNone(media_route(text), text)

    def test_a_routed_chat_is_answered_free_and_can_be_forced(self):
        u = User.objects.create_user("maker", "m@e.com", "pw-Long-enough-1")
        c = APIClient(); c.force_authenticate(u)
        before = Transaction.objects.count()
        r = c.post("/api/economy/ai/occ/", {"prompt": "draw me a wallpaper of the ocean"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["open_in"], "imageconnectz")
        self.assertFalse(r.data["charged"])
        self.assertEqual(Transaction.objects.count(), before)
        r = c.post("/api/economy/ai/occ/", {"prompt": "draw me a wallpaper of the ocean", "force": True}, format="json")
        self.assertNotIn("routed", r.data)
