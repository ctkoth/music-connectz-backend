"""LookZMaxZ invites and shares: nobody is rated from a photo somebody else uploads; the person in the
reading gets their own and chooses who sees it, from a server-signed snapshot, never the photo."""
from django.core import signing

from apps.economy import lookshare
from apps.economy.models import LookShare, Notification, profile_for
from apps.economy.test_lookmaxz import URL, Base, User

SHARE = URL + "share/"


def adult(u):
    p = profile_for(u)
    p.verified_18plus = True
    p.save(update_fields=["verified_18plus"])
    return u


class LookShareTests(Base):
    def setUp(self):
        super().setUp()
        self.verify()
        self.corey = adult(User.objects.create_user("corey", "c@e.com", "hunter2hunter2"))

    def reading(self):
        r = self.post()
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()["share"]["reading"]

    def test_a_reading_answers_with_a_signed_snapshot_and_no_photo(self):
        token = self.reading()
        data = signing.loads(token, salt=lookshare.SALT)
        self.assertEqual(data["u"], self.user.id)
        self.assertEqual(set(data["r"]["sectors"]), {"face", "skin", "teeth", "styling"})
        self.assertNotIn("body", data["r"]["sectors"])
        self.assertFalse({"photo", "photo_url", "image", "shop", "advice"} & set(data["r"]))
        self.assertLess(len(token), 4000)                         # numbers and words, no image bytes

    def test_sharing_with_a_named_adult_notifies_them_and_only_they_can_open_it(self):
        r = self.c.post(SHARE, {"reading": self.reading(), "to": "@Corey"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        token = r.json()["token"]
        self.assertTrue(Notification.objects.filter(user=self.corey, item_id=f"lookshare:{token}").exists())
        corey = self.client_for(self.corey)
        self.assertEqual(corey.get(f"{SHARE}{token}/").json()["username"], "m")
        stranger = self.client_for(adult(User.objects.create_user("x", "x@e.com", "hunter2hunter2")))
        self.assertEqual(stranger.get(f"{SHARE}{token}/").status_code, 404)

    def test_a_forged_or_someone_elses_reading_is_refused(self):
        forged = signing.dumps({"u": self.user.id, "r": {"overall": 10}}, salt="not-ours")
        self.assertEqual(self.c.post(SHARE, {"reading": forged}, format="json").status_code, 400)
        mine = self.reading()
        self.assertEqual(self.client_for(self.corey).post(SHARE, {"reading": mine}, format="json").status_code, 403)
        self.assertFalse(LookShare.objects.exists())

    def test_an_unverified_recipient_is_refused_and_an_unverified_viewer_sees_nothing(self):
        kid = User.objects.create_user("kid", "k@e.com", "hunter2hunter2")
        self.assertEqual(self.c.post(SHARE, {"reading": self.reading(), "to": "kid"}, format="json").status_code, 400)
        token = self.c.post(SHARE, {"reading": self.reading()}, format="json").json()["token"]
        self.assertEqual(self.client_for(kid).get(f"{SHARE}{token}/").status_code, 404)
        self.assertEqual(self.client_for(self.corey).get(f"{SHARE}{token}/").status_code, 200)

    def test_the_owner_takes_it_down_and_nobody_else_can(self):
        token = self.c.post(SHARE, {"reading": self.reading(), "to": "corey"}, format="json").json()["token"]
        self.assertEqual(self.client_for(self.corey).delete(f"{SHARE}{token}/").status_code, 404)
        self.assertEqual(self.c.delete(f"{SHARE}{token}/").status_code, 204)
        self.assertEqual(self.client_for(self.corey).get(f"{SHARE}{token}/").status_code, 404)

    def test_the_invite_is_public_and_says_only_she_can_share_it(self):
        from rest_framework.test import APIClient
        d = APIClient().get(URL + "invite/COREY/").json()
        self.assertEqual(d["link"], "/rate/corey")
        self.assertIn("Nobody can rate you from a photo they upload", d["rule"])
        self.assertIn("you choose whether @corey sees it", d["what"])

    def client_for(self, u):
        from rest_framework.test import APIClient
        c = APIClient()
        c.force_authenticate(u)
        return c
