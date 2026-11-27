from datetime import date

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy import lilith_auto
from apps.economy import lilith_taskz as L
from apps.economy.lilith_suggest import suggest
from apps.economy.models import (LilithAuto, LilithRoutine, LilithTask, Membership, membership_for,
                                 profile_for, wallet_for)

U = get_user_model()
BOARD = "/api/economy/lilith/"


def designer(user):
    p = profile_for(user)
    p.personas = [{"name": "Designer", "emoji": "🎨", "skills": []}]
    p.save()


class LilithAutoTests(TestCase):
    def setUp(self):
        cache.clear()
        self.me = U.objects.create_user("drawer", password="pw12345!x")
        designer(self.me)
        self.c = APIClient(); self.c.force_authenticate(self.me)

    def tier(self, t):
        membership_for(self.me)
        Membership.objects.filter(user=self.me).update(tier=t)

    def test_a_designer_is_suggested_routines_for_pictures_and_pages(self):
        got = {s["key"]: s for s in suggest(self.me) if s["kind"] == "routine"}
        # The top five are shared with the SkillZ routine a designer with no drills is offered, so only the first
        # picture routine is guaranteed a place here.
        self.assertIn("make_picture", got)
        self.assertIn("weak_spot", got)
        self.assertIn("Designer", got["make_picture"]["why"])
        self.assertEqual(got["make_picture"]["cadence"], "weekly")
        self.assertFalse([s for s in suggest(self.me) if s["kind"] == "task" and s["key"] == "make_picture"])

    def test_free_gets_suggestions_but_nothing_added(self):
        d = self.c.get(BOARD).data
        self.assertFalse(d["auto"]["allowed"])
        self.assertEqual(d["auto"]["added"], [])
        self.assertTrue([s for s in d["suggested"] if s["kind"] == "routine"])          # they can still add them by hand
        self.assertFalse(LilithRoutine.objects.filter(user=self.me, source="auto").exists())
        self.assertFalse(LilithTask.objects.filter(user=self.me, source="auto").exists())
        self.assertEqual(self.c.post("/api/economy/lilith/auto/", {"on": True}, format="json").status_code, 403)

    def test_statz_gets_up_to_three_a_day_as_routines_each_with_its_reason(self):
        self.tier("statz")
        d = self.c.get(BOARD).data
        added = d["auto"]["added"]
        self.assertEqual(len(added), lilith_auto.PER_DAY)
        rows = LilithRoutine.objects.filter(user=self.me, source="auto")
        self.assertEqual(rows.count(), 3)
        for r in rows:
            self.assertTrue(r.note.startswith(lilith_auto.NOTE_PREFIX))
            self.assertTrue(r.action)                                # verified: Lilith keeps it herself
        self.assertFalse(LilithTask.objects.filter(user=self.me, source="auto").exists())
        again = self.c.get(BOARD).data["auto"]["added"]              # still said on the next open, not more added
        self.assertEqual(sorted(a["id"] for a in again), sorted(a["id"] for a in added))
        self.assertTrue(all(a["why"] for a in again))
        self.assertEqual(LilithRoutine.objects.filter(user=self.me, source="auto").count(), 3)

    def test_a_deleted_one_never_comes_back(self):
        self.tier("statz")
        self.c.get(BOARD)
        r = LilithRoutine.objects.filter(user=self.me, source="auto").first()
        key = r.template
        r.trashed_at = timezone.now()
        r.save(update_fields=["trashed_at"])                         # the member said no: it goes to the Trash
        LilithRoutine.objects.filter(user=self.me, source="auto").exclude(pk=r.pk).delete()
        self.c.get(BOARD)
        self.assertFalse(LilithRoutine.objects.filter(user=self.me, template=key, trashed_at__isnull=True).exists())

    def test_off_means_off(self):
        self.tier("statz")
        self.assertEqual(self.c.post("/api/economy/lilith/auto/", {"on": False}, format="json").status_code, 200)
        self.c.get(BOARD)
        self.assertFalse(LilithRoutine.objects.filter(user=self.me, source="auto").exists())
        self.assertFalse(LilithAuto.objects.get(user=self.me).on)

    def test_an_automatic_routine_keeps_its_streak_and_pays_nothing(self):
        before = wallet_for(self.me).spinaz
        mine = LilithRoutine.objects.create(user=self.me, title="mine", cadence="weekly", streak=3,
                                            last_done=date(2026, 1, 12), source="self")
        auto = LilithRoutine.objects.create(user=self.me, title="auto", cadence="weekly", streak=3,
                                            last_done=date(2026, 1, 12), source="auto")
        L.keep_routine(mine, on=date(2026, 1, 19))                  # week four: a rung
        out = L.keep_routine(auto, on=date(2026, 1, 19))
        self.assertEqual(out["streak"], 4)                          # the streak counts
        self.assertIsNone(out["milestone"])                         # and nothing is paid for it
        self.assertEqual(wallet_for(self.me).spinaz, before + L.CADENCE_MILESTONES["weekly"][4])   # only the member's own

    def test_the_new_actions_are_counted_from_real_rows(self):
        from apps.economy import lilith_actions as A
        from apps.economy.models import MangaPage
        from datetime import timedelta
        MangaPage.objects.create(user=self.me, title="p1")
        self.assertEqual(len(A.events(self.me, "manga_page", timezone.now() - timedelta(days=1))), 1)
