"""MangaZ: supervised rooms, AI provenance, and the 10% royalty.

The supervision tests are the important half. Everything else here is a
feature; that part is a child-safety rule, and a rule enforced only in the UI
is not enforced.
"""
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.economy.models import membership_for, profile_for, wallet_for

from .ai import AiUnavailable
from .art import ArtUnavailable
from .models import (AI_ROYALTY_RATE, SOURCE_CHARACTER, SOURCE_HUMAN,
                     SOURCE_SCRIPT, CharacterZ, MangaZ, Meet, Page, Room,
                     RoomMember, Sale, Volume, is_minor,
                     is_verified_adult)

User = get_user_model()


def member(name, *, age=None, verified=False):
    u = User.objects.create_user(username=name, password="mangaz-pass-1")
    p = profile_for(u)
    if age is not None:
        today = date.today()
        p.birthday = f"{today.year - age}-{today.month:02d}-{today.day:02d}"
    p.verified_18plus = verified
    p.save()
    return u


def adult(name):
    return member(name, age=30, verified=True)


def kid(name):
    return member(name, age=14)


class AgeTests(TestCase):
    def test_a_known_under_18_is_a_minor(self):
        self.assertTrue(is_minor(kid("young")))

    def test_an_adult_is_not(self):
        self.assertFalse(is_minor(adult("grown")))

    def test_an_unknown_age_is_not_treated_as_a_minor(self):
        """Otherwise every room with an incomplete profile silently becomes a
        supervised one, which makes the feature unusable and teaches people to
        work around it. Age gating that matters keys off verification."""
        self.assertFalse(is_minor(member("mystery")))

    def test_a_birthday_alone_is_not_verification(self):
        """The whole point of the distinction."""
        self.assertFalse(is_verified_adult(member("says_30", age=30)))
        self.assertTrue(is_verified_adult(adult("proved_30")))


class SupervisionTests(TestCase):
    def setUp(self):
        self.sup = adult("supervisor")
        self.room = Room.objects.create(title="Studio", owner=self.sup,
                                        supervisor=self.sup)
        RoomMember.objects.create(room=self.room, user=self.sup)

    def test_an_adults_only_room_needs_no_supervisor(self):
        room = Room.objects.create(title="Grown-ups", owner=adult("a"))
        RoomMember.objects.create(room=room, user=room.owner)
        self.assertIsNone(room.supervision_error())

    def test_a_room_with_a_minor_and_no_supervisor_is_refused(self):
        room = Room.objects.create(title="Unsupervised", owner=adult("b"))
        RoomMember.objects.create(room=room, user=room.owner)
        RoomMember.objects.create(room=room, user=kid("child"))
        self.assertIn("verified adult supervisor", room.supervision_error())

    def test_an_unverified_supervisor_does_not_count(self):
        fake = member("claims_adult", age=30)     # birthday only, no verification
        room = Room.objects.create(title="Claimed", owner=fake, supervisor=fake)
        RoomMember.objects.create(room=room, user=fake)
        RoomMember.objects.create(room=room, user=kid("child2"))
        self.assertIn("verified adult", room.supervision_error())

    def test_the_supervisor_has_to_actually_be_in_the_room(self):
        absent = adult("absent")
        room = Room.objects.create(title="Absentee", owner=absent,
                                   supervisor=absent)
        RoomMember.objects.create(room=room, user=kid("child3"))
        self.assertIn("in the room", room.supervision_error())

    def test_a_supervised_room_with_a_minor_is_fine(self):
        RoomMember.objects.create(room=self.room, user=kid("child4"))
        self.assertIsNone(self.room.supervision_error())

    def test_the_rule_is_rechecked_when_someone_joins(self):
        """A room becomes one that needs supervision the moment a minor walks
        in. A check that only runs at creation stops being true."""
        plain = Room.objects.create(title="Was fine", owner=adult("c"))
        RoomMember.objects.create(room=plain, user=plain.owner)
        self.assertIsNone(plain.supervision_error())
        RoomMember.objects.create(room=plain, user=kid("child5"))
        self.assertIsNotNone(plain.supervision_error())


class JoinRuleTests(TestCase):
    def setUp(self):
        self.sup = adult("guardian")
        self.room = Room.objects.create(title="Class", owner=self.sup,
                                        supervisor=self.sup)
        RoomMember.objects.create(room=self.room, user=self.sup)

    def test_a_minor_can_join_a_supervised_room(self):
        self.assertIsNone(self.room.join_error(kid("student")))

    def test_a_minor_cannot_join_an_unsupervised_room(self):
        bare = Room.objects.create(title="Bare", owner=adult("d"))
        self.assertIn("verified adult supervisor",
                      bare.join_error(kid("student2")))

    def test_a_minor_cannot_join_an_adults_only_room(self):
        grown = Room.objects.create(title="18+", owner=self.sup,
                                    supervisor=self.sup,
                                    open_to_all_ages=False)
        self.assertIn("adults only", grown.join_error(kid("student3")))

    def test_an_adult_may_join_a_supervised_room_that_has_teens_in_it(self):
        """The point of an all-ages creative platform. A teenager working with
        an experienced adult is the ordinary case, and making it need
        per-person approval made the ordinary case the awkward one. The
        safeguard is that a verified adult is present and answerable — the
        closed surface is dating, not the studio."""
        RoomMember.objects.create(room=self.room, user=kid("student4"))
        self.assertIsNone(self.room.join_error(adult("collaborator")))

    def test_a_refused_adult_cannot(self):
        from .models import RoomApproval
        RoomMember.objects.create(room=self.room, user=kid("student6"))
        refused = adult("refused")
        RoomApproval.objects.create(room=self.room, user=refused,
                                    approved=False, decided_by=self.sup)
        self.assertIsNotNone(self.room.join_error(refused))

    def test_adults_join_freely_when_no_minor_is_present(self):
        self.assertIsNone(self.room.join_error(adult("colleague")))


