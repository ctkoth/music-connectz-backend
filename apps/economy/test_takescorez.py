"""The coach's memory, and the four ways it could lie.

The feature is a table and some arithmetic, so the interesting tests are not
"does it add up". They are the places where keeping a history makes it possible
to say something that isn't true, which is the failure this codebase already
knows the shape of — `directz_ai_rating` was a number derived from form
completeness, and it survived because nobody could check it.

So what is pinned here:

  1. **Nothing is scored out of nothing.** Every history finding returns None
     with a reason below its minimum, never a zero. An empty measurement and a
     bad one need opposite responses.
  2. **A range is parsed conservatively or not at all.** The prompt tells the
     coach to say when a take is too short to read a range from; a parser that
     guessed from that sentence would put the lie back in.
  3. **Strain is derived, so recovery clears itself.** No counter, no reset,
     and a rolling window that a quiet three days genuinely ends.
  4. **The safety block is not a tier feature.** No membership lifts it, which
     is the blueprint's rule rather than a preference.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from . import takescorez as T
from .instruments import profile_for_app
from .models import InstrumentProfile, TakeScore

User = get_user_model()


def member(name):
    return User.objects.create_user(name, f"{name}@mcz.test", "pw12345!")


def scored(user, app_key="singz", *, days_ago=0, hours_ago=0, **dims):
    """One kept take, backdated. `created_at` is auto_now_add, so it is moved
    with an UPDATE — a save() would stamp it now again."""
    row = TakeScore.objects.create(
        user=user, app_key=app_key, scores=dims,
        overall=round(sum(dims.values()) / len(dims)) if dims else None,
        weakest=min(dims, key=lambda k: dims[k]) if dims else "")
    if days_ago or hours_ago:
        TakeScore.objects.filter(pk=row.pk).update(
            created_at=timezone.now() - timedelta(days=days_ago, hours=hours_ago))
        row.refresh_from_db()
    return row


class ParseRangeTests(TestCase):
    RANGES = profile_for_app("singz")["ranges"]

    def test_it_reads_a_class_and_two_edges(self):
        cls, low, high = T.parse_range("Your range reads Baritone, G2 to E4.", self.RANGES)
        self.assertEqual((cls, low, high), ("baritone", "G2", "E4"))

    def test_a_take_too_short_to_tell_parses_to_nothing(self):
        """The coach is told to say this instead of guessing. A parser that
        found a range in it would put the guess back."""
        cls, low, high = T.parse_range(
            "This take is too short to read a range from.", self.RANGES)
        self.assertEqual((cls, low, high), ("", "", ""))

    def test_two_notes_less_than_an_octave_apart_are_not_a_range(self):
        """Far more likely an example than a range, and nothing anybody should
        build a warm-up around."""
        _, low, high = T.parse_range("You lost the pocket around C4 and E4.", self.RANGES)
        self.assertEqual((low, high), ("", ""))

    def test_accidentals_and_the_widest_span_win(self):
        _, low, high = T.parse_range("From F#2 up through A3 and topping out at C5.",
                                     self.RANGES)
        self.assertEqual((low, high), ("F#2", "C5"))

    def test_an_instrument_with_no_ranges_reads_no_class(self):
        cls, _, _ = T.parse_range("Bass drum was heavy.", profile_for_app("drumz")["ranges"])
        self.assertEqual(cls, "")


class RecordTests(TestCase):
    def setUp(self):
        self.u = member("recorder")

    def _payload(self, **scores):
        return {"score": 7, "scores": scores, "range_profile": "Reads Tenor, C3 to A4."}

    def test_it_keeps_the_scores_the_overall_and_the_weakest(self):
        row = T.record(self.u, "singz", self._payload(pitch=8, tone=7, breath=4,
                                                      range=6, agility=5))
        self.assertEqual(row.overall, 6)
        self.assertEqual(row.weakest, "breath")
        self.assertEqual(row.range_class, "tenor")

    def test_a_dimension_this_instrument_does_not_have_is_dropped(self):
        """A key the model invents must not reach a column, the same guard the
        payload already passes through in score_take."""
        row = T.record(self.u, "drumz", self._payload(timing=8, vibe=10))
        self.assertNotIn("vibe", row.scores)
        self.assertIn("timing", row.scores)

    def test_a_take_with_no_scored_dimension_stores_null_not_zero(self):
        row = T.record(self.u, "singz", {"scores": {}})
        self.assertIsNone(row.overall)

    def test_a_logged_out_take_is_not_recorded(self):
        """The trial has no member to remember."""
        self.assertIsNone(T.record(None, "singz", self._payload(pitch=8)))


class ThinHistoryTests(TestCase):
    """Below the minimum, every finding is None WITH A REASON — never a zero.

    This is the substance rule's own failure case in reverse: a fake number
    ends the question an empty one invites, and here the empty one comes with
    the sentence that says what would fill it.
    """

    def setUp(self):
        self.u = member("thin")

    def test_weakest_says_a_bad_day_is_not_a_weak_spot(self):
        scored(self.u, pitch=3, tone=9)
        out = T.weakest(self.u, "singz")
        self.assertEqual(out["key"], "")
        self.assertIn("bad day", out["why"])

    def test_consistency_is_none_not_zero(self):
        out = T.consistency(self.u, "singz")
        self.assertIsNone(out["score"])
        self.assertTrue(out["why"])

    def test_a_trend_through_two_dots_is_not_drawn(self):
        for _ in range(3):
            scored(self.u, pitch=5, tone=5, breath=5, range=5, agility=5)
        out = T.trend(self.u, "singz")
        self.assertEqual(out["rows"], [])
        self.assertIn("two dots", out["why"])

    def test_goal_match_with_no_goal_offers_the_control_that_sets_one(self):
        out = T.goal_match(self.u, "singz")
        self.assertIsNone(out["score"])
        self.assertEqual(out["open_in"], {"tab": "singz", "target": "singz:goal"})

    def test_detected_says_why_rather_than_naming_a_range(self):
        self.assertEqual(T.detected(self.u, "singz")["range"], "")
        self.assertTrue(T.detected(self.u, "singz")["why"])


class FindingsTests(TestCase):
    def setUp(self):
        self.u = member("deep")

    def test_the_weakest_dimension_is_the_repeated_one(self):
        for n in range(6):
            scored(self.u, days_ago=n, pitch=9, tone=8, breath=3, range=7, agility=8)
        out = T.weakest(self.u, "singz")
        self.assertEqual(out["key"], "breath")
        self.assertEqual(out["label"], "Breath 🫁")

    def test_a_trend_carries_both_counts(self):
        """100% of two people is not a working funnel, and a dimension that
        moved from one take to one take has not moved."""
        for n in range(8):
            scored(self.u, days_ago=8 - n, pitch=4 if n < 4 else 8,
                   tone=6, breath=6, range=6, agility=6)
        rows = {r["key"]: r for r in T.trend(self.u, "singz")["rows"]}
        self.assertEqual(rows["pitch"]["was"], 4.0)
        self.assertEqual(rows["pitch"]["now"], 8.0)
        self.assertEqual(rows["pitch"]["was_n"], 4)

    def test_consistency_counts_days_not_takes(self):
        """Ten takes in one afternoon is one day of showing up."""
        for _ in range(10):
            scored(self.u, pitch=7, tone=7, breath=7, range=7, agility=7)
        out = T.consistency(self.u, "singz")
        self.assertEqual(out["days"], 1)
        self.assertEqual(out["score"], 1)

    def test_detected_is_the_most_recent_readable_take(self):
        old = TakeScore.objects.create(user=self.u, app_key="singz", range_class="bass")
        TakeScore.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=5))
        TakeScore.objects.create(user=self.u, app_key="singz", range_class="")
        TakeScore.objects.create(user=self.u, app_key="singz", range_class="tenor",
                                 low_note="C3", high_note="A4")
        self.assertEqual(T.detected(self.u, "singz")["range"], "tenor")

    def test_the_declaration_never_becomes_the_measurement(self):
        """A member says what they are after; the coach says what it heard.
        Collapsing them is how a goal quietly turns into a finding."""
        InstrumentProfile.objects.create(user=self.u, app_key="singz",
                                         goal_range="soprano")
        scored(self.u, pitch=7)
        TakeScore.objects.filter(user=self.u).update(range_class="bass")
        self.assertEqual(T.detected(self.u, "singz")["range"], "bass")
        self.assertEqual(T.bridge(self.u, "singz")["to"], "soprano")
        self.assertFalse(T.bridge(self.u, "singz")["same"])


class StrainTests(TestCase):
    def setUp(self):
        self.u = member("tired")

    def _lows(self, n, **kw):
        for i in range(n):
            scored(self.u, hours_ago=i, pitch=8, tone=8, breath=2, range=8, agility=8, **kw)

    def test_three_low_breath_takes_is_strain(self):
        self._lows(3)
        self.assertEqual(T.strain(self.u, "singz")["level"], "strain")

    def test_two_is_a_warning_that_says_what_comes_next(self):
        self._lows(2)
        out = T.strain(self.u, "singz")
        self.assertEqual(out["level"], "watch")
        self.assertIn("One more", out["why"])

    def test_a_low_delivery_is_a_performance_note_not_a_health_one(self):
        """Somebody sounding bored must not be put into recovery."""
        for i in range(5):
            scored(self.u, "rapz", hours_ago=i, flow=8, timing=8, breath=9,
                   clarity=8, delivery=2)
        self.assertEqual(T.strain(self.u, "rapz")["level"], "clear")

    def test_it_clears_itself_because_the_window_rolls(self):
        """No counter, so nothing has to remember to reset. Three quiet days
        genuinely end it."""
        for i in range(4):
            scored(self.u, days_ago=5 + i, pitch=8, tone=8, breath=2, range=8, agility=8)
        self.assertEqual(T.strain(self.u, "singz")["level"], "clear")

    def test_sensitivity_moves_the_threshold_and_nothing_else(self):
        InstrumentProfile.objects.create(user=self.u, app_key="singz",
                                         fatigue_sensitivity="high")
        self._lows(2)
        self.assertEqual(T.strain(self.u, "singz")["level"], "strain")

    def test_an_instrument_with_no_strain_signal_says_unmeasured(self):
        """A clean bill of health nobody examined is worse than none."""
        out = T.strain(member("drummer"), "drumz")
        self.assertEqual(out["level"], "unmeasured")
        self.assertIsNone(T.voice_health(member("drummer2"), "drumz")["score"])

    def test_voice_health_tracks_strain(self):
        self._lows(3)
        self.assertEqual(T.voice_health(self.u, "singz")["score"], 3)
        self.assertEqual(T.voice_health(member("fresh"), "singz")["score"], 10)


class RecoveryBlockTests(TestCase):
    def setUp(self):
        self.u = member("pushing")
        for i in range(3):
            scored(self.u, hours_ago=i, pitch=8, tone=8, breath=2, range=8, agility=8)

    def test_the_hard_difficulties_are_held_back(self):
        out = T.recovery_block(self.u, "singz", "stageboss")
        self.assertIsNotNone(out)
        self.assertEqual(out["allowed"], ["starter", "builder"])

    def test_it_never_blocks_the_take_itself(self):
        """A limit that says whether rather than how much is a door out — and
        here it is also the wrong safety answer."""
        self.assertIsNone(T.recovery_block(self.u, "singz", "builder"))
        self.assertIsNone(T.recovery_block(self.u, "singz", "starter"))

    def test_no_tier_lifts_it(self):
        """The blueprint's rule, not a preference: automation and AI features
        may not override recovery warnings. So this asks about strain and never
        about membership — pinned because a tier check here would look like a
        courtesy to whoever added it."""
        from .models import membership_for
        m = membership_for(self.u)
        m.tier = "statz"
        m.save(update_fields=["tier"])
        self.assertIsNotNone(T.recovery_block(self.u, "singz", "performer"))
        import inspect
        src = inspect.getsource(T.recovery_block)
        self.assertNotIn("tier", src.split('"""')[2])

    def test_a_rested_member_is_not_blocked(self):
        self.assertIsNone(T.recovery_block(member("rested"), "singz", "stageboss"))


