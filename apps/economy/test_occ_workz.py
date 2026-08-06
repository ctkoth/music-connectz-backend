"""OCC WorkZ — text and attachments in, work out, in the PostZ format.

The rule being enforced here: an OCC result is not allowed to be a dead end. It
has to be shareable, and once shared it has to be rateable, likeable and
commentable on the SAME surface everything else uses — not a parallel one that
nothing renders.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.models import (
    TIER_FREE,
    TIER_PREMIUM,
    ItemRating,
    OccOutput,
    OccTask,
    Post,
    Reaction,
    SocialComment,
    membership_for,
    wallet_for,
)

User = get_user_model()
PW = "hunter2hunter2"

WORKZ = "/api/economy/occ/workz/"


def as_tier(user, tier):
    m = membership_for(user)
    m.tier = tier
    m.save(update_fields=["tier", "updated_at"])
    return user


class WorkzBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="maker", password=PW)
        as_tier(self.user, TIER_PREMIUM)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def make(self, **kw):
        body = {"title": "Hook idea", "input_text": "write me a hook about rain",
                "description": "Rain on the roof, keep the pocket."}
        body.update(kw)
        resp = self.client.post(WORKZ, body, format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.data


class InputAndOutputTests(WorkzBase):
    """Both halves are kept, and both are shaped like a post."""

    def test_it_keeps_what_went_in_and_what_came_out(self):
        w = self.make(input_items=[{"url": "/u/ref.mp3", "type": "audio",
                                    "title": "reference", "lyrics": ""}])
        self.assertEqual(w["input_text"], "write me a hook about rain")
        self.assertEqual(w["input_items"][0]["url"], "/u/ref.mp3")
        self.assertEqual(w["description"], "Rain on the roof, keep the pocket.")

    def test_the_output_uses_the_postz_field_names_exactly(self):
        # Same names as Post and CollabDeal, so sharing is a copy rather than a
        # translation — three composers accepting three shapes is how they drift.
        w = self.make(media_type="audio", media_url="/u/hook.mp3",
                      image_url="/u/cover.png", lyrics="rain, rain",
                      items=[{"url": "/u/alt.mp3", "type": "audio",
                              "title": "alt take", "lyrics": ""}])
        for field in ("title", "description", "media_type", "media_url",
                      "image_url", "lyrics", "items", "genre", "skills_used"):
            self.assertIn(field, w)
        self.assertEqual(w["media_url"], "/u/hook.mp3")
        self.assertEqual(w["items"][0]["title"], "alt take")

    def test_an_attachment_alone_is_enough(self):
        w = self.make(title="", description="", input_text="",
                      media_type="image", media_url="/u/art.png")
        self.assertTrue(w["title"], "untitled work is unfindable work")

    def test_nothing_at_all_is_refused(self):
        resp = self.client.post(WORKZ, {"title": "", "description": "",
                                        "input_text": ""}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("nothing here", resp.data["detail"])

    def test_the_prompt_answers_to_the_tier_char_limit(self):
        # Member-authored text answers to the tier's limit, never to a column
        # width — the prompt is the member's own writing.
        as_tier(self.user, TIER_FREE)
        resp = self.client.post(WORKZ, {"title": "long one", "input_text": "x" * 500},
                                format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["char_limit"], 400)

    def test_it_can_be_tied_to_the_task_that_made_it(self):
        task = OccTask.objects.create(user=self.user, title="Write the hook")
        w = self.make(task_id=task.id)
        self.assertEqual(w["task_id"], task.id)

    def test_someone_elses_task_is_not_mine_to_attach(self):
        other = User.objects.create_user(username="nosy", password=PW)
        task = OccTask.objects.create(user=other, title="theirs")
        resp = self.client.post(WORKZ, {"title": "t", "task_id": task.id}, format="json")
        self.assertEqual(resp.status_code, 404)

    def test_my_list_is_mine(self):
        self.make()
        other = User.objects.create_user(username="stranger", password=PW)
        OccOutput.objects.create(user=other, title="theirs")
        works = self.client.get(WORKZ).data["works"]
        self.assertEqual(len(works), 1)
        self.assertEqual(works[0]["title"], "Hook idea")

    def test_edit_and_delete(self):
        w = self.make()
        url = f"{WORKZ}{w['id']}/"
        resp = self.client.patch(url, {"description": "second pass"}, format="json")
        self.assertEqual(resp.data["description"], "second pass")
        self.assertEqual(self.client.delete(url).status_code, 200)
        self.assertFalse(OccOutput.objects.filter(pk=w["id"]).exists())


class PriceUpFrontTests(WorkzBase):
    """A price discovered by paying it is not a price, it's a bill."""

    def test_the_share_cost_is_on_the_row_before_the_button(self):
        w = self.make(skill_cost_cents=40)
        self.assertEqual(w["share_cost"], {"resource": "energy", "amount": 40})

    def test_sharing_charges_exactly_what_it_advertised(self):
        wallet = wallet_for(self.user)
        wallet.energy = 100
        wallet.save(update_fields=["energy"])
        w = self.make(skill_cost_cents=40)
        resp = self.client.post(f"{WORKZ}{w['id']}/share/", {}, format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data["energy_charged"], w["share_cost"]["amount"])
        self.assertEqual(wallet_for(self.user).energy, 60)


