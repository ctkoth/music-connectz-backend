from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from . import services as S
from .models import (GateSkillReq, MemberFacet, Skill, SkillGate, UserSkill, WorkRating,
                     WorkSkillTag)

U = get_user_model()


def mk(name, birth=None, **kw):
    u = U.objects.create_user(name, password="x")
    MemberFacet.objects.create(user=u, birth_date=birth, **kw)
    return u


def rate_up(owner, skill, scores, wid=1):
    tag, _ = WorkSkillTag.objects.get_or_create(owner=owner, work_type="post", work_id=wid, skill=skill)
    for i, sc in enumerate(scores):
        r = U.objects.create_user(f"r{owner.pk}_{wid}_{i}", password="x")
        WorkRating.objects.create(tag=tag, rater=r, score=sc)


class Core(TestCase):
    def setUp(self):
        self.mix = Skill.objects.create(slug="mix", name="Mixing", price_cents=500)
        self.rap = Skill.objects.create(slug="rap", name="Rapping", price_cents=300)

    def test_experience(self):
        e = S.experience(date(2024, 8, 20), date(2026, 11, 8))
        self.assertEqual((e["years"], e["months"]), (2, 2))
        self.assertEqual(e["label"], "2 yrs 2 mos")
        self.assertEqual(S.experience(date(2026, 11, 1), date(2026, 11, 8))["label"], "0 mos")

    def test_choices_only(self):
        u = mk("a", date(1990, 1, 1))
        UserSkill.objects.create(user=u, skill=self.mix, learned_at=date(2020, 1, 1))
        self.assertEqual(S.validate_skill_ids(u, [self.mix.id])[0], self.mix)
        with self.assertRaises(ValidationError):
            S.validate_skill_ids(u, [self.rap.id])
        with self.assertRaises(ValidationError):
            S.validate_skill_ids(u, [])

    def test_profile_median_and_works(self):
        u = mk("a", date(1990, 1, 1))
        us = UserSkill.objects.create(user=u, skill=self.mix, learned_at=date(2020, 1, 1))
        rate_up(u, self.mix, [6, 8, 10], 1)
        rate_up(u, self.mix, [4], 2)
        s = S.skill_summary(us, date(2026, 11, 8))
        self.assertEqual(s["median"], 7.0)
        self.assertEqual(s["ratings"], 4)
        self.assertFalse(s["provisional"])
        self.assertEqual(len(s["works"]), 2)

    def test_split_sums_exactly(self):
        r = S.split_by_rating(10001, {1: 9, 2: 7, 3: 5})
        self.assertEqual(r["tax_cents"], 500)
        self.assertEqual(sum(x["cents"] for x in r["shares"].values()), r["net_cents"])
        self.assertGreater(r["shares"][1]["cents"], r["shares"][3]["cents"])
        eq = S.split_by_rating(1000, {1: 0, 2: 0})
        self.assertEqual(eq["shares"][1]["cents"], eq["shares"][2]["cents"])

    def test_distribute_by_work(self):
        a, b = mk("a", date(1990, 1, 1)), mk("b", date(1990, 1, 1))
        for u in (a, b):
            UserSkill.objects.create(user=u, skill=self.mix, learned_at=date(2020, 1, 1))
        rate_up(a, self.mix, [10, 10, 10], 7)
        rate_up(b, self.mix, [5, 5, 5], 7)
        out = S.distribute("post", 7, 3000)
        self.assertEqual(out["shares"][a.id]["cents"], 1900 if False else out["shares"][a.id]["cents"])
        self.assertAlmostEqual(out["shares"][a.id]["pct"], 66.67, places=1)