class ApiTests(TestCase):
    def setUp(self):
        self.u = member("apiuser")
        self.c = APIClient()
        self.c.force_authenticate(self.u)

    def test_progress_is_mounted_for_every_instrument(self):
        from music_connectz.urls import INSTRUMENT_APP_KEYS
        for key in INSTRUMENT_APP_KEYS:
            r = self.c.get(f"/api/{key}/progress/")
            self.assertEqual(r.status_code, 200, key)
            self.assertEqual(r.data["app_key"], key)

    def test_it_needs_an_account(self):
        self.assertEqual(APIClient().get("/api/singz/progress/").status_code, 401)

    def test_a_goal_is_stored_and_comes_back_on_the_progress_screen(self):
        r = self.c.post("/api/singz/goal/", {"goal_range": "tenor",
                                             "fatigue_sensitivity": "high"}, format="json")
        self.assertEqual(r.data["declared"]["goal_range"], "tenor")
        self.assertEqual(r.data["declared"]["fatigue_sensitivity"], "high")

    def test_junk_clears_rather_than_refusing_the_save(self):
        """A profile write must not 400 over one bad value — and a wrong range
        silently kept is worse than a blank."""
        r = self.c.post("/api/singz/goal/", {"goal_range": "wizard"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["declared"]["goal_range"], "")

    def test_a_bpm_outside_anything_playable_is_dropped(self):
        r = self.c.post("/api/rapz/goal/", {"bpm_low": 80, "bpm_high": 9000}, format="json")
        self.assertEqual(r.data["declared"]["bpm_low"], 80)
        self.assertIsNone(r.data["declared"]["bpm_high"])

    def test_goals_do_not_leak_between_instruments(self):
        self.c.post("/api/singz/goal/", {"goal_range": "alto"}, format="json")
        self.assertEqual(self.c.get("/api/rapz/progress/").data["declared"]["goal_range"], "")

    def test_the_progress_screen_carries_the_three_history_scores(self):
        h = self.c.get("/api/singz/progress/").data["history_scores"]
        for k in ("consistency", "voice_health", "goal_match"):
            self.assertIn(k, h)
            self.assertIn("why", h[k])

    def test_a_take_leads_back_to_where_it_came_from(self):
        TakeScore.objects.create(user=self.u, app_key="singz", source="post",
                                 ref="post:12", overall=7)
        row = self.c.get("/api/singz/progress/").data["takes"][0]
        self.assertEqual(row["open_in"], {"tab": "postz", "target": "post:12"})

    def test_reading_progress_does_not_create_a_row(self):
        """get_or_create on a GET is a write on a read, and a table with an
        empty row for everybody who opened a coach is a table of nothing."""
        self.c.get("/api/singz/progress/")
        self.assertFalse(InstrumentProfile.objects.exists())


class ColumnWidthTests(TestCase):
    """Every string this code can write, against the column it goes in.

    The dullest test in the file and the one that earns its place: the suite
    runs on SQLite, **SQLite ignores varchar length**, and `build.sh` runs
    `migrate --no-input` on every deploy — so a column one character too
    narrow is invisible here and a 500 on Render, on a write nobody made until
    a member did. CLAUDE.md says a migration touching field widths gets
    checked against real Postgres before it reaches main; this is what can be
    checked from anywhere, every time, rather than once by hand.

    It covers the two new model families together because they were added in
    the same pass and share the same failure: a value that grew past a width
    nobody re-derived.
    """

    def _fits(self, model, field, values, label):
        width = model._meta.get_field(field).max_length
        for v in values:
            self.assertLessEqual(
                len(str(v)), width,
                f"{model.__name__}.{field} is {width} but {label} can write "
                f"{len(str(v))} chars: {v!r}")

    def test_every_range_and_sensitivity_key_fits(self):
        from .instruments import DIFFICULTIES, INSTRUMENTS, VOCAL_RANGES
        keys = [k for k, _ in VOCAL_RANGES]
        for field in ("range_class",):
            self._fits(TakeScore, field, keys, "a vocal range key")
        for field in ("confirmed_range", "goal_range"):
            self._fits(InstrumentProfile, field, keys, "a vocal range key")
        self._fits(InstrumentProfile, "fatigue_sensitivity",
                   [k for k, _ in InstrumentProfile.SENSITIVITY], "a sensitivity key")
        self._fits(TakeScore, "difficulty", DIFFICULTIES, "a difficulty")
        # `weakest` holds a scoring dimension key, from every instrument.
        dims = {k for p in INSTRUMENTS.values() for k in p["scores"]}
        self._fits(TakeScore, "weakest", dims, "a scoring dimension key")
        self._fits(TakeScore, "app_key", INSTRUMENTS, "an instrument key")

    def test_a_note_name_fits(self):
        """The widest a parsed note can be: letter, accidental, octave."""
        self._fits(TakeScore, "low_note", ["A#8", "Gb0"], "a parsed note")
        self._fits(TakeScore, "high_note", ["A#8", "Gb0"], "a parsed note")

    def test_every_source_label_fits(self):
        self._fits(TakeScore, "source", ["post", "journal", "upload"], "a take source")

    def test_every_lilith_choice_and_payout_kind_fits(self):
        from .models import BUCKETS, KINDS, LilithPayout, LilithSponsorship, LilithTask, SOURCES
        from . import lilith_taskz as L
        self._fits(LilithTask, "kind", [k for k, _ in KINDS], "a task kind")
        self._fits(LilithTask, "bucket", [k for k, _ in BUCKETS], "a bucket")
        self._fits(LilithTask, "source", [k for k, _ in SOURCES], "a task source")
        # Every kind `_pay` is ever called with, including the two passed as
        # bare strings rather than constants — which are exactly the ones a
        # width check by eye misses.
        kinds = [LilithPayout.KIND_SELF, LilithPayout.KIND_MILESTONE,
                 LilithPayout.KIND_SPONSOR, LilithPayout.KIND_HELP,
                 "task_xp", "collab_beginner"]
        self._fits(LilithPayout, "kind", kinds, "a payout kind")
        # And every refusal sentence, which is the widest free-ish text here.
        self._fits(LilithSponsorship, "refused",
                   ["graduated with the helper", "accounts strongly linked",
                    "sponsorship older than the new-member window"],
                   "a refusal reason")

    def test_the_voice_lines_fit_nothing_narrower_than_they_are(self):
        """VOICE is served, not stored — pinned so that stays true. The day a
        line is written to a column, this test is the one that fails."""
        from . import lilith_taskz as L
        from .models import LilithPayout
        self.assertFalse(
            any(f.name == "said" for f in LilithPayout._meta.get_fields()),
            "A VOICE line reached a column — give it a width and check it here.")
        self.assertTrue(all(isinstance(v, str) for v in L.VOICE.values()))
