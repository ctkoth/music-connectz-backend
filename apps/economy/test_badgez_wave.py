"""BadgeZ wave one: a badge per coach, the royalty pair, and the stickers made real."""
import pathlib
import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from . import badgez_wave as W
from .instruments import INSTRUMENTS
from .models import (BADGES, Badge, CollabDeal, ItemRating, Notification, Post, TakeScore,
                     Wallet, ai_energy_cost, grant_badge, recheck_badges, submission_cap_for,
                     wallet_for)

User = get_user_model()
HERE = pathlib.Path(__file__).parent


def _src_without_catalogue():
    """Every non-test module's source, with the BADGES catalogue itself cut out —
    an effect named only in the catalogue is a promise, not a reader."""
    out = []
    for f in HERE.glob("*.py"):
        if f.name.startswith("test_") or f.name == "badgez_wave.py":
            continue
        text = f.read_text()
        if f.name == "models.py":
            start = text.index("BADGES = {")
            end = text.index("\nclass Badge(models.Model)")
            text = text[:start] + text[end:]
        out.append(text)
    return "\n".join(out)


class ABadgeThatOnlyLooksNiceIsASticker(TestCase):
    """Five effects were promised on screen and read by nothing: Collaborator's
    +5 submissions and needs-first, Straight Shooter's waived stake, the
    discovery boost (read by a hardcoded key) and Bug Hunter's +50 🏷️."""

    def test_every_promised_effect_has_a_reader(self):
        src = _src_without_catalogue()
        keys = {k for spec in BADGES.values() for k in spec.get("effects", {})} - {"achievement"}
        for k in sorted(keys):
            self.assertTrue(re.search(rf'["\']{k}["\']', src), f"no system reads the badge effect {k!r}")


class TheNamesAreCoreysVoice(TestCase):
    def test_every_coach_has_a_badge(self):
        self.assertEqual(set(W.COACH_BADGES), set(INSTRUMENTS))

    def test_the_wave_uses_a_z_where_an_s_would_be(self):
        for key, spec in W.specs().items():
            self.assertTrue(spec["name"].endswith("Z"), spec["name"])
            self.assertTrue(spec["emoji"])
            self.assertEqual(spec["icon"], f"badge_{key}.png")