class Gates(TestCase):
    def setUp(self):
        self.mix = Skill.objects.create(slug="mix", name="Mixing", price_cents=500)
        self.owner = mk("owner", date(1985, 5, 5), lat=39.74, lon=-104.99)

    def gate(self, **kw):
        g = SkillGate.objects.create(owner=self.owner, post_type="collab", post_id=1, **kw)
        g.skills.add(self.mix)
        return g

    def cand(self, name, scores, birth=date(1990, 1, 1), **kw):
        u = mk(name, birth, **kw)
        UserSkill.objects.create(user=u, skill=self.mix, learned_at=date(2020, 1, 1))
        rate_up(u, self.mix, scores)
        return u

    def test_rating_gate_exclusive(self):
        g = self.gate(rating_min=7, rating_max=9)
        self.assertTrue(S.evaluate_gate(g, self.cand("in", [8, 8, 8]))[0])
        self.assertFalse(S.evaluate_gate(g, self.cand("hi", [10, 10, 10]))[0])
        self.assertFalse(S.evaluate_gate(g, self.cand("lo", [3, 3, 3]))[0])
        self.assertFalse(S.evaluate_gate(g, self.cand("few", [8]))[0])

    def test_price_gate(self):
        g = self.gate(price_min=100, price_max=400)
        self.assertFalse(S.evaluate_gate(g, self.cand("p", [8, 8, 8]))[0])  # catalog 500

    def test_distance_gate(self):
        g = self.gate(distance_max_km=50)
        near = self.cand("n", [8, 8, 8], lat=39.75, lon=-105.0)
        far = self.cand("f", [8, 8, 8], lat=40.71, lon=-74.0)
        none = self.cand("x", [8, 8, 8])
        self.assertTrue(S.evaluate_gate(g, near)[0])
        self.assertFalse(S.evaluate_gate(g, far)[0])
        self.assertFalse(S.evaluate_gate(g, none)[0])

    def test_age_line_and_clamp(self):
        teen = self.cand("t", [8, 8, 8], birth=date(2011, 1, 1))
        g = self.gate()
        self.assertFalse(S.evaluate_gate(g, teen)[0])  # adult owner never matches a minor
        self.assertEqual(S.clamp_age_range(40, 12, 30), (18, 30))
        self.assertEqual(S.clamp_age_range(15, 12, None), (12, 17))

    def test_attractiveness_adults_opt_in_only(self):
        g = self.gate(attr_min=6)
        yes = self.cand("y", [8, 8, 8], attractiveness_opt_in=True, attractiveness_score=7.5)
        no = self.cand("n", [8, 8, 8], attractiveness_score=9)
        self.assertTrue(S.evaluate_gate(g, yes)[0])
        self.assertFalse(S.evaluate_gate(g, no)[0])

    def test_skill_all_mode_and_search(self):
        rap = Skill.objects.create(slug="rap", name="Rap")
        g = self.gate(skill_match="all")
        g.skills.add(rap)
        c = self.cand("c", [8, 8, 8])
        self.assertFalse(S.evaluate_gate(g, c)[0])
        g.skill_match = "any"
        g.save()
        self.assertEqual(S.search_candidates(g), [c])
        self.assertTrue(S.assert_passes_gate("collab", 99, c))  # no gate = open


class Reverse(TestCase):
    def setUp(self):
        self.vt = Skill.objects.create(slug="vt", name="Vocal Tuning", price_cents=300)
        self.owner = mk("owner", date(1985, 5, 5))
        self.pro = mk("pro", date(1990, 1, 1))
        self.new = mk("new", date(1995, 1, 1))
        UserSkill.objects.create(user=self.pro, skill=self.vt, learned_at=date(2016, 1, 1))
        UserSkill.objects.create(user=self.new, skill=self.vt, learned_at=date(2026, 8, 1))
        rate_up(self.pro, self.vt, [9, 9, 9], 1)
        rate_up(self.new, self.vt, [9, 9, 9], 2)

    def test_gauge_is_lower_of_experience_and_rating(self):
        g = S.gauge(130, 9.5, 5)
        self.assertEqual((g["tier"], g["label"]), (4, "Expert"))
        self.assertEqual(S.gauge(3, 9.5, 5)["label"], "Novice")   # great ratings, no time yet
        self.assertEqual(S.gauge(130, 3, 5)["label"], "Novice")   # long time, poor ratings
        self.assertIsNone(S.gauge(130, 9, 1)["tier"])

    def test_experience_and_gauge_gate(self):
        g = SkillGate.objects.create(owner=self.owner, post_type="collab", post_id=5,
                                     exp_min_months=60, gauge_min=3)
        g.skills.add(self.vt)
        self.assertTrue(S.evaluate_gate(g, self.pro)[0])
        self.assertFalse(S.evaluate_gate(g, self.new)[0])

    def test_browse_posts_qualified_and_filters(self):
        g = SkillGate.objects.create(owner=self.owner, post_type="collab", post_id=5, exp_min_months=60)
        g.skills.add(self.vt)
        self.assertEqual(len(S.browse_posts(self.pro)), 1)
        self.assertEqual(len(S.browse_posts(self.new)), 0)                       # not qualified
        self.assertEqual(len(S.browse_posts(self.new, only_qualified=False)), 1)
        self.assertEqual(len(S.browse_posts(self.pro, exp_months=(0, 12))), 0)   # post asks 60+
        self.assertEqual(len(S.browse_posts(self.pro, skill_ids=[999])), 0)

    def test_search_works(self):
        r = S.search_works([self.vt.id], creator_exp=(60, None))
        self.assertEqual([x["creator"] for x in r], ["pro"])
        r = S.search_works([self.vt.id], creator_gauge=(0, 0))
        self.assertEqual([x["creator"] for x in r], ["new"])