class RoyaltyTests(TestCase):
    def setUp(self):
        self.owner = adult("author")
        room = Room.objects.create(title="Desk", owner=self.owner,
                                   supervisor=self.owner)
        RoomMember.objects.create(room=room, user=self.owner)
        self.manga = MangaZ.objects.create(title="Book", room=room,
                                           owner=self.owner)

    def page(self, number, source):
        return Page.objects.create(manga=self.manga, number=number,
                                   author=self.owner, source=source,
                                   script="words")

    def test_a_hand_written_manga_owes_no_ai_royalty(self):
        self.page(1, SOURCE_HUMAN)
        self.assertFalse(self.manga.used_ai())
        self.assertEqual(self.manga.ai_royalty_cents(10_000), 0)

    def test_one_ai_page_makes_the_work_ai_assisted(self):
        self.page(1, SOURCE_HUMAN)
        self.page(2, SOURCE_CHARACTER)
        self.assertTrue(self.manga.used_ai())

    def test_the_royalty_is_ten_percent(self):
        self.page(1, SOURCE_SCRIPT)
        self.assertEqual(AI_ROYALTY_RATE, 0.10)
        self.assertEqual(self.manga.ai_royalty_cents(10_000), 1000)

    def test_both_ai_routes_count(self):
        for source in (SOURCE_SCRIPT, SOURCE_CHARACTER):
            with self.subTest(source=source):
                m = MangaZ.objects.create(title=f"B-{source}",
                                          room=self.manga.room,
                                          owner=self.owner)
                Page.objects.create(manga=m, number=1, author=self.owner,
                                    source=source, script="x")
                self.assertEqual(m.ai_royalty_cents(1000), 100)

    def test_provenance_says_what_wrote_each_page(self):
        self.page(1, SOURCE_HUMAN)
        self.page(2, SOURCE_SCRIPT)
        prov = self.manga.provenance()
        self.assertEqual(prov["pages"], 2)
        self.assertEqual(prov["by_source"][SOURCE_HUMAN], 1)
        self.assertTrue(prov["used_ai"])
        self.assertIn("10%", prov["note"])

    def test_a_zero_sale_owes_nothing(self):
        self.page(1, SOURCE_SCRIPT)
        self.assertEqual(self.manga.ai_royalty_cents(0), 0)


class CharacterTests(TestCase):
    def test_an_mbti_typo_is_caught(self):
        c = CharacterZ(owner=adult("designer"), name="Rin", mbti="XXXX")
        self.assertIn("isn't an MBTI type", c.mbti_error())

    def test_a_real_type_passes(self):
        c = CharacterZ(owner=adult("designer2"), name="Rin", mbti="INFJ")
        self.assertIsNone(c.mbti_error())

    def test_no_mbti_at_all_is_fine(self):
        self.assertIsNone(CharacterZ(owner=adult("d3"), name="Rin").mbti_error())

    def test_the_prompt_sheet_is_what_the_ai_is_told(self):
        """A member can see exactly what was sent on their behalf — an AI that
        writes from hidden inputs is one nobody can correct."""
        c = CharacterZ(owner=adult("d4"), name="Rin", mbti="infj",
                       bio="Quiet", traits=["stubborn"], voice="clipped")
        sheet = c.prompt_sheet()
        self.assertEqual(sheet["mbti"], "INFJ")
        self.assertEqual(sheet["traits"], ["stubborn"])
        self.assertEqual(sheet["voice"], "clipped")


