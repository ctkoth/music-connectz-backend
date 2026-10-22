"""The SoundCloud library manager. Mocks the import; never touches SoundCloud."""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from .models import (Notification, Post, TIER_STATZ, Transaction, membership_for,
                     profile_for, wallet_for)

User = get_user_model()
LIB = "/api/economy/soundcloud/library/"


def imp(title, n, released_days=None, private=False, **kw):
    e = {"type": "soundcloud", "url": f"https://w.soundcloud.com/player/?url=x{n}", "title": title,
         "sc_id": str(n), "imported": True, "imported_at": timezone.now().isoformat(),
         "permalink": "" if private else f"https://soundcloud.com/me/t{n}"}
    if released_days is not None:
        e["released_at"] = (timezone.now() - timedelta(days=released_days)).isoformat()
    if private:
        e["private_on_sc"] = True
    return e


class Base(TestCase):
    def setUp(self):
        self.me = User.objects.create_user("importer", "i@x.com", "hunter2hunter2")
        self.c = APIClient()
        self.c.force_authenticate(self.me)
        w = wallet_for(self.me)
        w.energy = 100
        w.save(update_fields=["energy", "updated_at"])

    def post(self, n, vis="private", **kw):
        emb = kw.pop("embed", None) or imp(f"T{n}", n, released_days=100 + n)
        return Post.objects.create(author=self.me, title=emb["title"], visibility=vis,
                                   embeds=[emb], **kw)

    def priced(self):
        p = profile_for(self.me)
        p.personas = [{"key": "p", "name": "P", "skills": [{"name": "Mix", "rate_cents": 40}]}]
        p.save(update_fields=["personas"])


class ListingTests(Base):
    def test_shape_counts_and_scope(self):
        a, b = self.post(1), self.post(2, "public")
        self.post(3, embed=imp("Sec", 3, 5, private=True))
        Post.objects.create(author=self.me, title="Hand", embeds=[{"type": "soundcloud", "url": "u"}])
        other = User.objects.create_user("o", "o@x.com", "hunter2hunter2")
        Post.objects.create(author=other, title="Theirs", embeds=[imp("Theirs", 9)])
        d = self.c.get(LIB).data
        self.assertEqual(d["counts"]["total"], 3)
        self.assertEqual(d["counts"]["private"], 2)
        self.assertEqual(d["counts"]["public"], 1)
        self.assertEqual(d["counts"]["private_on_sc"], 1)
        row = next(r for r in d["rows"] if r["id"] == a.id)
        for k in ("title", "soundcloud_url", "artwork", "visibility", "private_on_sc", "imported_at",
                  "can_publish", "why_not", "publish_cost"):
            self.assertIn(k, row)
        sec = next(r for r in d["rows"] if r["private_on_sc"])
        self.assertEqual(sec["soundcloud_url"], "")
        self.assertIsNone(d["import"]["ladder"]["statz"])
        self.assertEqual(d["import"]["ladder"]["free"], 10)
        self.assertIn("restricted", d["explain"])
        from apps.economy.models import RESTRICTED_JOIN_REWARD_SPINAZ
        self.assertIn(str(RESTRICTED_JOIN_REWARD_SPINAZ), d["explain"]["restricted"])

    def test_queries_flat(self):
        for n in range(3):
            self.post(n)
        self.c.get(LIB)  # warm the lazily-made wallet/membership rows
        with CaptureQueriesContext(connection) as small:
            self.c.get(LIB)
        for n in range(3, 40):
            self.post(n)
        with CaptureQueriesContext(connection) as big:
            self.c.get(LIB)
        self.assertEqual(len(small), len(big))

    def test_paging_and_ids(self):
        for n in range(130):
            self.post(n)
        d = self.c.get(LIB + "?page=2").data
        self.assertEqual(len(d["rows"]), 30)
        self.assertEqual(len(self.c.get(LIB + "?ids=1&visibility=private").data["ids"]), 130)


