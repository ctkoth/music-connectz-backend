"""The coach's read, posted WITH a song and carrying its own visibility.

A member wants a stranger on Reddit or TikTok to hear the song and see the
score on the same page — and on other days wants the score kept for members, or
for nobody. These tests hold the two things that make that safe:

* **Nothing leaks.** Every serializer that hands a post to somebody is walked
  against a viewer matrix, and a viewer the read was refused gets none of it:
  not the verdict, not the notes, not the overall number, not a link preview
  with the score in its title.
* **Nothing is forged.** The read on a post is copied from a ScoreShare the
  coach minted for that same member, by token. A body that carries a number, a
  verdict or a whole payload is ignored.
"""
import io

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.economy.coachshare import (LOCKED_FOR_MEMBERS, coach_read_for,
                                     stored_read)
from apps.economy.models import (Post, ScoreShare, membership_for,
                                 mint_score_share, profile_for, wallet_for)

User = get_user_model()
PW = "hunter2hunter2"
POSTZ = "/api/economy/postz/"

# Words that exist in exactly one place — the stored read. If any of them shows
# up in a response, that response carried read content.
SENTINELS = ("Quartz-bright", "Zinnia-clean", "Mulberry breath", "Saffron sustained",
             "Cobalt-room", "Marigold hook")

READ = {
    "score": 9,
    "scores": {"pitch": 8, "tone": 7, "breath": 5, "range": 6, "agility": 7,
               "style_match": 8},
    "verdict": "Quartz-bright hook that lands. Breath runs out on the last bar.",
    "strengths": ["Zinnia-clean entry on the second verse."],
    "fixes": ["Mulberry breath marks needed before bar twelve."],
    "next_drill": "Saffron sustained exhale drill.",
    "now": "Cobalt-room warmth in the low notes.", "goal": "Hold the top phrase.",
    "song_score": 8, "song_why": "Marigold hook sticks after one listen.",
    "rated_lyrics": False, "rated_mix": False, "unscorable": "",
    # Plumbing the coach response carries and the share row must not keep.
    "cost_cents": 5, "share_url": "/s/abc", "claim_token": "tok",
}


def leaked(text):
    return [w for w in SENTINELS if w in text]


