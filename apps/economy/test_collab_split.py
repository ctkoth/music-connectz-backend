"""CollabZ: the work, the door, and the rating-based split.

Three things asked for together, because they're the same feature:

* a deal carries the WORK in the PostZ format — otherwise it's a settlement
  about something nobody in it can hear;
* the five exclusive ranges decide who may be ON the deal, not just what the
  listing says;
* the pot can be re-cut by what the community judged each person contributed.

The split answers three questions in code rather than in a doc:
  WHOSE rating — each contributor's rating ON THIS WORK, not their fame.
  WHEN — frozen at release; a share that changes after you agreed isn't a deal.
  WHAT STOPS FARMING — nobody on the deal may rate it, and below a real number
  of outside raters it falls back to the agreed worth.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import (
    RATING_SPLIT_MIN_RATERS,
    AttractivenessRating,
    CollabDeal,
    ItemRating,
    OverallRating,
    Post,
    contributor_item_key,
    profile_for,
    wallet_for,
)

User = get_user_model()
PW = "hunter2hunter2"


def rate_contributor(rater, deal_id, username, score):
    return ItemRating.objects.create(
        user=rater, item_id=contributor_item_key(deal_id, username), score=score)


class DealCarriesTheWorkTests(TestCase):
    """A deal that can't hold the track is a settlement about nothing."""

    def setUp(self):
        self.client = APIClient()
        self.me = User.objects.create_user("me", "me@e.com", PW)
        User.objects.create_user("mate", "m@e.com", PW)
        self.client.force_authenticate(self.me)

    def create(self, **over):
        return self.client.post("/api/economy/collab/", {
            "title": "EP", "currency": "spinaz",
            "participants": [{"username": "me", "worth_cents": 100},
                             {"username": "mate", "worth_cents": 100}],
            **over,
        }, format="json")

    def test_the_postz_format_survives_the_round_trip(self):
        resp = self.create(description="Rough cut.", media_type="audio",
                           media_url="https://x.test/a.mp3",
                           image_url="https://x.test/cover.jpg",
                           lyrics="verse one\nverse two")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["description"], "Rough cut.")
        self.assertEqual(resp.data["media_type"], "audio")
        self.assertEqual(resp.data["media_url"], "https://x.test/a.mp3")
        self.assertEqual(resp.data["image_url"], "https://x.test/cover.jpg")
        self.assertIn("verse two", resp.data["lyrics"])

    def test_an_album_of_items_is_sanitized_the_way_postz_does_it(self):
        resp = self.create(items=[
            {"url": "https://x.test/1.mp3", "type": "audio", "title": "One", "lyrics": "la"},
            "not a dict",
        ])
        self.assertEqual(len(resp.data["items"]), 1)
        self.assertEqual(resp.data["items"][0]["title"], "One")

    def test_a_deal_with_no_media_is_still_perfectly_valid(self):
        self.assertEqual(self.create().status_code, 201)


class DealGatesAreEnforcedTests(TestCase):
    """Storing gates and checking nothing made 'CollabZ carries the range gates'
    a label rather than a rule."""

    def setUp(self):
        self.client = APIClient()
        self.me = User.objects.create_user("me", "me@e.com", PW)
        self.weak = User.objects.create_user("weak", "w@e.com", PW)
        self.strong = User.objects.create_user("strong", "s@e.com", PW)
        judge = User.objects.create_user("judge", "j@e.com", PW)
        OverallRating.objects.create(rater=judge, target=self.strong, score=9)
        OverallRating.objects.create(rater=judge, target=self.me, score=9)
        OverallRating.objects.create(rater=judge, target=self.weak, score=2)
        self.client.force_authenticate(self.me)

    def create(self, other, gates):
        return self.client.post("/api/economy/collab/", {
            "title": "EP", "currency": "spinaz", "gates": gates,
            "participants": [{"username": "me", "worth_cents": 100},
                             {"username": other, "worth_cents": 100}],
        }, format="json")

    def test_somebody_outside_the_range_cannot_be_put_on_the_deal(self):
        resp = self.create("weak", {"rating": [6, 10]})
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertEqual(resp.data["gate"], "rating")
        self.assertEqual(resp.data["username"], "weak")
        self.assertIn("skill rating", resp.data["detail"])
        self.assertFalse(CollabDeal.objects.exists())

    def test_somebody_inside_it_can(self):
        self.assertEqual(self.create("strong", {"rating": [6, 10]}).status_code, 201)

    def test_gates_are_exclusive_here_too(self):
        User.objects.create_user("unrated", "u@e.com", PW)
        resp = self.create("unrated", {"rating": [1, 10]})
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_an_ungated_deal_asks_nobody_for_anything(self):
        User.objects.create_user("anyone", "a@e.com", PW)
        self.assertEqual(self.create("anyone", {}).status_code, 201)


class RatingSplitTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.a = User.objects.create_user("alpha", "a@e.com", PW)
        self.b = User.objects.create_user("beta", "b@e.com", PW)
        self.client.force_authenticate(self.a)
        self.deal = CollabDeal.objects.create(
            initiator=self.a, title="EP", currency=CollabDeal.CURRENCY_SPINAZ,
            status=CollabDeal.STATUS_FUNDED, split_mode=CollabDeal.SPLIT_RATING,
            held_spinaz=1000,
            participants=[
                {"username": "alpha", "worth_cents": 0, "pays_cents": 0,
                 "receives_cents": 500, "funded": True, "stake_paid": 0},
                {"username": "beta", "worth_cents": 0, "pays_cents": 0,
                 "receives_cents": 500, "funded": True, "stake_paid": 0},
            ])

    def outsiders(self, n):
        return [User.objects.create_user(f"j{i}", f"j{i}@e.com", PW) for i in range(n)]

    def release(self):
        from apps.economy.collab import release_deal
        return release_deal(self.deal)

    def test_the_pot_follows_the_ratings(self):
        for j in self.outsiders(RATING_SPLIT_MIN_RATERS):
            rate_contributor(j, self.deal.id, "alpha", 9)
            rate_contributor(j, self.deal.id, "beta", 3)
        deal = self.release()
        got = {p["username"]: p["receives_cents"] for p in deal.participants}
        self.assertGreater(got["alpha"], got["beta"])
        self.assertEqual(got["alpha"] + got["beta"], 1000)   # exact, to the cent

    def test_it_is_frozen_and_explains_itself(self):
        for j in self.outsiders(RATING_SPLIT_MIN_RATERS):
            rate_contributor(j, self.deal.id, "alpha", 8)
            rate_contributor(j, self.deal.id, "beta", 4)
        snap = self.release().split_snapshot
        self.assertTrue(snap["applied"])
        self.assertEqual(snap["raters"], RATING_SPLIT_MIN_RATERS)
        self.assertEqual(snap["ratings"]["alpha"], 8)
        self.assertIn("before", snap)
        self.assertIn("after", snap)
        self.assertIn("at", snap)

    def test_too_few_raters_falls_back_to_the_agreed_worth_and_says_why(self):
        # Two opinions are not a mandate to move somebody's money.
        for j in self.outsiders(RATING_SPLIT_MIN_RATERS - 1):
            rate_contributor(j, self.deal.id, "alpha", 10)
        deal = self.release()
        got = {p["username"]: p["receives_cents"] for p in deal.participants}
        self.assertEqual(got, {"alpha": 500, "beta": 500})
        self.assertFalse(deal.split_snapshot["applied"])
        self.assertIn(str(RATING_SPLIT_MIN_RATERS), deal.split_snapshot["reason"])

    def test_ratings_from_inside_the_deal_do_not_count(self):
        rate_contributor(self.b, self.deal.id, "beta", 10)
        for j in self.outsiders(RATING_SPLIT_MIN_RATERS - 1):
            rate_contributor(j, self.deal.id, "beta", 10)
        # Only MIN-1 raters actually count, so it falls back.
        self.assertFalse(self.release().split_snapshot["applied"])

    def test_a_member_of_the_deal_is_refused_at_the_rating_endpoint(self):
        self.client.force_authenticate(self.b)
        resp = self.client.post("/api/economy/social/rate/", {
            "item": contributor_item_key(self.deal.id, "alpha"),
            "action": "rate", "score": 1,
        }, format="json")
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertIn("can't rate its contributors", resp.data["detail"])

    def test_an_outsider_may_rate(self):
        self.client.force_authenticate(self.outsiders(1)[0])
        resp = self.client.post("/api/economy/social/rate/", {
            "item": contributor_item_key(self.deal.id, "alpha"),
            "action": "rate", "score": 8,
        }, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_an_unrated_contributor_gets_nothing_from_a_rated_split(self):
        for j in self.outsiders(RATING_SPLIT_MIN_RATERS):
            rate_contributor(j, self.deal.id, "alpha", 7)
        got = {p["username"]: p["receives_cents"] for p in self.release().participants}
        self.assertEqual(got["alpha"], 1000)
        self.assertEqual(got["beta"], 0)

    def test_a_worth_deal_is_never_re_cut(self):
        self.deal.split_mode = CollabDeal.SPLIT_WORTH
        self.deal.save(update_fields=["split_mode"])
        for j in self.outsiders(RATING_SPLIT_MIN_RATERS):
            rate_contributor(j, self.deal.id, "alpha", 10)
            rate_contributor(j, self.deal.id, "beta", 1)
        got = {p["username"]: p["receives_cents"] for p in self.release().participants}
        self.assertEqual(got, {"alpha": 500, "beta": 500})

    def test_the_money_actually_lands_that_way(self):
        for j in self.outsiders(RATING_SPLIT_MIN_RATERS):
            rate_contributor(j, self.deal.id, "alpha", 9)
            rate_contributor(j, self.deal.id, "beta", 3)
        self.release()
        self.assertEqual(wallet_for(self.a).spinaz + wallet_for(self.b).spinaz, 1000)
        self.assertGreater(wallet_for(self.a).spinaz, wallet_for(self.b).spinaz)

    def test_the_client_is_told_where_to_rate_and_what_it_takes(self):
        self.client.force_authenticate(self.a)
        data = self.client.get(f"/api/economy/collab/{self.deal.pk}/").data
        self.assertEqual(data["split_mode"], "rating")
        self.assertEqual(data["rating_min_raters"], RATING_SPLIT_MIN_RATERS)
        self.assertEqual(data["rating_keys"]["alpha"],
                         contributor_item_key(self.deal.id, "alpha"))