class ApplyTests(Base):
    def go(self, which, ids, vis, **kw):
        return self.c.post(LIB + which + "/", {"ids": ids, "visibility": vis, **kw}, format="json")

    def test_preview_equals_apply_and_ledger(self):
        self.priced()
        w = wallet_for(self.me); w.energy = 500; w.save(update_fields=["energy", "updated_at"])
        ps = [self.post(n, skills_used=["Mix"]) for n in range(3)]
        ids = [p.id for p in ps]
        pre = self.go("preview", ids, "public").data
        self.assertEqual(pre["cost"]["amount"], 120)
        self.assertTrue(pre["affordable_all"])
        before = wallet_for(self.me).energy
        out = self.go("apply", ids, "public").data
        self.assertEqual(out["charged"]["amount"], 120)
        self.assertEqual(before - wallet_for(self.me).energy, 120)
        self.assertEqual(Transaction.objects.filter(user=self.me, resource="energy").count(), 3)
        again = self.go("apply", ids, "public").data
        self.assertEqual(again["charged"]["amount"], 0)
        self.assertEqual(again["skipped"], 3)

    def test_stops_when_funds_run_out_no_overcharge(self):
        self.priced()
        w = wallet_for(self.me)
        w.energy = 90
        w.save(update_fields=["energy", "updated_at"])
        ps = [self.post(n, skills_used=["Mix"]) for n in range(4)]
        ids = [p.id for p in ps]
        pre = self.go("preview", ids, "public").data
        self.assertFalse(pre["affordable_all"])
        self.assertEqual(pre["affordable_count"], 2)
        out = self.go("apply", ids, "public").data
        self.assertEqual(out["published"], 2)
        self.assertEqual(out["charged"]["amount"], 80)
        self.assertEqual(wallet_for(self.me).energy, 10)
        self.assertEqual(out["not_attempted"], 1)
        self.assertEqual(Post.objects.filter(visibility="private").count(), 2)

    def test_soundcloud_private_needs_consent(self):
        p = self.post(1, embed=imp("Sec", 1, 5, private=True))
        pre = self.go("preview", [p.id], "public").data
        self.assertEqual(len(pre["needs_consent"]), 1)
        out = self.go("apply", [p.id], "public").data
        self.assertEqual(out["results"][0]["result"], "skipped")
        p.refresh_from_db()
        self.assertEqual(p.visibility, "private")
        self.go("apply", [p.id], "public", confirm_private_secret=True)
        p.refresh_from_db()
        self.assertEqual(p.visibility, "public")

    def test_not_yours_ignored_and_others_untouched(self):
        other = User.objects.create_user("o", "o@x.com", "hunter2hunter2")
        theirs = Post.objects.create(author=other, title="T", embeds=[imp("T", 9)], visibility="private")
        hand = Post.objects.create(author=self.me, title="H", embeds=[{"type": "soundcloud", "url": "u"}],
                                   visibility="private")
        out = self.go("apply", [theirs.id, hand.id, 99999], "public")
        self.assertEqual(out.status_code, 200)
        self.assertEqual({r["result"] for r in out.data["results"]}, {"ignored"})
        theirs.refresh_from_db(); hand.refresh_from_db()
        self.assertEqual((theirs.visibility, hand.visibility), ("private", "private"))

    def test_round_trip_and_private_is_free(self):
        p = self.post(1)
        self.go("apply", [p.id], "restricted")
        p.refresh_from_db(); self.assertEqual(p.visibility, "restricted")
        self.go("apply", [p.id], "public")
        w = wallet_for(self.me)
        w.energy = 0
        w.save(update_fields=["energy", "updated_at"])
        out = self.go("apply", [p.id], "private").data
        self.assertEqual(out["changed"], 1)
        p.refresh_from_db(); self.assertEqual(p.visibility, "private")

    def test_batch_dates_to_release_single_keeps_date_never_later(self):
        a, b = self.post(1), self.post(2)
        old_a = a.created_at
        self.go("apply", [a.id, b.id], "public")
        a.refresh_from_db(); b.refresh_from_db()
        self.assertLess(a.created_at, old_a - timedelta(days=50))
        self.assertLess(b.created_at, timezone.now() - timedelta(days=50))
        c = self.post(3)
        keep = c.created_at
        out = self.go("apply", [c.id], "public").data
        c.refresh_from_db()
        self.assertEqual(c.created_at, keep)
        self.assertFalse(out["dated_to_release"])
        # a release date NEWER than the post never moves it forward
        d, e = self.post(4, embed=imp("D", 4, -0)), self.post(5, embed=imp("E", 5, 0))
        before = d.created_at
        self.go("apply", [d.id, e.id], "public")
        d.refresh_from_db()
        self.assertLessEqual(d.created_at, before)

    def test_no_notifications_and_per_call_cap(self):
        ps = [self.post(n) for n in range(5)]
        self.go("apply", [p.id for p in ps], "public")
        self.assertEqual(Notification.objects.count(), 0)
        with patch("apps.economy.soundcloud_library.MAX_PER_CALL", 2):
            qs = [self.post(n) for n in range(10, 14)]
            out = self.go("apply", [p.id for p in qs], "public").data
        self.assertEqual(out["published"], 2)
        self.assertEqual(out["not_attempted"], 2)

    def test_tier_cap_statement_unchanged(self):
        m = membership_for(self.me); m.tier = TIER_STATZ; m.save(update_fields=["tier", "updated_at"])
        self.assertTrue(self.c.get("/api/economy/soundcloud/import/").data["whole_catalogue"])
