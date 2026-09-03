"""JournalZ — the properties that make a diary safe to put tagging on.

Four things these are really about:

* **Private means private.** A tag on a private entry notifies nobody, creates
  no JournalMention row, and the entry is unreachable to the person tagged.
  That is the promise the whole app is built around, so it is tested from both
  ends: what the author sees, and what the tagged member can reach.
* **The share is the only door out.** Notifications happen in exactly one place,
  once per person ever, whether the entry was widened by an edit or published
  as a post.
* **Nothing scores an entry.** No rating, no craft number, no quality field —
  the substance rule, pinned so a future "journal score" has to delete a test
  to exist.
* **The price and the gain are stated before the button.** `/cost/` says what
  writing pays before anything is written; `/share/` GET quotes what publishing
  costs and names who it will tell, before it tells them.
"""
import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.models import (JournalEntry, JournalMention, Notification,
                                 Post, TIER_PREMIUM, TIER_STATZ, Upload,
                                 membership_for, wallet_for)

COACHED = {"score": 7, "scores": {"pitch": 8, "tone": 7, "breath": 5, "range": 6,
                                  "agility": 7},
           "verdict": "It lands.", "strengths": ["Centred."], "fixes": ["Breathe."],
           "next_drill": "Sirens, five minutes."}


def fake_gemini(payload=COACHED, status_code=200):
    class R:
        text = '{"error": {"message": "fake"}}'

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]}
    R.status_code = status_code
    return R()

User = get_user_model()
PW = "hunter2hunter2"
LIST = "/api/economy/journalz/"
COST = "/api/economy/journalz/cost/"


class Base(TestCase):
    def setUp(self):
        self.me = User.objects.create_user(username="diarist", password=PW)
        self.them = User.objects.create_user(username="witness", password=PW)
        for u in (self.me, self.them):
            membership_for(u)
            wallet_for(u)
        self.c = APIClient()
        self.c.force_authenticate(self.me)
        self.other = APIClient()
        self.other.force_authenticate(self.them)

    def write(self, **kw):
        body = {"title": "A day", "body": "It rained and I wrote a hook."}
        body.update(kw)
        r = self.c.post(LIST, body, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def premium(self, user=None):
        m = membership_for(user or self.me)
        m.tier = TIER_PREMIUM
        m.save(update_fields=["tier"])


class PrivateMeansPrivateTests(Base):

    def test_tagging_somebody_on_a_private_entry_tells_them_nothing(self):
        d = self.write(people=["witness"], visibility="private")
        self.assertEqual(d["people"], ["witness"])
        self.assertTrue(d["private"])
        self.assertEqual(d["notified"], [])
        self.assertEqual(JournalMention.objects.count(), 0)
        self.assertEqual(Notification.objects.filter(user=self.them).count(), 0)

    def test_a_tagged_member_cannot_read_the_private_entry_they_are_named_in(self):
        d = self.write(people=["witness"])
        r = self.other.get(f"{LIST}{d['id']}/")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.other.get(f"{LIST}?view=tagged").data["entries"], [])

    def test_the_default_visibility_is_private_even_when_nothing_is_asked_for(self):
        """The whole product difference from PostZ, and the one thing a client
        bug must not be able to reverse by omitting a field."""
        self.assertTrue(self.write()["private"])

    def test_coordinates_never_leave_the_author_unless_they_say_exact(self):
        d = self.write(place_name="The Louisiana", place_lat=51.4489, place_lng=-2.5931,
                       people=["witness"], visibility="restricted")
        self.assertEqual(d["place"]["lat"], 51.4489)          # the author sees them
        row = self.other.get(f"{LIST}{d['id']}/").data
        self.assertEqual(row["place"]["name"], "The Louisiana")   # the name travels
        self.assertIsNone(row["place"]["lat"])                    # the pin does not
        self.assertIsNone(row["place"]["lng"])

    def test_exact_is_the_members_own_deliberate_choice(self):
        d = self.write(place_name="The Louisiana", place_lat=51.4489, place_lng=-2.5931,
                       place_exact=True, people=["witness"], visibility="restricted")
        self.assertEqual(self.other.get(f"{LIST}{d['id']}/").data["place"]["lat"], 51.4489)


