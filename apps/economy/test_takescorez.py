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
        # The overall is the number the member was SHOWN (the payload's 7), not the
        # plain mean of the dimensions (6) — the history must not disagree with the
        # score they were just given.
        self.assertEqual(row.overall, 7)
        self.assertEqual(row.weakest, "breath")
        self.assertEqual(row.range_class, "tenor")

    def test_with_no_shown_score_the_mean_is_the_fallback(self):
        row = T.record(self.u, "singz", {"scores": {"pitch": 8, "tone": 4}})
        self.assertEqual(row.overall, 6)

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

    def test_the_setting_says_what_each_choice_does_from_the_rule_itself(self):
        """The screen was explained as a mechanism ("eases you off the hard settings")
        and never as a result. Every number in the sentence is the rule's own."""
        out = T.progress(self.u, "singz")
        rows = {r["key"]: r for r in out["sensitivities"]}
        for key, n in T.THRESHOLD.items():
            self.assertEqual(rows[key]["lows_needed"], n)
            self.assertIn(f"after {n} low", rows[key]["result"])
            self.assertIn("Performer and Stage Boss", rows[key]["result"])
        rule = out["strain_rule"]
        self.assertEqual(rule["low_at"], T.LOW_AT)
        self.assertEqual(rule["days"], T.WINDOW_HOURS // 24)
        self.assertIn("Breath or Range", rule["summary"])
        self.assertIn("never changes a score", rule["never"])
        # the keys older clients read are still there
        self.assertTrue(all("key" in r and "label" in r for r in out["sensitivities"]))

    def test_an_instrument_with_no_strain_signal_has_no_rule_to_explain(self):
        out = T.progress(member("drummer3"), "drumz")
        self.assertEqual(out["strain_rule"], {})
        self.assertTrue(out["sensitivities"])  # still the plain list, as before

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

    def _keys(self, row):
        return {e["key"]: e for e in row["exports"]}

    def test_every_recent_take_can_go_to_postz_messagez_and_journalz(self):
        TakeScore.objects.create(user=self.u, app_key="rapz", overall=6, genre="Trap",
                                 scores={"flow": 6, "punchlines": 4}, weakest="punchlines",
                                 read={"verdict": "Locked in on the beat.", "strengths": ["Cadence"],
                                       "fixes": ["Land the last bar"], "exact": 6.2})
        row = self.c.get("/api/rapz/progress/").data["takes"][0]
        ex = self._keys(row)
        for k in ("postz", "messagez", "journalz", "drills"):
            self.assertIn(k, ex)
        self.assertEqual(ex["postz"]["tab"], "postz")
        body = ex["postz"]["carry"]["description"]
        self.assertIn("Locked in on the beat.", body)
        self.assertIn("Land the last bar", body)
        self.assertIn("6.2/10", ex["postz"]["carry"]["title"])        # the number they were shown
        self.assertEqual(ex["messagez"]["carry"], ex["postz"]["carry"])  # one wording, every door
        self.assertEqual(row["exact"], 6.2)

    def test_the_punchline_writer_is_offered_only_where_punchlines_are_low_and_says_its_price(self):
        TakeScore.objects.create(user=self.u, app_key="rapz", overall=6, scores={"punchlines": 4})
        TakeScore.objects.create(user=self.u, app_key="rapz", overall=6, scores={"punchlines": 8})
        rows = self.c.get("/api/rapz/progress/").data["takes"]
        low = [r for r in rows if r["scores"]["punchlines"] == 4][0]
        high = [r for r in rows if r["scores"]["punchlines"] == 8][0]
        self.assertNotIn("punchlines", self._keys(high))
        pl = self._keys(low)["punchlines"]
        self.assertEqual(pl["carry"]["kind"], "punchlines")
        self.assertEqual(pl["cost"]["resource"], "promptz")            # price before the press
        self.assertIn("royalty", pl["note"])
        self.assertIn("not charged", pl["note"])

    def test_a_battle_door_exists_only_for_a_take_that_came_from_a_post(self):
        TakeScore.objects.create(user=self.u, app_key="singz", overall=7, source="post", ref="post:12")
        TakeScore.objects.create(user=self.u, app_key="singz", overall=7, source="upload")
        a, b = self.c.get("/api/singz/progress/").data["takes"]
        by_ref = {r["open_in"] is not None: r for r in (a, b)}
        self.assertEqual(self._keys(by_ref[True])["battlez"]["carry"], {"kind": "post", "post_id": 12})
        self.assertNotIn("battlez", self._keys(by_ref[False]))

    def test_the_history_shows_the_score_the_member_was_given_not_the_mean(self):
        payload = {"score": 7, "score_exact": 7.4, "scores": {"flow": 5, "timing": 5, "hookz_unused": 9},
                   "verdict": "v", "strengths": ["s"], "fixes": ["f"],
                   "lyrics_read": "THE MEMBER'S OWN WORDS", "hook_score": 10}
        row = T.record(self.u, "rapz", payload)
        self.assertEqual(row.overall, 7)                               # not the mean (5)
        self.assertEqual(row.read["exact"], 7.4)
        self.assertEqual(row.read["hook"], 10)
        self.assertNotIn("THE MEMBER'S OWN WORDS", str(row.read))      # the words are not kept

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


class GameProfileTests(TestCase):
    """`/api/<key>/profile/` — the endpoint two panels had been calling since
    they were written.

    It 404'd, a bare `.catch(() => {})` swallowed it, and the RapZ and SingZ
    game profiles rendered nothing at all. Every value it serves already
    existed somewhere; only the door was missing. That is the same shape as the
    five trial coaches nothing linked to, and it is why the tab sweep that
    found it is worth keeping.
    """

    def setUp(self):
        self.u = member("gamer")
        self.c = APIClient()
        self.c.force_authenticate(self.u)

    def test_it_is_mounted_for_every_instrument(self):
        from music_connectz.urls import INSTRUMENT_APP_KEYS
        for key in INSTRUMENT_APP_KEYS:
            r = self.c.get(f"/api/{key}/profile/")
            self.assertEqual(r.status_code, 200, key)
            self.assertEqual(r.data["app_key"], key)

    def test_it_serves_the_shape_the_panel_reads(self):
        """The panel reads these exact keys. A response missing one is a panel
        that renders blank, which is what it did for its whole life."""
        d = self.c.get("/api/rapz/profile/").data
        for k in ("top_styles", "bpm_min", "bpm_max", "boss_unlocked",
                  "detected_low", "detected_high", "goal_low", "goal_high",
                  "range_work_allowed"):
            self.assertIn(k, d, k)

    def test_top_styles_is_capped_at_three_by_the_server(self):
        """The panel caps it at three, and a panel is not a rule."""
        r = self.c.patch("/api/rapz/profile/",
                         {"top_styles": ["trap", "drill", "boom-bap", "grime", "emo"]},
                         format="json")
        self.assertEqual(len(r.data["top_styles"]), 3)

    def test_declarations_survive_a_reload(self):
        self.c.patch("/api/rapz/profile/",
                     {"top_styles": ["trap"], "bpm_min": 80, "bpm_max": 140},
                     format="json")
        d = self.c.get("/api/rapz/profile/").data
        self.assertEqual(d["top_styles"], ["trap"])
        self.assertEqual((d["bpm_min"], d["bpm_max"]), (80, 140))

    def test_a_note_that_is_not_a_note_clears_rather_than_failing(self):
        r = self.c.patch("/api/singz/profile/",
                         {"goal_low": "A2", "goal_high": "banana"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["goal_low"], "A2")
        self.assertEqual(r.data["goal_high"], "")

    def test_what_was_heard_and_what_was_said_stay_apart(self):
        """Collapsing them is how a goal quietly becomes a finding about you."""
        self.c.patch("/api/singz/profile/", {"goal_low": "C3", "goal_high": "A4"},
                     format="json")
        TakeScore.objects.create(user=self.u, app_key="singz", range_class="bass",
                                 low_note="E2", high_note="D4")
        d = self.c.get("/api/singz/profile/").data
        self.assertEqual((d["detected_low"], d["detected_high"]), ("E2", "D4"))
        self.assertEqual((d["goal_low"], d["goal_high"]), ("C3", "A4"))

    def test_range_work_is_paused_when_the_member_is_straining(self):
        """The same judgement `recovery_block` makes, from the same place. Two
        answers to "is this member straining" would disagree, and this is the
        one telling somebody it is safe to push their voice."""
        self.assertTrue(self.c.get("/api/singz/profile/").data["range_work_allowed"])
        for i in range(4):
            scored(self.u, hours_ago=i, pitch=8, tone=8, breath=2, range=8, agility=8)
        self.assertFalse(self.c.get("/api/singz/profile/").data["range_work_allowed"])

    def test_boss_needs_takes_that_actually_scored(self):
        """Turning up is worth something; it is not worth being called good,
        and an unlock is a claim about being good."""
        from . import takescorez as K
        for _ in range(K.BOSS_NEEDS_TAKES + 2):
            TakeScore.objects.create(user=self.u, app_key="rapz",
                                     difficulty=K.BOSS_AT, overall=K.BOSS_NEEDS_SCORE - 2)
        self.assertFalse(self.c.get("/api/rapz/profile/").data["boss_unlocked"])
        for _ in range(K.BOSS_NEEDS_TAKES):
            TakeScore.objects.create(user=self.u, app_key="rapz",
                                     difficulty=K.BOSS_AT, overall=K.BOSS_NEEDS_SCORE)
        self.assertTrue(self.c.get("/api/rapz/profile/").data["boss_unlocked"])

    def test_the_unlock_does_not_leak_between_instruments(self):
        from . import takescorez as K
        for _ in range(K.BOSS_NEEDS_TAKES):
            TakeScore.objects.create(user=self.u, app_key="rapz",
                                     difficulty=K.BOSS_AT, overall=10)
        self.assertTrue(self.c.get("/api/rapz/profile/").data["boss_unlocked"])
        self.assertFalse(self.c.get("/api/singz/profile/").data["boss_unlocked"])

    def test_it_needs_an_account(self):
        self.assertEqual(APIClient().get("/api/singz/profile/").status_code, 401)


class CoachingBoardTests(TestCase):
    def setUp(self):
        self.u = member("boardx")
        self.c = APIClient()
        self.c.force_authenticate(self.u)

    def _take(self, days_ago, **scores):
        t = TakeScore.objects.create(user=self.u, app_key="rapz", overall=6, scores=scores,
                                     genre="Trap", weakest=min(scores, key=scores.get))
        TakeScore.objects.filter(pk=t.pk).update(created_at=timezone.now() - timedelta(days=days_ago))

    def test_a_real_improvement_is_congratulated_with_both_numbers_and_a_decline_is_flagged(self):
        for d in (12, 11, 10):
            self._take(d, flow=4, timing=8, punchlines=4)
        for d in (3, 2, 1):
            self._take(d, flow=7, timing=5, punchlines=4)
        board = self.c.get("/api/rapz/progress/").data["coaching"]
        win = [w for w in board["wins"] if w["key"] == "flow"][0]
        self.assertEqual((win["was"], win["now"]), (4.0, 7.0))
        self.assertIn("4.0 → 7.0", win["text"])
        self.assertEqual([a["key"] for a in board["alerts"]], ["timing"])

    def test_too_few_takes_means_no_congratulations(self):
        self._take(2, flow=2)
        self._take(1, flow=9)
        board = self.c.get("/api/rapz/progress/").data["coaching"]
        self.assertEqual(board["wins"], [])                       # a line through two dots

    def test_a_problem_area_carries_a_free_drill_and_a_priced_writer_with_the_royalty(self):
        for d in (3, 2, 1):
            self._take(d, flow=8, punchlines=3)
        board = self.c.get("/api/rapz/progress/").data["coaching"]
        prob = [p for p in board["problems"] if p["key"] == "punchlines"][0]
        keys = {h["key"]: h for h in prob["help"]}
        self.assertIsNone(keys["drills"]["cost"])                 # free
        w = keys["punchlines"]
        self.assertEqual(w["cost"]["resource"], "promptz")        # the price, before the press
        self.assertIn("royalty", w["note"])
        self.assertEqual(w["carry"]["kind"], "punchlines")
        self.assertNotIn("flow", [p["key"] for p in board["problems"]])   # 8 is not a problem

    def test_every_lyric_dimension_has_a_writer_and_every_writer_a_real_dimension(self):
        from apps.economy.instruments import LYRIC_SCORE
        from apps.economy.sentencez import FIXER_FOR_DIM, FIXERS
        for dim in LYRIC_SCORE:
            self.assertIn(dim, FIXER_FOR_DIM, f"{dim} is scored but no writer fixes it")
        for kind, f in FIXERS.items():
            self.assertTrue(f["dim"] in LYRIC_SCORE or f["dim"] == "hook", kind)
            self.assertIn("other", f["techniques"])
            self.assertLessEqual(len(kind), 16)                   # SentenceWork.kind is varchar(16)


class StrengthsAndAgreementTests(CoachingBoardTests):
    def test_strengths_are_said_as_plainly_as_problems(self):
        for d in (3, 2, 1):
            self._take(d, flow=8, punchlines=3)
        board = self.c.get("/api/rapz/progress/").data["coaching"]
        self.assertEqual([s["key"] for s in board["strengths"]], ["flow"])
        self.assertEqual(board["strengths"][0]["average"], 8.0)
        self.assertNotIn("punchlines", [s["key"] for s in board["strengths"]])

    def test_a_member_can_say_they_agree_and_it_is_shown_back_and_replaced(self):
        for d in (3, 2, 1):
            self._take(d, flow=8, punchlines=3)
        r = self.c.post("/api/rapz/agree/", {"area": "punchlines", "agree": True}, format="json")
        self.assertEqual(r.status_code, 200)
        board = self.c.get("/api/rapz/progress/").data["coaching"]
        self.assertTrue([p for p in board["problems"] if p["key"] == "punchlines"][0]["agreed"])
        self.assertIsNone(board["strengths"][0]["agreed"])            # not asked, not answered
        self.c.post("/api/rapz/agree/", {"area": "punchlines", "agree": False}, format="json")
        from apps.economy.models import CoachAgreement
        self.assertEqual(CoachAgreement.objects.filter(user=self.u).count(), 1)
        self.assertFalse(CoachAgreement.objects.get(user=self.u).agree)

    def test_an_invented_area_or_a_non_answer_is_refused(self):
        self.assertEqual(self.c.post("/api/rapz/agree/", {"area": "swagger", "agree": True}, format="json").status_code, 400)
        self.assertEqual(self.c.post("/api/rapz/agree/", {"area": "flow", "agree": "yes"}, format="json").status_code, 400)


class PastSessionsAreShareableTests(CoachingBoardTests):
    def _past(self):
        return TakeScore.objects.create(
            user=self.u, app_key="rapz", overall=6, genre="Trap", scores={"flow": 6},
            read={"verdict": "Locked in. Land the last bar.", "strengths": ["Cadence"],
                  "fixes": ["Last bar"], "exact": 6.2})

    def test_every_past_take_offers_share_first_and_it_is_free(self):
        self._past()
        row = self.c.get("/api/rapz/progress/").data["takes"][0]
        self.assertEqual(row["exports"][0]["key"], "share")
        self.assertIsNone(row["exports"][0]["cost"])
        self.assertEqual(row["share_url"], "")                          # not out there yet

    def test_sharing_mints_once_from_what_the_coach_said_and_is_idempotent(self):
        from apps.economy.models import ScoreShare
        t = self._past()
        a = self.c.post(f"/api/rapz/take/{t.pk}/share/", {"score": 10, "verdict": "perfect"}, format="json")
        b = self.c.post(f"/api/rapz/take/{t.pk}/share/", {}, format="json")
        self.assertEqual(a.status_code, 200)
        self.assertEqual(a.data["share_url"], b.data["share_url"])      # the same link every time
        self.assertEqual(ScoreShare.objects.count(), 1)
        card = ScoreShare.objects.get()
        self.assertEqual((card.score, card.verdict), (6, "Locked in. Land the last bar."))  # not the request's
        self.assertEqual(card.user, self.u)                              # their handle is the referral code
        row = self.c.get("/api/rapz/progress/").data["takes"][0]
        self.assertEqual(row["share_url"], a.data["share_url"])

    def test_you_cannot_share_somebody_elses_take_or_one_with_no_score(self):
        t = self._past()
        other = APIClient()
        other.force_authenticate(member("sharestranger"))
        self.assertEqual(other.post(f"/api/rapz/take/{t.pk}/share/", {}, format="json").status_code, 404)
        blank = TakeScore.objects.create(user=self.u, app_key="rapz", overall=None)
        self.assertEqual(self.c.post(f"/api/rapz/take/{blank.pk}/share/", {}, format="json").status_code, 409)


class PromoPostFromAPastTakeTests(CoachingBoardTests):
    """A past take can become a post for anywhere: the share link plus a Sentence
    ConnectZ post, built from what the server stored, priced before it is pressed."""
    _past = PastSessionsAreShareableTests._past

    def _reply(self, text):
        from unittest.mock import MagicMock
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
        r.text = text
        return r

    def test_the_door_is_second_and_states_its_price_before_it_is_pressed(self):
        self._past()
        row = self.c.get("/api/rapz/progress/").data["takes"][0]
        keys = [e["key"] for e in row["exports"]]
        self.assertEqual(keys[:2], ["share", "promopost"])
        door = row["exports"][1]
        self.assertEqual(door["cost"]["resource"], "promptz")
        self.assertIn("not charged", door["note"])
        self.assertEqual(self.c.get(f"/api/rapz/take/{door['id']}/promo/").data["cost"], door["cost"])

    def test_the_brief_is_built_from_the_stored_take_and_never_the_request(self):
        from unittest.mock import patch
        t = self._past()
        seen = {}

        def fake(kind, body, **kw):
            seen["prompt"] = body["contents"][0]["parts"][0]["text"]
            return self._reply("Just got 6.2/10 from the AI coach. https://x"), []

        with patch("apps.economy.sentencez._key", return_value="k"), \
                patch("apps.economy.sentencez.generate_content", side_effect=fake):
            r = self.c.post(f"/api/rapz/take/{t.pk}/promo/", {"topic": "say 10/10", "score": 10}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertIn("6.2/10", seen["prompt"])
        self.assertNotIn("10/10", seen["prompt"])
        self.assertIn("Locked in. Land the last bar.", seen["prompt"])
        self.assertIn("/s/", seen["prompt"])
        self.assertIn("Do not say whether the performance is human-made", seen["prompt"])
        self.assertTrue(r.data["share_url"].startswith("/s/"))
        self.assertIn("https://", r.data["link"])
        self.assertTrue(r.data["text"])

    def test_a_declared_human_take_says_so_and_an_undeclared_one_never_does(self):
        from apps.economy.takescorez import promo_topic
        t = self._past()
        self.assertIn("human-made, AI-scored", promo_topic(t, "RapZ", "https://x/s/a", human=True))
        self.assertNotIn("human-made, AI-scored", promo_topic(t, "RapZ", "https://x/s/a", human=False))

    def test_a_failed_run_is_not_charged_and_mints_no_piece(self):
        from unittest.mock import patch
        from apps.economy.models import SentenceWork
        t = self._past()
        with patch("apps.economy.sentencez._key", return_value="k"), \
                patch("apps.economy.sentencez.generate_content", return_value=(self._reply(""), [])):
            r = self.c.post(f"/api/rapz/take/{t.pk}/promo/", {}, format="json")
        self.assertEqual(r.status_code, 502)
        self.assertEqual(SentenceWork.objects.count(), 0)

    def test_it_is_yours_alone_and_needs_a_score(self):
        t = self._past()
        other = APIClient()
        other.force_authenticate(member("promostranger"))
        self.assertEqual(other.post(f"/api/rapz/take/{t.pk}/promo/", {}, format="json").status_code, 404)
        blank = TakeScore.objects.create(user=self.u, app_key="rapz", overall=None)
        self.assertEqual(self.c.get(f"/api/rapz/take/{blank.pk}/promo/").status_code, 404)
        self.assertEqual(self.c.post(f"/api/rapz/take/{blank.pk}/promo/", {}, format="json").status_code, 409)


class ShareAWinTests(CoachingBoardTests):
    def _climb(self):
        for d in (12, 11, 10):
            self._take(d, flow=4)
        for d in (3, 2, 1):
            self._take(d, flow=7)

    def test_a_real_climb_makes_a_card_from_the_trend_and_pressing_twice_is_one_card(self):
        from apps.economy.models import ScoreShare
        from apps.economy.scoreshare import share_dict
        self._climb()
        a = self.c.post("/api/rapz/win/flow/share/", {"was": 1, "now": 10}, format="json")
        b = self.c.post("/api/rapz/win/flow/share/", {}, format="json")
        self.assertEqual(a.status_code, 200)
        self.assertEqual(a.data["share_url"], b.data["share_url"])
        self.assertEqual(ScoreShare.objects.count(), 1)
        card = share_dict(ScoreShare.objects.get())
        self.assertEqual(card["shown"], "7.0")                       # the trend's number, not the request's
        self.assertIn("from 4.0 to 7.0", card["verdict"])
        self.assertEqual(card["progress"]["was"], 4.0)

    def test_a_dimension_that_did_not_move_has_no_card(self):
        self._climb()
        self.assertEqual(self.c.post("/api/rapz/win/timing/share/", {}, format="json").status_code, 409)

    def test_the_card_shows_the_number_the_member_saw_and_draws(self):
        from apps.economy.models import ScoreShare
        from apps.economy.scoreshare import render_card, share_dict
        row = ScoreShare.objects.create(token="t" * 12, app_key="rapz", score=6, verdict="Locked in.",
                                        payload={"score_exact": 6.2})
        d = share_dict(row)
        self.assertEqual(d["shown"], "6.2")
        self.assertTrue(render_card(d).startswith(b"\x89PNG"))
        self.assertTrue(render_card(d, story=True).startswith(b"\x89PNG"))


class PersonalBestTests(CoachingBoardTests):
    def test_only_the_take_that_first_tops_the_rest_holds_the_record_and_not_before_three_takes(self):
        t = TakeScore.objects.create(user=self.u, app_key="rapz", overall=5)
        self.assertFalse(self.c.get("/api/rapz/progress/").data["takes"][0]["pb"])      # one take is no record
        for days, overall in ((4, 6), (3, 7), (2, 7), (1, 4)):
            x = TakeScore.objects.create(user=self.u, app_key="rapz", overall=overall)
            TakeScore.objects.filter(pk=x.pk).update(created_at=timezone.now() - timedelta(days=days))
        rows = self.c.get("/api/rapz/progress/").data["takes"]
        by = {}
        for r in rows:
            by.setdefault(r["overall"], []).append(r["pb"])
        self.assertEqual(by[7].count(True), 1)                          # the first 7 holds it, the repeat doesn't
        self.assertNotIn(True, by[6])
        self.assertNotIn(True, by[4])


class MonthlyRecapTests(CoachingBoardTests):
    def test_no_recap_below_three_takes_and_then_it_says_only_what_the_data_says(self):
        self._take(2, flow=6)
        self.assertIsNone(self.c.get("/api/rapz/progress/").data["recap"])
        self.assertEqual(self.c.post("/api/rapz/recap/share/", {}, format="json").status_code, 409)
        for d in (25, 24, 23):
            self._take(d, flow=4, timing=8)
        for d in (6, 5, 4):
            self._take(d, flow=7, timing=8)
        r = self.c.get("/api/rapz/progress/").data["recap"]
        self.assertEqual(r["takes"], 7)
        self.assertEqual(r["strongest"]["key"], "timing")
        # The second half holds the 6 from two days ago as well as the three 7s: 6.75.
        self.assertEqual((r["climb"]["key"], r["climb"]["was"], r["climb"]["now"]), ("flow", 4.0, 6.8))
        self.assertEqual(r["days_shown_up"], 7)

    def test_sharing_the_month_is_one_card_a_day_built_from_the_takes(self):
        from apps.economy.models import ScoreShare
        from apps.economy.scoreshare import render_card, share_dict
        for d in (25, 24, 23, 6, 5, 4):
            self._take(d, flow=4 if d > 10 else 7)
        a = self.c.post("/api/rapz/recap/share/", {"best": 10}, format="json")
        b = self.c.post("/api/rapz/recap/share/", {}, format="json")
        self.assertEqual(a.status_code, 200)
        self.assertEqual(a.data["share_url"], b.data["share_url"])
        self.assertEqual(ScoreShare.objects.count(), 1)
        card = share_dict(ScoreShare.objects.get())
        self.assertEqual(card["score"], 6)                               # the stored best, not the request's
        self.assertIn("6 takes in 30 days", card["verdict"])
        self.assertTrue(render_card(card, story=True).startswith(b"\x89PNG"))
