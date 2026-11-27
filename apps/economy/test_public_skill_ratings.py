"""Each declared skill on a public card carries how it has been rated.

The number is `skills_of` — the one rating everywhere else (median, count, and the AI coach's share
when the member opted in) — joined on the skill's name. A skill nobody has rated says so: `rating`
None and `count` 0, never a 0 that reads as a verdict. A rating for a skill the member never declared
is not on the card, because the card is built from the profile and the ratings only join onto it.
The ratings sit inside `personas`, so they follow the member's personas setting like the skills do.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import SkillRating, TakeScore, membership_for, profile_for
from apps.economy.publicz import public_profile_dict

User = get_user_model()
PW = "hunter2hunter2"
CARD = "/api/economy/public/members/{}/"


class PublicSkillRatingTests(TestCase):
    def setUp(self):
        self.maker = User.objects.create_user(username="maker", password=PW)
        self.fans = [User.objects.create_user(username=f"fan{i}", password=PW) for i in range(6)]
        for u in [self.maker] + self.fans:
            membership_for(u)
        self.stranger = APIClient()       # logged out: the audience this card is for

    def learn(self, *skills):
        p = profile_for(self.maker)
        p.personas = (p.personas or []) + [{
            "key": "mixengineer", "name": "🎛️ Mix / Master Engineer",
            "skills": [{"name": s} for s in skills],
        }]
        p.save()

    def rate(self, skill, *scores):
        for who, score in zip(self.fans, scores):
            SkillRating.objects.create(rater=who, subject=self.maker, skill=skill,
                                       item_id=f"post:{who.id}", score=score)

    def card_skills(self):
        r = self.stranger.get(CARD.format("maker"))
        self.assertEqual(r.status_code, 200, r.content)
        return [s for per in r.data["personas"] for s in per["skills"]]

    def test_a_rated_skill_shows_its_median_and_count(self):
        self.learn("Mixing")
        self.rate("Mixing", 4, 6, 10)
        [s] = self.card_skills()
        self.assertEqual(s["name"], "Mixing")
        self.assertEqual((s["rating"], s["count"], s["coached"]), (6, 3, False))

    def test_an_even_number_of_ratings_takes_the_middle_pair(self):
        self.learn("Mixing")
        self.rate("Mixing", 4, 6, 7, 9)
        [s] = self.card_skills()
        self.assertEqual((s["rating"], s["count"]), (6.5, 4))

    def test_an_unrated_skill_says_so_and_never_reads_as_zero(self):
        self.learn("Mastering")
        [s] = self.card_skills()
        self.assertEqual({"rating": s["rating"], "count": s["count"], "coached": s["coached"]},
                         {"rating": None, "count": 0, "coached": False})

    def test_a_rating_the_member_never_declared_is_not_on_the_card(self):
        self.learn("Mixing")
        self.rate("Mixing", 8)
        self.rate("Vocalist", 9, 9)        # rated, but not on the profile
        self.assertEqual([s["name"] for s in self.card_skills()], ["Mixing"])

    def test_a_long_skill_name_joins_the_rating_stored_under_its_cut(self):
        long_name = "Lead " + "x" * 60     # 65 characters on the profile
        self.learn(long_name)
        self.rate(long_name[:60], 7, 7)     # how SkillRating stores a name: cut to 60
        [s] = self.card_skills()
        self.assertEqual((s["rating"], s["count"]), (7, 2))

    def test_a_coached_skill_says_the_ai_coach_is_in_the_number(self):
        self.learn("Rapping")
        self.rate("Rapping", 7, 7, 7)
        p = profile_for(self.maker)
        p.coach_counts_for_skillz = True
        p.save()
        for _ in range(3):
            TakeScore.objects.create(user=self.maker, app_key="rapz", overall=9)
        [s] = self.card_skills()
        self.assertTrue(s["coached"])
        self.assertEqual(s["count"], 3)

    def test_the_ratings_follow_the_personas_switch(self):
        self.learn("Mixing")
        self.rate("Mixing", 8, 8, 8)
        p = profile_for(self.maker)
        p.visibility = {"personas": "private"}
        p.save()
        r = self.stranger.get(CARD.format("maker"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["personas"], [])

    def test_a_card_that_names_no_skill_reads_no_ratings(self):
        with patch("apps.economy.publicz.skills_of") as skills_of:
            public_profile_dict(profile_for(self.maker))
        skills_of.assert_not_called()
