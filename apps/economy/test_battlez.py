"""BattleZ — the tab that had no backend.

It has been in the tab bar since the app was written with not one row behind
it, which made "BattleZ carries the range gates" a promise with nothing to
enforce. The challenge and every entry carry the work in the PostZ format, the
same five exclusive ranges decide who gets in, and judging rides the item space
RateZ already serves rather than a second rating system.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import (
    TIER_FREE,
    Battle,
    BattleEntry,
    ItemRating,
    Notification,
    OverallRating,
    award_spinaz,
    membership_for,
    profile_for,
    wallet_for,
)

User = get_user_model()
PW = "hunter2hunter2"


def rated(user, score):
    OverallRating.objects.create(
        rater=User.objects.create_user(f"r{user.username}", f"r{user.username}@e.com", PW),
        target=user, score=score)
    return user


class HostingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.host = User.objects.create_user("host", "h@e.com", PW)
        self.client.force_authenticate(self.host)

    def create(self, **over):
        return self.client.post("/api/economy/battlez/", {"title": "16 bars", **over},
                                format="json")

    def test_a_battle_needs_a_name(self):
        self.assertEqual(self.create(title="  ").status_code, 400)

    def test_the_challenge_carries_the_work_in_the_postz_format(self):
        resp = self.create(description="Beat's attached.", genre="Drill",
                           media_type="audio", media_url="https://x.test/beat.mp3",
                           image_url="https://x.test/art.jpg", lyrics="hook goes here")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["media_type"], "audio")
        self.assertEqual(resp.data["media_url"], "https://x.test/beat.mp3")
        self.assertEqual(resp.data["image_url"], "https://x.test/art.jpg")
        self.assertEqual(resp.data["lyrics"], "hook goes here")
        self.assertEqual(resp.data["genre"], "Drill")

    def test_it_is_judged_through_the_shared_item_space(self):
        resp = self.create()
        self.assertEqual(resp.data["item_key"], f"battle:{resp.data['id']}")

    def test_the_description_answers_to_the_tier_limit(self):
        m = membership_for(self.host)
        m.tier = TIER_FREE
        m.save(update_fields=["tier", "updated_at"])
        resp = self.create(description="d" * 401)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["char_limit"], 400)

    def test_the_host_can_close_it(self):
        pk = self.create().data["id"]
        resp = self.client.patch(f"/api/economy/battlez/{pk}/", {"status": "closed"},
                                 format="json")
        self.assertEqual(resp.data["status"], "closed")

    def test_nobody_else_can(self):
        pk = self.create().data["id"]
        self.client.force_authenticate(User.objects.create_user("x", "x@e.com", PW))
        self.assertEqual(self.client.patch(f"/api/economy/battlez/{pk}/",
                                           {"status": "closed"}, format="json").status_code, 404)


class EnteringTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.host = User.objects.create_user("host", "h@e.com", PW)
        self.entrant = User.objects.create_user("entrant", "e@e.com", PW)
        self.battle = Battle.objects.create(host=self.host, title="16 bars")
        self.client.force_authenticate(self.entrant)

    def enter(self, **over):
        return self.client.post(f"/api/economy/battlez/{self.battle.pk}/enter/",
                                {"title": "My 16", "media_type": "audio",
                                 "media_url": "https://x.test/me.mp3", **over},
                                format="json")

    def test_an_entry_carries_the_work_too(self):
        resp = self.enter(lyrics="my bars")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["entry"]["media_url"], "https://x.test/me.mp3")
        self.assertEqual(resp.data["entry"]["lyrics"], "my bars")

    def test_each_entry_is_judged_on_its_own_key(self):
        entry = self.enter().data["entry"]
        self.assertEqual(entry["item_key"], f"battle:{self.battle.pk}:entry:{entry['id']}")

    def test_the_host_is_told(self):
        self.enter()
        self.assertTrue(Notification.objects.filter(user=self.host).exists())

    def test_you_cannot_enter_twice(self):
        self.enter()
        self.assertEqual(self.enter().status_code, 409)

    def test_you_cannot_enter_your_own(self):
        self.client.force_authenticate(self.host)
        self.assertEqual(self.enter().status_code, 400)

    def test_a_closed_battle_takes_no_more(self):
        self.battle.status = Battle.STATUS_CLOSED
        self.battle.save(update_fields=["status"])
        self.assertEqual(self.enter().status_code, 409)

    def test_an_entry_can_bring_a_linked_track_instead_of_an_upload(self):
        resp = self.client.post(
            f"/api/economy/battlez/{self.battle.pk}/enter/",
            {"title": "My 16", "media_type": "", "media_url": "",
             "link": {"url": "https://open.spotify.com/track/xyz", "label": "My track",
                      "service": "spotify"}},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["entry"]["link"]["url"], "https://open.spotify.com/track/xyz")
        self.assertEqual(resp.data["entry"]["link"]["service"], "spotify")

    def test_a_link_with_no_url_is_dropped_not_stored_as_an_empty_shell(self):
        resp = self.enter(link={"label": "no url here"})
        self.assertEqual(resp.data["entry"]["link"], {})

    def test_withdrawing_removes_the_entry(self):
        self.enter()
        resp = self.client.delete(f"/api/economy/battlez/{self.battle.pk}/enter/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(BattleEntry.objects.exists())


class EntryFeeTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.host = User.objects.create_user("host", "h@e.com", PW)
        self.entrant = User.objects.create_user("entrant", "e@e.com", PW)
        self.battle = Battle.objects.create(host=self.host, title="16 bars", entry_spinaz=50)
        self.client.force_authenticate(self.entrant)

    def enter(self):
        return self.client.post(f"/api/economy/battlez/{self.battle.pk}/enter/", {},
                                format="json")

    def test_a_member_who_cannot_pay_is_told_the_price_and_their_balance(self):
        resp = self.enter()
        self.assertEqual(resp.status_code, 402, resp.content)
        self.assertEqual(resp.data["entry_spinaz"], 50)
        self.assertIn("50", resp.data["detail"])

    def test_the_fee_moves_to_the_host(self):
        award_spinaz(self.entrant, 100, "seed")
        self.assertEqual(self.enter().status_code, 201)
        self.assertEqual(wallet_for(self.entrant).spinaz, 50)
        self.assertEqual(wallet_for(self.host).spinaz, 50)

    def test_withdrawing_does_not_refund_it(self):
        # It was paid for the host's time the moment it was accepted; refunding
        # on withdrawal would make the fee meaningless.
        award_spinaz(self.entrant, 100, "seed")
        self.enter()
        self.client.delete(f"/api/economy/battlez/{self.battle.pk}/enter/")
        self.assertEqual(wallet_for(self.host).spinaz, 50)


class BattleGateTests(TestCase):
    """The same five ranges, from the same spec as search and VenueZ."""

    def setUp(self):
        self.client = APIClient()
        self.host = User.objects.create_user("host", "h@e.com", PW)

    def battle(self, gates):
        return Battle.objects.create(host=self.host, title="16 bars", gates=gates)

    def enter(self, b):
        return self.client.post(f"/api/economy/battlez/{b.pk}/enter/", {}, format="json")

    def test_somebody_below_the_bar_is_refused_and_told_which_range(self):
        b = self.battle({"rating": [6, 10]})
        self.client.force_authenticate(rated(User.objects.create_user("weak", "w@e.com", PW), 2))
        resp = self.enter(b)
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertEqual(resp.data["gate"], "rating")
        self.assertIn("skill rating", resp.data["detail"])
        self.assertFalse(BattleEntry.objects.exists())

    def test_somebody_inside_it_gets_in(self):
        b = self.battle({"rating": [6, 10]})
        self.client.force_authenticate(rated(User.objects.create_user("ace", "a@e.com", PW), 9))
        self.assertEqual(self.enter(b).status_code, 201)

    def test_an_unrated_entrant_is_excluded_because_the_gates_are_exclusive(self):
        b = self.battle({"rating": [1, 10]})
        self.client.force_authenticate(User.objects.create_user("unrated", "u@e.com", PW))
        self.assertEqual(self.enter(b).status_code, 403)

    def test_an_ungated_battle_asks_nobody_for_anything(self):
        b = self.battle({})
        self.client.force_authenticate(User.objects.create_user("anyone", "n@e.com", PW))
        self.assertEqual(self.enter(b).status_code, 201)

    def test_the_gates_a_host_posts_come_back_normalised(self):
        self.client.force_authenticate(self.host)
        resp = self.client.post("/api/economy/battlez/",
                                {"title": "Local only", "gates": {"km": 25}}, format="json")
        self.assertEqual(resp.data["gates"], {"km": [None, 25.0]})


class LeaderboardTests(TestCase):
    """A battle with no leaderboard is just a thread."""

    def setUp(self):
        self.client = APIClient()
        self.host = User.objects.create_user("host", "h@e.com", PW)
        self.battle = Battle.objects.create(host=self.host, title="16 bars")
        self.good = User.objects.create_user("good", "g@e.com", PW)
        self.poor = User.objects.create_user("poor", "p@e.com", PW)
        self.entries = {}
        for who, score in ((self.poor, 3), (self.good, 9)):
            e = BattleEntry.objects.create(battle=self.battle, user=who, title=who.username)
            self.entries[who.username] = e
            judge = User.objects.create_user(f"j{who.username}", f"j{who.username}@e.com", PW)
            ItemRating.objects.create(user=judge, item_id=e.item_key, score=score)
        self.client.force_authenticate(self.host)

    def test_best_judged_first(self):
        entries = self.client.get(f"/api/economy/battlez/{self.battle.pk}/").data["entries"]
        self.assertEqual([e["user"] for e in entries], ["good", "poor"])
        self.assertEqual(entries[0]["rating"], 9)

    def test_the_list_view_carries_the_count_without_the_entries(self):
        row = self.client.get("/api/economy/battlez/").data["battles"][0]
        self.assertEqual(row["entry_count"], 2)
        self.assertNotIn("entries", row)
