"""StatZ work autosave: a screen's unsaved work, kept on the member's account (worksaves.py)."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import worksaves
from apps.economy.models import Membership, WorkSave

User = get_user_model()
BASE = "/api/economy/works/"


def statz(user):
    Membership.objects.update_or_create(user=user, defaults={"tier": "statz"})


def free(user):
    Membership.objects.update_or_create(user=user, defaults={"tier": "free"})


class WorkSaveTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_user(username="maker", password="x-test-only-1")
        self.other = User.objects.create_user(username="other", password="x-test-only-2")
        free(self.me)
        self.c = APIClient()
        self.c.force_authenticate(self.me)

    def put(self, app="animez", wid="episode", data=None, updated=1000, name="Episode 1", client=None):
        body = {"data": {"title": "T"} if data is None else data, "updated": updated, "name": name}
        return (client or self.c).put(f"{BASE}{app}/{wid}/", body, format="json")

    def test_free_members_cannot_keep_work_on_the_account(self):
        r = self.put()
        self.assertEqual(r.status_code, 403)
        self.assertIn("StatZ", r.json()["detail"])
        self.assertFalse(WorkSave.objects.exists())

    def test_statz_keeps_the_work_and_it_comes_back(self):
        statz(self.me)
        self.assertEqual(self.put(data={"title": "Night", "scenes": []}, updated=2000).status_code, 200)
        g = self.c.get(f"{BASE}animez/episode/")
        self.assertEqual(g.status_code, 200)
        self.assertEqual(g.json()["data"], {"title": "Night", "scenes": []})
        self.assertEqual(g.json()["updated"], 2000)
        listed = self.c.get(f"{BASE}?app=animez").json()["works"]
        self.assertEqual([w["wid"] for w in listed], ["episode"])

    def test_a_stale_copy_cannot_overwrite_a_newer_one(self):
        statz(self.me)
        self.put(data={"title": "Newer"}, updated=5000)
        r = self.put(data={"title": "Older device"}, updated=4000)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["stored_updated"], 5000)
        self.assertEqual(self.c.get(f"{BASE}animez/episode/").json()["data"], {"title": "Newer"})

    def test_a_newer_copy_replaces_the_older_one(self):
        statz(self.me)
        self.put(data={"title": "One"}, updated=1000)
        self.assertEqual(self.put(data={"title": "Two"}, updated=2000).status_code, 200)
        self.assertEqual(self.c.get(f"{BASE}animez/episode/").json()["data"], {"title": "Two"})

    def test_only_the_apps_that_opted_in_can_keep_work(self):
        statz(self.me)
        self.assertEqual(self.put(app="videoz").status_code, 400)
        self.assertFalse(WorkSave.objects.exists())

    def test_the_id_and_the_shape_are_checked(self):
        statz(self.me)
        self.assertEqual(self.put(wid="bad id!").status_code, 400)
        bad_data = self.c.put(f"{BASE}animez/episode/", {"data": ["not", "an", "object"], "updated": 1}, format="json")
        self.assertEqual(bad_data.status_code, 400)
        bad_stamp = self.c.put(f"{BASE}animez/episode/", {"data": {}, "updated": "soon"}, format="json")
        self.assertEqual(bad_stamp.status_code, 400)

    def test_too_large_work_is_refused(self):
        statz(self.me)
        big = {"blob": "x" * (worksaves.MAX_JSON_BYTES + 10)}
        self.assertEqual(self.put(data=big).status_code, 413)

    def test_the_name_is_cut_to_its_column(self):
        statz(self.me)
        self.put(name="n" * 500)
        self.assertEqual(len(WorkSave.objects.get().name), worksaves.NAME_MAX)

    def test_a_member_cannot_see_or_change_anothers_work(self):
        statz(self.me)
        statz(self.other)
        self.put(data={"title": "Mine"})
        oc = APIClient()
        oc.force_authenticate(self.other)
        self.assertEqual(oc.get(f"{BASE}animez/episode/").status_code, 404)
        self.assertEqual(oc.get(f"{BASE}?app=animez").json()["works"], [])
        self.put(data={"title": "Theirs"}, updated=9999, client=oc)
        self.assertEqual(self.c.get(f"{BASE}animez/episode/").json()["data"], {"title": "Mine"})

    def test_the_count_per_app_is_capped(self):
        statz(self.me)
        with mock.patch.object(worksaves, "MAX_WORKS_PER_APP", 2):
            self.assertEqual(self.put(wid="a").status_code, 200)
            self.assertEqual(self.put(wid="b").status_code, 200)
            r = self.put(wid="c")
            self.assertEqual(r.status_code, 409)
            self.assertIn("remove one", r.json()["detail"])

    def test_delete_removes_it(self):
        statz(self.me)
        self.put()
        self.assertEqual(self.c.delete(f"{BASE}animez/episode/").status_code, 204)
        self.assertEqual(self.c.get(f"{BASE}animez/episode/").status_code, 404)

    def test_a_lapsed_member_can_still_read_their_work(self):
        statz(self.me)
        self.put(data={"title": "Kept"})
        free(self.me)
        self.assertEqual(self.c.get(f"{BASE}animez/episode/").json()["data"], {"title": "Kept"})
        self.assertEqual(self.put(data={"title": "Changed"}, updated=9000).status_code, 403)
