"""A post is not a dead end — it opens in the apps that can do something with it.

Two halves, both tested here:

* the DESTINATION LIST every post carries — which apps it can open in, what
  each one still needs when it can't go, and the price of the ones that cost
  something, stated before anything is spent;
* the IMPROVEMENT DOOR — a post handed to the SingZ / RapZ Boss Take coach,
  which is the whole reason the list exists. A post is a finished take standing
  still; the coach is what turns it into the next one.
"""
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.economy.crosspost import (COACH_APPS, destinations_for, post_take,
                                    take_bytes_for)
from apps.economy.models import (PROMPT_ALLOWANCE, TIER_FREE, TIER_STATZ, Post,
                                 PostContributor, Upload, membership_for,
                                 wallet_for)
from apps.economy.postz import media_slots

User = get_user_model()
PW = "hunter2hunter2"
POSTZ = "/api/economy/postz/"

GOOD = {"score": 7, "scores": {"pitch": 8, "tone": 7, "breath": 5, "range": 6, "agility": 7},
        "verdict": "The hook lands; the last phrase runs out of air.",
        "strengths": ["The first eight bars sit dead centre of pitch."],
        "fixes": ["You're breathing at the bar line — take it a beat earlier."],
        "next_drill": "Sustained 4-count exhale on an ee vowel."}


def fake_gemini(payload=GOOD, status_code=200):
    class R:
        text = '{"error": {"message": "fake"}}'
        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]}
    R.status_code = status_code
    return R()


def find(dests, app):
    return next(d for d in dests if d["app"] == app)


