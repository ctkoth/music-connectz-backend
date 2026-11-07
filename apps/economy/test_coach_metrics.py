from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from . import royaltyfactor as rf
from .instruments import profile_for_app
from .models import TakeScore, profile_for

User = get_user_model()


class CoachMetricsTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user(username="metricer", password="x-pass-123")
        self.dims = list(profile_for_app("singz")["scores"])
        self.a, self.b, self.c = self.dims[0], self.dims[1], self.dims[2]

    def _takes(self, scores_list):
        for s in scores_list:
            TakeScore.objects.create(user=self.u, app_key="singz", scores=s,
                                     overall=round(sum(s.values()) / len(s)))

    def test_metric_read_averages_only_chosen_dimensions(self):
        take = TakeScore(scores={self.a: 9, self.b: 2, self.c: 5})
        self.assertEqual(rf.metric_read(take, [self.a, self.c]), 7)
        self.assertIsNone(rf.metric_read(take, ["not_a_dim"]))

    def test_coach_median_uses_picked_metrics_not_overall(self):
        self._takes([{self.a: 9, self.b: 1}, {self.a: 9, self.b: 1}, {self.a: 9, self.b: 1}])
        self.assertEqual(rf._coach_median(self.u, "singz"), (5, 3))  # overall: mean of 9 and 1
        p = profile_for(self.u)
        p.coach_metrics = {"singz": [self.a, self.b]}
        p.save()
        self.assertEqual(rf._coach_median(self.u, "singz"), (5, 3))
        p.coach_metrics = {"singz": [self.a]}
        p.save()
        self.assertEqual(rf._coach_median(self.u, "singz"), (9, 3))

    def test_stale_metric_keys_are_dropped(self):
        p = profile_for(self.u)
        p.coach_metrics = {"singz": [self.a, "invented_dim"]}
        p.save()
        self.assertEqual(rf.coach_metrics_for(self.u, "singz"), [self.a])

    def test_put_rejects_single_metric_and_unknown_coach(self):
        client = APIClient()
        client.force_authenticate(self.u)
        url = "/api/economy/skillz-coach/"
        r = client.put(url, {"app_key": "singz", "metrics": [self.a]}, format="json")
        self.assertEqual(r.status_code, 400)
        r = client.put(url, {"app_key": "nope", "metrics": [self.a, self.b]}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_put_saves_and_empty_list_restores_overall(self):
        client = APIClient()
        client.force_authenticate(self.u)
        url = "/api/economy/skillz-coach/"
        r = client.put(url, {"app_key": "singz", "metrics": [self.a, self.b]}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(profile_for(self.u).coach_metrics, {"singz": sorted([self.a, self.b])})
        r = client.put(url, {"app_key": "singz", "metrics": []}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(profile_for(self.u).coach_metrics, {})
