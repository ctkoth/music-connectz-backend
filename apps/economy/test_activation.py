from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.models import TakeScore


class ActivationTests(TestCase):
    def test_first_take_within_a_day_counts(self):
        U = get_user_model()
        owner = U.objects.create_user("owner", password="pw-long-enough-1", is_staff=True, is_superuser=True)
        quick = U.objects.create_user("quick", password="pw-long-enough-1")
        slow = U.objects.create_user("slow", password="pw-long-enough-1")
        TakeScore.objects.create(user=quick, app_key="rapz", scores={})
        t = TakeScore.objects.create(user=slow, app_key="rapz", scores={})
        TakeScore.objects.filter(pk=t.pk).update(created_at=timezone.now() + timedelta(days=3))
        c = APIClient(); c.force_authenticate(owner)
        me = APIClient(); me.force_authenticate(quick)
        self.assertEqual(me.get("/api/auth/onboard/complete/").data["first_take"]["app_key"], "rapz")
        from unittest import mock
        with mock.patch("apps.economy.views.is_owner", return_value=True):
            r = c.get("/api/auth/funnel/summary/")
        self.assertEqual(r.status_code, 200, r.data)
        a = r.data["activation"]
        self.assertEqual(a["from"], 3); self.assertEqual(a["to"], 1)