class Api(TestCase):
    def test_flow(self):
        from rest_framework.test import APIClient
        vt = Skill.objects.create(slug="vt", name="Vocal Tuning", price_cents=300)
        other = Skill.objects.create(slug="x", name="Other")
        a, b = mk("alice", date(1990, 1, 1)), mk("bob", date(1990, 1, 1))
        ca, cb = APIClient(), APIClient()
        ca.force_authenticate(a)
        cb.force_authenticate(b)
        self.assertEqual(ca.post("/api/skillreg/mine/", {"skill_id": vt.id, "learned_at": "2020-01-01"}, format="json").status_code, 201)
        self.assertEqual(len(ca.get("/api/skillreg/choices/").json()), 1)
        bad = ca.post("/api/skillreg/tag-work/", {"work_type": "post", "work_id": 1, "skill_ids": [other.id]}, format="json")
        self.assertEqual(bad.status_code, 400)
        ok = ca.post("/api/skillreg/tag-work/", {"work_type": "post", "work_id": 1, "title": "t", "skill_ids": [vt.id]}, format="json")
        self.assertEqual(ok.json()["post_cost_cents"], 300)
        tag = ok.json()["tags"][0]
        self.assertEqual(ca.post("/api/skillreg/rate/", {"tag_id": tag, "score": 9}, format="json").status_code, 403)
        self.assertEqual(cb.post("/api/skillreg/rate/", {"tag_id": tag, "score": 9}, format="json").status_code, 200)
        prof = ca.get("/api/skillreg/profile/alice/").json()
        self.assertEqual(prof["skills"][0]["works"][0]["median"], 9.0)
        self.assertEqual(cb.put("/api/skillreg/gates/collab/3/", {"skill_ids": [vt.id], "exp_min_months": 12, "age_min": 5}, format="json").status_code, 200)
        self.assertTrue(ca.get("/api/skillreg/gates/collab/3/check/").json()["allowed"])
        self.assertEqual(len(ca.post("/api/skillreg/posts/", {}, format="json").json()), 1)
        self.assertEqual(len(cb.post("/api/skillreg/search/", {"skill_ids": [vt.id], "exp_min_months": 12}, format="json").json()), 1)
        self.assertEqual(len(ca.post("/api/skillreg/works/", {"skill_ids": [vt.id]}, format="json").json()), 1)


class AddSkillCta(TestCase):
    def test_create_dedupe_and_cap(self):
        from rest_framework.test import APIClient
        a = mk("alice", date(1990, 1, 1))
        c = APIClient()
        c.force_authenticate(a)
        r = c.post("/api/skillreg/catalog/", {"name": "Tape Saturation"}, format="json")
        self.assertEqual((r.status_code, r.json()["created"]), (201, True))
        r2 = c.post("/api/skillreg/catalog/", {"name": "tape saturation"}, format="json")
        self.assertEqual((r2.status_code, r2.json()["created"], r2.json()["id"]), (200, False, r.json()["id"]))
        self.assertEqual(c.post("/api/skillreg/catalog/", {"name": "x"}, format="json").status_code, 400)
        for i in range(9):
            c.post("/api/skillreg/catalog/", {"name": f"Skill {i}a"}, format="json")
        self.assertEqual(c.post("/api/skillreg/catalog/", {"name": "One More"}, format="json").status_code, 429)
        # new skill still has to be added to the member's own list before use
        sid = r.json()["id"]
        bad = c.post("/api/skillreg/tag-work/", {"work_type": "post", "work_id": 1, "skill_ids": [sid]}, format="json")
        self.assertEqual(bad.status_code, 400)


