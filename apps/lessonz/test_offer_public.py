"""A shared lesson link: a published listing anybody can read, without coordinates,
and never one that invites strangers to book an under-18 member."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.models import profile_for
from apps.lessonz.models import LessonOffer

User = get_user_model()


def teacher(name, age=None):
    u = User.objects.create_user(username=name, password="hunter2hunter2")
    if age is not None:
        p = profile_for(u)
        p.birthday = f"{timezone.now().year - age}-01-01"
        p.save()
    return u


def offer(t, **kw):
    return LessonOffer.objects.create(teacher=t, skill="rapz", title="Flow in 4 weeks",
                                      city="Leeds", latitude=53.8, longitude=-1.55, **kw)


class PublicLessonTests(TestCase):
    def read(self, o):
        return APIClient().get(f"/api/lessonz/offers/{o.pk}/public/")

    def test_logged_out_reads_it_without_coordinates(self):
        r = self.read(offer(teacher("coach", 34)))
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data["teacher_username"], r.data["city"]), ("coach", "Leeds"))
        self.assertNotIn("latitude", r.data)
        self.assertNotIn("longitude", r.data)

    def test_an_unpublished_listing_is_not_served(self):
        self.assertEqual(self.read(offer(teacher("off", 30), is_active=False)).status_code, 404)

    def test_a_minor_teachers_listing_is_not_served(self):
        self.assertEqual(self.read(offer(teacher("teen", 16))).status_code, 404)
