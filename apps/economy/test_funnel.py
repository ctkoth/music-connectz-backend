"""The join funnel — the one thing that turns "why isn't anybody joining"
from a guess into a number. FunnelEventView takes a step from a visitor who
may have no account; FunnelSummaryView reads the counts back, owner-only.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import FunnelEvent, membership_for

User = get_user_model()
PW = "hunter2hunter2"
EVENT = "/api/auth/funnel/"
SUMMARY = "/api/auth/funnel/summary/"


class FunnelEventTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_logs_a_known_kind_with_no_session(self):
        r = self.client.post(EVENT, {"kind": "landing_view", "anon_id": "abc123"}, format="json")
        self.assertEqual(r.status_code, 204)
        self.assertEqual(FunnelEvent.objects.filter(kind="landing_view", anon_id="abc123").count(), 1)

    def test_rejects_an_unknown_kind(self):
        r = self.client.post(EVENT, {"kind": "made_up_step", "anon_id": "abc123"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(FunnelEvent.objects.count(), 0)

    def test_rejects_a_missing_anon_id(self):
        r = self.client.post(EVENT, {"kind": "landing_view"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(FunnelEvent.objects.count(), 0)

    def test_meta_is_filtered_to_the_allowed_shape(self):
        r = self.client.post(EVENT, {
            "kind": "try_view",
            "anon_id": "abc123",
            "meta": {"app_key": "singz", "evil": "<script>drop table</script>", "user_id": 99999},
        }, format="json")
        self.assertEqual(r.status_code, 204)
        row = FunnelEvent.objects.get()
        self.assertEqual(row.meta, {"app_key": "singz"})

    def test_an_invalid_app_key_is_dropped_not_stored(self):
        r = self.client.post(EVENT, {
            "kind": "try_view", "anon_id": "abc123", "meta": {"app_key": "not-a-real-app"},
        }, format="json")
        self.assertEqual(r.status_code, 204)
        self.assertEqual(FunnelEvent.objects.get().meta, {})

    def test_the_share_step_is_accepted_and_carries_its_app(self):
        # The one outward-pointing step: somebody handing their score to
        # someone else is what widens the top of the funnel.
        r = self.client.post(EVENT, {
            "kind": "try_shared", "anon_id": "abc123", "meta": {"app_key": "rapz"},
        }, format="json")
        self.assertEqual(r.status_code, 204)
        row = FunnelEvent.objects.get()
        self.assertEqual(row.kind, "try_shared")
        self.assertEqual(row.meta, {"app_key": "rapz"})

    def test_a_kind_with_no_declared_shape_stores_no_meta(self):
        r = self.client.post(EVENT, {
            "kind": "landing_view", "anon_id": "abc123", "meta": {"app_key": "singz"},
        }, format="json")
        self.assertEqual(r.status_code, 204)
        self.assertEqual(FunnelEvent.objects.get().meta, {})


class FunnelSummaryTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        # is_owner() checks is_staff/is_superuser directly — set them here
        # rather than relying on ensure_owner()'s OWNER_EMAILS promotion,
        # which needs the setting active for the life of the request, not
        # just while the client is built.
        self.owner = User.objects.create_user(
            username="boss", email="boss@test.test", password=PW,
            is_staff=True, is_superuser=True,
        )
        membership_for(self.owner)
        self.member = User.objects.create_user(username="rando", email="rando@test.test", password=PW)
        membership_for(self.member)

    def owner_client(self):
        c = APIClient()
        c.force_authenticate(self.owner)
        return c

    def test_requires_a_session(self):
        r = self.client.get(SUMMARY)
        self.assertEqual(r.status_code, 401)

    def test_a_normal_member_is_refused(self):
        c = APIClient()
        c.force_authenticate(self.member)
        r = c.get(SUMMARY)
        self.assertEqual(r.status_code, 403)

    def test_counts_events_and_unique_visitors_separately(self):
        FunnelEvent.objects.create(kind="landing_view", anon_id="a")
        FunnelEvent.objects.create(kind="landing_view", anon_id="a")  # same visitor, twice
        FunnelEvent.objects.create(kind="landing_view", anon_id="b")
        FunnelEvent.objects.create(kind="register_success", anon_id="a")

        r = self.owner_client().get(SUMMARY)
        self.assertEqual(r.status_code, 200)
        steps = r.data["steps"]
        self.assertEqual(steps["landing_view"]["events"], 3)
        self.assertEqual(steps["landing_view"]["unique"], 2)
        self.assertEqual(steps["register_success"]["unique"], 1)
        # Every visitor who landed converted through to a real account here —
        # register_success unique (1) over landing_view unique (2) is 50%.
        self.assertEqual(steps["register_success"]["pct_of_base"], 50.0)

    def test_every_declared_kind_is_present_even_with_zero_events(self):
        r = self.owner_client().get(SUMMARY)
        from apps.economy.models import FUNNEL_KINDS
        for kind, _ in FUNNEL_KINDS:
            self.assertIn(kind, r.data["steps"])
            self.assertEqual(r.data["steps"][kind]["events"], 0)


class ChannelAttributionTests(TestCase):
    """`?src=` — which channel produced which arrival.

    Without it the funnel counts arrivals and cannot say which post, flyer or
    ad produced them, so every channel looks identical at zero — which is
    exactly the state this platform was in when the marketing plan was written.
    The first thing marketing money buys is otherwise an unanswerable question.
    """

    EVENT = "/api/auth/funnel/"
    SUMMARY = "/api/auth/funnel/summary/"

    def setUp(self):
        self.owner = User.objects.create_superuser("owner2", "o2@e.com", "hunter2hunter2")
        self.client = APIClient()

    def fire(self, kind, anon, src=None, **meta):
        body = {"kind": kind, "anon_id": anon, "meta": {**meta}}
        if src is not None:
            body["meta"]["src"] = src
        return self.client.post(self.EVENT, body, format="json")

    def summary(self):
        c = APIClient()
        c.force_authenticate(self.owner)
        return c.get(self.SUMMARY).data

    def test_a_source_is_stored_on_the_arrival(self):
        self.fire("landing_view", "a1", src="reddit")
        self.assertEqual(FunnelEvent.objects.get(kind="landing_view").meta["src"], "reddit")

    def test_a_source_is_a_channel_name_not_a_payload(self):
        # Short slug only. Anything else is somebody putting data in a URL.
        self.fire("landing_view", "a2", src="<script>alert(1)</script>")
        self.assertEqual(FunnelEvent.objects.get(kind="landing_view").meta, {})
        self.fire("landing_view", "a3", src="x" * 200)
        self.assertEqual(FunnelEvent.objects.filter(kind="landing_view").last().meta, {})

    def test_it_is_lowercased_so_two_spellings_are_one_channel(self):
        self.fire("landing_view", "a4", src="  Reddit  ")
        self.assertEqual(FunnelEvent.objects.last().meta["src"], "reddit")

    def test_the_summary_breaks_the_funnel_down_by_channel(self):
        # reddit sends people who score; flyer sends people who bounce. Those
        # need opposite responses, and one number cannot tell them apart.
        self.fire("landing_view", "r1", src="reddit")
        self.fire("try_scored", "r1", src="reddit")
        self.fire("landing_view", "f1", src="flyer")
        self.fire("landing_view", "f2", src="flyer")

        rows = {r["src"]: r for r in self.summary()["sources"]}
        self.assertEqual(rows["reddit"]["try_scored"], 1)
        self.assertEqual(rows["flyer"]["landing_view"], 2)
        self.assertEqual(rows["flyer"]["try_scored"], 0)

    def test_sources_are_ordered_by_how_many_people_they_sent(self):
        for i in range(3):
            self.fire("landing_view", f"b{i}", src="big")
        self.fire("landing_view", "s1", src="small")
        self.assertEqual([r["src"] for r in self.summary()["sources"]], ["big", "small"])

    def test_one_browser_is_one_person_per_channel(self):
        # Refreshing five times is not five people.
        for _ in range(5):
            self.fire("landing_view", "same", src="reddit")
        self.assertEqual(self.summary()["sources"][0]["landing_view"], 1)

    def test_untagged_traffic_is_still_counted_just_not_attributed(self):
        self.fire("landing_view", "u1")
        d = self.summary()
        self.assertEqual(d["steps"]["landing_view"]["unique"], 1)
        self.assertEqual(d["sources"], [])
        # And the empty list says which of the two problems it is.
        self.assertIn("Untagged", d["sources_note"])


class RecorderStepsTests(TestCase):
    """The trial recorder, measured.

    A month of this funnel read: 103 landed, 13 opened the trial, 1 got a
    score. Two rows for the step that loses 92% of everybody who wanted the
    product — and no way at all to tell a refused mic from a recorded take
    nobody sent from a take the coach failed. Three problems, three opposite
    fixes, one indistinguishable number.
    """

    def setUp(self):
        self.client = APIClient()

    def fire(self, kind, anon="v1", **meta):
        return self.client.post(
            EVENT, {"kind": kind, "anon_id": anon, "meta": meta}, format="json",
        )

    def test_each_recorder_step_is_a_kind_of_its_own(self):
        for kind in ("try_record", "try_mic_denied", "try_attach",
                     "try_send", "try_failed"):
            self.assertEqual(self.fire(kind, app_key="singz").status_code, 204, kind)
        self.assertEqual(FunnelEvent.objects.count(), 5)

    def test_the_camera_path_is_told_apart_from_the_mic(self):
        # A second permission and a file an order of magnitude bigger. A cliff
        # on one is not a cliff on the other, so they must not total together.
        self.fire("try_record", app_key="singz", video=True)
        self.assertEqual(FunnelEvent.objects.get().meta, {"app_key": "singz", "video": True})

    def test_a_failure_carries_a_reason_from_a_closed_list(self):
        self.fire("try_failed", app_key="rapz", why="too_big")
        self.assertEqual(FunnelEvent.objects.get().meta["why"], "too_big")

    def test_a_failure_reason_is_never_free_text(self):
        # The reason decides what gets fixed. Free text here would be the one
        # place a visitor's own words could land in this table.
        self.fire("try_failed", app_key="rapz", why="the coach said my singing was bad")
        self.assertNotIn("why", FunnelEvent.objects.get().meta)

    def test_every_kind_fits_the_column(self):
        # SQLite ignores varchar length and production is Postgres, so a kind
        # longer than the column is invisible locally and a 500 in production.
        from apps.economy.models import FUNNEL_KINDS
        width = FunnelEvent._meta.get_field("kind").max_length
        for kind, _ in FUNNEL_KINDS:
            self.assertLessEqual(len(kind), width, kind)


class HeadlineRateTests(TestCase):
    """The three rates the platform turns on, pinned rather than derived.

    Eleven step rows are a detail tab. Which of the three doors is shut is
    the whole decision, and reading it off the rows means doing arithmetic
    every time — which is how a funnel gets looked at once and never again.
    """

    def setUp(self):
        self.owner = User.objects.create_superuser("boss3", "b3@e.com", PW)

    def summary(self):
        c = APIClient()
        c.force_authenticate(self.owner)
        return c.get(SUMMARY).data

    def test_each_rate_carries_both_counts_and_not_only_a_percentage(self):
        # A rate with no denominator behind it is decoration: 100% of two
        # people is not a working funnel.
        FunnelEvent.objects.create(kind="landing_view", anon_id="a")
        FunnelEvent.objects.create(kind="landing_view", anon_id="b")
        FunnelEvent.objects.create(kind="try_view", anon_id="a")

        row = {r["key"]: r for r in self.summary()["headline"]}["try_view"]
        self.assertEqual((row["from"], row["to"]), (2, 1))
        self.assertEqual(row["pct"], 50.0)

    def test_an_empty_step_reads_as_no_measurement_not_as_zero_percent(self):
        # 0% against nobody reads as a broken product. It is an empty
        # measurement, and the two need opposite responses.
        row = {r["key"]: r for r in self.summary()["headline"]}["try_scored"]
        self.assertEqual((row["from"], row["to"]), (0, 0))
        self.assertIsNone(row["pct"])

    def test_the_three_are_the_three_that_decide_what_to_work_on(self):
        self.assertEqual([r["key"] for r in self.summary()["headline"]],
                         ["try_view", "try_scored", "register_success"])


class RegisterAttributionTests(TestCase):
    """A registration has to name the channel that produced it.

    `register_success` was shaped as "registered" — not a kind — so its `src`
    was dropped on the way in and the per-channel table's register column was
    structurally always zero. The one number a marketing spend is judged on
    could not be non-zero however well the channel worked.
    """

    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_superuser("boss4", "b4@e.com", PW)

    def fire(self, kind, anon, src):
        return self.client.post(
            EVENT, {"kind": kind, "anon_id": anon, "meta": {"src": src}}, format="json",
        )

    def test_a_registration_keeps_its_channel(self):
        self.fire("register_success", "r1", "reddit")
        self.assertEqual(FunnelEvent.objects.get().meta, {"src": "reddit"})

    def test_the_channel_table_can_show_a_registration(self):
        self.fire("landing_view", "r1", "reddit")
        self.fire("register_success", "r1", "reddit")
        c = APIClient()
        c.force_authenticate(self.owner)
        rows = {r["src"]: r for r in c.get(SUMMARY).data["sources"]}
        self.assertEqual(rows["reddit"]["register_success"], 1)

    def test_a_login_keeps_its_channel_too(self):
        self.fire("login_success", "r2", "flyer")
        self.assertEqual(FunnelEvent.objects.get().meta, {"src": "flyer"})


class DeviceShapeTests(TestCase):
    """What kind of screen a step happened on.

    The trial's first move is a browser mic dialog. A permission cliff on a
    phone is not a cliff on a laptop, and one number covering both hides
    whichever of the two is the actual problem — which is the position this
    funnel was in for its whole life.
    """

    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_superuser("boss5", "b5@e.com", PW)

    def fire(self, kind, anon, dev):
        return self.client.post(
            EVENT, {"kind": kind, "anon_id": anon, "meta": {"dev": dev}}, format="json",
        )

    def summary(self):
        c = APIClient()
        c.force_authenticate(self.owner)
        return c.get(SUMMARY).data

    def test_a_shape_is_stored_on_any_step(self):
        # Ambient: true of the visit, not of the step, so it rides every kind.
        self.fire("landing_view", "d1", "phone")
        self.fire("register_success", "d1", "phone")
        self.assertEqual(FunnelEvent.objects.filter(meta__dev="phone").count(), 2)

    def test_only_the_three_shapes_are_accepted(self):
        # Anything else is a user agent by another name.
        self.fire("landing_view", "d2", "iPhone15,3")
        self.assertEqual(FunnelEvent.objects.get().meta, {})

    def test_the_summary_splits_the_funnel_by_screen(self):
        # Phones open the trial and never score; desktops score. Those are
        # two different bugs and one number cannot tell them apart.
        self.fire("try_view", "p1", "phone")
        self.fire("try_view", "p2", "phone")
        self.fire("try_view", "w1", "desktop")
        self.fire("try_scored", "w1", "desktop")

        rows = {r["dev"]: r for r in self.summary()["devices"]}
        self.assertEqual(rows["phone"]["try_view"], 2)
        self.assertEqual(rows["phone"]["try_scored"], 0)
        self.assertEqual(rows["desktop"]["try_scored"], 1)

    def test_an_unshaped_visit_is_counted_in_the_steps_but_not_the_split(self):
        self.client.post(EVENT, {"kind": "landing_view", "anon_id": "old"}, format="json")
        d = self.summary()
        self.assertEqual(d["steps"]["landing_view"]["unique"], 1)
        self.assertEqual(d["devices"], [])
        self.assertIn("user agent", d["devices_note"])


class MemberShapeTests(TestCase):
    """Who actually joined — genders and age bands, off Profile.

    Deliberately not part of the funnel rows: a FunnelEvent is a browser with
    no account, so it has no age and no gender, and attaching either would
    break the promise that nothing here is joined against Users.
    """

    def setUp(self):
        self.owner = User.objects.create_superuser("boss6", "b6@e.com", PW)

    def member(self, name, gender="", birthday=""):
        from apps.economy.models import profile_for
        u = User.objects.create_user(username=name, email=f"{name}@e.com", password=PW)
        p = profile_for(u)
        p.gender, p.birthday = gender, birthday
        p.save()
        return u

    def summary(self):
        c = APIClient()
        c.force_authenticate(self.owner)
        return c.get(SUMMARY).data["members"]

    def test_the_denominator_travels_with_the_split(self):
        # Percentages of two people are not a demographic, and `total` is what
        # says so on a platform this size.
        self.member("m1", "woman", "1995-04-02")
        d = self.summary()
        self.assertEqual(d["total"], User.objects.count())

    def test_blanks_are_a_row_not_a_rounding_error(self):
        # A split over the members who filled it in, shown as the membership,
        # describes nobody.
        self.member("m2", "man", "1990-01-01")
        self.member("m3")
        genders = {r["gender"]: r["members"] for r in self.summary()["genders"]}
        self.assertEqual(genders["man"], 1)
        self.assertGreaterEqual(genders["unset"], 1)

    def test_an_age_is_a_band_and_never_a_date(self):
        import datetime
        born = datetime.date.today().replace(year=datetime.date.today().year - 30)
        self.member("m4", "", born.isoformat())
        bands = {r["band"]: r["members"] for r in self.summary()["ages"]}
        self.assertEqual(bands["25-34"], 1)
        # Nothing in the payload is a birthday.
        self.assertNotIn("birthday", str(self.summary()))

    def test_a_missing_birthday_lands_in_unset_not_in_a_band(self):
        self.member("m5", "man")
        bands = {r["band"]: r["members"] for r in self.summary()["ages"]}
        self.assertGreaterEqual(bands["unset"], 1)
        self.assertEqual(sum(bands.values()), self.summary()["total"])


class MicRefusalReasonTests(TestCase):
    """"Denied" was the only story, and usually the wrong one.

    getUserMedia fails for reasons that need opposite answers: a permission
    genuinely refused, a device that does not exist, a camera another app is
    holding, constraints we asked for that this hardware cannot meet, and a
    page that is not on https. Reporting all five as "access was refused"
    sends somebody to re-grant a permission they already granted.
    """

    def setUp(self):
        self.client = APIClient()

    def fire(self, why):
        return self.client.post(EVENT, {
            "kind": "try_mic_denied", "anon_id": "v1",
            "meta": {"app_key": "rapz", "video": True, "why": why},
        }, format="json")

    def test_each_real_cause_is_stored(self):
        for why in ("denied", "notfound", "inuse", "constrained", "insecure", "other"):
            self.fire(why)
        stored = {e.meta.get("why") for e in FunnelEvent.objects.all()}
        self.assertEqual(stored, {"denied", "notfound", "inuse", "constrained",
                                  "insecure", "other"})

    def test_an_invented_reason_is_dropped(self):
        self.fire("NotReadableError: could not start video source")
        self.assertNotIn("why", FunnelEvent.objects.get().meta)


class TheShutDoorIsAStepTests(TestCase):
    """18 opened the trial and 1 started the recorder, and nothing could say
    whether the other 17 were uninterested or were told no.

    `available: false` hides EVERY control on the trial — upload, mic and
    camera all vanish — so a refused visitor and a bored one produced the
    same two rows: a try_view and nothing after it. They need opposite fixes,
    one a product problem and one a cap set wrong."""

    def setUp(self):
        self.c = APIClient()

    def send(self, why=None):
        meta = {"app_key": "singz"}
        if why is not None:
            meta["why"] = why
        return self.c.post("/api/auth/funnel/",
                           {"kind": "try_blocked", "anon_id": "vis-1", "meta": meta},
                           format="json")

    def test_the_kind_is_accepted(self):
        from .models import FunnelEvent
        self.assertEqual(self.send("cap_reached").status_code, 204)
        self.assertEqual(FunnelEvent.objects.filter(kind="try_blocked").count(), 1)

    def test_each_no_is_kept_apart(self):
        """already_used is the per-IP window, cap_reached is the platform's
        daily ceiling, not_configured is a missing key. One row saying
        'blocked' sends somebody to fix whichever they guessed."""
        from .models import FunnelEvent
        for why in ("already_used", "cap_reached", "not_configured"):
            self.send(why)
        got = {e.meta.get("why") for e in FunnelEvent.objects.filter(kind="try_blocked")}
        self.assertEqual(got, {"already_used", "cap_reached", "not_configured"})

    def test_a_reason_outside_the_list_is_dropped_not_stored(self):
        """A closed list, like try_failed's — free text is how a table holding
        no PII starts holding some."""
        from .models import FunnelEvent
        self.send("because i said so")
        e = FunnelEvent.objects.get(kind="try_blocked")
        self.assertNotIn("why", e.meta)

    def test_it_appears_in_the_owner_summary(self):
        from django.contrib.auth import get_user_model
        self.send("cap_reached")
        owner = get_user_model().objects.create_superuser(
            "fowner", "fowner@mcz.test", "hunter2hunter2")
        c = APIClient()
        c.force_authenticate(owner)
        r = c.get("/api/auth/funnel/summary/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("try_blocked", r.data["steps"])
        self.assertEqual(r.data["steps"]["try_blocked"]["unique"], 1)


class WhatHappensAfterTheAccountTests(TestCase):
    """Ten kinds were being fired by live screens and refused as unknown.

    `track()` is fire-and-forget with a swallowed `.catch`, so every one of
    them was a 400 nobody could see — the same failure the recorder kinds were
    added to fix, four months later and eleven times over. A closed set catches
    a typo and cannot catch an omission: the client looks identical either way.

    Five are kept because they measure something this funnel could not see —
    it ended at "account created", and an account that never finishes
    onboarding is a row rather than a member. The other six were engagement
    telemetry on a table whose whole promise is that it is never joined to a
    User, and they were deleted at the call site instead."""

    def setUp(self):
        self.c = APIClient()

    def send(self, kind, meta=None):
        return self.c.post("/api/auth/funnel/",
                           {"kind": kind, "anon_id": "vis-1", "meta": meta or {}},
                           format="json")

    def test_the_onboarding_steps_are_accepted(self):
        for kind in ("onboard_habit", "onboard_skip",
                     "onboard_prefs"):
            self.assertEqual(self.send(kind).status_code, 204, kind)

    def test_the_link_steps_are_accepted(self):
        for kind in ("oauth_linked", "oauth_link_fail"):
            self.assertEqual(self.send(kind).status_code, 204, kind)

    def test_a_habit_keeps_its_instrument_and_cadence(self):
        self.send("onboard_habit",
                  {"app_key": "rapz", "frequency": "weekly"})
        e = FunnelEvent.objects.get(kind="onboard_habit")
        self.assertEqual(e.meta.get("app_key"), "rapz")
        self.assertEqual(e.meta.get("frequency"), "weekly")

    def test_a_cadence_outside_the_model_is_dropped(self):
        """`Habit.FREQUENCY_CHOICES` is the one list. A funnel that accepted
        "hourly" would be storing a cadence no habit can have."""
        self.send("onboard_habit",
                  {"app_key": "rapz", "frequency": "hourly"})
        self.assertNotIn("frequency",
                         FunnelEvent.objects.get(kind="onboard_habit").meta)

    def test_only_the_notification_switch_survives_the_preferences_step(self):
        """Language and sound are settings rather than steps. A funnel row that
        carries every preference a screen collects stops being a funnel."""
        self.send("onboard_prefs",
                  {"notifications_enabled": True, "language": "es",
                   "sound_enabled": False})
        e = FunnelEvent.objects.get(kind="onboard_prefs")
        self.assertEqual(e.meta.get("notifications_enabled"), True)
        self.assertNotIn("language", e.meta)
        self.assertNotIn("sound_enabled", e.meta)

    def test_a_provider_comes_from_the_one_provider_list(self):
        """Not a tuple typed into the view. The first draft of this typed the
        eight names in and got it wrong immediately — it listed "apple", which
        `provider_requirements()` has commented out, so the funnel would have
        accepted a step no button on the platform can fire."""
        from apps.accounts.oauth import provider_requirements
        known = sorted(provider_requirements())
        self.assertTrue(known)
        for name in known:
            self.send("oauth_linked", {"provider": name})
        stored = {e.meta.get("provider")
                  for e in FunnelEvent.objects.filter(kind="oauth_linked")}
        self.assertEqual(stored, set(known))
        self.assertNotIn("apple", known)

    def test_a_link_failure_never_stores_the_error_text(self):
        """The client sends `error: linkErr.message`, which is whatever the
        server or the network said — free text, on a table that holds no PII."""
        self.send("oauth_link_fail",
                  {"provider": "spotify", "error": "That email belongs to bob@x.com"})
        e = FunnelEvent.objects.get(kind="oauth_link_fail")
        self.assertEqual(e.meta.get("provider"), "spotify")
        self.assertNotIn("error", e.meta)

    def test_every_new_kind_still_fits_the_column(self):
        from .models import FUNNEL_KINDS, FunnelEvent as FE
        width = FE._meta.get_field("kind").max_length
        for key, _label in FUNNEL_KINDS:
            self.assertLessEqual(len(key), width, key)
