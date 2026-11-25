import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.economy import sentencez as S

SONG = "I wake up late and chase the bread\nMy phone keeps buzzing in my head\nShe wants the world, I want the bed"
GOAL = "Reframe a worn trope without bitterness; replace generic flexes with hyper-specific details."


class GoalPromptTests(TestCase):
    def test_the_goal_rides_in_the_edit_as_data_and_never_its_lyrics(self):
        p = S.prompt_for("revise", SONG, revise={"factors": [S.INSPIRATION], "goal": GOAL})
        self.assertIn("APPLY THE INSPIRATION'S PRINCIPLES", p); self.assertIn(GOAL, p)
        self.assertIn("Never copy or quote the inspiration's lyrics", p)
        self.assertIn("EDITING the member's own lyrics", p)

    def test_an_inspiration_change_survives_only_when_it_edits_a_real_line(self):
        reply = json.dumps({"lyrics": SONG.replace("She wants the world", "She wants Tokyo first class"), "changes": [
            {"factor": "inspiration", "before": "She wants the world, I want the bed", "after": "She wants Tokyo first class, I want the bed", "why": "specific"},
            {"factor": "inspiration", "before": "a line that was never there", "after": "x", "why": "made up"}]})
        got = S.parse_revision(reply, SONG, [S.INSPIRATION])
        self.assertEqual(len(got["changes"]), 1); self.assertEqual(got["changes"][0]["label"], "Inspiration's principles")
        self.assertEqual(got["kept_lines"], 2)


@override_settings(GEMINI_API_KEY="k")
class GoalViewTests(TestCase):
    def test_a_goal_alone_is_enough_to_rewrite(self):
        u = get_user_model().objects.create_user("writer", password="pw-long-enough-1")
        c = APIClient(); c.force_authenticate(u)
        r = c.post("/api/economy/sentencez/", {"kind": "revise", "topic": SONG}, format="json")
        self.assertEqual(r.status_code, 400)
        from rest_framework.response import Response
        with mock.patch.object(S, "write_piece", return_value=Response({})) as wp:
            c.post("/api/economy/sentencez/", {"kind": "revise", "topic": SONG, "goal": GOAL}, format="json")
        self.assertEqual(wp.call_args.kwargs["revise"]["goal"], GOAL)
        self.assertIn(S.INSPIRATION, wp.call_args.kwargs["revise"]["factors"])