class Base(TestCase):
    def setUp(self):
        self.author = User.objects.create_user("author", "a@e.com", PW)
        self.member = User.objects.create_user("member", "m@e.com", PW)
        self.credit = User.objects.create_user("credit", "c@e.com", PW)
        self.boss = User.objects.create_user("boss", "b@e.com", PW,
                                             is_staff=True, is_superuser=True)
        for u in (self.author, self.member, self.credit, self.boss):
            membership_for(u)
            wallet_for(u)
        self.ac = self.client_for(self.author)
        self.mc = self.client_for(self.member)
        self.anon = APIClient()

    @staticmethod
    def client_for(user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def share(self, user=None, payload=None, app_key="singz"):
        """A ScoreShare exactly as the coach mints it."""
        user = user or self.author
        return mint_score_share(app_key, payload or READ, user=user, genre="Trap")

    def read_on(self, author=None, **extra):
        """A read as it sits on a post after the member attached it."""
        return {**{k: v for k, v in READ.items()
                   if k not in ("cost_cents", "share_url", "claim_token")},
                "app_key": "singz", "coached_by": (author or self.author).username,
                "coached_at": "2026-01-02T03:04:05+00:00", "source": "share", **extra}

    def post(self, vis="public", cv="", read=True, **kw):
        return Post.objects.create(
            author=self.author, title="Night Drive", description="A first take.",
            genre="Trap", visibility=vis, score_visibility=cv,
            score=self.read_on() if read else {}, **kw)


# --------------------------------------------------------------------------
# The one function
# --------------------------------------------------------------------------

# viewer -> post visibility -> read setting -> state. Written out by hand so
# the table is a statement of the rule rather than a second copy of the code.
EXPECT = {
    "author": {v: {cv: "shown" for cv in ("", "members", "private")}
               for v in ("public", "restricted", "private")},
    "member": {
        "public": {"": "shown", "members": "shown", "private": "none"},
        "restricted": {"": "shown", "members": "shown", "private": "none"},
        "private": {"": "none", "members": "none", "private": "none"},
    },
    "anon": {
        "public": {"": "shown", "members": "locked", "private": "none"},
        "restricted": {"": "none", "members": "none", "private": "none"},
        "private": {"": "none", "members": "none", "private": "none"},
    },
}


class CoachReadForTests(Base):
    def viewer(self, who):
        return {"author": self.author, "member": self.member, "anon": None}[who]

    def test_the_whole_matrix(self):
        for who, by_vis in EXPECT.items():
            for vis, by_cv in by_vis.items():
                for cv, want in by_cv.items():
                    p = self.post(vis=vis, cv=cv)
                    got = coach_read_for(p, self.viewer(who))["state"]
                    self.assertEqual(got, want, f"{who} on a {vis} post, read={cv!r}")

    def test_no_read_is_none_for_everybody_including_the_author(self):
        p = self.post(read=False)
        for who in ("author", "member", "anon"):
            self.assertEqual(coach_read_for(p, self.viewer(who))["state"], "none")

    def test_the_locked_card_says_why_in_the_founders_words_and_carries_no_read(self):
        c = coach_read_for(self.post(cv="members"), None)
        self.assertEqual(c["state"], "locked")
        self.assertEqual(c["reason"], "The coach's read on this song is for members. "
                                      "It's free to join.")
        self.assertEqual(c["reason"], LOCKED_FOR_MEMBERS)
        self.assertNotIn("read", c)
        self.assertNotIn("score", c)
        self.assertFalse(leaked(repr(c)))
        # Enough to offer the stranger their own free take, nothing of the score.
        self.assertEqual(c["get_yours"]["path"], "/try/singz?ref=author")

    def test_private_is_not_even_locked_nobody_is_told_a_read_exists(self):
        self.assertEqual(coach_read_for(self.post(cv="private"), self.member), {"state": "none"})
        self.assertEqual(coach_read_for(self.post(cv="private"), None), {"state": "none"})

    def test_only_the_author_is_told_the_setting(self):
        p = self.post(cv="members")
        self.assertEqual(coach_read_for(p, self.author)["visibility"], "members")
        self.assertNotIn("visibility", coach_read_for(p, self.member))
        self.assertNotIn("visibility", coach_read_for(p, None))
        # Even with no read, the author sees their own setting.
        self.assertEqual(coach_read_for(self.post(cv="private", read=False),
                                        self.author)["visibility"], "private")

    def test_a_credited_contributor_sees_the_post_but_not_a_private_read(self):
        p = self.post(vis="public", cv="private", contributors=[{"username": "credit"}])
        self.assertEqual(coach_read_for(p, self.credit)["state"], "none")
        # ...and a private POST is the author's whatever the setting says.
        q = self.post(vis="private", cv="", contributors=[{"username": "credit"}])
        self.assertEqual(coach_read_for(q, self.credit)["state"], "none")

    def test_whoever_ran_the_coach_keeps_seeing_their_own_answer(self):
        p = self.post(vis="public", cv="private", contributors=[{"username": "credit"}])
        p.score = self.read_on(author=self.credit)
        self.assertEqual(coach_read_for(p, self.credit)["state"], "shown")
        self.assertEqual(coach_read_for(p, self.member)["state"], "none")

    def test_a_read_is_only_served_with_labels(self):
        read = coach_read_for(self.post(), self.member)["read"]
        self.assertEqual(read["labels"]["pitch"], "Pitch 🎯")
        self.assertEqual(read["labels"]["song_score"], "Song 🎶")
        self.assertEqual(set(read["scores"]), set(read["labels"]) - {"song_score"})
        # The caveat travels with the number.
        self.assertIn("what one take can show", read["caveat"])

    def test_a_dimension_the_server_cannot_name_is_dropped_not_shown_bare(self):
        p = self.post()
        p.score = self.read_on(scores={"pitch": 8, "made_up_axis": 3})
        read = coach_read_for(p, self.member)["read"]
        self.assertEqual(read["scores"], {"pitch": 8})
        self.assertNotIn("made_up_axis", read["labels"])

    def test_rated_lyrics_brings_its_own_labels(self):
        p = self.post()
        p.score = self.read_on(rated_lyrics=True, scores={"pitch": 8, "rhyme": 7})
        read = coach_read_for(p, self.member)["read"]
        self.assertIn("rhyme", read["scores"])
        self.assertTrue(read["labels"]["rhyme"])

    def test_it_costs_no_query(self):
        p = self.post()
        p.author   # noqa: B018 — loaded, as the feed has it
        with CaptureQueriesContext(connection) as q:
            for who in ("author", "member", "anon"):
                coach_read_for(p, self.viewer(who))
        self.assertEqual(len(q), 0)


class WhatCountsAsAReadTests(Base):
    def test_a_bare_score_is_not_a_coach_read(self):
        # The shape a client could POST before this file: no provenance.
        p = self.post(read=False)
        p.score = {"score": 10, "verdict": "perfect", "app_key": "singz"}
        self.assertIsNone(stored_read(p))
        self.assertEqual(coach_read_for(p, self.member)["state"], "none")

    def test_the_coaches_own_save_to_post_counts(self):
        # vocalcoach._save_to_post writes coached_by, never source.
        p = self.post(read=False)
        p.score = {**self.read_on(), "source": None}
        p.score.pop("source")
        self.assertIsNotNone(stored_read(p))

    def test_an_instrument_the_server_cannot_label_is_not_a_read(self):
        p = self.post()
        p.score = self.read_on(app_key="notacoach")
        self.assertIsNone(stored_read(p))

    def test_occ_provenance_is_not_a_read_and_is_still_served_as_before(self):
        p = self.post(read=False)
        p.score = {"occ": {"work_id": 4, "tab": "occ", "input": "a hook about rain"}}
        p.save()
        self.assertEqual(coach_read_for(p, self.member)["state"], "none")
        row = next(x for x in self.mc.get(POSTZ).data["posts"] if x["id"] == p.id)
        self.assertEqual(row["score"]["occ"]["work_id"], 4)
        self.assertEqual(row["coach"]["state"], "none")


# --------------------------------------------------------------------------
# Every serializer, every viewer
# --------------------------------------------------------------------------

class EverySerializerTests(Base):
    """Walk every place a post is handed to someone, against the matrix."""

    def clients(self):
        return {"author": self.ac, "member": self.mc, "anon": self.anon}

    def check_dict(self, d, want, where):
        """A post dict, whatever route it came from, obeys the state it was refused/shown."""
        coach = d["coach"]
        self.assertEqual(coach["state"], want, where)
        if want == "shown":
            self.assertEqual(coach["read"]["score"], 9, where)
            self.assertEqual(d["score"]["score"], 9, where)        # legacy key, same content
        else:
            self.assertNotIn("read", coach, where)
            self.assertEqual(d["score"], {}, f"{where}: legacy score key must be empty")
            self.assertFalse(leaked(repr(d)), f"{where}: read content in the dict")

    def test_the_feed_the_mine_filter_and_discovery(self):
        for vis in ("public", "restricted", "private"):
            for cv in ("", "members", "private"):
                p = self.post(vis=vis, cv=cv)
                for who in ("author", "member"):
                    want = EXPECT[who][vis][cv]
                    c = self.clients()[who]
                    for url in (POSTZ, f"{POSTZ}?sort=new", f"{POSTZ}discover/?genre=Trap"):
                        r = c.get(url)
                        self.assertEqual(r.status_code, 200)
                        if want != "shown":
                            self.assertFalse(leaked(r.content.decode()),
                                             f"{who} {vis}/{cv} {url}")
                        row = next((x for x in r.data["posts"] if x["id"] == p.id), None)
                        if row is None:
                            continue
                        self.check_dict(row, want, f"feed {url} {who} {vis}/{cv}")
                        if who == "author":
                            self.assertEqual(row["coach"]["visibility"], cv)
                        else:
                            self.assertNotIn("visibility", row["coach"])
                    if who == "author" and vis != "private":
                        r = c.get(f"{POSTZ}?mine=1")
                        row = next(x for x in r.data["posts"] if x["id"] == p.id)
                        self.check_dict(row, "shown", f"mine {vis}/{cv}")
                p.delete()

    def test_the_feed_never_carries_read_content_for_a_viewer_who_was_refused(self):
        for vis in ("public", "restricted"):
            for cv in ("private",):
                self.post(vis=vis, cv=cv)
        body = self.mc.get(POSTZ).content.decode()
        self.assertFalse(leaked(body))

    def test_the_public_page_json_under_both_of_its_mounts(self):
        for vis in ("public", "restricted", "private"):
            for cv in ("", "members", "private"):
                p = self.post(vis=vis, cv=cv)
                for who, c in self.clients().items():
                    viewable = (vis == "public" or (vis == "restricted" and who != "anon")
                                or (vis == "private" and who == "author"))
                    for url in (f"/api/postz/{p.id}/", f"{POSTZ}{p.id}/"):
                        r = c.get(url)
                        where = f"{url} {who} {vis}/{cv}"
                        if not viewable:
                            # 404, not 403, and nothing in it.
                            self.assertEqual(r.status_code, 404, where)
                            self.assertFalse(leaked(r.content.decode()), where)
                            continue
                        self.assertEqual(r.status_code, 200, where)
                        self.check_dict(r.data, EXPECT[who][vis][cv], where)
                        if EXPECT[who][vis][cv] != "shown":
                            self.assertFalse(leaked(r.content.decode()), where)
                        # Never cached for the next reader: the body depends on who asked.
                        self.assertIn("private", r["Cache-Control"])
                        self.assertIn("Authorization", r["Vary"])
                p.delete()

    def test_the_public_page_names_a_card_image_only_when_a_stranger_could_fetch_it(self):
        p = self.post(vis="public", cv="")
        d = self.anon.get(f"/api/postz/{p.id}/").data["coach"]
        self.assertEqual(d["card_image"], f"/api/economy/postz/{p.id}/coach-card.png")
        self.assertTrue(d["story_image"].endswith("?format=story"))
        p.score_visibility = "members"
        p.save()
        d = self.mc.get(f"/api/postz/{p.id}/").data["coach"]
        self.assertEqual(d["state"], "shown")
        self.assertNotIn("card_image", d)
        self.assertFalse(d["public"])

    def test_the_coach_endpoint_itself(self):
        for vis in ("public", "restricted", "private"):
            for cv in ("", "members", "private"):
                p = self.post(vis=vis, cv=cv)
                for who, c in self.clients().items():
                    r = c.get(f"{POSTZ}{p.id}/coach/")
                    if r.status_code == 404:
                        # Post not visible to them at all.
                        self.assertFalse(leaked(r.content.decode()))
                        continue
                    self.assertEqual(r.data["state"], EXPECT[who][vis][cv], f"{who} {vis}/{cv}")
                    if r.data["state"] != "shown":
                        self.assertFalse(leaked(r.content.decode()))
                p.delete()

    def test_the_coach_endpoint_says_who_can_open_the_post(self):
        p = self.post(vis="restricted", cv="")
        self.assertEqual(self.ac.get(f"{POSTZ}{p.id}/coach/").data["post_visibility"], "restricted")
        # A viewer who cannot open the post learns nothing, not even that it exists.
        q = self.post(vis="private", cv="")
        r = self.mc.get(f"{POSTZ}{q.id}/coach/")
        self.assertEqual(r.status_code, 404)
        self.assertNotIn("post_visibility", r.content.decode())

    def test_link_preview_html(self):
        for vis in ("public", "restricted", "private"):
            for cv in ("", "members", "private"):
                p = self.post(vis=vis, cv=cv)
                r = self.anon.get(f"/api/economy/share/p/{p.id}")
                want = EXPECT["anon"][vis][cv]
                if vis != "public":
                    self.assertEqual(r.status_code, 404)
                    p.delete()
                    continue
                body = r.content.decode()
                self.assertEqual(r.status_code, 200)
                if want == "shown":
                    self.assertIn("Night Drive — 9/10 from the Music ConnectZ coach", body)
                    self.assertIn('property="og:description" content="Quartz-bright hook that lands."', body)
                    self.assertIn(f"/api/economy/postz/{p.id}/coach-card.png", body)
                    self.assertNotIn("og-card.png", body)
                else:
                    self.assertFalse(leaked(body))
                    self.assertNotIn("/10", body)
                    self.assertNotIn("from the Music ConnectZ coach", body)
                    self.assertIn("og-card.png", body)
                    self.assertNotIn("coach-card.png", body)
                p.delete()

    def test_card_image_follows_the_same_rule_and_the_setting_takes_it_down_at_once(self):
        p = self.post(vis="public", cv="")
        r = self.anon.get(f"{POSTZ}{p.id}/coach-card.png")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/png")
        self.assertEqual(self.size(r.content), (1200, 630))
        story = self.anon.get(f"{POSTZ}{p.id}/coach-card.png?format=story")
        self.assertEqual(self.size(story.content), (1080, 1920))
        for cv in ("members", "private"):
            p.score_visibility = cv
            p.save()
            self.assertEqual(self.anon.get(f"{POSTZ}{p.id}/coach-card.png").status_code, 404, cv)
            self.assertEqual(self.mc.get(f"{POSTZ}{p.id}/coach-card.png").status_code, 404, cv)
        q = self.post(vis="restricted", cv="")
        self.assertEqual(self.anon.get(f"{POSTZ}{q.id}/coach-card.png").status_code, 404)

    @staticmethod
    def size(png):
        from PIL import Image
        return Image.open(io.BytesIO(png)).size

    def test_the_story_variant_exists_for_a_share_row_too(self):
        tok = self.share()
        self.assertEqual(self.size(self.anon.get(f"/api/economy/scores/{tok}/card.png").content),
                         (1200, 630))
        self.assertEqual(self.size(
            self.anon.get(f"/api/economy/scores/{tok}/card.png?format=story").content),
            (1080, 1920))

    def test_create_and_edit_responses(self):
        # The author's own response carries their view...
        r = self.ac.post(POSTZ, {"title": "T", "coach_token": self.share(),
                                 "score_visibility": "members"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["coach"]["state"], "shown")
        self.assertEqual(r.data["coach"]["visibility"], "members")
        # ...and the platform owner editing somebody else's post gets the
        # viewer's view, not the author's: a member's.
        p = self.post(vis="public", cv="private")
        r = self.client_for(self.boss).post(POSTZ, {"edit_id": p.id, "title": "fixed"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["coach"]["state"], "none")
        self.assertEqual(r.data["score"], {})
        self.assertFalse(leaked(r.content.decode()))

    def test_a_post_that_came_out_of_a_deal_is_the_same_serializer(self):
        # collab_post returns _post_dict as well; the walk above is the proof,
        # this pins that nothing there builds its own dict from Post.score.
        import inspect

        from apps.economy import collab_post
        src = inspect.getsource(collab_post)
        self.assertNotIn(".score", src.replace("score=", ""))


# --------------------------------------------------------------------------
# Attaching, removing, changing
# --------------------------------------------------------------------------

class AttachTests(Base):
    def attach(self, post, token, vis=None, client=None, **extra):
        body = {"share_token": token, **extra}
        if vis is not None:
            body["score_visibility"] = vis
        return (client or self.ac).post(f"{POSTZ}{post.id}/coach/", body, format="json")

    def bare(self, vis="public"):
        return Post.objects.create(author=self.author, title="Night Drive", visibility=vis)

    def test_the_author_attaches_one_of_their_own_reads(self):
        p, tok = self.bare(), self.share()
        r = self.attach(p, tok, "members")
        self.assertEqual(r.status_code, 200, r.data)
        p.refresh_from_db()
        self.assertEqual(p.score["score"], 9)
        self.assertEqual(p.score["verdict"], READ["verdict"])
        self.assertEqual(p.score["app_key"], "singz")
        self.assertEqual(p.score["source"], "share")
        self.assertEqual(p.score["coached_by"], "author")
        self.assertEqual(p.score["share_token"], tok)
        self.assertEqual(p.score_visibility, "members")
        self.assertEqual(r.data["coach"]["state"], "shown")
        self.assertEqual(r.data["coach"]["visibility"], "members")

    def test_the_plumbing_the_share_row_dropped_never_reaches_the_post(self):
        p = self.bare()
        self.attach(p, self.share())
        p.refresh_from_db()
        for k in ("cost_cents", "share_url", "claim_token"):
            self.assertNotIn(k, p.score)

    def test_a_body_cannot_supply_the_read(self):
        # The only thing the client chooses is WHICH of its own reads.
        p, tok = self.bare(), self.share()
        r = self.attach(p, tok, score=10, verdict="Perfect, flawless, 10/10",
                        payload={"score": 10, "verdict": "forged"},
                        scores={"pitch": 10}, strengths=["forged"])
        self.assertEqual(r.status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.score["score"], 9)
        self.assertEqual(p.score["verdict"], READ["verdict"])
        self.assertNotIn("forged", repr(p.score))

    def test_someone_elses_token_is_refused_and_says_so(self):
        p = self.bare()
        theirs = self.share(user=self.member)
        r = self.attach(p, theirs)
        self.assertEqual(r.status_code, 400)
        self.assertIn("isn't one of yours", r.data["detail"])
        p.refresh_from_db()
        self.assertEqual(p.score, {})

    def test_a_token_that_does_not_exist_gets_the_same_sentence(self):
        # Telling "no such token" from "not yours" would let a member probe which exist.
        p = self.bare()
        a = self.attach(p, "nope").data["detail"]
        b = self.attach(p, self.share(user=self.member)).data["detail"]
        self.assertEqual(a, b)

    def test_a_trial_take_has_nobody_to_attach_it_to(self):
        tok = mint_score_share("singz", READ)             # user=None
        r = self.attach(self.bare(), tok)
        self.assertEqual(r.status_code, 400)

    def test_a_share_row_from_before_reads_were_kept_is_refused_with_a_next_move(self):
        tok = self.share()
        ScoreShare.objects.filter(token=tok).update(payload={})
        r = self.attach(self.bare(), tok)
        self.assertEqual(r.status_code, 400)
        self.assertIn("Run the take through the coach once more", r.data["detail"])

    def test_no_token_is_a_sentence_not_a_500(self):
        r = self.ac.post(f"{POSTZ}{self.bare().id}/coach/", {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Choose which coach read", r.data["detail"])

    def test_junk_visibility_is_refused_never_defaulted_to_the_widest(self):
        p, tok = self.bare(), self.share()
        for junk in ("public", "everyone", "MEMBERS-ONLY", 3, "none"):
            r = self.attach(p, tok, junk)
            self.assertEqual(r.status_code, 400, junk)
            self.assertIn("Choose who sees the coach's read", r.data["detail"])
        p.refresh_from_db()
        self.assertEqual((p.score, p.score_visibility), ({}, ""))

    def test_the_value_is_forgiving_about_case_and_space_only(self):
        p = self.bare()
        self.assertEqual(self.attach(p, self.share(), " Members ").status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.score_visibility, "members")

    def test_only_the_author_attaches(self):
        p = self.bare()
        r = self.attach(p, self.share(user=self.member), client=self.mc)
        self.assertEqual(r.status_code, 403)
        # Not even the platform owner: it is the author's score to put on the song.
        r = self.attach(p, self.share(user=self.boss), client=self.client_for(self.boss))
        self.assertEqual(r.status_code, 403)

    def test_a_post_you_cannot_see_is_a_404_not_a_403(self):
        p = self.bare(vis="private")
        r = self.attach(p, self.share(user=self.member), client=self.mc)
        self.assertEqual(r.status_code, 404)

    def test_anonymous_cannot_write(self):
        p = self.bare()
        self.assertEqual(self.anon.post(f"{POSTZ}{p.id}/coach/",
                                        {"share_token": "x"}, format="json").status_code, 401)
        self.assertEqual(self.anon.delete(f"{POSTZ}{p.id}/coach/").status_code, 401)

    def test_the_spec_path_is_the_same_view(self):
        p = self.bare()
        r = self.ac.post(f"/api/economy/posts/{p.id}/coach/",
                         {"share_token": self.share()}, format="json")
        self.assertEqual(r.status_code, 200)

    def test_attaching_costs_nothing(self):
        p = self.bare()
        before = wallet_for(self.author)
        e, s, pr = before.energy, before.spinaz, before.promptz
        self.attach(p, self.share())
        w = wallet_for(self.author)
        self.assertEqual((w.energy, w.spinaz, w.promptz), (e, s, pr))

    def test_attaching_again_replaces_the_read_and_keeps_occ_provenance(self):
        p = self.bare()
        p.score = {"occ": {"work_id": 1}}
        p.save()
        self.attach(p, self.share(payload={**READ, "score": 4}))
        self.attach(p, self.share())
        p.refresh_from_db()
        self.assertEqual(p.score["score"], 9)
        self.assertEqual(p.score["occ"]["work_id"], 1)

    def test_remove_takes_the_read_off_and_keeps_the_setting(self):
        p = self.bare()
        self.attach(p, self.share(), "private")
        r = self.ac.delete(f"{POSTZ}{p.id}/coach/")
        self.assertEqual(r.status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.score, {})
        # The next read on this post should not arrive wider than the last one.
        self.assertEqual(p.score_visibility, "private")
        self.assertEqual(r.data["coach"], {"state": "none", "visibility": "private"})

    def test_only_the_author_removes(self):
        p = self.post()
        self.assertEqual(self.mc.delete(f"{POSTZ}{p.id}/coach/").status_code, 403)
        self.assertEqual(self.client_for(self.boss).delete(f"{POSTZ}{p.id}/coach/").status_code, 403)
        p.refresh_from_db()
        self.assertEqual(p.score["score"], 9)


class CreateWithReadTests(Base):
    def make(self, **body):
        return self.ac.post(POSTZ, {"title": "Night Drive", "visibility": "public", **body},
                            format="json")

    def test_a_song_and_its_read_in_one_step(self):
        r = self.make(coach_token=self.share(), score_visibility="members")
        self.assertEqual(r.status_code, 201, r.data)
        p = Post.objects.get(pk=r.data["id"])
        self.assertEqual((p.score["score"], p.score_visibility), (9, "members"))
        self.assertEqual(p.score["source"], "share")
        self.assertEqual(r.data["coach"]["state"], "shown")

    def test_someone_elses_token_refuses_the_whole_post_and_charges_nothing(self):
        w = wallet_for(self.author)
        w.energy = 100
        w.save()
        p = profile_for(self.author)
        p.personas = [{"key": "singer", "name": "Singer",
                       "skills": [{"name": "Vocals", "rate_cents": 40}]}]
        p.save()
        n = Post.objects.count()
        r = self.make(coach_token=self.share(user=self.member), skills_used=["Vocals"])
        self.assertEqual(r.status_code, 400)
        self.assertIn("isn't one of yours", r.data["detail"])
        self.assertEqual(Post.objects.count(), n)
        self.assertEqual(wallet_for(self.author).energy, 100)

    def test_the_read_adds_nothing_to_the_price(self):
        w = wallet_for(self.author)
        w.energy = 100
        w.save()
        p = profile_for(self.author)
        p.personas = [{"key": "singer", "name": "Singer",
                       "skills": [{"name": "Vocals", "rate_cents": 40}]}]
        p.save()
        plain = self.make(skills_used=["Vocals"])
        with_read = self.make(skills_used=["Vocals"], coach_token=self.share())
        self.assertEqual(plain.status_code, 201)
        self.assertEqual(with_read.status_code, 201)
        self.assertEqual(plain.data["energy_charged"], with_read.data["energy_charged"])
        self.assertEqual(wallet_for(self.author).energy, 100 - 2 * plain.data["energy_charged"])

    def test_a_score_in_the_body_is_never_a_coach_read(self):
        r = self.make(score={"score": 10, "verdict": "Quartz-bright forged", "app_key": "singz",
                             "coached_by": "author", "source": "share"})
        self.assertEqual(r.status_code, 201)
        p = Post.objects.get(pk=r.data["id"])
        self.assertEqual(p.score, {})
        self.assertEqual(r.data["coach"]["state"], "none")
        self.assertEqual(self.mc.get(f"{POSTZ}{p.id}/coach/").data["state"], "none")

    def test_junk_visibility_refuses_the_post(self):
        n = Post.objects.count()
        r = self.make(score_visibility="world")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Post.objects.count(), n)

    def test_a_visibility_without_a_read_is_kept_for_the_read_that_comes_later(self):
        r = self.make(score_visibility="private")
        self.assertEqual(r.status_code, 201)
        p = Post.objects.get(pk=r.data["id"])
        self.assertEqual(p.score_visibility, "private")
        self.assertEqual(r.data["coach"], {"state": "none", "visibility": "private"})


class EditVisibilityTests(Base):
    def edit(self, post, client=None, **body):
        return (client or self.ac).post(POSTZ, {"edit_id": post.id, **body}, format="json")

    def test_the_author_changes_who_sees_the_read(self):
        p = self.post(cv="")
        r = self.edit(p, score_visibility="members")
        self.assertEqual(r.status_code, 200, r.data)
        p.refresh_from_db()
        self.assertEqual(p.score_visibility, "members")
        self.assertEqual(r.data["coach"]["visibility"], "members")
        # And a stranger now meets the locked card.
        self.assertEqual(self.anon.get(f"/api/postz/{p.id}/").data["coach"]["state"], "locked")

    def test_going_to_only_me_hides_it_from_members_at_once(self):
        p = self.post(cv="")
        self.edit(p, score_visibility="private")
        self.assertEqual(self.mc.get(f"{POSTZ}{p.id}/coach/").data["state"], "none")
        self.assertFalse(leaked(self.mc.get(POSTZ).content.decode()))

    def test_it_is_not_held_to_the_edit_window(self):
        from datetime import timedelta

        from django.utils import timezone
        p = self.post()
        Post.objects.filter(pk=p.pk).update(created_at=timezone.now() - timedelta(days=400))
        self.assertEqual(self.edit(p, score_visibility="members").status_code, 200)

    def test_it_travels_with_a_post_visibility_change(self):
        p = self.post(vis="private", cv="")
        r = self.edit(p, visibility="public", score_visibility="members")
        self.assertEqual(r.status_code, 200, r.data)
        p.refresh_from_db()
        self.assertEqual((p.visibility, p.score_visibility), ("public", "members"))

    def test_the_platform_owner_cannot_change_it_on_somebody_elses_post(self):
        p = self.post(cv="private")
        r = self.edit(p, client=self.client_for(self.boss), score_visibility="")
        self.assertEqual(r.status_code, 403)
        p.refresh_from_db()
        self.assertEqual(p.score_visibility, "private")

    def test_junk_is_refused(self):
        p = self.post(cv="members")
        for junk in ("public", "", None, "all"):
            r = self.edit(p, score_visibility=junk)
            if junk == "":
                self.assertEqual(r.status_code, 200)       # "" is a real choice: same as the post
                p.refresh_from_db()
                self.assertEqual(p.score_visibility, "")
                p.score_visibility = "members"
                p.save()
            else:
                self.assertEqual(r.status_code, 400, junk)
        p.refresh_from_db()
        self.assertEqual(p.score_visibility, "members")


# --------------------------------------------------------------------------
# The legacy path: coaching your own post
# --------------------------------------------------------------------------

class SaveToPostTests(Base):
    def test_a_read_the_coach_wrote_onto_the_post_follows_the_setting_that_was_already_there(self):
        from apps.economy.vocalcoach import SingZCoachView
        p = self.post(read=False, cv="private")
        SingZCoachView._save_to_post(p, self.author, {k: v for k, v in READ.items()
                                                      if k not in ("cost_cents", "share_url", "claim_token")},
                                     "singz")
        p.refresh_from_db()
        self.assertEqual(coach_read_for(p, self.author)["state"], "shown")
        self.assertEqual(coach_read_for(p, self.member)["state"], "none")

    def test_with_no_setting_it_is_exactly_what_it_was_before_this_existed(self):
        from apps.economy.vocalcoach import SingZCoachView
        p = self.post(read=False)
        SingZCoachView._save_to_post(p, self.author, {k: v for k, v in READ.items()
                                                      if k not in ("cost_cents", "share_url", "claim_token")},
                                     "singz")
        p.refresh_from_db()
        self.assertEqual(coach_read_for(p, self.member)["state"], "shown")
        self.assertEqual(coach_read_for(p, None)["state"], "shown")


# --------------------------------------------------------------------------
# The feed stays flat
# --------------------------------------------------------------------------

class FeedCostTests(Base):
    def test_five_more_coached_cards_cost_no_more_queries(self):
        # Warm up: the first feed read creates wallets and rolls the daily counter.
        self.mc.get(POSTZ)
        self.post(cv="members")
        with CaptureQueriesContext(connection) as one:
            self.mc.get(POSTZ)
        for _ in range(5):
            self.post(cv="")
        with CaptureQueriesContext(connection) as six:
            self.mc.get(POSTZ)
        self.assertEqual(len(six) - len(one), 0,
                         "a coach read on every card must not put a query on any of them")

    def test_and_the_author_reading_their_own_feed(self):
        self.ac.get(POSTZ)
        self.post(cv="private")
        with CaptureQueriesContext(connection) as one:
            self.ac.get(POSTZ)
        for _ in range(5):
            self.post(cv="members")
        with CaptureQueriesContext(connection) as six:
            self.ac.get(POSTZ)
        self.assertEqual(len(six) - len(one), 0)
