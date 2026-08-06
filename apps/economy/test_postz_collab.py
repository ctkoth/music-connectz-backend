"""PostZ → CollabZ. PostZ is for show; CollabZ is for collaboration.

The seam between them is the move from "I heard it" to "let's make something".
Without it a member who wants to work on a track they just heard has to leave
the post, open CollabZ, and retype the thing they were looking at — which is
exactly the dead end the cross-pollination rule exists to prevent.

It runs both ways: a deal points back at the post it grew out of, and a post
knows how many deals came from it.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import CollabDeal, Notification, Post

User = get_user_model()
PW = "hunter2hunter2"


class HandoffTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.author = User.objects.create_user("author", "a@e.com", PW)
        self.fan = User.objects.create_user("fan", "f@e.com", PW)
        self.post = Post.objects.create(author=self.author, title="Midnight", visibility="public")
        self.client.force_authenticate(self.fan)

    def start(self, **over):
        payload = {"currency": "spinaz", "from_post": self.post.pk, **over}
        return self.client.post("/api/economy/collab/", payload, format="json")

    def test_one_call_turns_a_post_into_a_deal(self):
        resp = self.start()
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(CollabDeal.objects.get().source_post_id, self.post.pk)

    def test_the_title_is_seeded_from_the_post(self):
        # Nobody should have to retype the thing they were just looking at.
        self.assertEqual(self.start().data["title"], "Collab on 'Midnight'")

    def test_an_explicit_title_still_wins(self):
        self.assertEqual(self.start(title="Remix pack").data["title"], "Remix pack")

    def test_both_people_are_in_the_room_by_definition(self):
        names = {p["username"] for p in self.start().data["participants"]}
        self.assertEqual(names, {"author", "fan"})

    def test_naming_them_explicitly_does_not_duplicate_anyone(self):
        resp = self.start(participants=[{"username": "author", "worth_cents": 5000},
                                        {"username": "fan", "worth_cents": 2000}])
        names = [p["username"] for p in resp.data["participants"]]
        self.assertEqual(sorted(names), ["author", "fan"])
        self.assertEqual(len(names), len(set(names)))

    def test_extra_collaborators_can_be_added_alongside(self):
        User.objects.create_user("third", "t@e.com", PW)
        names = {p["username"] for p in
                 self.start(participants=[{"username": "third", "worth_cents": 0}]).data["participants"]}
        self.assertEqual(names, {"author", "fan", "third"})

    def test_the_author_is_told_somebody_wants_to_work_on_it(self):
        self.start()
        note = Notification.objects.filter(user=self.author).first()
        self.assertIsNotNone(note)
        self.assertIn("Midnight", note.text)
        self.assertIn("@fan", note.text)

    def test_starting_a_collab_on_your_own_post_does_not_notify_you(self):
        self.client.force_authenticate(self.author)
        self.start(participants=[{"username": "fan", "worth_cents": 0}])
        self.assertFalse(Notification.objects.filter(user=self.author).exists())

    def test_you_cannot_start_one_from_a_post_you_cannot_view(self):
        self.post.visibility = "private"
        self.post.save(update_fields=["visibility"])
        resp = self.start()
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertFalse(CollabDeal.objects.exists())

    def test_a_missing_post_is_refused_not_500(self):
        self.assertEqual(self.start(from_post=999999).status_code, 400)

    def test_a_plain_deal_with_no_post_still_works(self):
        resp = self.client.post("/api/economy/collab/", {
            "title": "Unrelated", "currency": "spinaz",
            "participants": [{"username": "fan", "worth_cents": 0},
                             {"username": "author", "worth_cents": 0}],
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertIsNone(resp.data["source_post"])


class BackReferenceTests(TestCase):
    """A deal that can't point back at its post is a dead end in the direction
    people actually travel."""

    def setUp(self):
        self.client = APIClient()
        self.author = User.objects.create_user("author", "a@e.com", PW)
        self.fan = User.objects.create_user("fan", "f@e.com", PW)
        self.post = Post.objects.create(author=self.author, title="Midnight", visibility="public")
        self.client.force_authenticate(self.fan)
        self.deal_id = self.client.post("/api/economy/collab/", {
            "currency": "spinaz", "from_post": self.post.pk}, format="json").data["id"]

    def test_the_deal_carries_the_post_it_grew_out_of(self):
        src = self.client.get(f"/api/economy/collab/{self.deal_id}/").data["source_post"]
        self.assertEqual(src["id"], self.post.pk)
        self.assertEqual(src["title"], "Midnight")
        self.assertEqual(src["author"], "author")
        self.assertEqual(src["open_in"], "social:post")
        self.assertEqual(src["url"], f"/p/{self.post.pk}")

    def test_a_members_only_post_gets_no_public_link(self):
        self.post.visibility = "restricted"
        self.post.save(update_fields=["visibility"])
        src = self.client.get(f"/api/economy/collab/{self.deal_id}/").data["source_post"]
        self.assertEqual(src["url"], "")

    def test_deleting_the_showcase_does_not_delete_the_deal(self):
        # Money is escrowed against it.
        self.post.delete()
        resp = self.client.get(f"/api/economy/collab/{self.deal_id}/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIsNone(resp.data["source_post"])


class PostSideTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.author = User.objects.create_user("author", "a@e.com", PW)
        self.fan = User.objects.create_user("fan", "f@e.com", PW)
        self.post = Post.objects.create(author=self.author, title="Midnight", visibility="public")
        self.client.force_authenticate(self.fan)

    def start(self):
        return self.client.post("/api/economy/collab/",
                                {"currency": "spinaz", "from_post": self.post.pk},
                                format="json")

    def test_the_post_counts_what_came_out_of_it(self):
        self.start()
        self.start()
        row = self.client.get("/api/economy/postz/").data["posts"][0]
        self.assertEqual(row["collab_count"], 2)
        self.assertEqual(row["open_in"], "collabz")

    def test_a_post_nobody_built_on_counts_zero(self):
        self.assertEqual(self.client.get("/api/economy/postz/").data["posts"][0]["collab_count"], 0)

    def test_the_count_is_a_door_not_a_statistic(self):
        deal_id = self.start().data["id"]
        resp = self.client.get(f"/api/economy/postz/{self.post.pk}/collabs/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual([d["id"] for d in resp.data["deals"]], [deal_id])
        self.assertEqual(resp.data["post"], "Midnight")

    def test_somebody_elses_draft_is_not_on_display(self):
        # A draft is private working-out until it is funded.
        self.start()
        self.client.force_authenticate(User.objects.create_user("nosy", "n@e.com", PW))
        self.assertEqual(self.client.get(f"/api/economy/postz/{self.post.pk}/collabs/").data["deals"], [])

    def test_but_the_people_in_it_can_see_it(self):
        self.start()
        for who in (self.author, self.fan):
            self.client.force_authenticate(who)
            self.assertEqual(len(self.client.get(
                f"/api/economy/postz/{self.post.pk}/collabs/").data["deals"]), 1)

    def test_a_post_you_cannot_view_gives_up_nothing(self):
        self.post.visibility = "private"
        self.post.save(update_fields=["visibility"])
        self.assertEqual(self.client.get(
            f"/api/economy/postz/{self.post.pk}/collabs/").status_code, 404)

    def test_the_feed_counts_deals_in_one_query_not_one_per_card(self):
        """The collab count must not scale with the feed.

        Asserted as a DIFFERENCE rather than a magic total: the feed already
        does two per-card queries (shares, rating median) that predate this
        change and aren't mine to fix here. What matters is that adding five
        more posts adds two queries each and not three.
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        self.start()

        with CaptureQueriesContext(connection) as one_card:
            self.client.get("/api/economy/postz/")
        for i in range(5):
            Post.objects.create(author=self.author, title=f"T{i}", visibility="public")
        with CaptureQueriesContext(connection) as six_cards:
            self.client.get("/api/economy/postz/")

        self.assertEqual(len(six_cards) - len(one_card), 10)   # 5 more cards x 2
        collab_counts = [q for q in six_cards.captured_queries
                         if "economy_collabdeal" in q["sql"]]
        self.assertEqual(len(collab_counts), 1)