class ShareTests(WorkzBase):
    """Sharing is what makes it rateable — by making a real post."""

    def test_it_makes_a_real_post_carrying_the_work(self):
        w = self.make(media_type="audio", media_url="/u/hook.mp3", genre="hiphop")
        resp = self.client.post(f"{WORKZ}{w['id']}/share/", {}, format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        post = Post.objects.get(pk=resp.data["post_id"])
        self.assertEqual(post.author, self.user)
        self.assertEqual(post.media_url, "/u/hook.mp3")
        self.assertEqual(post.genre, "hiphop")
        self.assertTrue(resp.data["shared"])

    def test_the_image_and_the_script_survive_the_copy(self):
        # A post has one media slot; the image and the lyrics ride as album
        # entries rather than being dropped on the way over.
        w = self.make(media_type="audio", media_url="/u/hook.mp3",
                      image_url="/u/cover.png", lyrics="rain, rain")
        resp = self.client.post(f"{WORKZ}{w['id']}/share/", {}, format="json")
        post = Post.objects.get(pk=resp.data["post_id"])
        urls = [i["url"] for i in post.items]
        lyrics = [i["lyrics"] for i in post.items]
        self.assertIn("/u/cover.png", urls)
        self.assertIn("rain, rain", lyrics)

    def test_the_post_remembers_it_was_made_in_occ_and_with_what(self):
        w = self.make()
        resp = self.client.post(f"{WORKZ}{w['id']}/share/", {}, format="json")
        post = Post.objects.get(pk=resp.data["post_id"])
        self.assertEqual(post.score["occ"]["work_id"], w["id"])
        self.assertEqual(post.score["occ"]["input"], "write me a hook about rain")

    def test_sharing_goes_through_the_composers_own_rules(self):
        # Media counts against the tier's daily submission cap, exactly as it
        # would if the member had posted it by hand.
        as_tier(self.user, TIER_FREE)
        for _ in range(5):
            w = self.make(media_type="audio", media_url="/u/x.mp3")
            self.assertEqual(
                self.client.post(f"{WORKZ}{w['id']}/share/", {}, format="json").status_code,
                201)
        w = self.make(media_type="audio", media_url="/u/x.mp3")
        resp = self.client.post(f"{WORKZ}{w['id']}/share/", {}, format="json")
        self.assertEqual(resp.status_code, 429)

    def test_it_cannot_be_shared_twice(self):
        w = self.make()
        self.client.post(f"{WORKZ}{w['id']}/share/", {}, format="json")
        again = self.client.post(f"{WORKZ}{w['id']}/share/", {}, format="json")
        self.assertEqual(again.status_code, 409)
        self.assertEqual(Post.objects.count(), 1)

    def test_visibility_is_the_members_call(self):
        w = self.make()
        resp = self.client.post(f"{WORKZ}{w['id']}/share/",
                                {"visibility": "restricted"}, format="json")
        self.assertEqual(Post.objects.get(pk=resp.data["post_id"]).visibility, "restricted")

    def test_unsharing_lets_go_of_the_post_without_deleting_it(self):
        w = self.make()
        post_id = self.client.post(f"{WORKZ}{w['id']}/share/", {}, format="json").data["post_id"]
        resp = self.client.post(f"{WORKZ}{w['id']}/unshare/", {}, format="json")
        self.assertEqual(resp.data["unlinked_post"], post_id)
        self.assertFalse(resp.data["shared"])
        # Retracting something others may have rated is a separate decision,
        # made where the ratings are visible.
        self.assertTrue(Post.objects.filter(pk=post_id).exists())

    def test_deleting_the_work_leaves_the_post_up(self):
        w = self.make()
        post_id = self.client.post(f"{WORKZ}{w['id']}/share/", {}, format="json").data["post_id"]
        resp = self.client.delete(f"{WORKZ}{w['id']}/")
        self.assertEqual(resp.data["post_id"], post_id)
        self.assertTrue(Post.objects.filter(pk=post_id).exists())


class RatedWhereItLivesTests(WorkzBase):
    """One item space. Rating, likes and comments are not reimplemented here."""

    def test_unshared_work_has_no_item_key(self):
        # An item key nobody can reach collects nothing, and a rating count on
        # a screen the data can never fill is the exact bug this app keeps
        # having to fix.
        w = self.make()
        self.assertIsNone(w["item_key"])
        self.assertIsNone(w["rating"])

    def test_once_shared_it_is_rated_liked_and_commented_as_a_post(self):
        w = self.make()
        share = self.client.post(f"{WORKZ}{w['id']}/share/", {}, format="json")
        item = share.data["item_key"]
        self.assertEqual(item, f"post:{share.data['post_id']}")

        fan = User.objects.create_user(username="fan", password=PW)
        c = APIClient()
        c.force_authenticate(fan)
        self.assertEqual(
            c.post("/api/economy/social/react/", {"item": item, "value": 1},
                   format="json").status_code, 200)
        self.assertEqual(
            c.post("/api/economy/social/react/", {"item": item, "value": -1},
                   format="json").status_code, 200)
        # The unlock windows apply here too — a shared OCC output is a post, so
        # nobody comments on it before they've had time to watch it.
        early = c.post("/api/economy/social/comment/", {"item": item, "body": "this slaps"},
                       format="json")
        self.assertEqual(early.status_code, 403)
        Post.objects.filter(pk=share.data["post_id"]).update(
            created_at=timezone.now() - timedelta(minutes=5))
        c.post("/api/economy/social/comment/", {"item": item, "body": "this slaps"},
               format="json")
        ItemRating.objects.create(user=fan, item_id=item, score=9)

        self.assertEqual(Reaction.objects.filter(item_id=item).count(), 1)
        self.assertEqual(SocialComment.objects.filter(item_id=item).count(), 1)
        row = self.client.get(f"{WORKZ}{w['id']}/").data
        self.assertEqual(row["rating"], 9)

    def test_the_shared_work_appears_in_the_feed(self):
        w = self.make()
        self.client.post(f"{WORKZ}{w['id']}/share/", {}, format="json")
        fan = User.objects.create_user(username="listener", password=PW)
        c = APIClient()
        c.force_authenticate(fan)
        titles = [p["title"] for p in c.get("/api/economy/postz/").data["posts"]]
        self.assertIn("Hook idea", titles)


class NotADeadEndTests(WorkzBase):
    """Everything must cross-pollinate."""

    def test_every_row_says_where_it_can_go(self):
        w = self.make(media_type="audio", media_url="/u/hook.mp3")
        keys = {t["key"] for t in w["send_to"]}
        self.assertIn("postz", keys)
        self.assertIn("collabz", keys)
        self.assertIn("distributez", keys)   # audio routes to DistributeZ
        self.assertEqual(w["open_in"], "distributez")

    def test_text_only_work_routes_to_writez_not_a_media_library(self):
        w = self.make()
        self.assertEqual(w["export_route"], "document")
        self.assertEqual(w["open_in"], "writez")

    def test_an_image_routes_to_imagez_even_with_no_media_type(self):
        w = self.make(image_url="/u/art.png")
        self.assertEqual(w["open_in"], "imagez")

    def test_a_target_that_needs_a_share_says_so_and_fills_in_after(self):
        w = self.make()
        collabz = next(t for t in w["send_to"] if t["key"] == "collabz")
        self.assertTrue(collabz["needs_share"])
        self.assertFalse(collabz["target"])

        share = self.client.post(f"{WORKZ}{w['id']}/share/", {}, format="json")
        collabz = next(t for t in share.data["send_to"] if t["key"] == "collabz")
        self.assertEqual(collabz["from_post"], share.data["post_id"])
        self.assertEqual(collabz["target"], f"post-{share.data['post_id']}")

    def test_the_post_leads_back_to_the_work_that_made_it(self):
        w = self.make()
        post_id = self.client.post(f"{WORKZ}{w['id']}/share/", {}, format="json").data["post_id"]
        resp = self.client.get(f"/api/economy/postz/{post_id}/occ/")
        self.assertEqual(resp.data["work"]["id"], w["id"])
        self.assertEqual(resp.data["open_in"], "occ")

    def test_someone_else_learns_it_was_made_in_occ_but_not_my_prompt(self):
        w = self.make()
        post_id = self.client.post(f"{WORKZ}{w['id']}/share/", {}, format="json").data["post_id"]
        c = APIClient()
        c.force_authenticate(User.objects.create_user(username="reader", password=PW))
        resp = c.get(f"/api/economy/postz/{post_id}/occ/")
        self.assertEqual(resp.data["work"]["made_in"], "occ")
        self.assertNotIn("input_text", resp.data["work"])

    def test_a_post_with_no_occ_behind_it_says_so_plainly(self):
        post = Post.objects.create(author=self.user, title="hand-made")
        self.assertIsNone(self.client.get(f"/api/economy/postz/{post.id}/occ/").data["work"])


class CollabHandoffTests(WorkzBase):
    """PostZ is for show, CollabZ is for collaboration — the handoff works."""

    def test_shared_occ_work_can_start_a_collab(self):
        User.objects.create_user(username="partner", password=PW)
        w = self.make(media_type="audio", media_url="/u/hook.mp3")
        post_id = self.client.post(f"{WORKZ}{w['id']}/share/", {}, format="json").data["post_id"]
        resp = self.client.post("/api/economy/collab/", {
            "from_post": post_id, "currency": "spinaz",
            "participants": [{"username": "partner", "worth_cents": 0}],
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data["source_post"]["id"], post_id)