class ApiTests(TestCase):
    def setUp(self):
        self.sup = adult("api_sup")
        self.client = APIClient()
        self.client.force_authenticate(self.sup)

    def make_room(self):
        r = self.client.post(reverse("mangaz-rooms"), {"title": "Room"},
                             format="json")
        return r.json()["room"]["id"]

    def make_manga(self, room_id):
        r = self.client.post(reverse("mangaz-works"),
                             {"title": "Work", "room_id": room_id},
                             format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["manga"]["id"]

    def test_the_catalog_is_public_and_states_the_age_rule(self):
        body = APIClient().get(reverse("mangaz-catalog")).json()
        self.assertEqual(body["ai_royalty_rate"], 0.10)
        self.assertIn("verified adult", body["rules"]["supervision"])

    def test_a_verified_adult_supervises_their_own_new_room(self):
        body = self.client.post(reverse("mangaz-rooms"), {"title": "Mine"},
                                format="json").json()["room"]
        self.assertEqual(body["supervisor"], "api_sup")

    def test_a_minors_room_starts_without_a_supervisor(self):
        c = APIClient()
        c.force_authenticate(kid("young_owner"))
        body = c.post(reverse("mangaz-rooms"), {"title": "Mine"},
                      format="json").json()["room"]
        self.assertIsNone(body["supervisor"])

    def test_a_minor_is_refused_from_an_unsupervised_room(self):
        c = APIClient()
        maker = kid("young_owner2")
        c.force_authenticate(maker)
        room_id = c.post(reverse("mangaz-rooms"), {"title": "Bare"},
                         format="json").json()["room"]["id"]
        joiner = APIClient()
        joiner.force_authenticate(kid("young_joiner"))
        r = joiner.post(reverse("mangaz-room-join", args=[room_id]), {},
                        format="json")
        self.assertEqual(r.status_code, 403)

    def test_an_unverified_member_cannot_take_on_supervision(self):
        room_id = self.make_room()
        pretender = APIClient()
        pretender.force_authenticate(member("pretender", age=40))
        r = pretender.post(reverse("mangaz-room-supervise", args=[room_id]),
                           {}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_only_the_supervisor_approves_other_adults(self):
        room_id = self.make_room()
        other = APIClient()
        other.force_authenticate(adult("busybody"))
        r = other.post(reverse("mangaz-room-supervise", args=[room_id]),
                       {"username": "someone"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_writing_stops_the_moment_the_room_is_unsafe(self):
        """A supervisor can leave. The room has to stop working, not carry on
        because it was fine when the manga was created."""
        room_id = self.make_room()
        manga_id = self.make_manga(room_id)
        room = Room.objects.get(pk=room_id)
        RoomMember.objects.create(room=room, user=kid("late_arrival"))
        room.supervisor = None
        room.save(update_fields=["supervisor"])
        r = self.client.post(reverse("mangaz-pages", args=[manga_id]),
                             {"mode": SOURCE_HUMAN, "script": "hi"},
                             format="json")
        self.assertEqual(r.status_code, 409)

    def test_a_hand_written_page_is_recorded_as_human(self):
        manga_id = self.make_manga(self.make_room())
        r = self.client.post(reverse("mangaz-pages", args=[manga_id]),
                             {"mode": SOURCE_HUMAN, "script": "PANEL 1"},
                             format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertFalse(r.json()["page"]["ai_assisted"])
        self.assertFalse(r.json()["provenance"]["used_ai"])

    def test_the_client_cannot_call_an_ai_page_human(self):
        """The source decides a 10% royalty. A field the payer controls is not
        a fact — the endpoint that ran the model sets it."""
        manga_id = self.make_manga(self.make_room())
        with patch("apps.mangaz.views.write_from_script",
                   return_value=("[PANEL 1] laid out", {"mode": "script"}, "m")):
            r = self.client.post(reverse("mangaz-pages", args=[manga_id]),
                                 {"mode": SOURCE_SCRIPT, "script": "hello",
                                  "source": SOURCE_HUMAN,
                                  "ai_assisted": False}, format="json")
        self.assertEqual(r.json()["page"]["source"], SOURCE_SCRIPT)
        self.assertTrue(r.json()["page"]["ai_assisted"])

    def test_writing_from_a_character_records_the_sheet_it_used(self):
        manga_id = self.make_manga(self.make_room())
        c = CharacterZ.objects.create(owner=self.sup, name="Rin", mbti="INFJ",
                                      bio="Quiet", voice="clipped")
        with patch("apps.mangaz.views.write_from_character",
                   return_value=("RIN: ...", {"mode": "character",
                                              "sheet": c.prompt_sheet()},
                                 "claude-sonnet-5")) as fake:
            r = self.client.post(reverse("mangaz-pages", args=[manga_id]),
                                 {"mode": SOURCE_CHARACTER,
                                  "character_id": c.id,
                                  "beat": "they argue"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(fake.called)
        page = Page.objects.get(manga_id=manga_id, number=1)
        self.assertEqual(page.ai_prompt["sheet"]["mbti"], "INFJ")
        self.assertEqual(page.ai_model, "claude-sonnet-5")

    def test_you_cannot_write_with_somebody_elses_private_character(self):
        manga_id = self.make_manga(self.make_room())
        theirs = CharacterZ.objects.create(owner=adult("other_owner"),
                                           name="Theirs", shared=False)
        r = self.client.post(reverse("mangaz-pages", args=[manga_id]),
                             {"mode": SOURCE_CHARACTER,
                              "character_id": theirs.id}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_a_shared_character_can_be_used(self):
        manga_id = self.make_manga(self.make_room())
        shared = CharacterZ.objects.create(owner=adult("generous"),
                                           name="Shared", shared=True)
        with patch("apps.mangaz.views.write_from_character",
                   return_value=("x", {}, "m")):
            r = self.client.post(reverse("mangaz-pages", args=[manga_id]),
                                 {"mode": SOURCE_CHARACTER,
                                  "character_id": shared.id}, format="json")
        self.assertEqual(r.status_code, 201, r.content)

    def test_the_ai_being_down_is_a_503_and_loses_nothing(self):
        manga_id = self.make_manga(self.make_room())
        with patch("apps.mangaz.views.write_from_script",
                   side_effect=AiUnavailable("not right now")):
            r = self.client.post(reverse("mangaz-pages", args=[manga_id]),
                                 {"mode": SOURCE_SCRIPT, "script": "hello"},
                                 format="json")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(Page.objects.filter(manga_id=manga_id).count(), 0)

    def test_the_royalty_quote_is_available_before_publishing(self):
        """A royalty somebody finds out about at payout is one they argue
        about."""
        manga_id = self.make_manga(self.make_room())
        with patch("apps.mangaz.views.write_from_script",
                   return_value=("x", {}, "m")):
            self.client.post(reverse("mangaz-pages", args=[manga_id]),
                             {"mode": SOURCE_SCRIPT, "script": "hi"},
                             format="json")
        body = self.client.get(reverse("mangaz-royalty", args=[manga_id]),
                               {"sale_cents": "2000"}).json()
        self.assertEqual(body["ai_royalty_cents"], 200)

    def test_you_cannot_read_a_manga_from_a_room_you_are_not_in(self):
        manga_id = self.make_manga(self.make_room())
        outsider = APIClient()
        outsider.force_authenticate(adult("outsider"))
        r = outsider.get(reverse("mangaz-work", args=[manga_id]))
        self.assertEqual(r.status_code, 404)


class ViewingFormatTests(TestCase):
    """ReelZ, EpisodeZ and MovieZ are the same collaboration as MangaZ with a
    runtime limit. The limits come off the app icons, which are the spec."""

    def setUp(self):
        self.sup = adult("format_sup")
        self.client = APIClient()
        self.client.force_authenticate(self.sup)
        self.room_id = self.client.post(reverse("mangaz-rooms"),
                                        {"title": "Set"},
                                        format="json").json()["room"]["id"]

    def make(self, fmt, seconds=None):
        body = {"title": fmt, "room_id": self.room_id, "format": fmt}
        if seconds is not None:
            body["runtime_seconds"] = seconds
        return self.client.post(reverse("mangaz-works"), body, format="json")

    def test_all_four_formats_are_offered(self):
        keys = [f["key"] for f in
                APIClient().get(reverse("mangaz-catalog")).json()["formats"]]
        self.assertEqual(sorted(keys), ["episode", "manga", "movie", "reel"])

    def test_an_episode_over_sixty_minutes_is_refused(self):
        r = self.make("episode", 61 * 60)
        self.assertEqual(r.status_code, 400)
        self.assertIn("60 minutes", r.json()["detail"])

    def test_an_episode_at_the_limit_is_fine(self):
        self.assertEqual(self.make("episode", 60 * 60).status_code, 201)

    def test_a_movie_under_an_hour_is_refused(self):
        r = self.make("movie", 30 * 60)
        self.assertEqual(r.status_code, 400)
        self.assertIn("at least", r.json()["detail"])

    def test_a_movie_over_three_hours_is_refused(self):
        self.assertEqual(self.make("movie", 4 * 60 * 60).status_code, 400)

    def test_a_two_hour_movie_is_fine(self):
        self.assertEqual(self.make("movie", 2 * 60 * 60).status_code, 201)

    def test_a_reel_is_capped_at_three_minutes(self):
        self.assertEqual(self.make("reel", 4 * 60).status_code, 400)
        self.assertEqual(self.make("reel", 90).status_code, 201)

    def test_manga_has_no_runtime_limit(self):
        """Pages, not minutes."""
        self.assertEqual(self.make("manga", 99999).status_code, 201)

    def test_no_runtime_yet_is_allowed(self):
        """Not cut yet — there's nothing to check."""
        self.assertEqual(self.make("movie").status_code, 201)

    def test_an_unknown_format_is_refused(self):
        self.assertEqual(self.make("podcast", 60).status_code, 400)

    def test_every_format_gets_the_same_ai_royalty(self):
        runtimes = {"reel": 120, "episode": 45 * 60, "movie": 90 * 60}
        for fmt, seconds in runtimes.items():
            with self.subTest(format=fmt):
                r = self.make(fmt, seconds)
                self.assertEqual(r.status_code, 201, r.content)
                mid = r.json()["manga"]["id"]
                with patch("apps.mangaz.views.write_from_script",
                           return_value=("x", {}, "m")):
                    self.client.post(reverse("mangaz-pages", args=[mid]),
                                     {"mode": SOURCE_SCRIPT, "script": "hi"},
                                     format="json")
                body = self.client.get(reverse("mangaz-royalty", args=[mid]),
                                       {"sale_cents": "1000"}).json()
                self.assertEqual(body["ai_royalty_cents"], 100)


class InPersonMeetTests(TestCase):
    """Teens and adults working together in the same room, in real life.

    Supported rather than refused — a studio afternoon is a real thing, and
    not supporting it moves it somewhere nothing is recorded.
    """

    def setUp(self):
        self.sup = adult("meet_sup")
        self.client = APIClient()
        self.client.force_authenticate(self.sup)
        self.room = Room.objects.create(title="Studio", owner=self.sup,
                                        supervisor=self.sup)
        RoomMember.objects.create(room=self.room, user=self.sup)

    def make_meet(self, **over):
        body = dict({"title": "Session", "place": "Community centre",
                     "starts_at": "2027-01-01T10:00:00Z"}, **over)
        return self.client.post(reverse("mangaz-meets", args=[self.room.id]),
                                body, format="json")

    def add_teen(self, meet_id, name="teen_attendee"):
        teen = kid(name)
        RoomMember.objects.create(room=self.room, user=teen)
        c = APIClient()
        c.force_authenticate(teen)
        c.post(reverse("mangaz-meet-attend", args=[meet_id]), {}, format="json")
        return teen

    def test_an_adults_only_meet_is_ready_immediately(self):
        self.assertTrue(self.make_meet().json()["meet"]["ready"])

    def test_a_teen_attending_creates_a_consent_requirement(self):
        meet_id = self.make_meet().json()["meet"]["id"]
        self.add_teen(meet_id)
        body = self.client.get(reverse("mangaz-meets",
                                       args=[self.room.id])).json()["meets"][0]
        self.assertFalse(body["ready"])
        self.assertIn("Guardian consent", body["why_not"])

    def test_a_teen_is_not_blocked_from_joining_just_flagged(self):
        """Blocking would hide the reason. Naming what's missing lets somebody
        go and get it."""
        meet_id = self.make_meet().json()["meet"]["id"]
        teen = self.add_teen(meet_id, "flagged_teen")
        meet = Meet.objects.get(pk=meet_id)
        self.assertIn(teen, [a.user for a in meet.attendees.all()])

    def test_recorded_consent_makes_it_ready(self):
        meet_id = self.make_meet().json()["meet"]["id"]
        self.add_teen(meet_id, "consented_teen")
        r = self.client.post(reverse("mangaz-meet-consent", args=[meet_id]),
                             {"username": "consented_teen",
                              "guardian_name": "A Parent",
                              "guardian_contact": "parent@example.com"},
                             format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["meet"]["ready"])

    def test_a_private_place_is_refused_when_a_teen_attends(self):
        meet_id = self.make_meet(is_public_place=False).json()["meet"]["id"]
        self.add_teen(meet_id, "private_place_teen")
        self.client.post(reverse("mangaz-meet-consent", args=[meet_id]),
                         {"username": "private_place_teen",
                          "guardian_name": "P", "guardian_contact": "p@e.com"},
                         format="json")
        meet = Meet.objects.get(pk=meet_id)
        self.assertIn("somewhere public", meet.readiness_error())

    def test_the_supervisor_has_to_be_attending_not_just_named(self):
        meet_id = self.make_meet().json()["meet"]["id"]
        self.add_teen(meet_id, "unsupervised_teen")
        self.client.post(reverse("mangaz-meet-consent", args=[meet_id]),
                         {"username": "unsupervised_teen",
                          "guardian_name": "P", "guardian_contact": "p@e.com"},
                         format="json")
        Meet.objects.get(pk=meet_id).attendees.filter(user=self.sup).delete()
        self.assertIn("has to be attending",
                      Meet.objects.get(pk=meet_id).readiness_error())

    def test_only_the_supervisor_records_consent(self):
        meet_id = self.make_meet().json()["meet"]["id"]
        teen = self.add_teen(meet_id, "other_teen")
        other = APIClient()
        other.force_authenticate(adult("random_adult"))
        r = other.post(reverse("mangaz-meet-consent", args=[meet_id]),
                       {"username": "other_teen", "guardian_name": "X",
                        "guardian_contact": "x@e.com"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_consent_needs_a_contact_not_just_a_name(self):
        meet_id = self.make_meet().json()["meet"]["id"]
        self.add_teen(meet_id, "nameonly_teen")
        r = self.client.post(reverse("mangaz-meet-consent", args=[meet_id]),
                             {"username": "nameonly_teen",
                              "guardian_name": "A Parent"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_consent_is_per_meet_not_blanket(self):
        """A guardian saying yes to one afternoon did not say yes to every
        future session — which is the shape that gets a platform in trouble."""
        first = self.make_meet(title="One").json()["meet"]["id"]
        self.add_teen(first, "returning_teen")
        self.client.post(reverse("mangaz-meet-consent", args=[first]),
                         {"username": "returning_teen", "guardian_name": "P",
                          "guardian_contact": "p@e.com"}, format="json")
        second = self.make_meet(title="Two").json()["meet"]["id"]
        c = APIClient()
        c.force_authenticate(User.objects.get(username="returning_teen"))
        c.post(reverse("mangaz-meet-attend", args=[second]), {}, format="json")
        self.assertIsNotNone(Meet.objects.get(pk=second).readiness_error())


class PremiumArtTests(TestCase):
    """The Premium hook. Everything else in MangaZ stays free — what you pay
    for is being able to MAKE something."""

    def setUp(self):
        self.owner = adult("art_owner")
        self.room = Room.objects.create(title="Studio", owner=self.owner,
                                        supervisor=self.owner)
        RoomMember.objects.create(room=self.room, user=self.owner)
        self.manga = MangaZ.objects.create(title="Book", room=self.room,
                                           owner=self.owner)
        self.character = CharacterZ.objects.create(owner=self.owner, name="Rin",
                                                   mbti="INFJ", bio="Quiet")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def set_tier(self, tier):
        m = membership_for(self.owner)
        m.tier = tier
        m.save(update_fields=["tier"])

    def draw(self, **over):
        body = dict({"character_id": self.character.id, "brief": "close up"},
                    **over)
        return self.client.post(reverse("mangaz-art", args=[self.manga.id]),
                                body, format="json")

    def test_a_free_member_is_refused_with_a_way_forward(self):
        """A dead-end 402 is a wasted upgrade."""
        self.set_tier("free")
        r = self.draw()
        self.assertEqual(r.status_code, 402)
        self.assertIn("Premium", r.json()["detail"])
        self.assertIn("upgrade", r.json())

    def test_the_refusal_says_what_is_still_free(self):
        self.set_tier("free")
        body = self.client.get(reverse("mangaz-art",
                                       args=[self.manga.id])).json()
        self.assertFalse(body["can_generate"])
        self.assertIn("writing", body["free_anyway"])
        self.assertIn("collabs", body["free_anyway"])

    def test_premium_can_generate(self):
        self.set_tier("premium")
        with patch("apps.mangaz.views.draw_from_character",
                   return_value=("data:image/png;base64,AAA",
                                 {"mode": "character_art"}, "gemini-x")):
            r = self.draw()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(r.json()["page"]["ai_assisted"])

    def test_statz_can_too(self):
        self.set_tier("statz")
        with patch("apps.mangaz.views.draw_from_character",
                   return_value=("data:image/png;base64,AAA", {}, "gemini-x")):
            self.assertEqual(self.draw().status_code, 201)

    def test_generated_art_earns_the_royalty_even_on_a_hand_written_page(self):
        """A page written by hand and drawn by the model still had the AI make
        part of what's being sold."""
        self.set_tier("premium")
        Page.objects.create(manga=self.manga, number=1, author=self.owner,
                            source=SOURCE_HUMAN, script="I wrote this")
        with patch("apps.mangaz.views.draw_from_character",
                   return_value=("data:image/png;base64,AAA", {}, "gemini-x")):
            self.draw(page=1)
        self.assertTrue(self.manga.used_ai())
        self.assertEqual(self.manga.ai_royalty_cents(10_000), 1000)

    def test_hand_drawn_and_hand_written_still_owes_nothing(self):
        Page.objects.create(manga=self.manga, number=1, author=self.owner,
                            source=SOURCE_HUMAN, art_source=SOURCE_HUMAN,
                            script="mine", art_url="https://example.com/a.png")
        self.assertEqual(self.manga.ai_royalty_cents(10_000), 0)

    def test_provenance_reports_writing_and_art_separately(self):
        self.set_tier("premium")
        Page.objects.create(manga=self.manga, number=1, author=self.owner,
                            source=SOURCE_HUMAN)
        with patch("apps.mangaz.views.draw_from_character",
                   return_value=("data:image/png;base64,AAA", {}, "gemini-x")):
            self.draw(page=1)
        prov = self.manga.provenance()
        self.assertEqual(prov["by_source"][SOURCE_HUMAN], 1)
        self.assertEqual(prov["art_by_source"][SOURCE_CHARACTER], 1)

    def test_the_image_service_being_down_is_a_503_not_a_500(self):
        self.set_tier("premium")
        with patch("apps.mangaz.views.draw_from_character",
                   side_effect=ArtUnavailable("not right now")):
            r = self.draw()
        self.assertEqual(r.status_code, 503)

    def test_you_cannot_draw_with_somebody_elses_private_character(self):
        self.set_tier("premium")
        theirs = CharacterZ.objects.create(owner=adult("stranger"),
                                           name="Theirs", shared=False)
        self.assertEqual(self.draw(character_id=theirs.id).status_code, 400)

    def test_art_is_refused_when_the_room_goes_unsafe(self):
        self.set_tier("premium")
        RoomMember.objects.create(room=self.room, user=kid("late_teen"))
        self.room.supervisor = None
        self.room.save(update_fields=["supervisor"])
        self.assertEqual(self.draw().status_code, 409)

    def test_the_prompt_records_the_sheet_it_drew_from(self):
        """Art generated from hidden inputs is art nobody can correct."""
        from .art import build_prompt
        prompt, sheet = build_prompt(self.character, "close up")
        self.assertIn("Rin", prompt)
        self.assertIn("Quiet", prompt)
        self.assertEqual(sheet["mbti"], "INFJ")

    def test_the_house_style_is_always_applied(self):
        from .art import build_prompt
        prompt, _ = build_prompt(self.character)
        self.assertIn("no sexual content", prompt)


class AiIsChargedAtCostTests(TestCase):
    """Every AI run bills what the model costs. Nothing on top.

    Writing ran entirely free until this existed — every AI page came out of
    the platform's pocket, and the bill grew with usage.
    """

    def setUp(self):
        self.owner = adult("payer")
        room = Room.objects.create(title="Desk", owner=self.owner,
                                   supervisor=self.owner)
        RoomMember.objects.create(room=room, user=self.owner)
        self.manga = MangaZ.objects.create(title="Book", room=room,
                                           owner=self.owner)
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def test_the_charge_is_pure_pass_through_no_developer_tax(self):
        """The member pays what the run costs. The platform's margin is the
        subscription and the 10% royalty, not a markup on every call."""
        from apps.economy.catalog import ai_cost
        from apps.economy.models import wallet_for
        from .ai import bill

        w = wallet_for(self.owner)
        w.money_cents, w.promptz = 10_000, 0
        w.prompts_used_today = 999         # daily allowance already spent
        w.prompt_day = date.today().isoformat()   # ...and spent TODAY
        w.save()
        charged = bill(self.owner, "test run")
        self.assertEqual(charged, ai_cost("standard"))
        wallet_for(self.owner).refresh_from_db()
        self.assertEqual(wallet_for(self.owner).money_cents,
                         10_000 - ai_cost("standard"))

    def test_a_free_daily_prompt_covers_a_run_before_any_money(self):
        from apps.economy.models import wallet_for
        from .ai import bill

        w = wallet_for(self.owner)
        w.money_cents, w.promptz = 10_000, 0
        w.save()
        bill(self.owner, "first of the day")
        self.assertEqual(wallet_for(self.owner).money_cents, 10_000)

    def test_promptz_are_spent_before_cash(self):
        from apps.economy.catalog import ai_cost
        from apps.economy.models import wallet_for
        from .ai import bill

        w = wallet_for(self.owner)
        w.money_cents, w.promptz = 10_000, 500
        w.prompts_used_today, w.prompt_day = 999, date.today().isoformat()
        w.save()
        bill(self.owner, "paid run")
        after = wallet_for(self.owner)
        self.assertEqual(after.money_cents, 10_000)
        self.assertEqual(after.promptz, 500 - ai_cost("standard"))

    def test_somebody_who_cannot_pay_is_told_before_the_model_runs(self):
        """Not after they've waited twenty seconds for it."""
        from apps.economy.models import wallet_for
        from .ai import affordable

        w = wallet_for(self.owner)
        w.money_cents, w.promptz = 0, 0
        w.prompts_used_today, w.prompt_day = 999, date.today().isoformat()
        w.save()
        self.assertFalse(affordable(self.owner))

    def test_a_failed_run_charges_nothing(self):
        """Billing for a call that returned nothing is what ends a
        subscription."""
        from apps.economy.models import wallet_for

        w = wallet_for(self.owner)
        w.money_cents, w.promptz = 10_000, 0
        w.prompts_used_today, w.prompt_day = 999, date.today().isoformat()
        w.save()
        with patch("apps.mangaz.ai._run",
                   side_effect=AiUnavailable("model down")):
            from .ai import write_from_script
            with self.assertRaises(AiUnavailable):
                write_from_script(self.owner, "some script")
        self.assertEqual(wallet_for(self.owner).money_cents, 10_000)

    def test_the_cost_is_reported_back_on_the_page(self):
        """A charge somebody discovers on their statement is one they dispute."""
        with patch("apps.mangaz.ai._run", return_value="[PANEL 1]"):
            from .ai import write_from_script
            _text, record, _model = write_from_script(self.owner, "hello")
        self.assertIn("cost_cents", record)

    def test_a_broke_member_with_an_unused_daily_prompt_is_not_turned_away(self):
        """The check has to match what the charge does. Without count_daily it
        refused a free member holding three unused prompts — a run that would
        have cost them nothing."""
        from apps.economy.models import wallet_for
        from .ai import affordable

        w = wallet_for(self.owner)
        w.money_cents, w.promptz = 0, 0
        w.save()
        self.assertTrue(affordable(self.owner))


class SellingTests(TestCase):
    """A MangaZ nobody can buy is a hobby.

    Three products, deliberately different: own it, rent it for a window, or
    hire the designer by the hour. There is no per-minute reading meter — see
    the note in models.py for why that's a worse deal than it sounds.
    """

    def setUp(self):
        self.owner = adult("vol_owner")
        p = profile_for(self.owner)
        p.skill_price_cents = 500          # $5/hr
        p.save(update_fields=["skill_price_cents"])
        room = Room.objects.create(title="Studio", owner=self.owner,
                                   supervisor=self.owner)
        RoomMember.objects.create(room=room, user=self.owner)
        self.room = room
        self.manga = MangaZ.objects.create(title="Book", room=room,
                                           owner=self.owner)
        for n in range(1, 5):
            Page.objects.create(manga=self.manga, number=n, author=self.owner,
                                source=SOURCE_HUMAN, script=f"p{n}")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def cut(self, **over):
        body = dict({"first_page": 1, "last_page": 4, "published": True,
                     "price_cents": 2000}, **over)
        r = self.client.post(reverse("mangaz-volumes", args=[self.manga.id]),
                             body, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["volume"]

    def buyer(self, name, cents=100_000):
        u = adult(name)
        w = wallet_for(u)
        w.money_cents = cents
        w.save(update_fields=["money_cents"])
        c = APIClient()
        c.force_authenticate(u)
        return u, c

    # --- pricing off the designer's own rate ---------------------------------

    def test_the_suggested_price_comes_from_their_hourly_rate(self):
        """$5/hr x 4 pages. A creator who doesn't want to think about pricing
        still ships."""
        v = self.cut()
        self.assertEqual(v["suggested_price_cents"], 500 * 4)

    def test_a_pass_costs_about_an_hour_of_their_rate(self):
        self.assertEqual(self.cut()["suggested_pass_cents"], 500)

    def test_pricing_nothing_falls_back_to_the_suggestion(self):
        v = self.cut(price_cents=0, pass_cents=0)
        self.assertGreater(v["price_cents"], 0)

    def test_a_creator_can_charge_what_they_like(self):
        self.assertEqual(self.cut(price_cents=99_00)["price_cents"], 9900)

    # --- buying --------------------------------------------------------------

    def test_buying_a_volume_pays_the_maker(self):
        v = self.cut()
        _u, c = self.buyer("reader")
        before = wallet_for(self.owner).money_cents
        r = c.post(reverse("mangaz-buy", args=[v["id"]]), {"kind": "own"},
                   format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertGreater(wallet_for(self.owner).money_cents, before)

    def test_owning_it_does_not_expire(self):
        v = self.cut()
        _u, c = self.buyer("keeper")
        body = c.post(reverse("mangaz-buy", args=[v["id"]]), {"kind": "own"},
                      format="json").json()
        self.assertIsNone(body["sale"]["expires_at"])
        self.assertTrue(body["sale"]["active"])

    def test_a_pass_expires(self):
        """A known price for a known window — which is what every rental on
        earth does, and what "by time" should mean."""
        v = self.cut(pass_price_cents=500)
        _u, c = self.buyer("renter")
        body = c.post(reverse("mangaz-buy", args=[v["id"]]), {"kind": "pass"},
                      format="json").json()
        self.assertIsNotNone(body["sale"]["expires_at"])
        self.assertTrue(body["sale"]["active"])

    def test_an_expired_pass_is_not_access(self):
        from django.utils import timezone
        v = self.cut(pass_price_cents=500)
        _u, c = self.buyer("lapsed")
        c.post(reverse("mangaz-buy", args=[v["id"]]), {"kind": "pass"},
               format="json")
        sale = Sale.objects.get(kind="pass")
        sale.expires_at = timezone.now() - timedelta(hours=1)
        sale.save(update_fields=["expires_at"])
        self.assertFalse(sale.active())

    def test_buying_twice_is_refused(self):
        v = self.cut()
        _u, c = self.buyer("double")
        c.post(reverse("mangaz-buy", args=[v["id"]]), {"kind": "own"}, format="json")
        r = c.post(reverse("mangaz-buy", args=[v["id"]]), {"kind": "own"}, format="json")
        self.assertEqual(r.status_code, 409)

    def test_a_broke_reader_gets_the_price_and_a_route(self):
        v = self.cut(price_cents=50_000)
        _u, c = self.buyer("skint_reader", cents=100)
        r = c.post(reverse("mangaz-buy", args=[v["id"]]), {"kind": "own"},
                   format="json")
        self.assertEqual(r.status_code, 402)
        self.assertIn("next", r.json())
        self.assertIn("short_cents", r.json())

    def test_an_unpublished_volume_is_not_on_sale(self):
        v = self.cut(published=False)
        _u, c = self.buyer("early")
        self.assertEqual(
            c.post(reverse("mangaz-buy", args=[v["id"]]), {"kind": "own"},
                   format="json").status_code, 404)

    # --- splits --------------------------------------------------------------

    def test_the_money_splits_by_pages_made(self):
        """The data already knows who made what. A split nobody has to
        negotiate is a split nobody argues about."""
        helper = adult("co_artist")
        RoomMember.objects.create(room=self.room, user=helper)
        for n in range(5, 9):                       # 4 pages each now
            Page.objects.create(manga=self.manga, number=n, author=helper,
                                source=SOURCE_HUMAN, script=f"p{n}")
        v = self.cut(last_page=8, price_cents=10_000)
        shares = Volume.objects.get(pk=v["id"]).split_cents(10_000)
        self.assertEqual(shares[self.owner], 5000)
        self.assertEqual(shares[helper], 5000)

    def test_rounding_remainder_goes_to_the_owner_not_the_void(self):
        """Cents that vanish in integer division are cents somebody earned."""
        helper = adult("third")
        for n in range(5, 7):
            Page.objects.create(manga=self.manga, number=n, author=helper,
                                source=SOURCE_HUMAN, script=f"p{n}")
        v = Volume.objects.create(manga=self.manga, number=9, first_page=1,
                                  last_page=6, price_cents=1000,
                                  published=True)
        self.assertEqual(sum(v.split_cents(1000).values()), 1000)

    def test_the_ai_royalty_comes_off_before_the_split(self):
        """Nobody's share should quietly pay somebody else's model bill."""
        Page.objects.create(manga=self.manga, number=9, author=self.owner,
                            source=SOURCE_SCRIPT, script="ai")
        v = self.cut(last_page=9, price_cents=10_000)
        _u, c = self.buyer("ai_reader")
        body = c.post(reverse("mangaz-buy", args=[v["id"]]), {"kind": "own"},
                      format="json").json()
        self.assertEqual(body["sale"]["ai_royalty_cents"], 1000)

    def test_a_hand_made_volume_owes_no_royalty(self):
        v = self.cut()
        _u, c = self.buyer("human_reader")
        body = c.post(reverse("mangaz-buy", args=[v["id"]]), {"kind": "own"},
                      format="json").json()
        self.assertEqual(body["sale"]["ai_royalty_cents"], 0)

    # --- commissions ---------------------------------------------------------

    def test_a_commission_quotes_before_anyone_pays(self):
        _u, c = self.buyer("client")
        body = c.get(reverse("mangaz-commission"),
                     {"designer": "vol_owner", "hours": "3"}).json()
        self.assertEqual(body["rate_cents"], 500)
        self.assertEqual(body["total_cents"], 1500)

    def test_a_commission_pays_the_designer_their_hourly_rate(self):
        _u, c = self.buyer("client2")
        before = wallet_for(self.owner).money_cents
        r = c.post(reverse("mangaz-commission"),
                   {"designer": "vol_owner", "hours": 3}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["commission"]["total_cents"], 1500)
        self.assertGreater(wallet_for(self.owner).money_cents, before)

    def test_a_designer_with_no_rate_cannot_be_commissioned(self):
        """Quoting $0 an hour for somebody's time is worse than saying no."""
        no_rate = adult("no_rate")
        _u, c = self.buyer("client3")
        r = c.post(reverse("mangaz-commission"),
                   {"designer": "no_rate", "hours": 2}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertIn("hourly skill price", r.json()["detail"])

    def test_you_cannot_commission_yourself(self):
        r = self.client.post(reverse("mangaz-commission"),
                             {"designer": "vol_owner", "hours": 1},
                             format="json")
        self.assertEqual(r.status_code, 400)


class DrawYourOwnPageTests(TestCase):
    """Drawing a page yourself is the whole point of a manga app.

    Two free routes — a finger/mouse drawing posted as a canvas data URI, and
    a file you already made. Charging for either would be charging somebody to
    use their own hands.
    """

    # A real 1x1 PNG, base64. Small, but a genuine image so ImageField's
    # validation actually runs — a fake payload would test nothing.
    PNG = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
           "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

    def setUp(self):
        self.owner = adult("artist")
        room = Room.objects.create(title="Studio", owner=self.owner,
                                   supervisor=self.owner)
        RoomMember.objects.create(room=room, user=self.owner)
        self.room = room
        self.manga = MangaZ.objects.create(title="Book", room=room,
                                           owner=self.owner)
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def url(self, number=1):
        return reverse("mangaz-page-art", args=[self.manga.id, number])

    def draw(self, number=1, mime="image/png"):
        return self.client.post(self.url(number),
                                {"image": f"data:{mime};base64,{self.PNG}"},
                                format="json")

    def test_a_finger_drawing_becomes_a_page(self):
        r = self.draw()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["page"]["art_source"], "drawn")
        self.assertTrue(r.json()["page"]["art"])

    def test_the_drawing_is_stored_as_a_file_not_a_data_uri(self):
        """An AI image base64s to well over 100,000 characters. art_url was a
        CharField(500) — sqlite ignores max_length, Postgres raises DataError,
        so this failed in production only."""
        self.draw()
        page = Page.objects.get(manga=self.manga, number=1)
        self.assertTrue(page.art)
        self.assertFalse(page.art_url.startswith("data:"))

    def test_uploading_a_file_works_too(self):
        import base64

        from django.core.files.uploadedfile import SimpleUploadedFile

        f = SimpleUploadedFile("page.png", base64.b64decode(self.PNG),
                               content_type="image/png")
        r = self.client.post(self.url(2), {"art": f}, format="multipart")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["page"]["art_source"], "upload")

    def test_drawing_your_own_page_is_never_ai(self):
        """No royalty for a page a person drew."""
        self.draw()
        self.assertFalse(Page.objects.get(manga=self.manga, number=1).ai_assisted)
        self.assertEqual(self.manga.ai_royalty_cents(10_000), 0)

    def test_redrawing_over_ai_art_clears_the_royalty(self):
        """Otherwise the work keeps paying on a page a person drew."""
        Page.objects.create(manga=self.manga, number=3, author=self.owner,
                            source=SOURCE_HUMAN, art_source=SOURCE_CHARACTER,
                            ai_prompt={"art": {"mode": "character_art"}})
        self.assertTrue(self.manga.used_ai())
        self.draw(number=3)
        self.assertFalse(self.manga.used_ai())
        self.assertEqual(self.manga.ai_royalty_cents(10_000), 0)

    def test_an_ai_written_page_you_drew_yourself_still_owes_the_royalty(self):
        """The words were still generated. Drawing over it doesn't undo that."""
        Page.objects.create(manga=self.manga, number=4, author=self.owner,
                            source=SOURCE_SCRIPT, script="ai wrote this")
        self.draw(number=4)
        self.assertTrue(self.manga.used_ai())

    def test_sending_nothing_says_what_it_accepts(self):
        r = self.client.post(self.url(), {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("accepts", r.json())

    def test_junk_that_looks_like_a_data_uri_is_refused(self):
        r = self.client.post(self.url(), {"image": "data:image/png;base64,!!!"},
                             format="json")
        self.assertEqual(r.status_code, 400)

    def test_a_non_image_data_uri_is_refused(self):
        """A data: URI is not automatically a picture."""
        r = self.client.post(self.url(),
                             {"image": "data:text/html;base64,PHNjcmlwdD4="},
                             format="json")
        self.assertEqual(r.status_code, 400)

    def test_you_can_rub_it_out_and_start_again(self):
        self.draw()
        r = self.client.delete(self.url())
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Page.objects.get(manga=self.manga, number=1).art)

    def test_somebody_outside_the_room_cannot_draw_on_your_book(self):
        outsider = APIClient()
        outsider.force_authenticate(adult("intruder"))
        r = outsider.post(self.url(),
                          {"image": f"data:image/png;base64,{self.PNG}"},
                          format="json")
        self.assertEqual(r.status_code, 404)

    def test_drawing_stops_when_the_room_goes_unsafe(self):
        RoomMember.objects.create(room=self.room, user=kid("late_teen"))
        self.room.supervisor = None
        self.room.save(update_fields=["supervisor"])
        self.assertEqual(self.draw().status_code, 409)

    def test_drawing_costs_nothing(self):
        """Charging somebody to use their own hands is not a business model."""
        before = wallet_for(self.owner).money_cents
        self.draw()
        self.assertEqual(wallet_for(self.owner).money_cents, before)
