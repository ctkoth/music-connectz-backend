from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import DawSession, Upload

U = get_user_model()
SESSION = {"v": 1, "name": "Verse idea", "bpm": 92, "sources": {"src1": {"name": "Beat", "duration": 4}}, "tracks": []}


class DawSessionTests(TestCase):
    def setUp(self):
        self.me = U.objects.create_user("producer", password="pw12345!x")
        self.other = U.objects.create_user("stranger", password="pw12345!x")
        self.c = APIClient()
        self.c.force_authenticate(self.me)

    def up(self, user):
        return Upload.objects.create(user=user, file=SimpleUploadedFile("daw-src1.wav", b"RIFFxxxx"), name="daw-src1.wav", size_bytes=8)

    def put(self, sid="ses_1", audio=None, updated=1000, session=SESSION):
        return self.c.put(f"/api/economy/dawz/sessions/{sid}/", {"app": "arsenal", "session": session, "audio": audio or {}, "updated": updated}, format="json")

    def test_save_list_open_on_another_device(self):
        u = self.up(self.me)
        self.assertEqual(self.put(audio={"src1": u.id}).status_code, 200)
        listed = self.c.get("/api/economy/dawz/sessions/").data["sessions"]
        self.assertEqual([(r["id"], r["name"], r["bpm"]) for r in listed], [("ses_1", "Verse idea", 92)])
        d = self.c.get("/api/economy/dawz/sessions/ses_1/").data
        self.assertEqual(d["session"]["name"], "Verse idea")
        self.assertEqual(d["audio"]["src1"]["id"], u.id)
        self.assertTrue(d["audio"]["src1"]["url"])

    def test_it_is_yours_only(self):
        self.put()
        other = APIClient(); other.force_authenticate(self.other)
        self.assertEqual(other.get("/api/economy/dawz/sessions/").data["sessions"], [])
        self.assertEqual(other.get("/api/economy/dawz/sessions/ses_1/").status_code, 404)

    def test_somebody_elses_upload_is_not_attached(self):
        theirs = self.up(self.other)
        self.put(audio={"src1": theirs.id})
        self.assertEqual(DawSession.objects.get().audio, {})

    def test_an_older_write_cannot_bury_a_newer_edit(self):
        self.put(updated=2000)
        r = self.put(updated=1500)
        self.assertEqual((r.status_code, r.data["stored_updated"]), (409, 2000))
        self.assertEqual(self.put(updated=2500).status_code, 200)

    def test_a_bad_id_and_a_bad_body_are_refused(self):
        self.assertEqual(self.put(sid="a b").status_code, 400)
        self.assertEqual(self.put(session={"sources": []}).status_code, 400)

    def test_removing_it_removes_its_sound_but_not_a_shared_one(self):
        a, b = self.up(self.me), self.up(self.me)
        self.put("one", audio={"src1": a.id}); self.put("two", audio={"src1": a.id})
        self.put("three", audio={"src1": b.id})
        self.c.delete("/api/economy/dawz/sessions/three/")
        self.assertFalse(Upload.objects.filter(pk=b.id).exists())
        self.c.delete("/api/economy/dawz/sessions/one/")
        self.assertTrue(Upload.objects.filter(pk=a.id).exists())   # "two" still plays it
        self.c.delete("/api/economy/dawz/sessions/two/")
        self.assertFalse(Upload.objects.filter(pk=a.id).exists())
