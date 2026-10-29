"""A reading of somebody else's photo happens only when they approve it; the photo is deleted whatever
they decide; the requester pays only for a reading that came back; and only the person in a reading
can post it."""
import json
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.economy import lookmaxz as lm
from apps.economy.models import Block, LookRequest, LookShare, Notification, Post
from apps.economy.test_lookmaxz import URL, Base, User, reply
from apps.economy.test_lookshare import adult

ASK = URL + "ask/"


def model(parsed):
    class R:
        status_code = 200

        def json(self_):
            return {"candidates": [{"content": {"parts": [{"text": json.dumps(parsed)}]}}]}
    return R()


def pic():
    return SimpleUploadedFile("her.jpg", b"\xff\xd8" + b"0" * 800, content_type="image/jpeg")


def client(u):
    c = APIClient()
    c.force_authenticate(u)
    return c


class LookAskTests(Base):
    def setUp(self):
        super().setUp()
        self.verify()
        self.her = adult(User.objects.create_user("her", "h@e.com", "hunter2hunter2"))
        self.she = client(self.her)

    def ask(self, to="her"):
        return self.c.post(ASK, {"to": to, "photo": pic()}, format="multipart")

    def answer(self, pk, parsed=None, **body):
        with patch.object(lm, "generate_content", return_value=(model(parsed or reply()), ["m"])) as g, \
                patch.object(lm, "_key", return_value="k"), \
                patch("apps.economy.lookask.charge_ai_usage") as charge:
            r = self.she.post(f"{ASK}{pk}/", body, format="json")
        return r, g, charge

    def test_nothing_is_read_until_she_approves_and_then_both_see_it(self):
        r = self.ask()
        self.assertEqual(r.status_code, 201, r.content)
        pk = r.json()["id"]
        self.assertTrue(Notification.objects.filter(user=self.her, item_id=f"lookask:{pk}").exists())
        self.assertTrue(self.she.get(f"{ASK}{pk}/").json()["data_url"].startswith("data:image/jpeg;base64,"))
        r, g, charge = self.answer(pk, decision="approve")
        self.assertEqual(r.status_code, 400)                       # "it's me" not confirmed
        g.assert_not_called()
        r, g, charge = self.answer(pk, decision="approve", confirm_self=True)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(charge.call_args.args[0], self.user)      # the requester pays
        req = LookRequest.objects.get(pk=pk)
        self.assertEqual(req.status, "approved")
        self.assertFalse(req.photo)                                # the photo is gone
        share = LookShare.objects.get()
        self.assertEqual((share.user, share.to_user), (self.her, self.user))
        self.assertEqual(self.c.get(f"{URL}share/{share.token}/").status_code, 200)

    def test_a_decline_deletes_the_photo_charges_nothing_and_says_no_more(self):
        pk = self.ask().json()["id"]
        r, g, charge = self.answer(pk, decision="decline")
        self.assertEqual(r.json()["status"], "declined")
        g.assert_not_called(); charge.assert_not_called()
        self.assertFalse(LookRequest.objects.get(pk=pk).photo)
        self.assertEqual(self.c.get(f"{ASK}{pk}/").status_code, 404)
        self.assertNotIn("note", self.c.get(ASK).json()["sent"][0])

    def test_an_unreadable_photo_is_not_charged(self):
        pk = self.ask().json()["id"]
        r, _g, charge = self.answer(pk, parsed={"unreadable": "No face visible."}, decision="approve", confirm_self=True)
        self.assertEqual(r.json()["status"], "failed")
        charge.assert_not_called()
        self.assertFalse(LookShare.objects.exists())

    def test_only_she_answers_and_only_the_requester_cancels(self):
        pk = self.ask().json()["id"]
        self.assertEqual(self.c.post(f"{ASK}{pk}/", {"decision": "approve", "confirm_self": True},
                                     format="json").status_code, 404)
        self.assertEqual(self.she.delete(f"{ASK}{pk}/").status_code, 404)
        stranger = client(adult(User.objects.create_user("x", "x@e.com", "hunter2hunter2")))
        self.assertEqual(stranger.get(f"{ASK}{pk}/").status_code, 404)
        self.assertEqual(self.c.delete(f"{ASK}{pk}/").status_code, 204)
        self.assertEqual(LookRequest.objects.get(pk=pk).status, "cancelled")

    def test_refusals_before_any_photo_is_kept(self):
        kid = User.objects.create_user("kid", "k@e.com", "hunter2hunter2")
        self.assertEqual(self.ask("kid").status_code, 400)
        self.assertEqual(self.ask("m").status_code, 400)            # yourself
        Block.objects.create(blocker=self.her, blocked=self.user)
        self.assertEqual(self.ask().status_code, 403)
        self.assertFalse(LookRequest.objects.exists())
        del kid

    def test_one_waiting_request_per_person(self):
        self.assertEqual(self.ask().status_code, 201)
        self.assertEqual(self.ask().status_code, 400)

    def test_only_the_person_in_the_reading_can_post_it_and_the_post_is_built_by_the_server(self):
        pk = self.ask().json()["id"]
        self.answer(pk, decision="approve", confirm_self=True)
        token = LookShare.objects.get().token
        self.assertEqual(self.c.post(f"{URL}share/{token}/post/", {}, format="json").status_code, 404)
        r = self.she.post(f"{URL}share/{token}/post/", {"visibility": "private", "description": "10/10!!"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        post = Post.objects.get(pk=r.json()["post_id"])
        self.assertEqual((post.author, post.visibility), (self.her, "private"))
        self.assertIn("Overall", post.description)
        self.assertNotIn("10/10!!", post.description)


class ShowThePhotoTests(LookAskTests):
    def test_approving_with_show_the_photo_keeps_it_as_her_upload(self):
        from apps.economy.models import Upload
        pk = self.ask().json()["id"]
        r, _g, _c = self.answer(pk, decision="approve", confirm_self=True, show_photo=True)
        self.assertEqual(r.status_code, 200, r.content)
        up = Upload.objects.get()
        self.assertEqual(up.user, self.her)
        self.assertIn(f"/media/{up.id}/", self.c.get(f"{URL}share/{r.json()['share']['token']}/").json()["photo_url"])
        self.assertFalse(LookRequest.objects.get(pk=pk).photo)    # the request's own copy is still gone

    def test_without_the_tick_nothing_is_kept(self):
        from apps.economy.models import Upload
        pk = self.ask().json()["id"]
        self.answer(pk, decision="approve", confirm_self=True)
        self.assertFalse(Upload.objects.exists())
