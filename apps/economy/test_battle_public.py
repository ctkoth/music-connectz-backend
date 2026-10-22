"""A shared battle link: anybody can read it; an under-18 member is not on it."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.models import Battle, BattleEntry, profile_for

User = get_user_model()


def member(name, age=None):
    u = User.objects.create_user(username=name, password="hunter2hunter2")
    if age is not None:
        p = profile_for(u)
        p.birthday = f"{timezone.now().year - age}-01-01"
        p.save()
    return u


class PublicBattleTests(TestCase):
    def read(self, b):
        return APIClient().get(f"/api/economy/battlez/{b.pk}/public/")

    def test_logged_out_reads_it_and_a_minor_entry_is_absent(self):
        host = member("host", 30)
        b = Battle.objects.create(host=host, title="16 bars", kind="freestyle", media_url="/m/host.webm")
        BattleEntry.objects.create(battle=b, user=member("adult", 25), title="mine", media_url="/m/a.webm")
        BattleEntry.objects.create(battle=b, user=member("teen", 15), title="young", media_url="/m/t.webm")
        BattleEntry.objects.create(battle=b, user=member("noage"), title="unknown age")   # unknown = adult
        r = self.read(b)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["host"], "host")
        self.assertEqual([e["username"] for e in r.data["entries"]], ["adult", "noage"])
        self.assertNotIn("teen", str(r.data))

    def test_a_minor_host_is_not_named_and_their_take_is_not_served(self):
        b = Battle.objects.create(host=member("younghost", 16), title="x", media_url="/m/y.webm",
                                  description="about me")
        d = self.read(b).data
        self.assertEqual((d["host"], d["media_url"], d["description"]), ("", "", ""))

    def test_a_minor_winner_is_not_named(self):
        teen = member("teenwin", 14)
        b = Battle.objects.create(host=member("h2", 40), title="y", winner=teen)
        self.assertEqual(self.read(b).data["winner"], "")

    def test_missing_battle_is_404(self):
        self.assertEqual(APIClient().get("/api/economy/battlez/999999/public/").status_code, 404)
