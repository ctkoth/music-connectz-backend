from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.catalog import BATTLE_CALLOUT_ENERGY
from apps.economy.models import Battle, ChallengeFilter, Post, Wallet, wallet_for

User = get_user_model()
CH = "/api/economy/battlez/challenge/"
FILTERS = "/api/economy/battlez/challengez/filters/"
INBOX = "/api/economy/battlez/challengez/"


def client(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


class CalloutFilterTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_user("me", "me@x.com", "pw12345678")
        self.foe = User.objects.create_user("foe", "foe@x.com", "pw12345678")
        Wallet.objects.update_or_create(user=self.me, defaults={"energy": 50})
        self.c = client(self.me)
        self.f = client(self.foe)
        self.post = Post.objects.create(author=self.foe, title="verse", genre="Trap")

    def energy(self):
        return wallet_for(self.me).energy

    def test_challenge_from_a_post_aims_at_its_author_and_remembers_it(self):
        r = self.c.post(CH, {"post_id": self.post.id}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        b = Battle.objects.get(pk=r.data["id"])
        self.assertEqual(b.opponent_id, self.foe.id)
        self.assertEqual(b.source_item, f"post:{self.post.id}")
        self.assertEqual(b.genre, "Trap")
        self.assertEqual(b.status, Battle.STATUS_PENDING)

    def test_challenging_your_own_post_is_refused(self):
        mine = Post.objects.create(author=self.me, title="mine")
        r = self.c.post(CH, {"post_id": mine.id}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_missing_post_is_404(self):
        self.assertEqual(self.c.post(CH, {"post_id": 999999}, format="json").status_code, 404)

    def test_no_filter_row_means_open_to_everybody(self):
        self.assertEqual(self.c.post(CH, {"opponent": "foe"}, format="json").status_code, 201)

    def test_genre_filter_refuses_free_and_says_why(self):
        self.f.put(FILTERS, {"genres": ["Drill"]}, format="json")
        before = self.energy()
        r = self.c.post(CH, {"opponent": "foe", "genre": "Pop"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data["filtered"], "genre")
        self.assertIn("Drill", r.data["detail"])
        self.assertIn("Nothing was sent or charged", r.data["detail"])
        self.assertEqual(self.energy(), before)
        self.assertFalse(Battle.objects.exists())

    def test_genre_filter_lets_a_matching_genre_through_case_insensitively(self):
        self.f.put(FILTERS, {"genres": ["Drill"]}, format="json")
        r = self.c.post(CH, {"opponent": "foe", "genre": "drill"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)

    def test_paused_and_muted_look_the_same_to_the_challenger(self):
        self.f.put(FILTERS, {"paused": True}, format="json")
        a = self.c.post(CH, {"opponent": "foe"}, format="json")
        self.f.put(FILTERS, {"muted": ["me"]}, format="json")
        b = self.c.post(CH, {"opponent": "foe"}, format="json")
        self.assertEqual((a.status_code, b.status_code), (403, 403))
        self.assertEqual(a.data["detail"], b.data["detail"])
        self.assertNotIn("mute", b.data["detail"].lower())

    def test_range_filter_applies_to_the_challenger(self):
        self.f.put(FILTERS, {"gates": {"rating": [9, 10]}}, format="json")
        r = self.c.post(CH, {"opponent": "foe"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data["filtered"], "range")

    def test_auto_accept_opens_the_battle_at_once(self):
        self.f.put(FILTERS, {"auto_accept": True}, format="json")
        r = self.c.post(CH, {"opponent": "foe"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        b = Battle.objects.get(pk=r.data["id"])
        self.assertEqual(b.status, Battle.STATUS_OPEN)
        self.assertIsNotNone(b.ends_at)
        self.assertEqual(self.energy(), 50 - BATTLE_CALLOUT_ENERGY)

    def test_auto_accept_never_overrides_a_filter(self):
        self.f.put(FILTERS, {"auto_accept": True, "genres": ["Drill"]}, format="json")
        r = self.c.post(CH, {"opponent": "foe", "genre": "Pop"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Battle.objects.exists())

    def test_paused_defender_does_not_auto_accept_even_with_the_flag_set(self):
        self.f.put(FILTERS, {"auto_accept": True, "paused": True}, format="json")
        self.assertEqual(self.c.post(CH, {"opponent": "foe"}, format="json").status_code, 403)

    def test_manual_accept_still_works_and_still_refunds_on_decline(self):
        r = self.c.post(CH, {"opponent": "foe"}, format="json")
        self.f.post(f"/api/economy/battlez/{r.data['id']}/respond/", {"accept": False}, format="json")
        self.assertEqual(self.energy(), 50)
        r2 = self.c.post(CH, {"opponent": "foe"}, format="json")
        self.f.post(f"/api/economy/battlez/{r2.data['id']}/respond/", {"accept": True}, format="json")
        self.assertEqual(Battle.objects.get(pk=r2.data["id"]).status, Battle.STATUS_OPEN)


class FilterEndpointTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_user("me", "me@x.com", "pw12345678")
        User.objects.create_user("pal", "pal@x.com", "pw12345678")
        self.c = client(self.me)

    def test_get_with_no_row_is_the_open_default(self):
        d = self.c.get(FILTERS).data
        self.assertEqual(d, {"paused": False, "genres": [], "gates": {}, "muted": [], "auto_accept": False})
        self.assertFalse(ChallengeFilter.objects.exists())

    def test_put_replaces_everything_and_round_trips(self):
        self.c.put(FILTERS, {"genres": ["Trap", "trap", " Drill "], "muted": ["@pal", "nobody", "me"],
                             "auto_accept": True}, format="json")
        d = self.c.get(FILTERS).data
        self.assertEqual(d["genres"], ["Trap", "Drill"])
        self.assertEqual(d["muted"], ["pal"])
        self.assertTrue(d["auto_accept"])
        self.c.put(FILTERS, {}, format="json")
        self.assertEqual(self.c.get(FILTERS).data["genres"], [])

    def test_requires_login(self):
        self.assertIn(APIClient().get(FILTERS).status_code, (401, 403))


class InboxTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_user("me", "me@x.com", "pw12345678")
        self.foe = User.objects.create_user("foe", "foe@x.com", "pw12345678")
        Wallet.objects.update_or_create(user=self.me, defaults={"energy": 50})
        Wallet.objects.update_or_create(user=self.foe, defaults={"energy": 50})
        self.post = Post.objects.create(author=self.me, title="mine")

    def test_incoming_and_sent_state_their_costs_up_front(self):
        client(self.foe).post(CH, {"post_id": self.post.id}, format="json")
        mine = client(self.me).get(INBOX).data
        self.assertEqual(len(mine["incoming"]), 1)
        row = mine["incoming"][0]
        self.assertEqual(row["accept_cost"]["amount"], 0)
        self.assertEqual(row["decline_refunds_challenger"]["amount"], BATTLE_CALLOUT_ENERGY)
        self.assertEqual(row["open_in"], {"tab": "postz", "target": f"post:{self.post.id}"})
        theirs = client(self.foe).get(INBOX).data
        self.assertEqual(len(theirs["sent"]), 1)
        self.assertEqual(theirs["incoming"], [])
        self.assertEqual(theirs["callout_cost_energy"], BATTLE_CALLOUT_ENERGY)

    def test_answered_challenges_leave_incoming(self):
        r = client(self.foe).post(CH, {"opponent": "me"}, format="json")
        client(self.me).post(f"/api/economy/battlez/{r.data['id']}/respond/", {"accept": False}, format="json")
        self.assertEqual(client(self.me).get(INBOX).data["incoming"], [])


class SharedInstrumentalTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_user("me", "me@x.com", "pw12345678")
        self.foe = User.objects.create_user("foe", "foe@x.com", "pw12345678")
        Wallet.objects.update_or_create(user=self.me, defaults={"energy": 50})
        self.c, self.f = client(self.me), client(self.foe)

    def test_challenge_carries_one_beat_and_both_sides_enter_their_own_track_over_it(self):
        r = self.c.post(CH, {"opponent": "foe", "instrumental_url": "/m/beat.mp3",
                             "instrumental_title": "Night Drive"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(r.data["same_instrumental"])
        self.assertEqual(r.data["instrumental_title"], "Night Drive")
        self.f.post(f"/api/economy/battlez/{r.data['id']}/respond/", {"accept": True}, format="json")
        e1 = self.c.post(f"/api/economy/battlez/{r.data['id']}/enter/",
                         {"media_url": "/m/me.mp3", "media_type": "audio"}, format="json")
        e2 = self.f.post(f"/api/economy/battlez/{r.data['id']}/enter/",
                         {"media_url": "/m/foe.mp3", "media_type": "audio"}, format="json")
        self.assertEqual((e1.status_code, e2.status_code), (201, 201), (e1.content, e2.content))
        b = self.c.get(f"/api/economy/battlez/{r.data['id']}/").data
        self.assertEqual({e["media_url"] for e in b["entries"]}, {"/m/me.mp3", "/m/foe.mp3"})
        self.assertEqual(b["instrumental_url"], "/m/beat.mp3")
        self.assertIn("scoreboard", b)

    def test_no_instrumental_means_each_side_brings_their_own(self):
        r = self.c.post(CH, {"opponent": "foe"}, format="json")
        self.assertFalse(r.data["same_instrumental"])
