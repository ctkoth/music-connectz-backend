"""Location sharing: opt-in, approximate, adults only, and clearable."""
import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import profile_for

User = get_user_model()
URL = "/api/economy/profile/location/"


def member(name, age=None):
    u = User.objects.create_user(name, f"{name}@x.test", "hunter2hunter2")
    if age is not None:
        p = profile_for(u)
        today = datetime.date.today()
        p.birthday = today.replace(year=today.year - age) - datetime.timedelta(days=2)
        p.save()
    c = APIClient(); c.force_authenticate(u)
    return u, c


class LocationSharingTests(TestCase):
    def test_coordinates_are_stored_approximately(self):
        u, c = member("loc_adult", 30)
        r = c.post(URL, {"share": True, "lat": 39.74381, "lng": -104.98764}, format="json")
        self.assertEqual(r.status_code, 200)
        p = profile_for(u); p.refresh_from_db()
        self.assertTrue(p.share_location)
        self.assertEqual((p.lat, p.lng), (39.74, -104.99))

    def test_turning_it_off_deletes_the_position(self):
        u, c = member("loc_off", 30)
        c.post(URL, {"share": True, "lat": 10.5, "lng": 20.5}, format="json")
        r = c.post(URL, {"share": False}, format="json")
        self.assertEqual(r.status_code, 200)
        p = profile_for(u); p.refresh_from_db()
        self.assertFalse(p.share_location)
        self.assertIsNone(p.lat); self.assertIsNone(p.lng)

    def test_a_minor_is_refused_and_nothing_is_stored(self):
        u, c = member("loc_teen", 15)
        r = c.post(URL, {"share": True, "lat": 10.5, "lng": 20.5}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertTrue(r.data["adult_only"])
        p = profile_for(u); p.refresh_from_db()
        self.assertFalse(p.share_location); self.assertIsNone(p.lat)

    def test_a_minor_can_still_turn_it_off(self):
        # A teen who somehow has a stored position can always clear it.
        u, c = member("loc_teen2", 15)
        r = c.post(URL, {"share": False}, format="json")
        self.assertEqual(r.status_code, 200)

    def test_bad_coordinates_are_refused(self):
        _, c = member("loc_bad", 30)
        self.assertEqual(c.post(URL, {"share": True, "lat": 91, "lng": 0}, format="json").status_code, 400)
        self.assertEqual(c.post(URL, {"share": True}, format="json").status_code, 400)