class DestinationListTests(TestCase):
    """What every post row now carries."""

    def setUp(self):
        self.me = User.objects.create_user(username="maker", password=PW)
        self.them = User.objects.create_user(username="rando", password=PW)
        for u in (self.me, self.them):
            membership_for(u)
            w = wallet_for(u); w.money_cents = 100000; w.save()
        self.c = APIClient(); self.c.force_authenticate(self.me)

    def post_with(self, **kw):
        return Post.objects.create(author=kw.pop("author", self.me),
                                   title=kw.pop("title", "She's too Good for me"), **kw)

    def dests(self, p, user=None):
        return destinations_for(p, user or self.me, media_slots(p))

    # ---- the improvement doors ----
    def test_a_post_with_audio_can_be_coached_in_singz_and_rapz(self):
        p = self.post_with(media_type="audio", media_url="/media/uploads/1/take.webm")
        d = self.dests(p)
        for app in COACH_APPS:
            self.assertTrue(find(d, app)["available"], f"{app} should take this post")
            self.assertEqual(find(d, app)["coach_kind"], "audio")

    def test_a_post_with_only_lyrics_says_what_the_coach_needs(self):
        """Not hidden — a member with a lyrics post should learn the coach wants
        a take, not wonder where SingZ went."""
        p = self.post_with(items=[{"type": "text", "lyrics": "verse one"}])
        singz = find(self.dests(p), "singz")
        self.assertFalse(singz["available"])
        self.assertIn("recording", singz["needs"][0])

    def test_video_is_coachable_when_there_is_no_audio(self):
        p = self.post_with(media_type="video", media_url="/media/uploads/1/take.mp4")
        self.assertEqual(find(self.dests(p), "rapz")["coach_kind"], "video")

    def test_audio_wins_over_video_so_the_prompt_buys_the_performance(self):
        p = self.post_with(media_type="video", media_url="/media/uploads/1/clip.mp4",
                           items=[{"type": "audio", "url": "/media/uploads/1/song.ogg"}])
        self.assertEqual(find(self.dests(p), "singz")["coach_kind"], "audio")

    # ---- the ceiling, before the button that would hit it ----
    def stored(self, mb, owner=None):
        """A post whose take is a real stored Upload of `mb` megabytes."""
        owner = owner or self.me
        size = int(mb * 1024 * 1024)
        up = Upload.objects.create(
            user=owner, name="take.webm", size_bytes=size, content_type="audio/webm",
            file=SimpleUploadedFile("take.webm", b"0" * 16, content_type="audio/webm"))
        return self.post_with(author=owner, media_type="audio", media_url=up.file.url)

    def test_a_track_too_big_for_the_coach_says_so_on_the_row(self):
        """The bug this exists to stop: a 29MB post offered the coach door, the
        post travelled, the button went live, and the ceiling announced itself
        by being hit. A refusal discovered by pressing is a bill, not a price."""
        from apps.economy.vocalcoach import MAX_MB
        p = self.stored(MAX_MB + 15)
        d = destinations_for(p, self.me, media_slots(p),
                             take_bytes=take_bytes_for([(p, media_slots(p))]).get(p.id))
        singz = find(d, "singz")
        self.assertFalse(singz["available"])
        need = singz["needs"][0]
        self.assertIn(f"{MAX_MB + 15}MB", need)          # what theirs is
        self.assertIn(f"under {MAX_MB}MB", need)          # what the coach takes
        self.assertIn("not\nyour tier's".replace("\n", " "), need)

    def test_a_track_inside_the_ceiling_still_opens_the_door(self):
        from apps.economy.vocalcoach import MAX_MB
        p = self.stored(MAX_MB - 2)
        d = destinations_for(p, self.me, media_slots(p),
                             take_bytes=take_bytes_for([(p, media_slots(p))]).get(p.id))
        self.assertTrue(find(d, "singz")["available"])

    def test_a_size_nobody_measured_is_not_a_size_over_the_limit(self):
        """A take hosted elsewhere has no stored size. The door stays open —
        claiming a limit you never read is its own kind of lie, and the coach
        still holds the wall."""
        p = self.post_with(media_type="audio", media_url="https://example.com/x.mp3")
        self.assertTrue(find(self.dests(p), "singz")["available"])

    def test_the_size_of_every_take_in_the_feed_is_one_query(self):
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        for _ in range(6):
            self.stored(2)
        rows = [(p, media_slots(p)) for p in Post.objects.all()]   # not measured
        with CaptureQueriesContext(connection) as ctx:
            sizes = take_bytes_for(rows)
        self.assertEqual(len(ctx), 1)
        self.assertEqual(len(sizes), 6)

    def test_the_feed_carries_the_ceiling_so_the_card_can_state_it(self):
        from apps.economy.vocalcoach import MAX_MB
        p = self.stored(MAX_MB + 15)
        row = next(r for r in self.c.get(POSTZ).data["posts"] if r["id"] == p.id)
        singz = find(row["destinations"], "singz")
        self.assertFalse(singz["available"])
        self.assertGreater(singz["take_bytes"], singz["max_bytes"])

    # ---- the price, before it is spent ----
    def test_the_coach_door_quotes_its_price_up_front(self):
        p = self.post_with(media_type="audio", media_url="/media/uploads/1/take.webm")
        cost = find(self.dests(p), "singz")["cost"]
        self.assertEqual(cost["resource"], "promptz")
        self.assertGreater(cost["amount"], 0)
        self.assertFalse(cost["charged_on_failure"])

    def test_a_free_daily_prompt_is_said_rather_than_a_price_nobody_pays(self):
        p = self.post_with(media_type="audio", media_url="/media/uploads/1/take.webm")
        self.assertTrue(find(self.dests(p), "singz")["cost"]["free_today"])
        # Spend the day's allowance and the same door quotes the real price.
        w = wallet_for(self.me)
        w.prompts_used_today = PROMPT_ALLOWANCE[TIER_FREE] + 10
        from django.utils import timezone
        w.prompt_day = timezone.now().strftime("%Y-%m-%d")
        w.save()
        self.assertFalse(find(self.dests(p), "singz")["cost"]["free_today"])

    def test_a_post_with_no_words_has_nothing_for_occ_to_rework(self):
        p = self.post_with(media_type="audio", media_url="/media/uploads/1/take.webm")
        occ = find(self.dests(p), "occ")
        self.assertFalse(occ["available"])
        self.assertIn("words", occ["needs"][0])
        # A description is enough — the hook is usually in the caption.
        p2 = self.post_with(description="verse one, and the hook after it")
        self.assertTrue(find(self.dests(p2), "occ")["available"])

    def test_the_free_doors_say_free(self):
        p = self.post_with(media_type="audio", media_url="/media/uploads/1/take.webm")
        for app in ("collabz", "playlistz", "battlez", "occ", "directz"):
            self.assertEqual(find(self.dests(p), app)["cost"]["amount"], 0)

    # ---- doors that are honestly shut ----
    def test_a_post_kept_out_of_playlists_says_so_rather_than_offering_the_door(self):
        p = self.post_with(allow_in_playlists=False)
        pl = find(self.dests(p), "playlistz")
        self.assertFalse(pl["available"])
        self.assertIn("consent", pl["needs"][0])

    def test_a_release_is_the_authors_to_start(self):
        p = self.post_with(author=self.them, media_type="audio",
                           media_url="/media/uploads/2/take.webm")
        d = find(self.dests(p), "directz")
        self.assertFalse(d["available"])
        self.assertIn("your own post", d["needs"][0])

    def test_a_contributor_may_start_the_release_too(self):
        """A collab post belongs to everyone credited on it."""
        p = self.post_with(author=self.them, media_type="audio",
                           media_url="/media/uploads/2/take.webm",
                           contributors=[{"username": "maker", "slot": "audio"}])
        self.assertTrue(find(self.dests(p), "directz")["available"])

    # ---- what travels with the post ----
    def test_the_post_travels_with_its_work_so_nothing_is_reattached(self):
        p = self.post_with(genre="Drill", description="verse one",
                           media_type="audio", media_url="/media/uploads/1/take.webm",
                           items=[{"type": "text", "lyrics": "the hook"},
                                  {"type": "image", "url": "/media/uploads/1/cover.png"}])
        carry = find(self.dests(p), "battlez")["carry"]
        self.assertEqual(carry["audio_url"], "/media/uploads/1/take.webm")
        self.assertEqual(carry["lyrics"], "the hook")
        self.assertEqual(carry["image_url"], "/media/uploads/1/cover.png")
        self.assertEqual(carry["genre"], "Drill")
        self.assertEqual(carry["post_id"], p.id)

    # ---- served on the API ----
    def test_the_feed_carries_the_destinations_on_every_row(self):
        self.post_with(media_type="audio", media_url="/media/uploads/1/take.webm")
        r = self.c.get(POSTZ)
        self.assertEqual(r.status_code, 200)
        row = r.data["posts"][0]
        self.assertTrue(any(d["app"] == "singz" for d in row["destinations"]))
        # The old single door still answers for anything already reading it.
        self.assertEqual(row["open_in"], "collabz")

    def test_one_post_can_be_asked_where_it_can_go(self):
        p = self.post_with(media_type="audio", media_url="/media/uploads/1/take.webm")
        r = self.c.get(f"{POSTZ}{p.id}/open/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["post_id"], p.id)
        self.assertGreaterEqual(r.data["open_count"], 5)

    def test_you_cannot_ask_where_a_post_you_cannot_see_goes(self):
        p = self.post_with(author=self.them, visibility="private")
        self.assertEqual(self.c.get(f"{POSTZ}{p.id}/open/").status_code, 403)

    def test_pricing_the_feed_does_not_cost_a_wallet_read_per_row(self):
        """Every card offers SingZ and RapZ, and the price of a coached take is
        the same number on all of them — so it is read ONCE for the request.

        Counted as the DIFFERENCE between a short feed and a long one rather
        than as an absolute: the feed has its own per-row queries that predate
        this, and pinning a total here would make an unrelated change to them
        look like a regression in the destination list.
        """
        # One warm-up: the day's prompt counter rolls over on first read and
        # writes once, which would otherwise land in whichever measurement
        # happened to run first.
        self.c.get(POSTZ)

        def queries_for(n):
            Post.objects.all().delete()
            for i in range(n):
                self.post_with(title=f"take {i}", media_type="audio",
                               media_url=f"/media/uploads/1/t{i}.webm")
            with CaptureQueriesContext(connection) as ctx:
                self.assertEqual(len(self.c.get(POSTZ).data["posts"]), n)
            return len(ctx)

        four, twelve = queries_for(4), queries_for(12)
        # Two per post already: the share count and the rating median. Anything
        # more would mean the price is being re-read per card.
        self.assertEqual(twelve - four, 2 * (12 - 4))


class CoachThePostTests(TestCase):
    """The improvement door, end to end: a post sent to the Boss Take coach."""

    def setUp(self):
        self.me = User.objects.create_user(username="maker", password=PW)
        self.them = User.objects.create_user(username="rando", password=PW)
        for u in (self.me, self.them):
            m = membership_for(u); m.tier = TIER_STATZ; m.save()
            w = wallet_for(u); w.money_cents = 100000; w.save()
        self.c = APIClient(); self.c.force_authenticate(self.me)
        self.tc = APIClient(); self.tc.force_authenticate(self.them)

    def stored_post(self, owner=None, ct="audio/webm", **kw):
        owner = owner or self.me
        up = Upload.objects.create(
            user=owner, file=SimpleUploadedFile("take.webm", b"0" * 900, content_type=ct),
            name="take.webm", size_bytes=900, content_type=ct)
        return Post.objects.create(author=owner, title="She's too Good for me",
                                   genre="Drill", media_type="audio",
                                   media_url=up.file.url, **kw), up

    # ---- it scores ----
    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.vocalcoach.requests.post", return_value=fake_gemini())
    def test_a_post_can_be_coached_without_uploading_the_take_again(self, _rq, _k):
        p, _ = self.stored_post()
        r = self.c.post("/api/singz/coach/", {"post_id": p.id}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["score"], 7)
        self.assertEqual(r.data["source"], "post")
        self.assertEqual(r.data["post_id"], p.id)
        # And the way back — the score is not a dead end either.
        self.assertEqual(r.data["open_in"], "postz")

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.vocalcoach.requests.post", return_value=fake_gemini())
    def test_the_posts_genre_seeds_the_coach(self, rq, _k):
        p, _ = self.stored_post()
        self.c.post("/api/singz/coach/", {"post_id": p.id}, format="json")
        sent = rq.call_args.kwargs["json"]["contents"][0]["parts"][0]["text"]
        self.assertIn("Drill", sent)

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.vocalcoach.requests.post", return_value=fake_gemini())
    def test_rapz_scores_the_same_post_on_its_own_dimensions(self, _rq, _k):
        p, _ = self.stored_post()
        r = self.c.post("/api/rapz/coach/", {"post_id": p.id}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn("flow", r.data["scores"])
        self.assertNotIn("pitch", r.data["scores"])

    # ---- it is billed exactly like a recorded take ----
    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.vocalcoach.requests.post", return_value=fake_gemini())
    def test_coaching_a_post_spends_a_prompt_like_any_other_take(self, _rq, _k):
        p, _ = self.stored_post()
        before = wallet_for(self.me).prompts_used_today or 0
        self.c.post("/api/singz/coach/", {"post_id": p.id}, format="json")
        self.assertEqual(wallet_for(self.me).prompts_used_today, before + 1)

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.vocalcoach.requests.post", return_value=fake_gemini(status_code=429))
    def test_a_take_the_coach_could_not_read_is_not_charged(self, _rq, _k):
        p, _ = self.stored_post()
        before = wallet_for(self.me).prompts_used_today or 0
        r = self.c.post("/api/singz/coach/", {"post_id": p.id}, format="json")
        self.assertEqual(r.status_code, 502)
        self.assertEqual(wallet_for(self.me).prompts_used_today or 0, before)

    # ---- the coaching stays with the work ----
    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.vocalcoach.requests.post", return_value=fake_gemini())
    def test_your_own_post_keeps_the_coaching_it_was_given(self, _rq, _k):
        p, _ = self.stored_post()
        r = self.c.post("/api/singz/coach/", {"post_id": p.id}, format="json")
        self.assertTrue(r.data["saved_to_post"])
        p.refresh_from_db()
        self.assertEqual(p.score["score"], 7)
        self.assertEqual(p.score["app_key"], "singz")
        self.assertEqual(p.score["coached_by"], "maker")

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.vocalcoach.requests.post", return_value=fake_gemini())
    def test_coaching_somebody_elses_post_never_writes_on_their_post(self, _rq, _k):
        """You paid for the read, so you get the read. Their post carries their
        name, and a score that appeared on it because a stranger spent a prompt
        is the platform putting words in their mouth."""
        p, _ = self.stored_post(owner=self.them)
        r = self.c.post("/api/singz/coach/", {"post_id": p.id}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(r.data["saved_to_post"])
        p.refresh_from_db()
        self.assertEqual(p.score, {})

    # ---- what it refuses ----
    def test_a_post_you_cannot_view_cannot_be_sent_to_a_model(self):
        p, _ = self.stored_post(owner=self.them, visibility="private")
        r = self.c.post("/api/singz/coach/", {"post_id": p.id}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_a_post_with_no_recording_says_the_coach_needs_one(self):
        p = Post.objects.create(author=self.me, title="lyrics only",
                                items=[{"type": "text", "lyrics": "verse"}])
        r = self.c.post("/api/singz/coach/", {"post_id": p.id}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("no recording", r.data["detail"].lower())

    def test_a_take_hosted_somewhere_else_says_so_rather_than_failing_upstream(self):
        p = Post.objects.create(author=self.me, title="linked", media_type="audio",
                                media_url="https://example.com/someone-elses.mp3")
        r = self.c.post("/api/singz/coach/", {"post_id": p.id}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("isn't stored", r.data["detail"])

    def test_a_posted_track_over_the_coachs_ceiling_says_whose_limit_it_is(self):
        """The post accepted the file and the coach is refusing the same one —
        so the refusal has to name the scorer's ceiling, not the member's tier,
        or a StatZ member reads it as the plan they paid for being ignored."""
        from apps.economy.vocalcoach import MAX_MB
        up = Upload.objects.create(
            user=self.me, name="long.webm", size_bytes=(MAX_MB + 5) * 1024 * 1024,
            content_type="audio/webm",
            file=SimpleUploadedFile("long.webm", b"0" * ((MAX_MB + 5) * 1024 * 1024),
                                    content_type="audio/webm"))
        p = Post.objects.create(author=self.me, title="the whole set",
                                media_type="audio", media_url=up.file.url)
        r = self.c.post("/api/singz/coach/", {"post_id": p.id}, format="json")
        self.assertEqual(r.status_code, 413)
        self.assertFalse(r.data["max_mb_is_tier_limit"])
        self.assertIn("isn't your tier's upload limit", r.data["detail"])

    def test_neither_a_file_nor_a_post_still_asks_for_a_take(self):
        r = self.c.post("/api/singz/coach/", {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Record or attach", r.data["detail"])

    def test_a_post_id_that_is_not_a_number_is_refused_plainly(self):
        r = self.c.post("/api/singz/coach/", {"post_id": "nope"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_a_missing_post_is_a_404_not_a_coaching_failure(self):
        r = self.c.post("/api/singz/coach/", {"post_id": 99999}, format="json")
        self.assertEqual(r.status_code, 404)

    # ---- whose file it is ----
    def test_the_take_is_found_through_the_people_whose_post_it_is(self):
        """The URL comes off the Post row, never from the client — so the file
        is looked up among the author and everyone credited on the post."""
        p, up = self.stored_post(owner=self.them)
        PostContributor.objects.create(post=p, user=self.me, slot="audio")
        found, kind, why = post_take(p, media_slots(p))
        self.assertEqual(why, "")
        self.assertEqual(found.pk, up.pk)
        self.assertEqual(kind, "audio")

    def test_a_file_belonging_to_nobody_on_the_post_is_not_reachable_through_it(self):
        """A post pointing at a stranger's upload resolves to nothing rather
        than reading it."""
        stranger = User.objects.create_user(username="third", password=PW)
        up = Upload.objects.create(
            user=stranger, file=SimpleUploadedFile("secret.webm", b"0" * 10,
                                                   content_type="audio/webm"),
            name="secret.webm", size_bytes=10, content_type="audio/webm")
        p = Post.objects.create(author=self.me, title="borrowed",
                                media_type="audio", media_url=up.file.url)
        found, _kind, why = post_take(p, media_slots(p))
        self.assertIsNone(found)
        self.assertIn("isn't stored", why)
