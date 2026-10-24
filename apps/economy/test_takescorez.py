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

    def test_progress_names_the_personal_best_across_every_take(self):
        self.assertIsNone(self.c.get("/api/rapz/progress/").data["personal_best"])
        scored(self.u, "rapz", flow=8, timing=8)
        scored(self.u, "rapz", flow=5, timing=5)
        scored(self.u, "singz", pitch=10, tone=10)          # another coach's best is not this one's
        self.assertEqual(self.c.get("/api/rapz/progress/").data["personal_best"], 8)

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


class ShowAllTakesTests(CoachingBoardTests):
    """The history listed ten takes and said nothing about the rest."""

    def test_the_first_page_is_ten_and_the_total_says_how_many_more(self):
        for i in range(13):
            TakeScore.objects.create(user=self.u, app_key="rapz", overall=6, scores={"flow": 6})
        d = self.c.get("/api/rapz/progress/").data
        self.assertEqual(len(d["takes"]), 10)
        self.assertEqual(d["total_takes"], 13)

    def test_show_all_returns_every_take_newest_first_and_is_bounded(self):
        for i in range(13):
            TakeScore.objects.create(user=self.u, app_key="rapz", overall=i % 9 + 1, scores={"flow": 6})
        d = self.c.get("/api/rapz/progress/?takes=all").data
        self.assertEqual(len(d["takes"]), 13)
        ids = [t["id"] for t in d["takes"]]
        self.assertEqual(ids, sorted(ids, reverse=True))
        from apps.economy.takescorez import ALL_TAKES_CAP
        self.assertLessEqual(ALL_TAKES_CAP, 200)

    def test_another_members_takes_never_appear(self):
        TakeScore.objects.create(user=self.u, app_key="rapz", overall=6, scores={})
        other = APIClient(); other.force_authenticate(member("alltakesother"))
        self.assertEqual(other.get("/api/rapz/progress/?takes=all").data["takes"], [])


class DownloadTakesTests(CoachingBoardTests):
    """Every take, and the whole history, can leave as a file — built from what the
    server stored, for the member's own takes only."""

    def _mine(self, **kw):
        base = dict(user=self.u, app_key="rapz", overall=6, genre="Trap", scores={"flow": 7, "breath": 4},
                    read={"verdict": "Locked in.", "strengths": ["Cadence"], "fixes": ["Last bar"], "exact": 6.4,
                          "practice": [{"what": "Breath hold", "why": "Run out of air", "how": "4-4-4-4"}]})
        base.update(kw)
        return TakeScore.objects.create(**base)

    def test_every_take_offers_a_free_download_door_last(self):
        self._mine()
        row = self.c.get("/api/rapz/progress/").data["takes"][0]
        door = row["exports"][-1]
        self.assertEqual((door["key"], door["kind"]), ("download", "download"))
        self.assertIsNone(door["cost"])
        self.assertEqual(door["id"], row["id"])

    def test_one_take_downloads_as_a_readable_report_with_every_dimension_named(self):
        t = self._mine()
        d = self.c.get(f"/api/rapz/take/{t.pk}/download/").data
        self.assertTrue(d["filename"].endswith(".txt"))
        for want in ("Overall: 6.4/10", "Locked in.", "Cadence", "Last bar", "Breath hold", "Trap"):
            self.assertIn(want, d["text"])
        self.assertIn("Flow", d["text"])        # the label, not the key

    def test_a_take_with_no_read_says_so_rather_than_inventing_one(self):
        t = self._mine(read={}, scores={})
        text = self.c.get(f"/api/rapz/take/{t.pk}/download/").data["text"]
        self.assertIn("scored before the coach's read was kept", text)

    def test_json_download_is_the_stored_data(self):
        import json
        t = self._mine()
        d = self.c.get(f"/api/rapz/take/{t.pk}/download/?format=json").data
        self.assertEqual(json.loads(d["text"])["scores"], {"flow": 7, "breath": 4})

    def test_the_whole_history_exports_as_csv_with_labelled_columns_and_blanks_not_zeros(self):
        import csv, io
        self._mine()
        self._mine(scores={"flow": 5}, read={"verdict": "ok", "exact": 5.0})
        d = self.c.get("/api/rapz/takes/export/").data
        self.assertTrue(d["filename"].endswith(".csv"))
        self.assertEqual(d["count"], 2)
        rows = list(csv.DictReader(io.StringIO(d["text"])))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["Flow \U0001F30A"], "7")
        self.assertEqual(rows[1]["Breath \U0001FAC1"], "")          # not measured is blank, never 0

    def test_a_verdict_that_starts_like_a_formula_is_made_a_literal(self):
        from apps.economy.takescorez import _csv_safe
        self.assertEqual(_csv_safe("=HYPERLINK(\"x\")"), "'=HYPERLINK(\"x\")")
        self.assertEqual(_csv_safe("+1+1"), "'+1+1")
        self.assertEqual(_csv_safe("-3.5"), "-3.5")             # a number stays a number
        self.assertEqual(_csv_safe("plain"), "plain")

    def test_only_your_own_takes_and_nothing_when_empty(self):
        t = self._mine()
        other = APIClient(); other.force_authenticate(member("dlstranger"))
        self.assertEqual(other.get(f"/api/rapz/take/{t.pk}/download/").status_code, 404)
        self.assertEqual(other.get("/api/rapz/takes/export/").status_code, 404)   # nothing of theirs

    def test_every_instrument_has_both_routes(self):
        from django.urls import reverse
        from music_connectz.urls import INSTRUMENT_APP_KEYS
        for key in INSTRUMENT_APP_KEYS:
            self.assertTrue(reverse(f"{key}-take-download", args=[1]), key)
            self.assertTrue(reverse(f"{key}-takes-export"), key)