class TheShareIsTheOnlyDoorOutTests(Base):

    def test_widening_an_entry_notifies_the_people_on_it_once_ever(self):
        d = self.write(people=["witness"])
        self.assertEqual(JournalMention.objects.count(), 0)
        up = self.c.post(LIST, {"entry_id": d["id"], "visibility": "restricted"},
                         format="json").data
        self.assertEqual(up["notified"], ["witness"])
        self.assertEqual(Notification.objects.filter(user=self.them).count(), 1)
        # Toggling back and forth is not a second notification.
        self.c.post(LIST, {"entry_id": d["id"], "visibility": "private"}, format="json")
        again = self.c.post(LIST, {"entry_id": d["id"], "visibility": "restricted"},
                            format="json").data
        self.assertEqual(again["notified"], [])
        self.assertEqual(Notification.objects.filter(user=self.them).count(), 1)

    def test_publishing_makes_a_post_tells_the_people_and_marks_the_entry(self):
        d = self.write(people=["witness"], place_name="The Louisiana")
        r = self.c.post(f"{LIST}{d['id']}/share/", {"visibility": "public"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        post = Post.objects.get(pk=r.data["post_id"])
        self.assertIn("It rained", post.description)
        self.assertIn("📍 The Louisiana", post.description)
        self.assertEqual(r.data["notified"], ["witness"])
        e = JournalEntry.objects.get(pk=d["id"])
        self.assertEqual(e.shared_post_id, post.id)
        self.assertEqual(e.visibility, "public")

    def test_the_quote_names_who_will_be_told_before_anybody_is_told(self):
        d = self.write(people=["witness"])
        q = self.c.get(f"{LIST}{d['id']}/share/").data
        self.assertEqual(q["will_notify"], ["witness"])
        self.assertEqual(q["already_notified"], [])
        self.assertTrue(q["warn"])                       # it is private, and it says so
        self.assertIn("amount", q["cost"])
        self.assertEqual(Notification.objects.filter(user=self.them).count(), 0)

    def test_publishing_twice_is_refused_rather_than_making_a_second_post(self):
        d = self.write()
        self.c.post(f"{LIST}{d['id']}/share/", {"visibility": "public"}, format="json")
        r = self.c.post(f"{LIST}{d['id']}/share/", {"visibility": "public"}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(Post.objects.count(), 1)

    def test_an_entry_shared_with_you_is_readable_and_nothing_more(self):
        """Every door that only the author may walk through says so on the row.
        The server refuses each of them anyway; a button that can only fail is
        the thing this list exists to stop."""
        d = self.write(people=["witness"], body="words and more words")
        self.c.post(f"{LIST}{d['id']}/share/", {"visibility": "restricted"}, format="json")
        row = self.other.get(f"{LIST}{d['id']}/").data
        doors = {x["app"]: x for x in row["destinations"]}
        for app in ("postz", "occ", "singz", "rapz", "messagez"):
            self.assertFalse(doors[app]["available"], f"{app} offered on somebody else's entry")
            self.assertIn("your own entry", " ".join(doors[app]["needs"]))
        # And it really is refused, not merely greyed.
        self.assertEqual(
            self.other.post(f"{LIST}{d['id']}/share/", {"visibility": "public"},
                            format="json").status_code, 404)

    def test_a_shared_entry_reaches_the_tagged_members_own_view(self):
        d = self.write(people=["witness"])
        self.c.post(f"{LIST}{d['id']}/share/", {"visibility": "restricted"}, format="json")
        rows = self.other.get(f"{LIST}?view=tagged").data["entries"]
        self.assertEqual([r["id"] for r in rows], [d["id"]])
        self.assertFalse(rows[0]["mine"])


class NothingScoresAnEntryTests(Base):

    def test_an_entry_carries_no_rating_of_any_kind(self):
        """Substance before the game layer: a diary is the easiest place in the
        app to bolt a fake number onto, so the absence is pinned."""
        d = self.write()
        for banned in ("rating", "score", "quality", "craft", "depth", "stars"):
            self.assertNotIn(banned, d, f"JournalZ grew a {banned} field")

    def test_the_streak_counts_days_and_says_that_is_all_it_is(self):
        today = timezone.localdate()
        for n in (1, 2, 3):
            JournalEntry.objects.create(author=self.me, day=today - timedelta(days=n),
                                        body="x")
        d = self.c.get(LIST).data
        self.assertEqual(d["streak"], 3)
        self.assertEqual(d["days_kept"], 3)
        self.assertIn("Days you turned up", d["streak_note"])

    def test_five_entries_in_one_day_is_one_day_kept(self):
        """A streak somebody can inflate by pressing save is not a streak."""
        self.premium()
        for i in range(4):
            self.write(title=f"entry {i}")
        d = self.c.get(LIST).data
        self.assertEqual(d["entries_kept"], 4)
        self.assertEqual(d["days_kept"], 1)


class WhatWasPlayingTests(Base):
    """A linked track — what was playing while the entry got written."""

    def test_a_link_rides_along_with_an_entry(self):
        d = self.write(link={"url": "https://open.spotify.com/track/x",
                             "label": "That song", "service": "spotify"})
        self.assertEqual(d["link"]["url"], "https://open.spotify.com/track/x")
        self.assertEqual(d["link"]["service"], "spotify")

    def test_a_link_with_no_url_is_dropped(self):
        d = self.write(link={"label": "no url"})
        self.assertEqual(d["link"], {})

    def test_a_link_alone_with_no_title_or_body_is_still_something(self):
        r = self.c.post(LIST, {"title": "", "body": "",
                               "link": {"url": "https://open.spotify.com/track/x"}},
                        format="json")
        self.assertEqual(r.status_code, 201, r.data)

    def test_an_entry_with_truly_nothing_is_still_refused(self):
        r = self.c.post(LIST, {"title": "", "body": ""}, format="json")
        self.assertEqual(r.status_code, 400, r.data)

    def test_editing_replaces_the_link(self):
        d = self.write(link={"url": "https://open.spotify.com/track/x"})
        r = self.c.post(LIST, {"entry_id": d["id"],
                               "link": {"url": "https://soundcloud.com/y", "service": "soundcloud"}},
                        format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["link"]["service"], "soundcloud")


class ThePriceAndTheGainAreStatedFirstTests(Base):

    def test_cost_states_that_writing_is_free_and_what_it_pays(self):
        d = self.c.get(COST).data
        self.assertEqual(d["cost"]["amount"], 0)
        self.assertEqual(d["gain"]["resource"], "energy")
        self.assertGreater(d["gain"]["amount"], 0)
        # A gain is a doorway, not a boast: it says where to claim it.
        self.assertEqual(d["gain"]["app"], "mimez")
        self.assertEqual(d["gain"]["target"], "questz-daily")

    def test_cost_carries_the_tier_room_from_the_server_not_the_client(self):
        d = self.c.get(COST).data
        self.assertEqual(d["limits"]["people"], 3)           # free tier
        self.assertEqual(d["limits"]["char_limit"], 400)
        self.premium()
        d = self.c.get(COST).data
        self.assertEqual(d["limits"]["people"], 10)
        self.assertEqual(d["limits"]["char_limit"], 1500)

    def test_an_entry_is_never_a_dead_end(self):
        d = self.write()
        apps = {x["app"]: x for x in d["destinations"]}
        self.assertIn("postz", apps)
        self.assertIn("occ", apps)
        self.assertTrue(apps["postz"]["available"])
        # A door that can't go says what it is missing rather than vanishing.
        self.assertFalse(apps["singz"]["available"])
        self.assertTrue(apps["singz"]["needs"])
        for door in d["destinations"]:
            self.assertTrue(door["target"], f"{door['app']} lands at the top of a tab")


class TheRoomATierBuysTests(Base):

    def test_the_free_tier_keeps_three_entries_a_day_and_says_so_when_it_stops(self):
        for i in range(3):
            self.write(title=f"e{i}")
        r = self.c.post(LIST, {"title": "one more"}, format="json")
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.data["cap"], 3)
        self.assertIn("MembershipZ", r.data["detail"])

    def test_tags_over_the_cap_are_reported_never_silently_dropped(self):
        d = self.write(tags=["hook", "bristol", "late", "rain", "demo", "sixth", "seventh"])
        self.assertEqual(len(d["tags"]), 5)
        self.assertEqual(d["dropped"]["tags"], ["sixth", "seventh"])

    def test_a_person_who_isnt_a_member_is_named_in_the_answer(self):
        d = self.write(people=["nobody-here"])
        self.assertEqual(d["people"], [])
        self.assertEqual(d["dropped"]["people"][0]["name"], "nobody-here")

    def test_the_body_answers_to_the_tier_char_limit_not_a_column_width(self):
        r = self.c.post(LIST, {"title": "long", "body": "x" * 401}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["char_limit"], 400)
        self.premium()
        self.assertEqual(self.c.post(LIST, {"title": "long", "body": "x" * 401},
                                     format="json").status_code, 201)


class SearchLooksAtTheWholePileTests(Base):
    """A tag filter must not search only the newest page.

    The JSON columns are matched in Python, and the obvious way to write that —
    slice a page, then filter it — would answer "nothing tagged #bristol" to a
    member with thirty of them from two years ago. That is a search that lies
    while returning 200.
    """

    def test_a_tag_from_far_back_is_still_found(self):
        old = JournalEntry.objects.create(
            author=self.me, day=timezone.localdate() - timedelta(days=900),
            title="the one", tags=["bristol"])
        for i in range(30):
            JournalEntry.objects.create(author=self.me, title=f"filler {i}",
                                        day=timezone.localdate() - timedelta(days=i))
        rows = self.c.get(f"{LIST}?tag=bristol").data["entries"]
        self.assertEqual([r["id"] for r in rows], [old.id])


class TheGatesTests(Base):

    def test_lookback_is_premium_and_the_refusal_says_what_is_behind_it(self):
        r = self.c.get(f"{LIST}lookback/")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data["required_tier"], "premium")
        self.assertIn("entries_on_this_date", r.data["preview"])
        self.premium()
        self.assertEqual(self.c.get(f"{LIST}lookback/").status_code, 200)

    def test_lookback_shows_the_same_date_in_other_years_and_not_today(self):
        self.premium()
        today = timezone.localdate()
        JournalEntry.objects.create(author=self.me, day=today, body="now")
        old = JournalEntry.objects.create(author=self.me, body="then",
                                          day=today.replace(year=today.year - 1))
        d = self.c.get(f"{LIST}lookback/").data
        self.assertEqual([e["id"] for e in d["years"]], [old.id])

    def test_the_account_export_carries_the_words_at_every_tier(self):
        """The free floor the gate's refusal points at. If this stops being
        true, the refusal copy becomes a lie, which is worse than the gate."""
        self.write(body="Something only I know.")
        d = self.c.get("/api/economy/account/export/").data
        self.assertEqual(len(d["journal"]), 1)
        self.assertEqual(d["journal"][0]["body"], "Something only I know.")

    def test_export_is_premium_but_never_claims_your_words_are_locked_up(self):
        self.write()
        r = self.c.get(f"{LIST}export/")
        self.assertEqual(r.status_code, 403)
        self.assertIn("account/export", r.data["always_free"])
        self.premium()
        d = self.c.get(f"{LIST}export/").data
        self.assertIn("It rained", d["markdown"])
        self.assertEqual(d["count"], 1)


class DeletingSaysWhatItDidNotDeleteTests(Base):

    def test_deleting_an_entry_leaves_the_post_up_and_says_so(self):
        d = self.write()
        self.c.post(f"{LIST}{d['id']}/share/", {"visibility": "public"}, format="json")
        r = self.c.delete(f"{LIST}{d['id']}/")
        self.assertTrue(r.data["deleted"])
        self.assertTrue(r.data["note"])
        self.assertEqual(Post.objects.count(), 1)     # the post is not collateral


class TheDiaryDoesNotCountPerRowTests(Base):
    """A page of entries must not cost a query per entry.

    The PostZ feed learned this twice — the coach's price and the take sizes are
    both read once for the whole page. `mentions_sent` is the same shape of
    number: it sits on every row, it is usually zero, and read per card it is a
    COUNT per entry behind one screen.

    The slope is what is asserted, not an absolute count. Pinning the exact
    number would make this a test of whatever the ORM happened to do the day it
    was written; what has to stay true is that six entries cost what one does.
    """

    def queries_for(self, n):
        JournalEntry.objects.filter(author=self.me).delete()
        for i in range(n):
            JournalEntry.objects.create(author=self.me, day=timezone.localdate(),
                                        title=f"e{i}", body="words")
        self.c.get(LIST)                       # warm anything cached per process
        with CaptureQueriesContext(connection) as ctx:
            self.c.get(LIST)
        return len(ctx)

    def test_the_page_is_flat_in_the_number_of_entries(self):
        self.premium()
        self.assertEqual(self.queries_for(6), self.queries_for(1))


class TheReturnLegTests(Base):
    """Cross-pollination runs both ways or it isn't a loop."""

    def test_every_post_offers_to_be_kept_in_the_journal(self):
        Post.objects.create(author=self.them, title="a track", description="words")
        feed = self.c.get("/api/economy/postz/").data["posts"]
        door = next(x for x in feed[0]["destinations"] if x["app"] == "journalz")
        self.assertTrue(door["available"])
        self.assertEqual(door["target"], "journalz-composer")
        self.assertEqual(door["cost"]["amount"], 0)


class CoachingAVoiceNoteWithoutPublishingItTests(Base):
    """A voice note kept in the diary is a take like any other.

    The point of this path is what it does NOT ask for: making somebody publish
    their diary to have a take scored would be the app charging privacy as the
    price of a feature. The entry stays private and the coach still reads it.
    """

    def setUp(self):
        super().setUp()
        for u in (self.me, self.them):
            m = membership_for(u)
            m.tier = TIER_STATZ
            m.save(update_fields=["tier"])
            w = wallet_for(u)
            w.money_cents = 100000
            w.save(update_fields=["money_cents"])

    def with_take(self, owner=None, **kw):
        owner = owner or self.me
        up = Upload.objects.create(
            user=owner, file=SimpleUploadedFile("note.webm", b"0" * 900,
                                                content_type="audio/webm"),
            name="note.webm", size_bytes=900, content_type="audio/webm")
        e = JournalEntry.objects.create(
            author=owner, day=timezone.localdate(), title="Sang it in the car",
            items=[{"url": up.file.url, "type": "audio", "title": "note", "lyrics": ""}],
            **kw)
        return e, up

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.gemini.requests.post", return_value=fake_gemini())
    def test_a_private_entry_can_be_coached_and_stays_private(self, _rq, _k):
        e, _ = self.with_take()
        r = self.c.post("/api/singz/coach/", {"journal_id": e.id}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["score"], 7)
        self.assertEqual(r.data["source"], "journal")
        self.assertEqual(r.data["journal_id"], e.id)
        # The way back — a score is not a dead end either.
        self.assertEqual(r.data["open_in"], "journalz")
        e.refresh_from_db()
        self.assertTrue(e.is_private)
        self.assertIsNone(e.shared_post_id)
        self.assertEqual(Post.objects.count(), 0)

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.gemini.requests.post", return_value=fake_gemini())
    def test_somebody_elses_diary_is_not_coachable(self, _rq, _k):
        """The only door into a stranger's work is the POST door, which has its
        own view check. A diary has no shared reading at all."""
        e, _ = self.with_take(owner=self.them)
        r = self.c.post("/api/singz/coach/", {"journal_id": e.id}, format="json")
        self.assertEqual(r.status_code, 404)

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    def test_an_entry_with_no_recording_says_so_instead_of_failing(self, _k):
        e = JournalEntry.objects.create(author=self.me, day=timezone.localdate(),
                                        body="just words")
        r = self.c.post("/api/singz/coach/", {"journal_id": e.id}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("no recording", r.data["detail"])

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.gemini.requests.post", return_value=fake_gemini())
    def test_the_entry_carries_the_coach_door_once_there_is_a_take(self, _rq, _k):
        e, _ = self.with_take()
        row = self.c.get(f"{LIST}{e.id}/").data
        singz = next(d for d in row["destinations"] if d["app"] == "singz")
        self.assertTrue(singz["available"])
        self.assertEqual(singz["coach_kind"], "audio")
        self.assertEqual(singz["carry"]["journal_id"], e.id)