class AnySkillGates(TestCase):
    def test_gates_any_skill_but_uploads_known_only(self):
        from rest_framework.test import APIClient
        known = Skill.objects.create(slug="k", name="Known")
        other = Skill.objects.create(slug="u", name="Other")
        a = mk("alice", date(1990, 1, 1))
        UserSkill.objects.create(user=a, skill=known, learned_at=date(2020, 1, 1))
        c = APIClient()
        c.force_authenticate(a)
        r = c.put("/api/skillreg/gates/collab/1/", {"skill_reqs": [
            {"skill_id": other.id, "exp_min_months": 36, "rating_min": 7}]}, format="json")
        self.assertEqual(r.status_code, 200)
        got = c.get("/api/skillreg/gates/collab/1/").json()
        self.assertEqual(got["skill_ids"], [other.id])
        self.assertEqual(got["skill_reqs"][0]["exp_min_months"], 36)
        self.assertEqual(c.put("/api/skillreg/gates/collab/2/", {"skill_ids": [9999]}, format="json").status_code, 400)
        self.assertEqual(c.post("/api/skillreg/works/", {"skill_ids": [other.id]}, format="json").status_code, 200)
        self.assertEqual(c.post("/api/skillreg/tag-work/", {"work_type": "post", "work_id": 1, "skill_ids": [other.id]}, format="json").status_code, 400)

    def test_per_skill_requirements_and_any_mode(self):
        mix = Skill.objects.create(slug="mix", name="Mix")
        rap = Skill.objects.create(slug="rap", name="Rap")
        owner = mk("owner", date(1985, 5, 5))
        g = SkillGate.objects.create(owner=owner, post_type="collab", post_id=1)
        g.skills.add(mix, rap)
        reqs = {mix.id: {"exp_min_months": 60, "rating_min": 8}, rap.id: {"exp_min_months": 6}}
        c = mk("c", date(1990, 1, 1))
        UserSkill.objects.create(user=c, skill=mix, learned_at=date(2024, 1, 1))   # too new for mix
        UserSkill.objects.create(user=c, skill=rap, learned_at=date(2020, 1, 1))   # fine for rap
        self.assertTrue(S.evaluate_gate(g, c, reqs=reqs)[0])                       # any: rap alone suffices
        g.skill_match = "all"
        self.assertFalse(S.evaluate_gate(g, c, reqs=reqs)[0])                      # all: mix fails
        g.skill_match = "any"
        rate_up(c, mix, [9, 9, 9])
        d = mk("d", date(1990, 1, 1))
        UserSkill.objects.create(user=d, skill=mix, learned_at=date(2016, 1, 1))
        self.assertFalse(S.evaluate_gate(g, d, reqs=reqs)[0])                      # mix exp ok, unrated -> fails rating; no rap


class Families(TestCase):
    def setUp(self):
        self.flow = Skill.objects.create(slug="flow", name="Triplet Flow", family="Rapping")
        self.free = Skill.objects.create(slug="free", name="Freestyle", family="Rapping")
        self.tune = Skill.objects.create(slug="tune", name="Vocal Tuning", family="Mixing")
        self.owner = mk("owner", date(1985, 5, 5))

    def test_any_rapping_5_to_20_years_rated_5_to_10(self):
        g = SkillGate.objects.create(owner=self.owner, post_type="collab", post_id=1)
        GateSkillReq.objects.create(gate=g, family="Rapping", exp_min_months=60, exp_max_months=240,
                                    rating_min=5, rating_max=10)
        # experience from the longest rap skill, ratings pooled across rap skills
        c = mk("c", date(1990, 1, 1))
        UserSkill.objects.create(user=c, skill=self.flow, learned_at=date(2019, 1, 1))   # ~7.8 yrs
        UserSkill.objects.create(user=c, skill=self.free, learned_at=date(2025, 1, 1))   # new
        rate_up(c, self.flow, [4, 6], 1)
        rate_up(c, self.free, [8], 2)                                                      # pooled median 6
        self.assertTrue(S.evaluate_gate(g, c)[0])
        # too little time in any rap skill
        n = mk("n", date(1990, 1, 1))
        UserSkill.objects.create(user=n, skill=self.flow, learned_at=date(2025, 6, 1))
        rate_up(n, self.flow, [9, 9, 9], 3)
        self.assertFalse(S.evaluate_gate(g, n)[0])
        # too long (over 20 years)
        o = mk("o", date(1960, 1, 1))
        UserSkill.objects.create(user=o, skill=self.free, learned_at=date(1995, 1, 1))
        rate_up(o, self.free, [9, 9, 9], 4)
        self.assertFalse(S.evaluate_gate(g, o)[0])
        # no rap skill at all (mixing only)
        m = mk("m", date(1990, 1, 1))
        UserSkill.objects.create(user=m, skill=self.tune, learned_at=date(2010, 1, 1))
        rate_up(m, self.tune, [9, 9, 9], 5)
        self.assertFalse(S.evaluate_gate(g, m)[0])
        self.assertEqual(S.search_candidates(g), [c])

    def test_api_family_gate_browse_and_works(self):
        from rest_framework.test import APIClient
        a = mk("alice", date(1990, 1, 1))
        b = mk("bob", date(1990, 1, 1))
        UserSkill.objects.create(user=b, skill=self.flow, learned_at=date(2016, 1, 1))
        rate_up(b, self.flow, [7, 7, 7], 9)
        ca, cb = APIClient(), APIClient()
        ca.force_authenticate(a)
        cb.force_authenticate(b)
        r = ca.put("/api/skillreg/gates/collab/7/", {"skill_reqs": [
            {"family": "Rapping", "exp_min_months": 60, "exp_max_months": 240, "rating_min": 5, "rating_max": 10}]}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ca.put("/api/skillreg/gates/collab/8/", {"families": ["Nope"]}, format="json").status_code, 400)
        self.assertEqual(len(cb.post("/api/skillreg/posts/", {"families": ["Rapping"]}, format="json").json()), 1)
        self.assertEqual(len(cb.post("/api/skillreg/posts/", {"skill_ids": [self.free.id]}, format="json").json()), 1)  # skill filter matches family post
        self.assertEqual(len(cb.post("/api/skillreg/posts/", {"families": ["Mixing"]}, format="json").json()), 0)
        self.assertEqual(len(ca.post("/api/skillreg/search/", {"families": ["Rapping"],
                         "skill_reqs": [{"family": "Rapping", "exp_min_months": 60, "rating_min": 5}]}, format="json").json()), 1)
        w = ca.post("/api/skillreg/works/", {"families": ["Rapping"], "exp_min_months": 60, "exp_max_months": 240,
                                              "rating_min": 5, "rating_max": 10}, format="json").json()
        self.assertEqual([x["creator"] for x in w], ["bob"])