class PromoCaptionAndFollowUpDoorsTests(PromoPostFromAPastTakeTests):
    """A take can write a caption as well as a post, and points at where its link's results are."""

    def test_both_promo_doors_sit_after_share_and_the_viewz_door_follows_a_link(self):
        t = self._past()
        row = self.c.get("/api/rapz/progress/").data["takes"][0]
        self.assertEqual([e["key"] for e in row["exports"]][:3], ["share", "promopost", "promocaption"])
        self.assertNotIn("viewz", [e["key"] for e in row["exports"]])       # no link yet, nothing to watch
        self.c.post(f"/api/rapz/take/{t.pk}/share/", {}, format="json")
        keys = [e["key"] for e in self.c.get("/api/rapz/progress/").data["takes"][0]["exports"]]
        self.assertIn("viewz", keys)
        self.assertEqual(keys[-1], "download")

    def test_a_caption_runs_the_caption_writer_and_an_unknown_kind_falls_back_to_a_post(self):
        from unittest.mock import patch
        from apps.economy.models import SentenceWork
        t = self._past()
        with patch("apps.economy.sentencez._key", return_value="k"), \
                patch("apps.economy.sentencez.generate_content", return_value=(self._reply("Fire take 🔥 #rap"), [])):
            r = self.c.post(f"/api/rapz/take/{t.pk}/promo/", {"kind": "caption"}, format="json")
            self.assertEqual(r.status_code, 201, r.data)
            r2 = self.c.post(f"/api/rapz/take/{t.pk}/promo/", {"kind": "../etc"}, format="json")
        self.assertEqual(sorted(SentenceWork.objects.values_list("kind", flat=True)), ["caption", "post"])
        self.assertEqual(r2.status_code, 201)


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


class ProgressCostsTheSameForAnyNumberOfTakesTests(TestCase):
    """The history screen is opened often; its cost must not grow with the history. It once ran a
    query per take that tied the personal best, and re-read the same tables a dozen times."""

    def _cost(self, n):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        u = member(f"cost{n}")
        for _ in range(n):
            scored(u, flow=7, timing=7)                      # every take ties the best: the worst case
        c = APIClient(); c.force_authenticate(u)
        with CaptureQueriesContext(connection) as q:
            r = c.get("/api/singz/progress/?takes=all")
        self.assertEqual(r.status_code, 200)
        return len(q), r.data

    def test_query_count_is_flat_and_only_the_first_best_is_a_personal_best(self):
        few, _ = self._cost(4)
        many, data = self._cost(40)
        self.assertEqual(few, many)
        pbs = [t for t in data["takes"] if t["pb"]]
        self.assertEqual(len(pbs), 1)
        self.assertEqual(pbs[0]["id"], min(t["id"] for t in data["takes"]))


