"""PersonalitieZ — four declared axes, one filter, every search.

The rule that makes this allowed under the substance rule is that it is a
DECLARATION and not a measurement: an axis has two sides and neither is
better, so "could a member get a good one without getting good?" has no good
one to ask about. These tests pin the three lines that keep it that way.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import profile_for
from apps.economy import personalityz as pz

User = get_user_model()
PW = "hunter2hunter2"
AXES_URL = "/api/economy/personalityz/"
MEMBERS = "/api/economy/members/"


class CodeTests(TestCase):
    def test_a_four_letter_code_reads_straight(self):
        self.assertEqual(pz.clean_code("INFP"), "INFP")
        self.assertEqual(pz.clean_code(" infp "), "INFP")

    def test_a_partial_answer_is_kept_as_a_partial_answer(self):
        # Two axes answered is a complete answer to two questions, not an
        # incomplete answer to four.
        self.assertEqual(pz.clean_code("IN"), "IN--")
        self.assertEqual(pz.clean_code({"ie": "e", "jp": "P"}), "E--P")

    def test_a_letter_in_the_wrong_slot_is_not_silently_reversed(self):
        # "PFNI" is INFP backwards. Reading it positionally is the only way a
        # code can't mean two things, so this is nothing rather than a guess.
        self.assertEqual(pz.clean_code("PFNI"), "")

    def test_junk_becomes_nothing_said_and_never_refuses_a_save(self):
        # A profile write must not 400 over a letter, and a wrong letter kept
        # would be worse than a blank one.
        self.assertEqual(pz.clean_code("xxxx"), "")
        self.assertEqual(pz.clean_code(None), "")
        self.assertEqual(pz.clean_code({"nope": "Z"}), "")

    def test_no_two_axes_share_a_letter(self):
        # Load-bearing rather than a happy accident: a shared letter makes a
        # code ambiguous and the filter silently wrong.
        letters = [c for a in pz.AXES for c in (a["left"]["code"], a["right"]["code"])]
        self.assertEqual(len(set(letters)), len(letters))

    def test_undeclared_never_matches_a_filter(self):
        # A search for Introverts that returned everyone who said nothing is a
        # filter that does not filter, and the searcher would never know.
        self.assertTrue(pz.matches("INFP", {"ie": "I"}))
        self.assertFalse(pz.matches("-NFP", {"ie": "I"}))
        self.assertFalse(pz.matches("", {"ie": "I"}))

    def test_axes_are_ANDed_like_every_other_filter(self):
        self.assertTrue(pz.matches("INFP", {"ie": "I", "tf": "F"}))
        self.assertFalse(pz.matches("INFP", {"ie": "I", "tf": "T"}))


class AxesEndpointTests(TestCase):
    def test_it_opens_logged_out(self):
        r = APIClient().get(AXES_URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["axes"]), 4)

    def test_it_says_neither_side_is_better(self):
        # The one sentence that stops this becoming a score.
        note = APIClient().get(AXES_URL).data["note"].lower()
        self.assertIn("never a score", note)

    def test_no_side_carries_a_rank_of_any_kind(self):
        # A weight, a score or a "rarity" on one side is the change that would
        # look harmless and turn a declaration into a measurement.
        for axis in APIClient().get(AXES_URL).data["axes"]:
            for side in ("left", "right"):
                self.assertEqual(set(axis[side]) - {"code", "label", "blurb"}, set())


class SearchFilterTests(TestCase):
    """One filter, in the one member search every screen uses."""

    def setUp(self):
        self.me = User.objects.create_user("searcher", "s@e.com", PW)
        profile_for(self.me)
        self.client = APIClient()
        self.client.force_authenticate(self.me)

    def member(self, name, code):
        u = User.objects.create_user(name, f"{name}@e.com", PW)
        p = profile_for(u)
        p.personality = code
        p.save()
        return u

    def usernames(self, query):
        return {m["username"] for m in self.client.get(f"{MEMBERS}?{query}").data["members"]}

    def test_one_axis_filters(self):
        self.member("innie", "INFP")
        self.member("outie", "ENFP")
        self.assertEqual(self.usernames("ie=I"), {"innie"})

    def test_axes_combine(self):
        self.member("a", "INFP")
        self.member("b", "INTP")
        self.assertEqual(self.usernames("ie=I&tf=F"), {"a"})

    def test_a_whole_code_is_shorthand_for_all_four(self):
        self.member("a", "INFP")
        self.member("b", "INTP")
        self.assertEqual(self.usernames("personality=INFP"), {"a"})

    def test_no_filter_returns_everyone_including_the_undeclared(self):
        self.member("said", "INFP")
        self.member("quiet", "")
        self.assertEqual(self.usernames(""), {"said", "quiet"})

    def test_the_undeclared_are_hidden_and_the_hiding_is_said_out_loud(self):
        # An empty grid has two completely different causes and they look
        # identical. On a field this new the second is usually the real one.
        self.member("said", "INFP")
        self.member("quiet", "")
        d = self.client.get(f"{MEMBERS}?ie=E").data
        self.assertEqual(d["members"], [])
        self.assertIn("hidden for not having said", d["personality_note"])

    def test_nothing_is_said_when_no_filter_is_on(self):
        self.member("quiet", "")
        self.assertEqual(self.client.get(MEMBERS).data["personality_note"], "")


class ProfileWriterTests(TestCase):
    """A field with two endpoints gets one cleaner, not two."""

    def setUp(self):
        self.user = User.objects.create_user("writer", "w@e.com", PW)
        profile_for(self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_the_economy_profile_writer_cleans_it(self):
        self.client.post("/api/economy/profile/", {"personality": " infp "}, format="json")
        self.assertEqual(profile_for(self.user).personality, "INFP")

    def test_the_auth_writer_cleans_it_the_same_way(self):
        self.client.patch("/api/auth/me/", {"personality": {"ie": "E", "jp": "J"}}, format="json")
        self.assertEqual(profile_for(self.user).personality, "E--J")

    def test_junk_from_either_writer_is_nothing_said_not_a_500(self):
        for path, method in (("/api/economy/profile/", self.client.post),
                             ("/api/auth/me/", self.client.patch)):
            r = method(path, {"personality": "!!!!"}, format="json")
            self.assertLess(r.status_code, 400, path)
            self.assertEqual(profile_for(self.user).personality, "")

    def test_the_profile_serves_both_the_code_and_the_axes(self):
        # The screen renders four toggles and the card renders one string.
        # Neither should re-derive the other, and a client splitting the
        # letters itself would be the second place the slot order lives.
        self.client.patch("/api/auth/me/", {"personality": "INFP"}, format="json")
        d = self.client.get("/api/economy/profile/").data
        self.assertEqual(d["personality"], "INFP")
        self.assertEqual(d["personality_axes"]["tf"], "F")


class NeverAMeasurementTests(TestCase):
    """The line that must not be crossed later for convenience."""

    def test_nothing_scores_a_personality_from_activity(self):
        # "We detected you're an Extravert" would be directz_ai_rating wearing
        # a personality quiz — a number derived from form activity, presented
        # as a fact about a person. Only the member's own declaration writes
        # this column.
        import subprocess
        out = subprocess.run(
            ["grep", "-rn", "personality", "--include=*.py", "apps/"],
            capture_output=True, text=True).stdout
        # A grep that found nothing would pass this vacuously, which is the
        # failure mode of every test built on shelling out.
        self.assertIn("personalityz", out)
        for line in out.splitlines():
            if "test_personalityz" in line or "personalityz.py" in line:
                continue
            # No writer anywhere but the two cleaned profile endpoints.
            if ".personality =" in line:
                self.assertTrue(
                    "social.py" in line or "accounts/views.py" in line or "models.py" in line,
                    f"a third writer for personality: {line}")


class ColumnWidthTests(TestCase):
    """The dullest test here, and the one that would catch the fifth axis.

    SQLite ignores varchar length and production is Postgres, so a code one
    character too long is invisible locally and a DataError in production.
    Adding a fifth axis is a one-line change to a tuple; widening the column
    is not, and nothing else connects the two.
    """

    def test_a_code_can_never_be_wider_than_its_column(self):
        from apps.economy.models import Profile
        width = Profile._meta.get_field("personality").max_length
        self.assertEqual(len(pz.AXES), width)
        # And the cleaner never produces anything longer, whatever it is fed.
        for value in ("INFPX", "IIIIIIII", {"ie": "I", "ns": "N", "tf": "T", "jp": "J"}):
            self.assertLessEqual(len(pz.clean_code(value)), width)


class TestBankTests(TestCase):
    """The questionnaire. Balance is the whole thing.

    An axis with more statements on one side measures agreeableness rather
    than personality — people say yes more often than no, so an unbalanced
    bank hands nearly everybody the same letter and looks like it is working.
    """

    def test_every_axis_is_balanced_at_every_depth(self):
        from collections import Counter
        for depth in pz.DEPTHS:
            counts = Counter((q["axis"], q["side"]) for q in pz.questions(depth))
            self.assertEqual(len(set(counts.values())), 1, f"{depth}: {counts}")
            self.assertEqual(len(counts), 2 * len(pz.AXES), depth)

    def test_agreeing_with_everything_yields_no_type_at_all(self):
        # The acquiescence check, and the reason balance is asserted rather
        # than eyeballed. On an unbalanced bank this person gets a full type.
        for depth in pz.DEPTHS:
            answers = {q["id"]: 2 for q in pz.questions(depth)}
            self.assertEqual(pz.score(answers, depth)["code"], "", depth)

    def test_disagreeing_with_everything_also_yields_nothing(self):
        for depth in pz.DEPTHS:
            answers = {q["id"]: -2 for q in pz.questions(depth)}
            self.assertEqual(pz.score(answers, depth)["code"], "", depth)

    def test_answering_one_way_on_one_axis_reads_that_way(self):
        qs = pz.questions("basic")
        answers = {q["id"]: (2 if q["side"] == "I" else -2)
                   for q in qs if q["axis"] == "ie"}
        out = pz.score(answers, "basic")
        self.assertEqual(out["axes" if "axes" in out else "clarity"] and out["code"][0], "I")
        self.assertEqual(out["clarity"]["ie"], 100)

    def test_a_middle_answer_stays_unsaid_rather_than_guessing(self):
        # Being genuinely in the middle is an answer, and a coin flip would
        # put a letter on somebody that they never chose.
        answers = {q["id"]: 0 for q in pz.questions("basic")}
        out = pz.score(answers, "basic")
        self.assertEqual(out["code"], "")
        self.assertEqual(set(out["clarity"].values()), {0})

    def test_clarity_is_consistency_and_never_a_ranking(self):
        qs = pz.questions("advanced")
        strong = {q["id"]: (2 if q["side"] == "I" else -2) for q in qs if q["axis"] == "ie"}
        weak = dict(strong)
        # Flip a third of them: same letter, lower clarity, not a worse person.
        for q in [q for q in qs if q["axis"] == "ie"][:4]:
            weak[q["id"]] = -weak[q["id"]]
        a, b = pz.score(strong, "advanced"), pz.score(weak, "advanced")
        self.assertEqual(a["code"][0], b["code"][0])
        self.assertGreater(a["clarity"]["ie"], b["clarity"]["ie"])

    def test_junk_answers_are_ignored_not_scored(self):
        qs = pz.questions("basic")
        answers = {q["id"]: "yes please" for q in qs}
        answers["not-a-question"] = 2
        answers[qs[0]["id"]] = 99          # outside the scale
        out = pz.score(answers, "basic")
        self.assertEqual(out["answered"], 0)
        self.assertEqual(out["code"], "")


class TestEndpointTests(TestCase):
    URL = "/api/economy/personalityz/test/"

    def setUp(self):
        self.client = APIClient()

    def test_a_stranger_can_take_it(self):
        r = self.client.get(self.URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["questions"]), 16)

    def test_advanced_is_the_longer_one(self):
        self.assertEqual(len(self.client.get(f"{self.URL}?depth=advanced").data["questions"]), 48)

    def test_an_unknown_depth_falls_back_rather_than_erroring(self):
        self.assertEqual(self.client.get(f"{self.URL}?depth=galaxy").data["depth"], "basic")

    def test_it_says_neither_side_is_better_before_the_first_question(self):
        self.assertIn("better", self.client.get(self.URL).data["note"])

    def test_a_stranger_gets_a_result_and_is_told_it_was_not_saved(self):
        qs = self.client.get(self.URL).data["questions"]
        answers = {q["id"]: (2 if q["side"] in ("I", "N", "F", "P") else -2) for q in qs}
        r = self.client.post(self.URL, {"answers": answers}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["code"], "INFP")
        self.assertFalse(r.data["saved"])

    def test_a_member_result_lands_on_the_profile(self):
        user = User.objects.create_user("taker", "t@e.com", PW)
        profile_for(user)
        c = APIClient(); c.force_authenticate(user)
        qs = c.get(self.URL).data["questions"]
        answers = {q["id"]: (2 if q["side"] in ("E", "S", "T", "J") else -2) for q in qs}
        r = c.post(self.URL, {"answers": answers}, format="json")
        self.assertTrue(r.data["saved"])
        p = profile_for(user)
        self.assertEqual(p.personality, "ESTJ")
        self.assertEqual(p.personality_detail["depth"], "basic")
        self.assertEqual(p.personality_detail["clarity"]["ie"], 100)

    def test_nothing_ranks_on_clarity(self):
        # The line that keeps a questionnaire from becoming a score.
        import subprocess
        out = subprocess.run(["grep", "-rn", "clarity", "--include=*.py", "apps/"],
                             capture_output=True, text=True).stdout
        self.assertIn("personalityz", out)
        for line in out.splitlines():
            if "test_personalityz" in line or "personalityz.py" in line:
                continue
            self.assertNotRegex(line, r"order_by|sort|rank|median|leaderboard")
