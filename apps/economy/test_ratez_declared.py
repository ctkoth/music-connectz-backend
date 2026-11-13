"""The "Skills used on this" picker offers only skills the member has LEARNED.

A post's skills are rated for its author, so offering the whole catalogue let a rating land on a
skill nobody had claimed. The list is the profile now, and each skill carries the median it has
earned and the work that earned it.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy import ratez
from apps.economy.models import Post, SkillRating, membership_for, profile_for, skill_rating_median

User = get_user_model()
PW = "hunter2hunter2"
URL = "/api/economy/ratez/skills/"
RATE = "/api/economy/social/rate/"


class DeclaredSkillsBase(TestCase):
    def setUp(self):
        self.maker = User.objects.create_user(username="maker", password=PW)
        self.fans = [User.objects.create_user(username=f"fan{i}", password=PW) for i in range(5)]
        for u in [self.maker] + self.fans:
            membership_for(u)
        self.client = APIClient()
        self.client.force_authenticate(self.maker)

    def learn(self, *skills, persona="mixengineer", name="🎛️ Mix / Master Engineer"):
        p = profile_for(self.maker)
        p.personas = (p.personas or []) + [{"key": persona, "name": name,
                                            "skills": [{"name": s} for s in skills]}]
        p.save()

    def make_post(self, skills, title="Midnight", visibility="public"):
        p = Post.objects.create(author=self.maker, title=title, skills_used=skills, visibility=visibility)
        Post.objects.filter(pk=p.pk).update(created_at=timezone.now() - timedelta(minutes=5))
        return Post.objects.get(pk=p.pk)

    def rate(self, who, post, score):
        c = APIClient()
        c.force_authenticate(who)
        return c.post(RATE, {"item": f"post:{post.id}", "score": score}, format="json")

    def skills(self):
        r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        return {s["skill"]: s for p in r.data["personas"] for s in p["skills"]}


class OnlyLearnedSkillsAreOfferedTests(DeclaredSkillsBase):
    def test_the_list_is_the_profile_and_nothing_else(self):
        self.learn("mixing", "mastering")
        self.assertEqual(set(self.skills()), {"mixing", "mastering"})

    def test_a_skill_rated_but_never_learned_is_not_offered(self):
        # Rated rows can exist for a name that is not on the profile (older posts, collab slots):
        # having been rated does not make it a skill they have learned.
        self.learn("mixing")
        post = self.make_post(["flstudio"])
        self.rate(self.fans[0], post, 9)
        self.assertNotIn("flstudio", self.skills())

    def test_no_profile_skills_is_an_empty_list_with_the_way_to_add_some(self):
        r = self.client.get(URL)
        self.assertEqual(r.data["personas"], [])
        self.assertEqual(r.data["total"], 0)
        self.assertEqual(r.data["open_in"]["tab"], "personaz")

    def test_it_is_the_callers_own_and_a_username_changes_nothing(self):
        self.learn("mixing")
        other = APIClient()
        other.force_authenticate(self.fans[0])
        self.assertEqual(other.get(URL, {"username": "maker"}).data["personas"], [])

    def test_it_needs_a_login(self):
        self.assertIn(APIClient().get(URL).status_code, (401, 403))

    def test_a_skill_on_two_personas_is_offered_once(self):
        self.learn("mixing")
        self.learn("mixing", "mastering", persona="producer", name="🎚️ Beat Producer")
        r = self.client.get(URL)
        names = [s["skill"] for p in r.data["personas"] for s in p["skills"]]
        self.assertEqual(sorted(names), ["mastering", "mixing"])

    def test_a_mangled_skill_entry_does_not_break_the_list(self):
        p = profile_for(self.maker)
        # A nameless entry is dropped; a bare string is how skills were first stored and still counts.
        p.personas = [{"key": "mixengineer", "name": "Mix",
                       "skills": [{"name": "mixing"}, {"nope": 1}, {"name": ""}, "mastering"]}]
        p.save()
        self.assertEqual(set(self.skills()), {"mixing", "mastering"})


class TheRatingAndItsEvidenceTests(DeclaredSkillsBase):
    def test_the_median_is_the_one_every_other_screen_shows(self):
        self.learn("mixing")
        a, b = self.make_post(["mixing"], "one"), self.make_post(["mixing"], "two")
        self.rate(self.fans[0], a, 10)
        self.rate(self.fans[1], b, 6)
        s = self.skills()["mixing"]
        self.assertEqual(s["rating"], skill_rating_median(self.maker, "mixing"))
        self.assertEqual(s["rating"], 8)
        self.assertEqual(s["count"], 2)

    def test_an_unrated_skill_is_none_not_zero(self):
        self.learn("mixing")
        s = self.skills()["mixing"]
        self.assertIsNone(s["rating"])
        self.assertEqual(s["count"], 0)
        self.assertEqual(s["work"], [])

    def test_it_links_the_work_that_gave_the_rating(self):
        self.learn("mixing")
        post = self.make_post(["mixing"], "Midnight")
        self.rate(self.fans[0], post, 8)
        self.rate(self.fans[1], post, 6)
        (w,) = self.skills()["mixing"]["work"]
        self.assertEqual(w["id"], post.id)
        self.assertEqual(w["title"], "Midnight")
        self.assertEqual(w["url"], f"/p/{post.id}")
        self.assertEqual(w["count"], 2)
        self.assertEqual(w["rating"], 7)

    def test_work_is_only_the_posts_that_used_that_skill(self):
        self.learn("mixing", "mastering")
        post = self.make_post(["mixing"])
        self.rate(self.fans[0], post, 9)
        s = self.skills()
        self.assertEqual(len(s["mixing"]["work"]), 1)
        self.assertEqual(s["mastering"]["work"], [])

    def test_a_deleted_post_is_not_offered_as_a_link(self):
        self.learn("mixing")
        gone, kept = self.make_post(["mixing"], "gone"), self.make_post(["mixing"], "kept")
        self.rate(self.fans[0], gone, 9)
        self.rate(self.fans[0], kept, 5)
        Post.objects.filter(pk=gone.pk).delete()
        s = self.skills()["mixing"]
        self.assertEqual([w["title"] for w in s["work"]], ["kept"])
        # The median is still the one the rest of the app uses; the link list never invents work.
        self.assertEqual(s["rating"], skill_rating_median(self.maker, "mixing"))

    def test_a_post_the_member_cannot_open_is_not_linked(self):
        self.learn("mixing")
        other = User.objects.create_user(username="other", password=PW)
        membership_for(other)
        hidden = Post.objects.create(author=other, title="secret", skills_used=["mixing"], visibility="private")
        SkillRating.objects.create(rater=self.fans[0], subject=self.maker, skill="mixing",
                                   item_id=f"post:{hidden.id}", score=9)
        self.assertEqual(self.skills()["mixing"]["work"], [])

    def test_the_list_is_capped_and_says_how_many_were_left_off(self):
        self.learn("mixing")
        for i in range(ratez.WORK_PER_SKILL + 2):
            self.rate(self.fans[0], self.make_post(["mixing"], f"p{i}"), 7)
        s = self.skills()["mixing"]
        self.assertEqual(len(s["work"]), ratez.WORK_PER_SKILL)
        self.assertEqual(s["work_total"], ratez.WORK_PER_SKILL + 2)

    def test_the_most_rated_work_comes_first(self):
        self.learn("mixing")
        few, many = self.make_post(["mixing"], "few"), self.make_post(["mixing"], "many")
        self.rate(self.fans[0], few, 7)
        for f in self.fans[:3]:
            self.rate(f, many, 7)
        self.assertEqual([w["title"] for w in self.skills()["mixing"]["work"]], ["many", "few"])

    def queries(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(URL)
        return len(ctx)

    def test_the_query_count_does_not_grow_with_the_work(self):
        self.learn("mixing", "mastering")
        self.rate(self.fans[0], self.make_post(["mixing"]), 8)
        before = self.queries()
        for i in range(6):
            self.rate(self.fans[1], self.make_post(["mixing", "mastering"], f"x{i}"), 7)
        # skills_of costs one median query per RATED skill, and "mastering" just became rated;
        # what must not move is anything per post.
        self.assertLessEqual(self.queries(), before + 1)


class ExperienceBesideTheRatingTests(DeclaredSkillsBase):
    """Skills and experience are the platform's focus, so the picker states both, apart."""

    def learn_dated(self, name, periods=None, start=None):
        s = {"name": name}
        if periods:
            s["periods"] = periods
        if start:
            s["start"] = start
        p = profile_for(self.maker)
        p.personas = [{"key": "mixengineer", "name": "Mix", "skills": [s]}]
        p.save()

    def test_experience_is_the_time_served_not_the_time_elapsed(self):
        # 2000-2010 then stopped: ten years served, however long ago it ended.
        self.learn_dated("mixing", periods=[{"start": "2000-01-01", "end": "2010-01-01"}])
        s = self.skills()["mixing"]
        self.assertEqual(s["years"], 10)
        self.assertFalse(s["active"])
        self.assertEqual(s["last_played"], "2010-01-01")

    def test_a_skill_never_dated_has_no_years_not_zero(self):
        self.learn("mixing")
        s = self.skills()["mixing"]
        self.assertIsNone(s["years"])
        self.assertIsNone(s["active"])

    def test_an_open_stint_is_still_practising(self):
        self.learn_dated("mixing", start="2015-06-01")
        s = self.skills()["mixing"]
        self.assertGreaterEqual(s["years"], 10)
        self.assertTrue(s["active"])

    def test_experience_never_moves_the_rating(self):
        self.learn_dated("mixing", start="2001-01-01")
        self.assertIsNone(self.skills()["mixing"]["rating"])

    def test_it_names_the_date_learned_and_the_stints_the_length_comes_from(self):
        self.learn_dated("mixing", periods=[{"start": "2012-03-01", "end": "2014-03-01"},
                                            {"start": "2018-01-01"}])
        s = self.skills()["mixing"]
        self.assertEqual(s["learned"], "2012-03-01")
        self.assertEqual(s["periods"], [{"start": "2012-03-01", "end": "2014-03-01"}, {"start": "2018-01-01"}])

    def test_undated_has_no_learned_date(self):
        self.learn("mixing")
        s = self.skills()["mixing"]
        self.assertIsNone(s["learned"])
        self.assertEqual(s["periods"], [])
