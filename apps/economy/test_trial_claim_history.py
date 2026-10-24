"""A scored trial take, claimed at signup, is the first row of the member's coach history."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.models import TakeScore, TrialTake

User = get_user_model()


def trial(token, app="rapz", score=7, **kw):
    t = TrialTake.objects.create(token=token, app_key=app, anon_id="b1", scored=score is not None,
                                 result={"score": score, "scores": {"flow": 7, "timing": 6},
                                         "verdict": "Tight pocket."}, **kw)
    return t


class ClaimedTakeShowsUpTests(TestCase):
    def join(self, token):
        r = APIClient().post("/api/auth/register/", {
            "username": "newbie", "email": "n@example.com", "password": "Sturdy-pass-8812",
            "trial_token": token}, format="json")
        self.assertIn(r.status_code, (200, 201), r.data)
        return User.objects.get(username="newbie")

    def test_the_take_is_in_the_coach_history_dated_when_it_was_made(self):
        t = trial("tok-a")
        TrialTake.objects.filter(pk=t.pk).update(created_at=timezone.now() - timedelta(days=2))
        u = self.join("tok-a")
        row = TakeScore.objects.get(user=u, app_key="rapz")
        self.assertEqual((row.overall, row.source, row.ref), (7, "trial", f"trial:{t.pk}"))
        self.assertLess(row.created_at, timezone.now() - timedelta(days=1))
        c = APIClient(); c.force_authenticate(u)
        self.assertEqual(c.get("/api/rapz/progress/").data["total_takes"], 1)

    def test_an_unscored_take_writes_no_history(self):
        trial("tok-b", score=None)
        u = self.join("tok-b")
        self.assertFalse(TakeScore.objects.filter(user=u).exists())


class BackfillTests(TestCase):
    def test_an_old_claim_is_backfilled_once(self):
        from apps.economy.models import backfill_trial_history
        u = User.objects.create_user(username="early", password="hunter2hunter2")
        t = trial("old-1")
        TrialTake.objects.filter(pk=t.pk).update(claimed_by=u, claimed_at=timezone.now())  # claimed before the fix
        self.assertEqual(len(backfill_trial_history(write=False)), 1)               # dry: listed, not written
        self.assertFalse(TakeScore.objects.filter(user=u).exists())
        self.assertEqual(len(backfill_trial_history(write=True)), 1)
        self.assertEqual(TakeScore.objects.get(user=u).ref, f"trial:{t.pk}")
        self.assertEqual(backfill_trial_history(write=True), [])                    # a re-run adds nothing
        self.assertEqual(TakeScore.objects.filter(user=u).count(), 1)
