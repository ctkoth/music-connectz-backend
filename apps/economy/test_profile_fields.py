from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.social import clean_profile_field


class CleanTests(TestCase):
    def test_caps_and_dedupes(self):
        self.assertEqual(len(clean_profile_field("headline", "x" * 300)), 100)
        self.assertEqual(clean_profile_field("genres", ["Trap", "trap", "Drill"]), ["Trap", "Drill"])
        self.assertEqual(len(clean_profile_field("genres", [f"g{i}" for i in range(30)])), 8)

    def test_cover_must_be_our_media(self):
        self.assertEqual(clean_profile_field("cover_url", "https://evil.example/x.png"), "")
        self.assertEqual(clean_profile_field("cover_url", "/api/economy/media/3/a.png"), "/api/economy/media/3/a.png")
        # The upload endpoint hands out an absolute URL; the path is kept.
        self.assertEqual(clean_profile_field("cover_url", "https://api.x/api/economy/media/3/a.png"), "/api/economy/media/3/a.png")
        self.assertEqual(clean_profile_field("cover_url", "javascript:/api/economy/media/1/a"), "")

    def test_timezone_shape(self):
        self.assertEqual(clean_profile_field("timezone", "America/Denver"), "America/Denver")
        self.assertEqual(clean_profile_field("timezone", "<script>"), "")


class WritersTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("pf", password="pw12345!x")
        self.c = APIClient(); self.c.force_authenticate(self.u)

    def test_both_writers_clean(self):
        r = self.c.patch("/api/auth/me/", {"headline": "Producer", "cover_url": "javascript:x"}, format="json")
        self.assertIn(r.status_code, (200, 201))
        from apps.economy.models import Profile
        p = Profile.objects.get(user=self.u)
        self.assertEqual((p.headline, p.cover_url), ("Producer", ""))
        self.c.post("/api/economy/profile/", {"genres": ["Lo-fi", "lo-fi"], "pronouns": "they/them"}, format="json")
        p.refresh_from_db()
        self.assertEqual((p.genres, p.pronouns), (["Lo-fi"], "they/them"))


class PinnedTests(TestCase):
    def test_pinned_shows_only_own_public_post(self):
        from apps.economy.models import Post, Profile
        u = User.objects.create_user("pin", password="pw12345!x")
        other = User.objects.create_user("oth", password="pw12345!x")
        mine = Post.objects.create(author=u, title="Best", visibility="public")
        theirs = Post.objects.create(author=other, title="Not mine", visibility="public")
        p, _ = Profile.objects.get_or_create(user=u)
        c = APIClient()
        p.pinned_post_id = theirs.id; p.save()
        self.assertIsNone(c.get("/api/economy/public/members/pin/").json()["pinned_post"])
        p.pinned_post_id = mine.id; p.save()
        self.assertEqual(c.get("/api/economy/public/members/pin/").json()["pinned_post"]["title"], "Best")
        mine.visibility = "private"; mine.save()
        self.assertIsNone(c.get("/api/economy/public/members/pin/").json()["pinned_post"])


class PortfolioLinkLadderTests(TestCase):
    """A member's links are their portfolio. The ceiling is the tier's, it is SAID
    when it is hit (the old flat 50 cut the list and answered 200), and a number
    moving never takes a link away from somebody who already holds it."""

    def member(self, name, tier=None):
        from apps.economy.models import membership_for
        u = User.objects.create_user(name, password="pw12345!x")
        if tier:
            m = membership_for(u)
            m.tier = tier
            m.save()
        c = APIClient(); c.force_authenticate(u)
        return u, c

    @staticmethod
    def links(n):
        return [{"label": f"L{i}", "url": f"https://example.com/{i}"} for i in range(n)]

    def test_the_ladder_goes_up_and_every_tier_has_one(self):
        from apps.economy.catalog import limits_for
        free, prem, statz = (limits_for(t)["profile_links"] for t in ("free", "premium", "statz"))
        self.assertLess(free, prem)
        self.assertLess(prem, statz)
        self.assertGreater(free, 20)      # generous at the bottom: the work is why people visit

    def test_a_list_at_the_ceiling_saves_and_one_over_is_refused_with_the_number(self):
        from apps.economy.catalog import limits_for
        cap = limits_for("free")["profile_links"]
        _, c = self.member("atcap")
        self.assertEqual(c.post("/api/economy/profile/", {"links": self.links(cap)}, format="json").status_code, 200)
        r = c.post("/api/economy/profile/", {"links": self.links(cap + 1)}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["links_limit"], cap)
        self.assertEqual(r.json()["links_count"], cap + 1)
        self.assertIn(str(cap), r.json()["detail"])

    def test_a_refused_list_loses_nothing_else_in_the_same_save(self):
        from apps.economy.catalog import limits_for
        from apps.economy.models import Profile
        cap = limits_for("free")["profile_links"]
        u, c = self.member("onerequest")
        r = c.post("/api/economy/profile/", {"headline": "Producer", "links": self.links(cap + 5)}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Profile.objects.get(user=u).headline, "")     # nothing was written, and the member is told

    def test_a_higher_tier_holds_more(self):
        from apps.economy.catalog import limits_for
        n = limits_for("free")["profile_links"] + 10
        _, c = self.member("prem", "premium")
        self.assertEqual(c.post("/api/economy/profile/", {"links": self.links(n)}, format="json").status_code, 200)

    def test_nobody_loses_a_link_when_the_ceiling_is_below_what_they_hold(self):
        from apps.economy.catalog import limits_for
        from apps.economy.models import Profile, profile_for
        cap = limits_for("free")["profile_links"]
        u, c = self.member("grandfathered")
        p = profile_for(u)
        p.links = self.links(cap + 15)               # held under the old flat 50
        p.save()
        # Editing what is there — reordering, removing one — is always allowed...
        mine = c.get("/api/economy/profile/").json()["links"]
        self.assertEqual(c.post("/api/economy/profile/", {"links": list(reversed(mine))}, format="json").status_code, 200)
        self.assertEqual(c.post("/api/economy/profile/", {"links": mine[:-1]}, format="json").status_code, 200)
        # ...adding a link past what they hold is not.
        r = c.post("/api/economy/profile/", {"links": mine + self.links(5)}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(len(Profile.objects.get(user=u).links), cap + 14)

    def test_the_owner_is_told_the_ceiling_before_adding_anything(self):
        from apps.economy.catalog import limits_for
        cap = limits_for("free")["profile_links"]
        _, c = self.member("told")
        d = c.get("/api/economy/profile/").json()
        self.assertEqual(d["links_limit"], cap)
        self.assertEqual(d["links_tier_cap"], cap)

    def test_somebody_elses_card_carries_no_ceiling(self):
        _, c = self.member("viewer")
        other, _ = self.member("other")
        d = c.get(f"/api/economy/members/{other.username}/").json()
        self.assertNotIn("links_limit", d)

    def test_every_tier_is_published_to_the_screen(self):
        _, c = self.member("ladderseer")
        lim = c.get("/api/economy/limits/").json()
        self.assertEqual([lim["tiers"][t]["profile_links"] for t in ("free", "premium", "statz")],
                         [25, 100, 300])

    def test_an_unsafe_link_is_still_dropped_before_it_is_counted(self):
        from apps.economy.models import Profile
        u, c = self.member("unsafe")
        r = c.post("/api/economy/profile/", {"links": self.links(3) + [{"label": "x", "url": "javascript:alert(1)"}]}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(Profile.objects.get(user=u).links), 3)
