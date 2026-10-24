from datetime import datetime, timedelta, timezone as dtz

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import challengez as C
from apps.economy.models import ScoreShare, TakeScore
from apps.economy.takescorez import share_take

User = get_user_model()


class ChallengeTests(TestCase):
    def test_it_is_one_prompt_per_coach_per_week_the_same_for_everybody_and_changes_weekly(self):
        a = C.challenge_for("rapz", datetime(2026, 10, 14, tzinfo=dtz.utc))
        b = C.challenge_for("rapz", datetime(2026, 10, 16, tzinfo=dtz.utc))    # same ISO week
        self.assertEqual(a, b)
        self.assertEqual(a["week"], "2026-W42")
        weeks = {C.challenge_for("rapz", datetime(2026, 1, 5, tzinfo=dtz.utc) + timedelta(weeks=i))["title"] for i in range(12)}
        self.assertGreater(len(weeks), 1)                                       # it actually rotates
        self.assertIn(a["genre"], C.GENRES["rapz"])
        self.assertEqual(a["difficulty"], C.DIFFICULTY)

    def test_a_take_counts_only_in_that_genre_at_that_difficulty_in_that_week(self):
        c = C.challenge_for("rapz")
        self.assertEqual(C.challenge_tag("rapz", c["genre"], c["difficulty"]), c["week"])
        self.assertEqual(C.challenge_tag("rapz", "Polka", c["difficulty"]), "")
        self.assertEqual(C.challenge_tag("rapz", c["genre"], "starter"), "")

    def test_a_shared_take_carries_the_week_it_was_made_in_not_the_week_it_was_shared(self):
        u = User.objects.create_user("chal", "c@e.com", "pw-Long-enough-1")
        c = C.challenge_for("rapz")
        t = TakeScore.objects.create(user=u, app_key="rapz", overall=7, genre=c["genre"], difficulty=c["difficulty"],
                                     read={"verdict": "v", "exact": 7.4})
        token = share_take(t)
        self.assertEqual(ScoreShare.objects.get(token=token).payload["challenge"], c["week"])
        off = TakeScore.objects.create(user=u, app_key="rapz", overall=7, genre="Polka", difficulty="builder")
        self.assertNotIn("challenge", ScoreShare.objects.get(token=share_take(off)).payload)

    def test_the_top_cards_are_shared_ones_one_per_member_best_first_and_public(self):
        c = C.challenge_for("rapz")
        users = [User.objects.create_user(f"u{i}", f"u{i}@e.com", "pw-Long-enough-1") for i in range(3)]
        for u, s in zip(users, (6.0, 8.2, 7.1)):
            ScoreShare.objects.create(token=f"t{u.id}a", app_key="rapz", score=round(s), user=u,
                                      payload={"challenge": c["week"], "score_exact": s})
        ScoreShare.objects.create(token="best0", app_key="rapz", score=9, user=users[0],
                                  payload={"challenge": c["week"], "score_exact": 9.0})   # same member, better
        ScoreShare.objects.create(token="old", app_key="rapz", score=10, user=users[1],
                                  payload={"challenge": "1999-W01", "score_exact": 10})   # another week
        d = APIClient().get("/api/economy/challenge/rapz/").json()                        # no sign-in
        self.assertEqual([r["username"] for r in d["top"]], ["u0", "u1", "u2"])
        self.assertEqual(d["top"][0]["shown"], "9")
        self.assertEqual(len(d["top"]), 3)                                                # one per member
        self.assertEqual(APIClient().get("/api/economy/challenge/nope/").status_code, 404)

    def test_the_coach_publishes_it_before_anything_runs(self):
        u = User.objects.create_user("coachchal", "cc@e.com", "pw-Long-enough-1")
        c = APIClient()
        c.force_authenticate(u)
        d = c.get("/api/rapz/coach/").json()
        self.assertEqual(d["challenge"], C.challenge_for("rapz"))
