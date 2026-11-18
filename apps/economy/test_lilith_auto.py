from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import lilith_auto
from apps.economy.lilith_suggest import suggest
from apps.economy.models import LilithAuto, Membership, membership_for, profile_for
from apps.economy.lilith_taskz import LilithTask

U = get_user_model()
BOARD = "/api/economy/lilith/"


def designer(user):
    p = profile_for(user)
    p.personas = [{"name": "Designer", "emoji": "🎨", "skills": []}]
    p.save()


class LilithAutoTests(TestCase):
    def setUp(self):
        self.me = U.objects.create_user("drawer", password="pw12345!x")
        designer(self.me)
        self.c = APIClient(); self.c.force_authenticate(self.me)

    def tier(self, t):
        membership_for(self.me)
        Membership.objects.filter(user=self.me).update(tier=t)

    def test_a_designer_is_suggested_imagez_mangaz_and_image_connectz_tasks(self):
        keys = [s["key"] for s in suggest(self.me) if s["kind"] == "task"]
        for k in ("make_image", "edit_picture", "manga_page"):
            self.assertIn(k, keys)
        why = [s["why"] for s in suggest(self.me) if s["key"] == "make_image"][0]
        self.assertIn("Designer", why)

    def test_free_gets_suggestions_but_nothing_added(self):
        d = self.c.get(BOARD).data
        self.assertFalse(d["auto"]["allowed"])
        self.assertEqual(d["auto"]["added"], [])
        self.assertFalse(LilithTask.objects.filter(user=self.me, source="auto").exists())
        self.assertEqual(self.c.post("/api/economy/lilith/auto/", {"on": True}, format="json").status_code, 403)

    def test_statz_gets_up_to_three_a_day_each_with_its_reason(self):
        self.tier("statz")
        d = self.c.get(BOARD).data
        added = d["auto"]["added"]
        self.assertEqual(len(added), lilith_auto.PER_DAY)
        rows = LilithTask.objects.filter(user=self.me, source="auto")
        self.assertEqual(rows.count(), 3)
        for t in rows:
            self.assertTrue(t.note.startswith(lilith_auto.NOTE_PREFIX))
            self.assertTrue(t.action)                      # verified: Lilith ticks it herself
        self.assertEqual(self.c.get(BOARD).data["auto"]["added"], [])   # not more the same day

    def test_a_deleted_one_never_comes_back(self):
        self.tier("statz")
        self.c.get(BOARD)
        t = LilithTask.objects.filter(user=self.me, source="auto").first()
        key = t.template
        t.bucket = "trash"; t.save()
        LilithTask.objects.filter(user=self.me, source="auto").exclude(pk=t.pk).delete()
        LilithTask.objects.filter(pk=t.pk).update(created_at=t.created_at.replace(year=2020))
        self.c.get(BOARD)
        self.assertFalse(LilithTask.objects.filter(user=self.me, template=key).exclude(bucket="trash").exists())

    def test_off_means_off(self):
        self.tier("statz")
        self.assertEqual(self.c.post("/api/economy/lilith/auto/", {"on": False}, format="json").status_code, 200)
        self.assertEqual(self.c.get(BOARD).data["auto"]["added"], [])
        self.assertFalse(LilithAuto.objects.get(user=self.me).on)

    def test_an_automatic_task_pays_no_spinaz(self):
        self.tier("statz")
        self.c.get(BOARD)
        t = LilithTask.objects.filter(user=self.me, source="auto").first()
        from apps.economy.lilith_taskz import complete
        out = complete(t)
        self.assertEqual(out["spinaz"], 0)

    def test_the_new_actions_are_counted_from_real_rows(self):
        from apps.economy import lilith_actions as A
        from apps.economy.models import MangaPage
        from django.utils import timezone
        from datetime import timedelta
        MangaPage.objects.create(user=self.me, title="p1")
        self.assertEqual(len(A.events(self.me, "manga_page", timezone.now() - timedelta(days=1))), 1)