class CoachBadges(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("singer", password="pw")

    def take(self, overall, app="singz", days_ago=0):
        t = TakeScore.objects.create(user=self.u, app_key=app, overall=overall, scores={})
        if days_ago:
            TakeScore.objects.filter(pk=t.pk).update(created_at=timezone.now() - timedelta(days=days_ago))

    def test_three_takes_scored_eight_earn_it(self):
        self.take(8); self.take(9)
        recheck_badges(self.u)
        self.assertFalse(Badge.objects.filter(user=self.u, key="high_notez").exists())
        self.take(8)
        recheck_badges(self.u)
        self.assertTrue(Badge.objects.filter(user=self.u, key="high_notez").exists())
        self.assertFalse(Badge.objects.filter(user=self.u, key="hot_barz").exists())

    def test_takes_outside_the_window_do_not_count_and_it_lapses(self):
        for _ in range(3):
            self.take(9)
        recheck_badges(self.u)
        TakeScore.objects.filter(user=self.u).update(created_at=timezone.now() - timedelta(days=W.HOT_DAYS + 1))
        recheck_badges(self.u)
        self.assertFalse(Badge.objects.filter(user=self.u, key="high_notez").exists())

    def test_a_scored_take_lands_the_badge_on_the_spot(self):
        from .takescorez import record
        for _ in range(3):
            record(self.u, "rapz", {"score": 8, "scores": {}})
        self.assertTrue(Badge.objects.filter(user=self.u, key="hot_barz").exists())

    def test_the_perk_is_in_the_price_the_screen_shows(self):
        before = ai_energy_cost(self.u, "fable")
        grant_badge(self.u, "high_notez")
        self.assertEqual(ai_energy_cost(self.u, "fable"), max(1, -(-before * 90 // 100)))

    def test_every_coach_badge_together_stops_at_the_cap(self):
        for key, _n, _e in W.COACH_BADGES.values():
            grant_badge(self.u, key)
        self.assertEqual(ai_energy_cost(self.u, "fable"), 4)   # 8 × 50%, never under


class RoyaltyPair(TestCase):
    def setUp(self):
        self.a = User.objects.create_user("artist", password="pw")
        self.post = Post.objects.create(author=self.a, title="Track", visibility="public")

    def rate(self, *scores):
        for i, s in enumerate(scores):
            r = User.objects.create_user(f"r{len(ItemRating.objects.all())}_{i}", password="pw")
            ItemRating.objects.create(user=r, item_id=f"post:{self.post.id}", score=s)

    def test_four_outside_raters_move_nothing(self):
        self.rate(9, 9, 9, 9)
        recheck_badges(self.a)
        self.assertFalse(Badge.objects.filter(user=self.a, key="royal_ratingz").exists())

    def test_a_track_the_room_rates_seven_plus_is_royal(self):
        self.rate(7, 8, 8, 9, 7)
        recheck_badges(self.a)
        self.assertTrue(Badge.objects.filter(user=self.a, key="royal_ratingz").exists())

    def test_the_cut_is_a_hidden_penalty_and_says_so(self):
        self.rate(2, 3, 3, 4, 2)
        recheck_badges(self.a)
        b = Badge.objects.get(user=self.a, key="cut_royaltiez")
        self.assertFalse(b.visible)
        self.assertTrue(Notification.objects.filter(user=self.a, text__contains="applies to you").exists())
        self.assertFalse(Notification.objects.filter(user=self.a, text__contains="You earned Cut").exists())

    def test_the_artists_own_rating_does_not_count(self):
        ItemRating.objects.create(user=self.a, item_id=f"post:{self.post.id}", score=10)
        self.rate(9, 9, 9, 9)
        recheck_badges(self.a)
        self.assertFalse(Badge.objects.filter(user=self.a, key="royal_ratingz").exists())


class StickersMadeReal(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("vet", password="pw")

    def test_collaborator_raises_the_submission_cap(self):
        before = submission_cap_for(self.u)
        grant_badge(self.u, "collaborator")
        self.assertEqual(submission_cap_for(self.u), before + 5)

    def test_bug_hunter_pays_its_promptz_once(self):
        grant_badge(self.u, "bug_hunter")
        grant_badge(self.u, "bug_hunter")
        self.assertEqual(wallet_for(self.u).promptz, 50)

    def test_straight_shooter_funds_without_a_stake(self):
        other = User.objects.create_user("other", password="pw")
        grant_badge(self.u, "straight_shooter")
        Wallet.objects.filter(user=wallet_for(self.u).user).update(spinaz=100)
        deal = CollabDeal.objects.create(
            initiator=other, title="d", currency=CollabDeal.CURRENCY_SPINAZ, stake_spinaz=40,
            participants=[{"username": "vet", "pays_cents": 0, "accepted_at": "x"},
                          {"username": "other", "receives_cents": 0}])
        c = APIClient()
        c.force_authenticate(self.u)
        card = c.get("/api/economy/collab/").data["deals"][0]
        self.assertEqual(card["my_stake"], 0)
        self.assertTrue(card["stake_waived"])
        r = c.post(f"/api/economy/collab/{deal.id}/fund/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(wallet_for(self.u).spinaz, 100)


class TappingABadgeShowsWhoElseHasIt(TestCase):
    def test_holders_are_the_ones_who_show_it(self):
        a, b, c = (User.objects.create_user(n, password="pw") for n in ("aa", "bb", "cc"))
        for u in (a, b, c):
            grant_badge(u, "ear")
        Badge.objects.filter(user=c).update(visible=False)
        api = APIClient()
        api.force_authenticate(a)
        d = api.get("/api/economy/badgez/holders/?key=ear").data
        self.assertEqual(sorted(h["username"] for h in d["holders"]), ["aa", "bb"])
        self.assertEqual(d["count"], 2)
        self.assertTrue(d["badge"]["effect_note"])
        self.assertTrue(d["mine"]["held"])

    def test_a_penalty_nobody_chose_to_show_lists_nobody(self):
        u = User.objects.create_user("cut", password="pw")
        grant_badge(u, "cut_royaltiez")
        api = APIClient()
        api.force_authenticate(u)
        self.assertEqual(api.get("/api/economy/badgez/holders/?key=cut_royaltiez").data["holders"], [])