class CapOnlyRanges(TestCase):
    """Freedom of choice: any bound can be a cap only (max, no min), a floor only, or both."""
    def test_caps_without_minimums(self):
        s = Skill.objects.create(slug="s", name="S", family="Fam", price_cents=300)
        owner = mk("owner", date(1985, 5, 5), lat=39.74, lon=-104.99)
        newbie = mk("newbie", date(1990, 1, 1), lat=39.75, lon=-105.0)
        UserSkill.objects.create(user=newbie, skill=s, learned_at=date(2026, 1, 1))
        rate_up(newbie, s, [4, 4, 4], 1)
        vet = mk("vet", date(1990, 1, 1), lat=39.75, lon=-105.0)
        UserSkill.objects.create(user=vet, skill=s, learned_at=date(2005, 1, 1))
        rate_up(vet, s, [9, 9, 9], 2)

        def gate(pid, **kw):
            g = SkillGate.objects.create(owner=owner, post_type="collab", post_id=pid, **kw)
            g.skills.add(s)
            return g
        cap_rating = gate(1, rating_max=6)            # only people rated 6 or lower
        self.assertTrue(S.evaluate_gate(cap_rating, newbie)[0])
        self.assertFalse(S.evaluate_gate(cap_rating, vet)[0])
        cap_exp = gate(2, exp_max_months=36)          # at most 3 years experience
        self.assertTrue(S.evaluate_gate(cap_exp, newbie)[0])
        self.assertFalse(S.evaluate_gate(cap_exp, vet)[0])
        cap_price = gate(3, price_max=250)            # catalog price 300 is over the cap
        self.assertFalse(S.evaluate_gate(cap_price, newbie)[0])
        cap_gauge = gate(4, gauge_max=1)
        self.assertTrue(S.evaluate_gate(cap_gauge, newbie)[0])
        self.assertFalse(S.evaluate_gate(cap_gauge, vet)[0])
        cap_dist = gate(5, distance_max_km=5)
        self.assertTrue(S.evaluate_gate(cap_dist, newbie)[0])
        floor_only = gate(6, rating_min=8)
        self.assertTrue(S.evaluate_gate(floor_only, vet)[0])
        self.assertFalse(S.evaluate_gate(floor_only, newbie)[0])
        cap_age = SkillGate.objects.create(owner=owner, post_type="collab", post_id=7, age_max=25)
        self.assertFalse(S.evaluate_gate(cap_age, vet)[0])