class HashtagCountTests(PromoPostFromAPastTakeTests):
    """The member says how many hashtags they want; the server asks for that many, most relevant
    first, and holds the model to it — and says asked vs got rather than pretending."""
    # Only the new tests: the inherited ones are covered by their own class.
    def test_the_inherited_ones_are_not_rerun_here(self):
        pass

    def _run(self, reply, n, kind="post"):
        from unittest.mock import patch
        t = self._past()
        seen = {}

        def fake(k, body, **kw):
            seen["prompt"] = body["contents"][0]["parts"][0]["text"]
            return self._reply(reply), []

        with patch("apps.economy.sentencez._key", return_value="k"), \
                patch("apps.economy.sentencez.generate_content", side_effect=fake):
            body = {"kind": kind} if n is None else {"kind": kind, "hashtags": n}
            r = self.c.post(f"/api/rapz/take/{t.pk}/promo/", body, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r, seen["prompt"]

    def test_the_prompt_asks_for_exactly_n_most_relevant_first(self):
        _, prompt = self._run("Just got 6.2/10. https://x\n\n#a #b #c", 3)
        self.assertIn("exactly 3 hashtags", prompt)
        self.assertIn("MOST to LEAST relevant", prompt)

    def test_extra_tags_in_the_trailing_block_are_trimmed_to_the_first_n(self):
        r, _ = self._run("Locked in. https://x\n\n#one #two #three #four #five", 2)
        self.assertTrue(r.data["text"].endswith("#one #two"))
        self.assertNotIn("#three", r.data["text"])
        self.assertEqual(r.data["hashtags"], {"asked": 2, "got": 2})

    def test_zero_means_none_and_a_tag_inside_a_sentence_is_left_alone(self):
        r, prompt = self._run("Big night for #hiphop. https://x\n\n#one #two", 0)
        self.assertIn("no hashtags at all", prompt)
        self.assertNotIn("#one", r.data["text"])
        self.assertIn("#hiphop", r.data["text"])

    def test_fewer_than_asked_is_reported_not_padded(self):
        r, _ = self._run("Take. https://x\n\n#one", 5)
        self.assertEqual(r.data["hashtags"], {"asked": 5, "got": 1})

    def test_not_saying_changes_nothing_and_junk_is_not_a_refusal(self):
        r, prompt = self._run("Take. https://x\n\n#one #two #three", None)
        self.assertNotIn("HASHTAGS:", prompt)
        self.assertNotIn("hashtags", r.data)
        r, _ = self._run("Take. https://x\n\n#one", "lots")
        self.assertNotIn("hashtags", r.data)

    def test_it_is_capped(self):
        from apps.economy.sentencez import HASHTAG_MAX, clean_hashtags
        self.assertEqual(clean_hashtags(999), HASHTAG_MAX)
        self.assertEqual(clean_hashtags(-4), 0)

    def test_the_caption_default_of_five_to_ten_gives_way_to_the_number(self):
        _, prompt = self._run("Hook\n\n#a #b", 2, kind="caption")
        self.assertNotIn("5-10 relevant hashtags", prompt)
        self.assertIn("exactly 2 hashtags", prompt)


class TeachOrLearnFromTheScoreTests(CoachingBoardTests):
    _past = PastSessionsAreShareableTests._past
    """Corey: 6 or above → commend teaching/coaching in LessonZ; below 5 → advice and teachers
    with the same skill. 5 to under 6 gets neither."""

    def _offer(self, who, skill="rapz", rating=8, **kw):
        from apps.lessonz.models import LessonOffer
        t = member(who)
        return LessonOffer.objects.create(teacher=t, skill=skill, title=f"{who} lessons", rating_snapshot=rating, **kw)

    def _row(self, exact, **dims):
        t = self._past()
        TakeScore.objects.filter(pk=t.pk).update(read={**(t.read or {}), "exact": exact}, overall=round(exact))
        return self.c.get("/api/rapz/progress/").data["takes"][0]

    def test_the_thresholds_are_lessonzs_own_and_five_gets_nothing(self):
        from apps.economy import takelessons as tl
        from apps.lessonz.models import MIN_TEACH_RATING
        self.assertEqual(tl.TEACH_AT, MIN_TEACH_RATING)
        self.assertEqual([tl.zone(x) for x in (6, 6.0, 7.4, 5.9, 5, 4.9, 1, None)],
                         ["teach", "teach", "teach", None, None, "learn", "learn", None])

    def test_six_and_up_commends_teaching_and_is_honest_about_the_lessonz_rating(self):
        lessons = self._row(6.4)["lessons"]
        self.assertEqual(lessons["zone"], "teach")
        self.assertEqual(lessons["cta"]["tab"], "lessonz")
        self.assertEqual(lessons["cta"]["carry"], {"view": "teach", "skill": "rapz"})
        self.assertFalse(lessons["can_teach"])                      # one take is not a LessonZ rating
        self.assertIn("single take", lessons["text"])
        from apps.lessonz.models import TeacherSkillRating
        TeacherSkillRating.objects.create(user=self.u, skill="rapz", rating=7)
        lessons = self.c.get("/api/rapz/progress/").data["takes"][0]["lessons"]
        self.assertTrue(lessons["can_teach"])
        self.assertEqual(lessons["cta"]["label"], "Teach it on LessonZ")

    def test_below_five_suggests_real_teachers_of_the_same_skill_priced_up_front(self):
        self._offer("rapteacher", "rapz", 9)
        self._offer("rapper2", "rap", 7)                            # filed without the Z
        self._offer("guitarguy", "guitarz", 10)                     # a different skill
        lessons = self._row(3.2)["lessons"]
        self.assertEqual(lessons["zone"], "learn")
        self.assertEqual([t["teacher"] for t in lessons["teachers"]], ["rapteacher", "rapper2"])
        self.assertTrue(all(t["price"] and t["currency"] and t["mode"] for t in lessons["teachers"]))
        self.assertEqual(lessons["cta"]["carry"], {"view": "browse", "skill": "rapz"})

    def test_with_nobody_teaching_it_says_so_instead_of_inventing_a_teacher(self):
        lessons = self._row(2.0)["lessons"]
        self.assertEqual(lessons["teachers"], [])
        self.assertIn("Nobody offers", lessons["text"])

    def test_the_middle_of_the_scale_and_unscored_takes_get_neither(self):
        self.assertIsNone(self._row(5.5)["lessons"])

    def test_a_minor_gets_neither_and_you_never_get_yourself_or_a_blocked_teacher(self):
        from apps.economy.models import profile_for
        self._offer("rapteacher", "rapz", 9)
        from apps.lessonz.models import LessonOffer
        LessonOffer.objects.create(teacher=self.u, skill="rapz", title="mine", rating_snapshot=10)
        self.assertEqual([t["teacher"] for t in self._row(3.0)["lessons"]["teachers"]], ["rapteacher"])
        p = profile_for(self.u); p.birthday = "2011-01-01"; p.save()
        self.c.force_authenticate(User.objects.get(pk=self.u.pk))     # a fresh request, not a cached profile
        self.assertIsNone(self.c.get("/api/rapz/progress/").data["takes"][0]["lessons"])

    def test_the_history_costs_the_same_queries_for_any_number_of_low_takes(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        self._offer("rapteacher", "rapz", 9)

        def cost(n):
            u = member(f"lowq{n}")
            for _ in range(n):
                scored(u, flow=2, timing=2)
            c = APIClient(); c.force_authenticate(u)
            with CaptureQueriesContext(connection) as q:
                c.get("/api/rapz/progress/?takes=all")
            return len(q)

        self.assertEqual(cost(3), cost(30))


class SendToCollabzAtAnyScoreTests(CoachingBoardTests):
    """Corey: a weaker take needs better help and a good one needs what it wants — so the
    CollabZ door is there at every score and for every age, worded by the number."""
    _past = PastSessionsAreShareableTests._past

    def _door(self, exact):
        t = self._past()
        TakeScore.objects.filter(pk=t.pk).update(read={**(t.read or {}), "exact": exact}, overall=round(exact))
        row = self.c.get("/api/rapz/progress/").data["takes"][0]
        return next(e for e in row["exports"] if e["key"] == "collabz")

    def test_it_is_offered_at_every_score_with_wording_by_the_number(self):
        low, mid, high = self._door(2.5), self._door(5.5), self._door(8.0)
        self.assertEqual(low["label"], "Find a stronger collaborator")
        self.assertEqual(mid["label"], "Find a stronger collaborator")        # under 6 still wants better help
        self.assertEqual(high["label"], "Take it to a collab")
        self.assertEqual((low["carry"]["seek"], high["carry"]["seek"]), ("help", "partner"))
        self.assertEqual(high["tab"], "collabz")
        self.assertIn("⚡", high["note"])                                      # the cost is stated before it is pressed
        self.assertEqual(high["carry"]["skill"], "rapz")

    def test_a_minor_still_gets_it_because_collabs_are_open_at_any_age(self):
        from apps.economy.models import profile_for
        p = profile_for(self.u); p.birthday = "2011-01-01"; p.save()
        self.c.force_authenticate(User.objects.get(pk=self.u.pk))
        self.assertEqual(self._door(3.0)["key"], "collabz")
        self.assertIsNone(self.c.get("/api/rapz/progress/").data["takes"][0]["lessons"])   # but no LessonZ CTA


class HookAndFeelzOnTheRowTests(TestCase):
    """HookZ and FeelZ are rated beside the dimensions, with their reasons, and are never a 0."""

    def setUp(self):
        self.u = member("hf")
        self.c = APIClient()
        self.c.force_authenticate(self.u)

    def take(self, read):
        t = scored(self.u, flow=7, timing=7)
        TakeScore.objects.filter(pk=t.pk).update(read=read)
        t.refresh_from_db()
        return t

    def test_read_keeps_the_reasons_only_with_their_number(self):
        r = T.read_of({"verdict": "v", "hook_score": 8, "hook_why": "The chorus repeats the title.",
                       "feelz_score": 7, "feelz_emotion": "longing", "feelz_why": "The voice cracks on the ask.",
                       "hook_why_orphan": "x"})
        self.assertEqual(r["hook_why"], "The chorus repeats the title.")
        self.assertEqual(r["feelz_emotion"], "longing")
        self.assertEqual(T.read_of({"verdict": "v", "hook_why": "no number"}).get("hook_why"), None)

    def test_extras_are_labelled_and_absent_when_unscored(self):
        rows = T.extras_of({"hook": 8, "hook_why": "Sticky.", "feelz": 6, "feelz_emotion": "joy", "feelz_why": "Bright."})
        self.assertEqual([x["key"] for x in rows], ["hook", "feelz"])
        self.assertEqual(rows[0]["label"], "HookZ 🪝")
        self.assertIn("Felt: joy", rows[1]["detail"])
        self.assertEqual(T.extras_of({"verdict": "v"}), [])
        self.assertEqual(T.extras_of({"hook": 0 if False else None}), [])

    def test_the_row_says_whether_each_is_inside_the_overall_it_was_shown(self):
        r = T.read_of({"verdict": "v", "hook_score": 8, "hook_counted": True, "feelz_score": 6, "feelz_counted": False})
        rows = {e["key"]: e for e in T.extras_of(r)}
        self.assertIs(rows["hook"]["counted"], True)
        self.assertIs(rows["feelz"]["counted"], False)
        self.assertIsNone(T.extras_of({"hook": 5})[0]["counted"])       # an older take says nothing

    def test_the_rule_is_stated_with_the_row(self):
        t = self.take({"verdict": "v", "feelz": 7})
        self.assertIn("overall", T.take_row(t, "SingZ")["extras_note"])

    def test_the_row_serves_them(self):
        t = self.take({"verdict": "v", "hook": 9, "hook_why": "Memorable.", "feelz": 5})
        row = T.take_row(t, "SingZ")
        self.assertEqual({e["key"] for e in row["extras"]}, {"hook", "feelz"})

    def test_a_post_or_message_draft_carries_them_with_the_score(self):
        t = self.take({"verdict": "v", "hook": 9, "hook_why": "Memorable.", "feelz": 5, "feelz_emotion": "calm"})
        body = T._read_text(t, "SingZ")
        self.assertIn("HookZ 🪝 9/10 — Memorable.", body)
        self.assertIn("FeelZ 💗 5/10 — Felt: calm", body)

    def test_the_share_card_payload_carries_the_reasons(self):
        t = self.take({"verdict": "v", "hook": 9, "hook_why": "Memorable.", "feelz": 5, "feelz_emotion": "calm",
                       "feelz_why": "Quiet."})
        p = T.share_payload(t)
        self.assertEqual(p["hook_why"], "Memorable.")
        self.assertEqual(p["feelz_emotion"], "calm")


class PostATakeTests(TestCase):
    """A take as a PostZ post: what the member ticks is what goes, built from what the server stored."""

    def setUp(self):
        from .models import Upload
        self.u = member("poster")
        self.c = APIClient()
        self.c.force_authenticate(self.u)
        self.t = scored(self.u, flow=7, timing=7)
        TakeScore.objects.filter(pk=self.t.pk).update(read={"verdict": "Solid.", "strengths": ["flow"], "hook": 8})
        self.url = f"/api/singz/take/{self.t.pk}/post/"

    def keep(self):
        from django.core.files.base import ContentFile
        from .models import Upload
        up = Upload.objects.create(user=self.u, name="take.webm", size_bytes=10, content_type="audio/webm")
        up.file.save("take.webm", ContentFile(b"x" * 10))
        TakeScore.objects.filter(pk=self.t.pk).update(upload=up)

    def test_get_says_whether_there_is_a_recording_before_anything_is_made(self):
        d = self.c.get(self.url).json()
        self.assertFalse(d["file"]["kept"])
        self.assertIn("wasn't kept", d["note"])
        self.assertIsNone(d["cost"])
        self.assertIn("cap", d["submissions"])

    def test_an_unkept_take_posts_score_and_feedback_without_media(self):
        r = self.c.post(self.url, {"score": True, "feedback": True, "recording": True}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()
        self.assertFalse(d["playable"])
        from .models import Post
        p = Post.objects.get(pk=d["post_id"])
        self.assertEqual(p.media_url, "")
        self.assertIn("7/10", p.title)
        self.assertIn("Solid.", p.description + str(p.score))

    def test_a_kept_take_posts_a_playable_recording(self):
        self.keep()
        d = self.c.post(self.url, {"recording": True}, format="json").json()
        self.assertTrue(d["playable"])
        from .models import Post
        p = Post.objects.get(pk=d["post_id"])
        self.assertTrue(p.media_url)
        self.assertEqual(p.media_type, "audio")

    def test_unticked_parts_are_not_included(self):
        self.keep()
        d = self.c.post(self.url, {"score": False, "feedback": False, "recording": False}, format="json").json()
        from .models import Post
        p = Post.objects.get(pk=d["post_id"])
        self.assertNotIn("7/10", p.title)
        self.assertEqual(p.media_url, "")
        self.assertFalse(p.score)

    def test_score_and_feedback_together_carry_the_coach_card_from_the_server(self):
        d = self.c.post(self.url, {"score": True, "feedback": True, "recording": False}, format="json").json()
        self.assertTrue(d["included"]["card"])
        from .models import Post
        self.assertTrue(Post.objects.get(pk=d["post_id"]).score)

    def test_it_is_only_ever_your_own_take(self):
        other = member("other")
        c = APIClient()
        c.force_authenticate(other)
        self.assertEqual(c.get(self.url).status_code, 404)
        self.assertEqual(c.post(self.url, {}, format="json").status_code, 404)

    def test_the_post_counts_against_the_daily_submission_cap(self):
        from .models import submission_cap_for
        for _ in range(submission_cap_for(self.u)):
            self.c.post(self.url, {}, format="json")
        self.assertEqual(self.c.post(self.url, {}, format="json").status_code, 429)

    def test_the_row_offers_the_door(self):
        row = T.take_row(TakeScore.objects.get(pk=self.t.pk), "SingZ")
        self.assertIn("post_take", [e["key"] for e in row["exports"]])


class FeelzTipsTests(TestCase):
    def test_tips_only_for_a_low_feelz_and_capped(self):
        from .vocalcoach import _feelz_tips
        raw = ["a", "b", "c", "d"]
        self.assertEqual([x["tip"] for x in _feelz_tips(raw, 5)], ["a", "b", "c"])
        self.assertEqual(_feelz_tips(raw, 7), [])
        self.assertEqual(_feelz_tips(raw, None), [])
        self.assertEqual(_feelz_tips("nope", 3), [])

    def test_the_prompt_asks_for_them_and_names_the_threshold(self):
        from .instruments import prompt_for
        p = prompt_for("singz", "", "", "rookie")
        self.assertIn("feelz_tips", p)
        self.assertIn("6 or lower", p)
        self.assertIn("gear", p)
        self.assertIn("never a brand", p)

    def test_stored_and_served_on_the_row_and_in_the_draft(self):
        u = member("ft")
        t = scored(u, flow=6, timing=6)
        read = T.read_of({"verdict": "v", "feelz_score": 4, "feelz_emotion": "flat", "feelz_why": "Even.",
                          "feelz_tips": ["Let the second verse breathe before the last line."]})
        TakeScore.objects.filter(pk=t.pk).update(read=read)
        t.refresh_from_db()
        row = T.take_row(t, "SingZ")
        feelz = next(e for e in row["extras"] if e["key"] == "feelz")
        self.assertEqual(feelz["emotion"], "flat")
        self.assertEqual(feelz["tips"][0]["what"], "Let the second verse breathe before the last line.")
        self.assertEqual(feelz["tips"][0]["kind"], "delivery")
        self.assertIn("To bring more feeling", T._read_text(t, "SingZ"))

    def test_a_high_feelz_carries_no_tips_even_if_stored(self):
        feelz = T.extras_of({"feelz": 9, "feelz_tips": ["x"]})[0]
        self.assertEqual(feelz["tips"], [])


class FeelzTipKindTests(TestCase):
    def test_kinds_are_the_servers_and_an_invented_one_becomes_delivery(self):
        from .vocalcoach import FEELZ_TIP_KINDS, _feelz_tips
        tips = _feelz_tips([{"kind": "gear", "tip": "Your mic sounds thin on the low lines; try a dynamic mic closer in."},
                            {"kind": "vibes", "tip": "Lean into the last line."},
                            {"kind": "room", "tip": ""}], 4)
        self.assertEqual([t["kind"] for t in tips], ["delivery", "gear"])      # delivery leads, the recording last
        self.assertEqual(tips[1]["label"], FEELZ_TIP_KINDS["gear"])
        self.assertEqual(tips[1]["label"], "Mic & gear")

    def test_a_mic_tip_reaches_the_draft_with_its_label(self):
        u = member("mic")
        t = scored(u, flow=6)
        TakeScore.objects.filter(pk=t.pk).update(read=T.read_of({
            "verdict": "v", "feelz_score": 3,
            "feelz_tips": [{"kind": "gear", "tip": "Thin low end — try a dynamic mic closer to the mouth."}]}))
        t.refresh_from_db()
        self.assertIn("Mic & gear: Thin low end", T._read_text(t, "SingZ"))


class MixTipsTests(TestCase):
    def test_a_mix_tip_is_what_why_how_and_capped(self):
        from .vocalcoach import _mix_tips
        raw = [{"helps": "clarity", "what": "Cut 250-400 Hz on the vocal.", "why": "Mud under the words.",
                "how": "A gentle bell, 3 dB, then compare."}] * 4
        out = _mix_tips(raw)
        self.assertEqual(len(out), 3)
        self.assertEqual(out[0]["helps_label"], "Clarity")
        self.assertEqual(out[0]["how"], "A gentle bell, 3 dB, then compare.")

    def test_an_unknown_helps_is_both_and_an_empty_what_is_dropped(self):
        from .vocalcoach import _mix_tips
        out = _mix_tips([{"helps": "vibes", "what": "Bring the vocal up 2 dB."}, {"what": ""}, "Add a de-esser."])
        self.assertEqual([x["helps"] for x in out], ["both", "both"])
        self.assertEqual(_mix_tips("nope"), [])

    def test_the_prompt_asks_for_what_why_how_and_for_the_mix_apart_from_the_performance(self):
        from .instruments import prompt_for
        p = prompt_for("singz", "", "", "rookie")
        self.assertIn("mix_tips", p)
        self.assertIn("about the MIX, not the performance", p)
        self.assertIn("EQ", p)

    def test_stored_served_and_drafted_with_the_reasons(self):
        u = member("mixer")
        t = scored(u, flow=6)
        TakeScore.objects.filter(pk=t.pk).update(read=T.read_of({
            "verdict": "v", "feelz_score": 4,
            "feelz_tips": [{"kind": "gear", "what": "Thin low end.", "why": "The warmth is missing.", "how": "Dynamic mic, closer."}],
            "mix_tips": [{"helps": "both", "what": "Raise the vocal 2 dB over the beat.", "why": "It is buried.",
                          "how": "Automate the verse up first."}]}))
        t.refresh_from_db()
        row = T.take_row(t, "SingZ")
        self.assertEqual(row["mix_tips"][0]["why"], "It is buried.")
        feelz = next(e for e in row["extras"] if e["key"] == "feelz")
        self.assertEqual(feelz["tips"][0]["how"], "Dynamic mic, closer.")
        body = T._read_text(t, "SingZ")
        self.assertIn("Mix suggestions:", body)
        self.assertIn("Why: It is buried.", body)
        self.assertIn("How: Dynamic mic, closer.", body)

    def test_a_mix_tip_is_kept_even_when_feelz_is_fine(self):
        r = T.read_of({"verdict": "v", "feelz_score": 9, "mix_tips": [{"what": "De-ess the chorus.", "why": "Sibilance.", "how": "Narrow 6-8 kHz."}]})
        self.assertIn("mix_tips", r)
        self.assertNotIn("feelz_tips", r)


class FeelzCauseTests(TestCase):
    def test_the_cause_is_the_servers_and_only_for_a_low_feelz(self):
        from .vocalcoach import _feelz_cause
        self.assertEqual(_feelz_cause("performance", 4), "performance")
        self.assertEqual(_feelz_cause("vibes", 4), "")
        self.assertEqual(_feelz_cause("mix", 9), "")
        self.assertEqual(_feelz_cause("mix", None), "")

    def test_a_performance_cause_means_no_mix_suggestions_at_all(self):
        r = T.read_of({"verdict": "v", "feelz_score": 3, "feelz_cause": "performance",
                       "mix_tips": [{"what": "Raise the vocal.", "why": "w", "how": "h"}]})
        self.assertEqual(r["feelz_cause"], "performance")
        self.assertNotIn("mix_tips", r)
        # …and a row built from an older read that carries both does not serve them
        self.assertEqual(T.mix_tips_of({"feelz_cause": "performance", "mix_tips": [{"what": "x"}]}), [])

    def test_a_mix_cause_keeps_them_and_the_row_names_the_cause(self):
        r = T.read_of({"verdict": "v", "feelz_score": 3, "feelz_cause": "mix",
                       "mix_tips": [{"what": "Raise the vocal.", "why": "w", "how": "h"}]})
        self.assertIn("mix_tips", r)
        feelz = T.extras_of({**r, "feelz": 3})[0]
        self.assertEqual(feelz["cause"]["label"], "The mix")

    def test_diction_and_projection_are_kinds_and_the_prompt_says_unclear_is_often_the_performance(self):
        from .instruments import prompt_for
        from .vocalcoach import FEELZ_TIP_KINDS
        self.assertIn("diction", FEELZ_TIP_KINDS)
        self.assertIn("projection", FEELZ_TIP_KINDS)
        p = prompt_for("singz", "", "", "rookie")
        self.assertIn("feelz_cause", p)
        self.assertIn("never default to blaming the mix", p)
        self.assertIn("mumbling", p)


class DeliveryLeadsTests(TestCase):
    RAW = [{"kind": "gear", "what": "g"}, {"kind": "pacing", "what": "p"}, {"kind": "delivery", "what": "d"},
           {"kind": "room", "what": "r"}]

    def test_delivery_comes_first_and_the_recording_last(self):
        from .vocalcoach import _feelz_tips
        self.assertEqual([t["kind"] for t in _feelz_tips(self.RAW, 4)], ["delivery", "pacing", "gear"])

    def test_when_the_recording_is_the_cause_it_leads(self):
        from .vocalcoach import _feelz_tips
        self.assertEqual([t["kind"] for t in _feelz_tips(self.RAW, 4, "recording")], ["gear", "room", "delivery"])

    def test_the_prompt_says_delivery_is_the_biggest_lever(self):
        from .instruments import prompt_for
        self.assertIn("Delivery is the biggest lever", prompt_for("singz", "", "", "rookie"))
