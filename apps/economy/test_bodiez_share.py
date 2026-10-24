"""Sharing a routine by code: one routine, library lifts only, expiring, free."""
from unittest import mock

from django.contrib.auth.models import User
from django.core import signing
from django.test import TestCase
from rest_framework.test import APIClient

from .bodiez import SHARE_SALT
from .models import BodieZExercise, BodieZRoutine


class ShareTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user(username="sharer", password="pw")
        self.b = User.objects.create_user(username="taker", password="pw")
        self.ca, self.cb = APIClient(), APIClient()
        self.ca.force_authenticate(self.a)
        self.cb.force_authenticate(self.b)
        self.lib = BodieZExercise.objects.create(name="SH Bench", muscle_group="chest", equipment="barbell")
        self.mine = BodieZExercise.objects.create(name="SH Secret", muscle_group="back", equipment="barbell", created_by=self.a)
        self.r = BodieZRoutine.objects.create(user=self.a, title="Push", exercises=[
            {"exercise_id": self.lib.id, "order": 0, "sets": 3, "reps": 8},
            {"exercise_id": self.mine.id, "order": 1, "sets": 3, "reps": 8}])

    def code(self):
        return self.ca.post(f"/api/economy/bodiez/routines/{self.r.id}/share/").data["code"]

    def test_redeem_copies_library_lifts_and_says_what_was_left_out(self):
        out = self.cb.post("/api/economy/bodiez/routines/redeem/", {"code": self.code()}, format="json")
        self.assertEqual(out.status_code, 201, out.data)
        self.assertEqual(out.data["left_out"], 1)
        self.assertEqual([e["exercise_id"] for e in out.data["exercises"]], [self.lib.id])
        self.assertTrue(BodieZRoutine.objects.filter(user=self.b, title="Push", source="member").exists())

    def test_only_the_owner_can_make_a_code(self):
        r = self.cb.post(f"/api/economy/bodiez/routines/{self.r.id}/share/")
        self.assertEqual(r.status_code, 404)

    def test_junk_and_expired_codes_are_refused_with_a_sentence(self):
        self.assertEqual(self.cb.post("/api/economy/bodiez/routines/redeem/", {"code": "nope"}, format="json").status_code, 400)
        old = signing.dumps({"r": self.r.id}, salt=SHARE_SALT)
        with mock.patch("django.core.signing.time.time", return_value=__import__("time").time() + 31 * 86400):
            r = self.cb.post("/api/economy/bodiez/routines/redeem/", {"code": old}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_deleted_routine_ends_the_code(self):
        c = self.code()
        self.r.delete()
        self.assertEqual(self.cb.post("/api/economy/bodiez/routines/redeem/", {"code": c}, format="json").status_code, 404)
